"""기본적 분석 탭(사업보고서 5개년 · 분기 2개년)용 실적 수치 — DART 원본 공시(.cache/fs)에서 추출.

annual(code)  → {연도: {rev, oi, pretax, ni, nip, eps}}  (최근 5개 사업연도)
quarters(code) → [(라벨, {rev, oi, pretax, ni, nip})]     (최근 8개 분기, 3개월 단독)
4분기 단독 = 사업보고서 연간 − 3분기 누적. 금액 단위는 원.
"""
import os, re, json

from fetch import CACHE, RC
from engine import IS, num, get, eps_by_name, px_at, TYPES

KEYS = ('rev', 'oi', 'pretax', 'ni', 'nip')
IDS = {'rev': ['Revenue'], 'oi': ['OperatingIncomeLoss', 'ProfitLossFromOperatingActivities'], 'pretax': ['ProfitLossBeforeTax'],
       'ni': ['ProfitLoss'], 'nip': ['ProfitLossAttributableToOwnersOfParent']}
# account_id가 표준이 아닌 회사(금융사·일부 제조사)를 위한 계정명 대체
NAMES = {'rev': ('매출액', '영업수익', '수익(매출액)', '매출', '순영업수익'),
         'oi': ('영업이익', '영업이익(손실)', '영업손익'),
         'pretax': ('법인세비용차감전순이익', '법인세비용차감전순이익(손실)', '법인세차감전순이익', '법인세비용차감전계속영업이익',
                    '법인세비용차감전순손익', '법인세비용차감전계속사업이익'),
         'ni': ('당기순이익', '당기순이익(손실)', '분기순이익', '반기순이익', '분기순이익(손실)', '반기순이익(손실)', '당기순손익',
                '연결당기순이익', '연결당기순이익(손실)', '연결분기순이익', '연결반기순이익', '당기순손실', '분기순손실', '반기순손실'),
         'nip': ()}


def _fs(code):
    p = os.path.join(CACHE, 'fs', f'{code}.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def _clean(nm):
    return re.sub(r'^[IVX]+\.|^\d+\.|^[가-하]\.', '', nm.replace(' ', ''))


def _by_name(L, names, field):
    for nm in names:
        for x in L:
            if x.get('sj_div') in IS and _clean(x.get('account_nm', '')) == nm:
                v = num(x.get(field))
                if v is not None:
                    return v
    return None


def _nip_by_name(L, field):
    for x in L:
        nm = x.get('account_nm', '').replace(' ', '')
        if x.get('sj_div') in IS and '지배기업' in nm and '소유주' in nm and '포괄' not in nm and '비지배' not in nm:
            v = num(x.get(field))
            if v is not None:
                return v
    return None


def _val(L, k, field):
    v = get(L, IDS[k], IS, field)
    if v is None:
        v = _nip_by_name(L, field) if k == 'nip' else _by_name(L, NAMES[k], field)
    return v


def _usd(L):
    return any(x.get('currency') == 'USD' for x in L[:5])


def _row(L, field, y, m, krw=True):
    r = {k: _val(L, k, field) for k in KEYS}
    if r['nip'] is None:
        r['nip'] = r['ni']
    if r['ni'] is None:
        r['ni'] = r['nip']
    return _krw(r, L, y, m) if krw else r


def _krw(r, L, y, m):
    """달러 공시 회사는 기간 말 원/달러 환율로 환산(분기는 단독 분기 금액을 그 분기 말 환율로)."""
    if not _usd(L):
        return r
    f = px_at('USDKRW', y, m) or 1.0
    return {k: (v * f if isinstance(v, (int, float)) and k != 'fs_div' else v) for k, v in r.items()}


def src_code(code):
    """우선주는 보통주 재무제표를 씀."""
    return TYPES['우선주'].get(code, code) if isinstance(TYPES.get('우선주'), dict) else code


def annual(code, n=5):
    d = _fs(src_code(code))
    out = {}
    ok = lambda y: (d.get(f'{y}_11011') or {}).get('status') == '000'
    ys = sorted({int(k[:4]) for k in d if k.endswith('_11011') and ok(int(k[:4]))})
    if not ys:
        return out
    for y in range(ys[-1] - n + 1, ys[-1] + 1):
        # 그해 사업보고서가 없으면(금융사 등) 이듬해·2년 뒤 사업보고서의 비교 열로
        for sy, col in ((y, 'thstrm'), (y + 1, 'frmtrm'), (y + 2, 'bfefrmtrm')):
            if not ok(sy):
                continue
            L = d[f'{sy}_11011']['list']
            r = _row(L, f'{col}_amount', y, 12, krw=False)
            if r['nip'] is None:
                continue
            eps = get(L, ['BasicEarningsLossPerShare'], IS, f'{col}_amount')
            if eps is None:
                eps = eps_by_name(L, f'{col}_amount')
            if eps is None:
                ce = get(L, ['BasicEarningsLossPerShareFromContinuingOperations'], IS, f'{col}_amount')
                if ce is not None:
                    eps = ce + (get(L, ['BasicEarningsLossPerShareFromDiscontinuedOperations'], IS, f'{col}_amount') or 0)
            r['eps'] = eps
            r = _krw(r, L, y, 12)
            r['fs_div'] = d[f'{sy}_11011'].get('fs_div', 'CFS')
            out[y] = r
            break
    for y, r in out.items():
        if r['eps'] is None:
            r['eps'] = alot_eps(code, y)
    return out


def alot_eps(code, y):
    """재무제표에 EPS 줄이 없는 해: 사업보고서 '배당에 관한 사항'의 (연결)주당순이익."""
    from fetch import corp_map, dart, _save
    p = os.path.join(CACHE, 'alot_eps', f'{code}.json')
    c = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    if str(y) not in c:
        corp = corp_map()['map'].get(src_code(code), [None])[0]
        c[str(y)] = dart('alotMatter', corp_code=corp, bsns_year=y, reprt_code='11011') if corp else {}
        _save(p, c)
    rows = c[str(y)].get('list') or []
    for pre in ('(연결)주당순이익', '(별도)주당순이익'):
        for x in rows:
            if x.get('se', '').startswith(pre) and (x.get('stock_knd') in (None, '', '-', '보통주')):
                v = num(x.get('thstrm'))
                if v is not None:
                    return v
    return None


def quarters(code, n=8):
    d = _fs(src_code(code))
    ok = lambda y, q: (d.get(f'{y}_{RC[q]}') or {}).get('status') == '000'
    L = lambda y, q: d[f'{y}_{RC[q]}']['list']
    seq = []
    for y in range(2020, 2031):
        for q in (1, 2, 3, 4):
            if not ok(y, q):
                continue
            m = q * 3
            if q < 4:
                r = _row(L(y, q), 'thstrm_amount', y, m)
            else:
                a = _row(L(y, 4), 'thstrm_amount', y, 12, krw=False)
                if ok(y, 3):
                    c = _row(L(y, 3), 'thstrm_add_amount', y, 9, krw=False)
                    if any(c[k] is None and a[k] is not None for k in KEYS):
                        # 3분기 누적이 없으면 1~3분기 단독 합으로
                        parts = [_row(L(y, qq), 'thstrm_amount', y, qq * 3, krw=False) for qq in (1, 2, 3) if ok(y, qq)]
                        if len(parts) == 3:
                            for k in KEYS:
                                if c[k] is None and all(p[k] is not None for p in parts):
                                    c[k] = sum(p[k] for p in parts)
                    r = {k: (a[k] - c[k] if a[k] is not None and c[k] is not None else None) for k in KEYS}
                    r = _krw(r, L(y, 4), y, 12)
                else:
                    r = {k: None for k in KEYS}
            seq.append((f'{q}Q{str(y)[2:]}', r, y, q))
    # 마지막 분기에서 거꾸로 n개 — 중간에 빠진 분기가 있으면 빈 칸으로 채움
    if not seq:
        return []
    last_y, last_q = seq[-1][2], seq[-1][3]
    have = {(y, q): r for _, r, y, q in seq}
    out = []
    y, q = last_y, last_q
    for _ in range(n):
        out.append((f'{q}Q{str(y)[2:]}', have.get((y, q), {k: None for k in KEYS})))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out[::-1]


if __name__ == '__main__':
    import sys
    for c in sys.argv[1:]:
        print(c, src_code(c))
        for y, r in annual(c).items():
            print(' ', y, {k: (round(v / 1e8) if isinstance(v, float) and k != 'eps' else v) for k, v in r.items()})
        for lab, r in quarters(c):
            print(' ', lab, {k: (round(v / 1e8) if v is not None else None) for k, v in r.items()})
