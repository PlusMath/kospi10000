"""종목 페이지 '기본적 분석' 분기 탭을 3분기보고서(3Q26) 기준으로 갱신 (2026-11-18).

python valuation/q3_update.py facts 코드...          # 해설 작성용 수치 요약 출력
python valuation/q3_update.py apply notes.json [--dry] # notes의 종목만 페이지 갱신

notes.json = {코드: {"core": 보고서 핵심 해설, "tl_title": 시계열 제목, "tl_body": 시계열 본문}}
- 탭 이름 → '3분기보고서 · 3Q26'
- 분기 탭 수치 행(dp-g2) → 3Q26 누적·단독 실적, 9월 말 재무상태(전 종목 같은 틀)
- '보고서 핵심' 해설 → notes의 core (직접 작성한 문단)
- 투자지표의 '1H26 EPS' 카드 → 3Q26 누적 EPS(연환산)
- 시계열에 3분기보고서 공시 항목 추가(날짜 순서 유지, 이미 있으면 교체)
- 분기 차트·2개년 흐름 문장 → fund_render.transform 재실행
수치는 모두 DART 3분기보고서(bsns_year=2026, reprt_code=11014) 원본.
"""
import os, re, sys, json, html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import IS, num, get, eps_by_name
from fund_report import _fs, _row, annual, quarters, src_code
from fund_render import krw, pct, transform, STOCKS, LEGACY_ACCENT

Y, RC3 = 2026, '11014'
TAB = '3분기보고서 · 3Q26'


def _bs(L, ids, names, field):
    v = get(L, ids, ('BS',), field)
    if v is None:
        v = next((num(x.get(field)) for x in L if x.get('sj_div') == 'BS' and x.get('account_nm', '').replace(' ', '') in names), None)
    return v


def _eps(L, field):
    e = get(L, ['BasicEarningsLossPerShare'], IS, field)
    if e is None:
        e = eps_by_name(L, field)
    if e is None:
        ce = get(L, ['BasicEarningsLossPerShareFromContinuingOperations'], IS, field)
        if ce is not None:
            e = ce + (get(L, ['BasicEarningsLossPerShareFromDiscontinuedOperations'], IS, field) or 0)
    return e


def facts(code):
    d = _fs(src_code(code))
    r = d.get(f'{Y}_{RC3}') or {}
    if r.get('status') != '000':
        return None
    L = r['list']
    cum = _row(L, 'thstrm_add_amount', Y, 9)
    cum_p = _row(L, 'frmtrm_add_amount', Y - 1, 9)
    q3 = _row(L, 'thstrm_amount', Y, 9)
    Q = dict(quarters(code))
    q2, q3p = Q.get('2Q26') or {}, Q.get('3Q25') or {}
    eps9 = _eps(L, 'thstrm_add_amount')
    eps9p = _eps(L, 'frmtrm_add_amount')
    A = annual(code)
    eps25 = (A.get(2025) or {}).get('eps')
    liab = _bs(L, ['Liabilities'], ('부채총계',), 'thstrm_amount')
    eq_t = _bs(L, ['Equity'], ('자본총계',), 'thstrm_amount')
    eq_p = _bs(L, ['EquityAttributableToOwnersOfParent'], ('지배기업의소유주에게귀속되는자본', '지배기업소유주지분'), 'thstrm_amount')
    eq_p0 = _bs(L, ['EquityAttributableToOwnersOfParent'], ('지배기업의소유주에게귀속되는자본', '지배기업소유주지분'), 'frmtrm_amount')
    cash = _bs(L, ['CashAndCashEquivalents'], ('현금및현금성자산',), 'thstrm_amount')
    rno = next((x.get('rcept_no') for x in L if x.get('rcept_no')), '')
    return {'code': code, 'cum': cum, 'cum_prev': cum_p, 'q3': q3, 'q2': q2, 'q3_prev': q3p, 'eps9': eps9, 'eps9_prev': eps9p,
            'eps25': eps25, 'liab': liab, 'eq_total': eq_t, 'eq_parent': eq_p, 'eq_parent_ye': eq_p0, 'cash': cash,
            'rcept_date': f'{rno[:4]}.{rno[4:6]}.{rno[6:8]}' if len(rno) >= 8 else '', 'fs_div': r.get('fs_div', 'CFS'),
            'quarters': Q}


def won(v):
    return '—' if v is None else f'{v:,.0f}원'


def _cls(a, b):
    p = pct(a, b) or ''
    return ' up' if p.startswith('▲') or p == '흑자전환' else (' dn' if p.startswith('▼') or '적자' in p else '')


def g2_html(f):
    c, p, q3, q2, q3p = f['cum'], f['cum_prev'], f['q3'], f['q2'], f['q3_prev']
    left, right = [], []

    def row(lst, label, val, cls=''):
        lst.append(f'          <div class="dp-row2"><span class="l">{label}</span><span class="v{cls}">{val}</span></div>')
    for k, nm in (('rev', '매출액'), ('oi', '영업이익'), ('nip', '지배주주 순이익')):
        if c.get(k) is None:
            continue
        g = pct(p.get(k), c[k])
        row(left, f'3Q26 누적 {nm}', krw(c[k]) + (f' (전년동기比 {g})' if g else ''), _cls(p.get(k), c[k]))
    if q3.get('oi') is not None:
        parts = [x for x in ((f'3Q25 대비 {pct(q3p.get("oi"), q3["oi"])}' if pct(q3p.get('oi'), q3['oi']) else None),
                             (f'2Q26 대비 {pct(q2.get("oi"), q3["oi"])}' if pct(q2.get('oi'), q3['oi']) else None)) if x]
        row(left, '3Q26 단독 영업이익', krw(q3['oi']) + (f' ({", ".join(parts)})' if parts else ''), _cls(q2.get('oi'), q3['oi']))
    if f['eps9'] is not None:
        row(right, '3Q26 누적 기본EPS' + ('(보통주)' if src_code(f['code']) != f['code'] else ''), f'{won(f["eps9"])} (연환산 {won(f["eps9"] * 4 / 3)})', ' up' if f['eps9'] > 0 else ' dn')
    if f['liab'] is not None and f['eq_total']:
        row(right, '9월 말 부채비율', f'{f["liab"] / f["eq_total"] * 100:.1f}%')
    if f['eq_parent'] is not None:
        g = pct(f['eq_parent_ye'], f['eq_parent'])
        row(right, '9월 말 지배지분', krw(f['eq_parent']) + (f' (작년 말 대비 {g})' if g else ''))
    if f['cash']:
        row(right, '9월 말 현금성자산', krw(f['cash']))
    return ('<div class="dp-g2">\n        <div>\n' + '\n'.join(left) + '\n        </div>\n        <div>\n' + '\n'.join(right)
            + '\n        </div>\n      </div>')


def _replace_g2(Q, new):
    """분기 탭 첫 dp-g2 블록(div 균형으로 끝 찾기)."""
    s = Q.find('<div class="dp-g2">')
    if s < 0:
        return None
    i, depth = s, 0
    for m in re.finditer(r'<div\b|</div>', Q[s:]):
        depth += 1 if m.group(0) == '<div' else -1
        if depth == 0:
            return Q[:s] + new + Q[s + m.end():]
    return None


def apply(code, note, dry=False):
    path = next((os.path.join(STOCKS, f) for f in os.listdir(STOCKS) if re.match(rf'\d{{3}}_{code}\.html$', f)), None)
    if not path:
        return 'skip: 페이지 없음'
    if code in LEGACY_ACCENT:
        return 'skip: 구형 레이아웃'
    f = facts(code)
    if not f:
        return 'skip: 3분기보고서 없음'
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = '\r\n' in raw
    t = raw.replace('\r\n', '\n')
    log = []
    # 1) 탭 이름
    t, n = re.subn(r'(id="dpFundQuarterBtn"[^>]*>)[^<]*(</button>)', rf'\g<1>{TAB}\g<2>', t)
    log.append(f'tab {n}')
    # 2) 분기 탭 수치 행 + 핵심 해설
    q0, e0 = t.find('<div id="dpFundQuarter"'), t.find('<!-- 3. 투자지표')
    if q0 < 0 or e0 < 0:
        return 'skip: 분기 탭 없음'
    Q = t[q0:e0]
    Q2 = _replace_g2(Q, g2_html(f))
    if Q2 is None:
        return 'skip: dp-g2 없음'
    Q = Q2
    core = html.escape(note['core'])
    pat = r'(<div class="dp-insight">\s*<div class="dp-insight-t">)[^<]*(?:반기|분기|1분기)보고서 핵심[^<]*(</div>\s*<div class="dp-insight-b">)[^<]*(</div>)'
    Q, n = re.subn(pat, lambda m: f'{m.group(1)}3분기보고서 핵심 — 전년동기(3Q25 누적) 대비{m.group(2)}{core}{m.group(3)}', Q, count=1)
    if not n:
        return 'skip: 보고서 핵심 해설 못 찾음'
    t = t[:q0] + Q + t[e0:]
    # 3) 투자지표 EPS 카드
    if f['eps9'] is not None:
        t, n = re.subn(r'(<div class="dp-share-l">)(?:1H26|1Q26|2Q26|3Q26 누적) EPS(</div><div class="dp-share-v"[^>]*>)[^<]*(</div><div class="dp-share-s">)[^<]*(</div>)',
                       lambda m: f'{m.group(1)}3Q26 누적 EPS{m.group(2)}{won(f["eps9"])}{m.group(3)}연환산 {won(f["eps9"] * 4 / 3)}{m.group(4)}', t, count=1)
        log.append(f'eps-card {n}')
    # 4) 시계열
    if note.get('tl_title'):
        item = ('      <div class="dp-tl-item">\n        <div class="dp-tl-dot"></div>\n'
                f'        <div class="dp-tl-date">{f["rcept_date"]} (3분기보고서)</div>\n'
                f'        <div class="dp-tl-title">{html.escape(note["tl_title"])}</div>\n'
                f'        <div class="dp-tl-body">{html.escape(note.get("tl_body", ""))}</div>\n      </div>\n')
        old = re.search(r'      <div class="dp-tl-item">\s*<div class="dp-tl-dot"></div>\s*<div class="dp-tl-date">[^<]*\(3분기보고서\)</div>.*?</div>\s*</div>\n', t, re.S)
        if old:
            t = t[:old.start()] + item + t[old.end():]
            log.append('tl replaced')
        else:
            items = list(re.finditer(r'      <div class="dp-tl-item">\s*<div class="dp-tl-dot"></div>\s*<div class="dp-tl-date">([^<]*)</div>.*?</div>\s*</div>\n', t, re.S))
            if items:
                key = f['rcept_date']
                pos = items[-1].end()
                for m in items:
                    dm = re.match(r'(\d{4})\.(\d{2})(?:\.(\d{2}))?', m.group(1).strip())
                    if dm and f'{dm.group(1)}.{dm.group(2)}.{dm.group(3) or "00"}' > key:
                        pos = m.start()
                        break
                t = t[:pos] + item + t[pos:]
                log.append('tl added')
            else:
                log.append('tl: 시계열 없음')
    if not dry:
        out = t.replace('\n', '\r\n') if crlf else t
        open(path, 'wb').write(out.encode('utf-8'))
        log.append('fund_render: ' + str(transform(path, code)))
    return ', '.join(log)


def show(code):
    f = facts(code)
    if not f:
        print(code, '3분기보고서 없음')
        return
    c, p = f['cum'], f['cum_prev']
    print(f'== {code} 공시 {f["rcept_date"]} {f["fs_div"]}')
    for k in ('rev', 'oi', 'pretax', 'nip'):
        print(f'  9M {k}: {krw(p.get(k))} → {krw(c.get(k))} {pct(p.get(k), c.get(k)) or ""}')
    print('  분기 OI:', ' '.join(f'{l}:{krw(r.get("oi"))}' for l, r in f['quarters'].items()))
    print('  분기 매출:', ' '.join(f'{l}:{krw(r.get("rev"))}' for l, r in f['quarters'].items()))
    print('  분기 지배순익:', ' '.join(f'{l}:{krw(r.get("nip"))}' for l, r in f['quarters'].items()))
    print(f'  EPS 9M {won(f["eps9_prev"])} → {won(f["eps9"])} (연환산 {won(f["eps9"] * 4 / 3) if f["eps9"] is not None else "—"}), 2025 EPS {won(f["eps25"])}')
    if f['liab'] is not None and f['eq_total']:
        print(f'  부채비율 {f["liab"] / f["eq_total"] * 100:.1f}%, 지배지분 {krw(f["eq_parent"])} (작년말 {krw(f["eq_parent_ye"])}), 현금 {krw(f["cash"])}')


if __name__ == '__main__':
    if sys.argv[1] == 'facts':
        for c in sys.argv[2:]:
            show(c)
    elif sys.argv[1] == 'apply':
        notes = json.load(open(sys.argv[2], encoding='utf-8'))
        for c, n in notes.items():
            print(c, apply(c, n, dry='--dry' in sys.argv))
