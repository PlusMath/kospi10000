"""종목 유형별 가중 다중평가 내재가치 — 분기 말마다 그 시점에 알 수 있던 재무제표로 평가.

할인율 12%, 안전마진 미적용. 방식: DCF(주주이익), RIM, 정상화 PER, 적정 PBR(PBR-ROE), 배당할인, NAV(지주사).
입력은 fetch.py가 채운 .cache/ 데이터.
"""
import os, re, json, math, datetime, statistics as st

from fetch import CACHE, RC

R = 0.12
HOLD_DISCOUNT = (0.5, 0.3)   # 지주사 할인 50%(하단) ~ 30%(상단)
WEIGHTS = {
    '안정':        {'DCF': 40, 'RIM': 30, '정상화 PER': 30},
    '경기민감':    {'DCF': 30, 'RIM': 30, '정상화 PER': 40},
    '금융':        {'RIM': 50, 'PBR-ROE': 30, '배당할인': 20},
    '지주·투자':   {'NAV': 60, 'RIM': 20, '정상화 PER': 20},
    '규제·유틸리티': {'RIM': 40, '정상화 PER': 30, '배당할인': 30},
    '고성장·적자': {'RIM': 50, 'PBR-ROE': 50},               # 이익 기반 평가 제외, 참고용
}
TYPES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'types.json'), encoding='utf-8'))
FIN, HOLD, UTIL, PREF = set(TYPES['금융']), set(TYPES['지주·투자']), set(TYPES['규제·유틸리티']), TYPES['우선주']
IS = ('IS', 'CIS')
CAPEX = ['PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
         'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities']
DEBT = ['ShorttermBorrowings', 'ShortTermBorrowings', 'CurrentPortionOfLongtermBorrowings', 'LongTermBorrowingsGross',
        'BondsIssued', 'NoncurrentPortionOfNoncurrentBondsIssued', 'ConvertibleBondsNet']
THIS_YEAR = datetime.date.today().year


def _p(*a):
    return os.path.join(CACHE, *a)


def _load(path, default=None):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


NAVER = _load(_p('naver.json'), {})


def num(s):
    try:
        return float(str(s).replace(',', ''))
    except Exception:
        return None


def get(L, names, sj, field='thstrm_amount'):
    for n in names:
        for pre in ('ifrs-full_', 'ifrs_', 'dart_'):
            for x in L:
                if x.get('account_id') == pre + n and x.get('sj_div') in sj:
                    v = num(x.get(field))
                    if v is not None:
                        return v
    return None


def eps_by_name(L, field):
    for strict in (True, False):
        for x in L:
            nm = x.get('account_nm', '')
            bad = ('희석', '계속', '중단', '우선주') if strict else ('계속', '중단', '우선주')
            if '기본' in nm and '주당' in nm and all(w not in nm for w in bad) and x.get('sj_div') in IS:
                v = num(x.get(field))
                return v if v is not None else num(x.get('thstrm_amount'))
    return None


# ── 가격 ──
_PX = {}


def px_series(code):
    """{'YYYY-MM': close} 월간 종가(분할 조정)."""
    if code not in _PX:
        p = _load(_p('px', f'{code}.json'))
        _PX[code] = {datetime.datetime.fromtimestamp(ts).strftime('%Y-%m'): c
                     for ts, c in zip(p['ts'], p['c']) if c is not None} if p else {}
    return _PX[code]


def px_at(code, y, m):
    s = px_series(code)
    key = f'{y}-{m:02d}'
    ks = [k for k in s if k <= key]
    return s[max(ks)] if ks else None


def conv(r, L, y, m):
    """달러로 공시하는 회사(예: 두산밥캣 2023~)는 기간 말 원/달러 환율로 환산."""
    if r and L and any(x.get('currency') == 'USD' for x in L[:5]):
        f = px_at('USDKRW', y, m) or 1.0
        r = dict(r)
        for k in ('nip', 'ni', 'eps', 'rev', 'oi', 'ocf', 'capex', 'div', 'eq', 'cash', 'debt'):
            if r.get(k) is not None:
                r[k] = r[k] * f
    return r


def flow(L, q, col='thstrm'):
    """보고서 하나의 누적(YTD) 손익·현금흐름. col='frmtrm'/'bfefrmtrm'이면 비교 기간 열."""
    f = f'{col}_amount' if q in (1, 4) else f'{col}_add_amount'
    r = {}
    for k, names in (('nip', ['ProfitLossAttributableToOwnersOfParent']), ('ni', ['ProfitLoss']),
                     ('eps', ['BasicEarningsLossPerShare']), ('rev', ['Revenue']), ('oi', ['OperatingIncomeLoss'])):
        r[k] = get(L, names, IS, f)
        if r[k] is None:
            r[k] = get(L, names, IS, f'{col}_amount')
    if r['eps'] is None:
        r['eps'] = eps_by_name(L, f)
    if r['eps'] is None:
        ce = get(L, ['BasicEarningsLossPerShareFromContinuingOperations'], IS, f)
        if ce is not None:
            r['eps'] = ce + (get(L, ['BasicEarningsLossPerShareFromDiscontinuedOperations'], IS, f) or 0)
    if r['nip'] is None:
        r['nip'] = r['ni']
    if r['ni'] is None:
        r['ni'] = r['nip']
    r['ocf'] = get(L, ['CashFlowsFromUsedInOperatingActivities'], ('CF',), f'{col}_amount')
    r['capex'] = sum(abs(get(L, [n], ('CF',), f'{col}_amount') or 0) for n in CAPEX)
    dv = get(L, ['DividendsPaidClassifiedAsFinancingActivities', 'DividendsPaid'], ('CF',), f'{col}_amount')
    r['div'] = abs(dv) if dv else 0
    return r


def bal(L, col='thstrm'):
    f = f'{col}_amount'
    eq = get(L, ['EquityAttributableToOwnersOfParent'], ('BS',), f) or get(L, ['Equity'], ('BS',), f)
    return {'eq': eq, 'cash': get(L, ['CashAndCashEquivalents'], ('BS',), f) or 0,
            'debt': sum(get(L, [n], ('BS',), f) or 0 for n in DEBT)}


def alot_rows(code):
    """전체 재무제표가 없는 해(금융사 2015~2020 등): 배당 공시의 순이익·EPS·배당 (재무상태표 없음)."""
    out = {}
    for y, d in (_load(_p('alot', f'{code}.json'), {}) or {}).items():
        v = {}
        for x in d.get('list') or []:
            se, val = x.get('se', ''), num(x.get('thstrm'))
            if val is None:
                continue
            if se.startswith('(연결)당기순이익'):
                v['nip'] = val * 1e6
            elif se.startswith('(별도)당기순이익') and 'nip' not in v:
                v['nip_sep'] = val * 1e6
            elif se.startswith('(연결)주당순이익'):
                v['eps'] = val
            elif se.startswith('현금배당금총액'):
                v['div'] = val * 1e6
        if 'nip' not in v and 'nip_sep' in v:
            v['nip'] = v['nip_sep']
        if 'nip' in v:
            out[int(y)] = {'nip': v['nip'], 'ni': v['nip'], 'eps': v.get('eps'), 'div': v.get('div', 0), 'eq': None,
                           'rev': None, 'oi': None, 'ocf': None, 'capex': 0, 'cash': 0, 'debt': 0, 'lite': True}
    return out


def _shares(r):
    return r['nip'] / r['eps'] if r.get('eps') and r.get('nip') and r['nip'] / r['eps'] > 0 else None


def load(code):
    d = _load(_p('fs', f'{code}.json'), {})
    L = lambda y, q: (d.get(f'{y}_{RC[q]}') or {}).get('list') or []
    rows = {}
    for y in range(2015, THIS_YEAR):
        for src_y, col in ((y, 'thstrm'), (y + 1, 'frmtrm'), (y + 2, 'bfefrmtrm')):
            lst = L(src_y, 4) if src_y < THIS_YEAR else []
            if not lst:
                continue
            r = conv({**flow(lst, 4, col), **bal(lst, col)}, lst, y, 12)
            if r['nip'] is None or not r['eq']:
                continue
            r['shares'] = _shares(r)
            rows[y] = r
            break
    for y, r in alot_rows(code).items():
        if y not in rows:
            r['shares'] = _shares(r)
            rows[y] = r
    return rows, L


def roe_series(rows, ys):
    out = []
    for y in ys:
        if not rows[y].get('eq'):
            continue
        prev = rows.get(y - 1, {}).get('eq')
        base = (prev + rows[y]['eq']) / 2 if prev else rows[y]['eq']
        if base and base > 0:
            out.append(rows[y]['nip'] / base)
    return out


def classify(code, rows):
    if code in FIN:
        return '금융', '은행·보험·증권 등 금융업'
    if code in HOLD:
        return '지주·투자', '지주·투자회사'
    if code in UTIL:
        return '규제·유틸리티', '요금 규제 산업'
    ys = sorted(rows)
    nips = [rows[y]['nip'] for y in ys]
    roe = roe_series(rows, ys)
    roe_avg = st.mean(roe) if roe else 0
    if nips[-1] < 0 or roe_avg <= 0:
        return '고성장·적자', ('최근 연도 적자' if nips[-1] < 0 else f'평균 ROE {roe_avg*100:.1f}%')
    revs = [rows[y]['rev'] for y in ys if rows[y]['rev']]
    if len(revs) >= 4 and revs[0] > 0 and revs[-1] > 0:
        cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
        if cagr > 0.15 and roe_avg < R:
            return '고성장·적자', f'매출 연평균 {cagr*100:.0f}% 성장, 평균 ROE {roe_avg*100:.1f}%'
    mv = [rows[y]['oi'] / rows[y]['rev'] * 100 for y in ys if rows[y]['rev'] and rows[y]['oi'] is not None]
    sd = st.pstdev(mv) if len(mv) >= 3 else 0
    losses = sum(1 for v in nips if v < 0)
    if sd > 5 or losses:
        return '경기민감', f'영업이익률 표준편차 {sd:.1f}%p' + (f', 적자 {losses}년' if losses else '')
    return '안정', f'영업이익률 표준편차 {sd:.1f}%p, 적자 연도 없음'


def dcf(oe, g1, years=10, g2=0.025, r=R):
    v, cf = 0.0, oe
    for t in range(1, years + 1):
        cf *= (1 + g1)
        v += cf / (1 + r) ** t
    return v + cf * (1 + g2) / (r - g2) / (1 + r) ** years


def rim(bps, roe_start, payout, r=R, years=10):
    """초과 ROE가 10년에 걸쳐 선형으로 0이 되고, BPS는 유보이익만큼 증가."""
    v = b = bps
    for t in range(1, years + 1):
        roe = r + (roe_start - r) * (1 - (t - 1) / years)
        v += (roe - r) * b / (1 + r) ** t
        b *= 1 + roe * (1 - payout)
    return v


def pctl(vals, p):
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


# ── NAV (지주·투자회사) ──
_CORP_NAMES = None


def _norm(n):
    n = re.sub(r'\((?:주|\*)?\s*\d*\)', '', n)          # (주2) (*1) 같은 주석
    n = n.replace('보통주', '').upper()
    for a, b in (('㈜', ''), ('(주)', ''), ('주식회사', ''), (' ', ''), ('.', ''), (',', ''),
                 ('엘지', 'LG'), ('에스케이', 'SK'), ('지에스', 'GS'), ('엘에스', 'LS'), ('씨제이', 'CJ'),
                 ('케이티', 'KT'), ('에이치디', 'HD'), ('에이치엠엠', 'HMM'), ('에스디아이', 'SDI'),
                 ('에스디에스', 'SDS'), ('씨앤씨', 'C&C'), ('이앤에스', 'E&S')):
        n = n.replace(a, b)
    return n


def listed_code(name):
    """출자현황의 법인명 → 상장 종목코드 (없으면 None)."""
    global _CORP_NAMES
    if '우선주' in name:
        return None
    if _CORP_NAMES is None:
        cm = (_load(_p('corp.json'), {}) or {}).get('map', {})
        _CORP_NAMES = {}
        for code, (corp, nm) in cm.items():
            if re.fullmatch(r'\d{5}[0-9A-Z]', code) and code[-1] == '0':   # 보통주만
                _CORP_NAMES.setdefault(_norm(nm), code)
    return _CORP_NAMES.get(_norm(name))


def holdings_at(code, y, q):
    """분기 (y, q) 시점에 알 수 있던 가장 최근 출자현황(사업·반기보고서)."""
    inv = _load(_p('inv', f'{code}.json'), {}) or {}
    best = None
    for k, d in inv.items():
        if d.get('status') != '000':
            continue
        ky, rc = int(k[:4]), k[5:]
        km = 12 if rc == '11011' else 6
        if (ky, km) <= (y, q * 3) and (best is None or (ky, km) > best[0]):
            best = ((ky, km), d['list'])
    return best


def nav_at(code, y, q, shares, ofs_L, latest=False):
    """NAV = 별도 자본 + Σ(상장 지분 시장가치 − 장부가). 지주사 할인 50~30% 적용."""
    lst = ofs_L(y, q)
    if not lst or not shares:
        return None
    eq_sep = bal(lst)['eq']
    h = holdings_at(code, y, q)
    if not eq_sep or not h:
        return None
    gain, mv_tot, n_listed = 0.0, 0.0, 0
    for x in h[1]:
        lc = listed_code(x.get('inv_prm', ''))
        book = num(x.get('trmend_blce_acntbk_amount'))
        rt = num(x.get('trmend_blce_qota_rt'))
        if not lc or lc == code or book is None or not rt:
            continue
        p_t = px_at(lc, 9999, 12) if latest else px_at(lc, y, q * 3)   # 최신 분기는 현재 주가로
        cur_sh = (NAVER.get(lc) or {}).get('shares')
        if not (p_t and cur_sh):
            continue
        mv = rt / 100 * p_t * cur_sh    # 분할 조정 주가 × 현재 주식 수 = 분할 조정 시가총액
        gain += mv - book
        mv_tot += mv
        n_listed += 1
    if not n_listed:
        return None
    nav = (eq_sep + gain) / shares
    return (nav * (1 - HOLD_DISCOUNT[0]), nav * (1 - HOLD_DISCOUNT[1]),
            f'주당 NAV {nav:,.0f}원(별도 자본 {eq_sep/1e12:.1f}조 + 상장 자회사 {n_listed}곳 지분 시가 {mv_tot/1e12:.1f}조 반영) × 지주사 할인 50~30%')


def value_at(typ, rows, ys, px, qb, ttm, shares, nav=None):
    roe = roe_series(rows, ys)
    if not roe or not shares or shares <= 0 or not qb['eq']:
        return None
    roe_avg, roe_rec3 = st.mean(roe), st.mean(roe[-3:])
    pays = [rows[y]['div'] / rows[y]['nip'] for y in ys if rows[y]['nip'] > 0]
    payout = max(0.0, min(0.9, st.mean(pays))) if pays else 0.0
    # 주주이익(순이익·영업현금흐름)은 이자비용 차감 후 값이라 순부채를 또 빼지 않는다. 순현금(초과 현금)만 더함.
    nc_ps = max(0.0, (qb['cash'] - qb['debt']) / shares)
    bps = qb['eq'] / shares
    p75 = pctl(roe, 0.75)
    m = {}
    w = WEIGHTS[typ]
    if 'DCF' in w:
        if typ == '경기민감':
            oe = [(rows[y]['ocf'] - rows[y]['capex']) * (rows[y]['nip'] / rows[y]['ni'] if rows[y]['ni'] else 1)
                  for y in ys if rows[y]['ocf'] is not None]
            ni_avg = st.mean([rows[y]['nip'] for y in ys])
            if oe and st.mean(oe) > 0 and 0.5 * ni_avg <= st.mean(oe) <= 2 * ni_avg:
                lo_oe = st.mean(oe)
                hi_oe = lo_oe
                if ttm and ttm.get('ocf') is not None:
                    hi_oe = max(lo_oe, (ttm['ocf'] - ttm['capex']) * (ttm['nip'] / ttm['ni'] if ttm['ni'] else 1))
                m['DCF'] = (dcf(lo_oe, 0.03) / shares + nc_ps, dcf(hi_oe, 0.03) / shares + nc_ps,
                            f'주주이익(영업현금흐름−설비투자) {len(oe)}년 평균 {lo_oe/1e12:.2f}조 ~ 최근 4분기 {hi_oe/1e12:.2f}조, 성장률 3%')
            elif ni_avg > 0:
                # 현금흐름 기준 주주이익이 순이익과 크게 어긋남(성장 투자·리스 상환 등) → 순이익 기준
                hi_ni = max(ni_avg, ttm['nip']) if ttm and ttm.get('nip') is not None else ni_avg
                m['DCF'] = (dcf(ni_avg, 0.03) / shares + nc_ps, dcf(hi_ni, 0.03) / shares + nc_ps,
                            f'주주이익=순이익 {len(ys)}년 평균 {ni_avg/1e12:.2f}조 ~ 최근 4분기 {hi_ni/1e12:.2f}조(현금흐름이 순이익과 크게 달라 순이익 사용), 성장률 3%')
        else:
            ni3 = st.mean([rows[y]['nip'] for y in ys[-3:]])
            if ni3 > 0:
                g = max(0.0, min(0.06, roe_avg * (1 - payout)))
                m['DCF'] = (dcf(ni3, 0.0) / shares + nc_ps, dcf(ni3, g) / shares + nc_ps,
                            f'주주이익=최근 3년 평균 순이익 {ni3/1e12:.2f}조, 성장률 0~{g*100:.1f}%')
    ttm_roe = ttm['nip'] / qb['eq'] if ttm and ttm.get('nip') is not None else None
    if typ == '경기민감':
        r_lo, r_hi = roe_avg, max(roe_avg, p75, ttm_roe or -1)
    else:
        r_lo, r_hi = min(roe_avg, roe_rec3), max(roe_avg, roe_rec3, p75)
    if 'NAV' in w and nav:
        m['NAV'] = nav
    if 'RIM' in w and bps > 0:
        m['RIM'] = (max(0, rim(bps, r_lo, payout)), max(0, rim(bps, r_hi, payout)),
                    f'BPS {bps:,.0f}원, ROE {r_lo*100:.1f}~{r_hi*100:.1f}%가 10년에 걸쳐 요구수익률로 수렴')
    if '정상화 PER' in w and px:
        pers = []
        for y in ys:
            p = px_at(px, y, 12)
            if p and rows[y]['nip'] > 0:
                pers.append(p / (rows[y]['nip'] / shares))
        eps_n = st.mean([rows[y]['nip'] for y in ys]) / shares
        if len(pers) >= 3 and eps_n > 0:
            pl, ph = pctl(pers, 0.25), pctl(pers, 0.75)
            m['정상화 PER'] = (eps_n * pl, eps_n * ph, f'{len(ys)}년 평균 EPS {eps_n:,.0f}원 × 과거 PER {pl:.1f}~{ph:.1f}배')
    if 'PBR-ROE' in w and bps > 0:
        g = max(0.0, min(0.03, roe_avg * (1 - payout)))
        pb = lambda x: max(0.0, (x - g) / (R - g))
        m['PBR-ROE'] = (bps * pb(r_lo), bps * pb(r_hi),
                        f'BPS {bps:,.0f}원 × 적정 PBR {pb(r_lo):.2f}~{pb(r_hi):.2f}배 (ROE {r_lo*100:.1f}~{r_hi*100:.1f}%, 성장률 {g*100:.1f}%)')
    if '배당할인' in w:
        dps = rows[ys[-1]]['div'] / shares
        if dps > 0:
            gh = max(0.0, min(0.04, roe_avg * (1 - payout)))
            m['배당할인'] = (dps / R, dps * (1 + gh) / (R - gh), f'주당 배당 {dps:,.0f}원, 배당 성장률 0~{gh*100:.1f}%')
    keys = [k for k in w if k in m]
    if not keys:
        return None
    tot = sum(w[k] for k in keys)
    lo = sum(m[k][0] * w[k] for k in keys) / tot
    hi = sum(m[k][1] * w[k] for k in keys) / tot
    mids = [(m[k][0] + m[k][1]) / 2 for k in keys]
    spread = max(mids) / min(mids) if min(mids) > 0 else 99
    return {'low': lo, 'high': hi, 'spread': spread, 'bps': bps,
            'methods': [{'name': k, 'w': round(w[k] * 100 / tot), 'low': m[k][0], 'high': m[k][1], 'note': m[k][2]} for k in keys],
            'missing': [k for k in w if k not in m]}


def split_multiple(r):
    """최신/과거 주식 수 비율이 분할(2·5·10배 등) 또는 병합으로 보이면 그 배수, 아니면 1."""
    if r >= 1.8:
        k = round(r)
        return k if abs(r - k) / k < 0.08 else 1
    if r <= 1 / 1.8:
        k = round(1 / r)
        return 1 / k if abs(1 / r - k) / k < 0.08 else 1
    return 1


def run(code, factor=None):
    rows, L = load(code)
    if len(rows) < 3:
        return {'code': code, 'error': f'연간 재무 이력 부족({len(rows)}년)'}
    typ, why = classify(code, rows)
    px = code if px_series(code) else None
    ofs = _load(_p('ofs', f'{code}.json'), {}) or {}
    ofs_L = lambda y, q: (ofs.get(f'{y}_{RC[q]}') or {}).get('list') or []
    out = []
    full = {y for y in rows if not rows[y].get('lite')}
    target = (NAVER.get(code) or {}).get('shares')

    def pick(cands):
        if target:
            return min(cands, key=lambda k: abs(math.log(rows[k]['shares'] / target)))
        return max(cands, key=lambda k: abs(rows[k]['nip']))
    # 액면분할·인적분할 등으로 주당 기준이 바뀐 경우: 최신 BPS가 네이버 BPS와 크게 다르면 전 기간 주식 수를 같은 비율로 보정(아래 재귀)
    factor = 1.0 if factor is None else factor
    items = []
    for y in range(2020, THIS_YEAR + 1):
        for q in (1, 2, 3, 4):
            if y == 2020 and q < 4:
                continue
            fy = y if q == 4 else y - 1
            ys = sorted(k for k in rows if k <= fy)
            if len(ys) < 3 or len([k for k in ys if k in full]) < 2:
                continue
            cur = L(y, q)
            if cur:
                c, qb = conv(flow(cur, q), cur, y, q * 3), conv(bal(cur), cur, y, q * 3)
            elif q == 4 and y in full:
                c, qb = rows[y], {k: rows[y][k] for k in ('eq', 'cash', 'debt')}
            else:
                continue
            if q == 4:
                ttm = c
            else:
                p = conv(flow(L(y - 1, q), q), L(y - 1, q), y - 1, q * 3) if L(y - 1, q) else conv(flow(cur, q, 'frmtrm'), cur, y - 1, q * 3)
                a = conv(flow(L(y - 1, 4), 4), L(y - 1, 4), y - 1, 12) if L(y - 1, 4) else rows.get(y - 1)
                ttm = None
                if a:
                    try:
                        ttm = {k: a[k] + c[k] - p[k] for k in ('nip', 'ni', 'ocf', 'capex')}
                    except TypeError:
                        ttm = None
            # 주식 수 = 순이익/EPS. 이익이 작은 해는 오차가 커서 최근 4년 중 현재 주식 수(네이버)에 가장 가까운 해를 기준으로 삼음
            cands = [k for k in ys[-4:] if rows[k].get('shares')] or [k for k in sorted(rows) if rows[k].get('shares')]
            ref = rows[pick(cands)]['shares'] if cands else None
            shares = _shares(c) or ref
            if shares and ref and not (0.8 < shares / ref < 1.25):
                shares = ref
            if shares:
                shares *= factor
                items.append((y, q, fy, ys, qb, ttm, shares))
    # 이후 액면분할·병합: 차트 주가(Yahoo)는 분할 조정돼 있으므로, 최신 주식 수와 거의 정수배로
    # 차이 나는 과거 분기는 그 배수만큼 주식 수를 맞춘다(유상증자 같은 비정수 변화는 그대로 둠)
    latest_sh = items[-1][6] if items else None
    for i, (y, q, fy, ys, qb, ttm, shares) in enumerate(items):
        k = split_multiple(latest_sh / shares)
        if k != 1:
            shares *= k
        last = i == len(items) - 1
        # 최신 분기의 NAV는 보유 지분을 현재 주가로 평가(지분 시가는 매일 알 수 있으므로)
        nav = nav_at(code, y, q, shares, ofs_L, latest=last) if typ == '지주·투자' else None
        v = value_at(typ, rows, ys, px, qb, ttm, shares, nav)
        if v:
            v['q'] = f'{y}-{q*3:02d}'
            v['fy'] = fy
            out.append(v)
    if not out:
        return {'code': code, 'error': '평가 가능한 분기 없음'}
    nb = (NAVER.get(code) or {}).get('bps')
    if factor == 1.0 and nb and out[-1].get('bps'):
        ratio = out[-1]['bps'] / nb
        if not (0.7 < ratio < 1.45):
            return run(code, factor * ratio)
    return {'code': code, 'type': typ, 'type_why': why, 'first_year': min(rows), 'quarters': out}


def cache_complete(code):
    """수집해야 할 공시가 캐시에 빠짐없이 있는지(제출·미제출 응답 모두 기록됨) — 일시적 수집 실패와 진짜 이력 부족을 구분."""
    from fetch import report_jobs
    d = _load(_p('fs', f'{code}.json'), {}) or {}
    return bool(d) and all(f'{y}_{rc}' in d for y, rc in report_jobs())


def run_all(stocks, log=print):
    res = {}
    for s in stocks:
        code = PREF.get(s['code'], s['code'])
        if not os.path.exists(_p('fs', f'{code}.json')):
            res[s['code']] = {'code': s['code'], 'error': 'DART 데이터 없음'}
            continue
        try:
            r = run(code)
        except Exception as e:
            r = {'code': code, 'error': f'{type(e).__name__}: {e}'}
        # 캐시가 완전한데도 평가 불가면 진짜 이력 부족(영구) — 그 외(예외·수집 누락)는 일시적 오류로 보고 기존 게시본 유지
        if 'error' in r and not r['error'].startswith(('KeyError', 'TypeError', 'ValueError', 'ZeroDivisionError')):
            r['permanent'] = cache_complete(code)
        r['page_code'] = s['code']
        res[s['code']] = r
    return res
