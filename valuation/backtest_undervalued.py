"""분기보고서 마감일 기준 저평가 종목 백테스트 페이지(earnings/backtest.html) 생성.

- 분기: data/earnings_review/<slug>.json의 period(예: 1Q26)마다 한 번씩.
- 매수일: 법정 제출 마감일(분기·반기 = 분기 말 + 45일, 사업보고서 = 결산 후 90일). 그날이 휴장이면 다음 거래일 종가.
- 저평가: 매수일 종가 < 그 분기 말 재무제표로 계산한 내재가치 하단(종목 페이지 data-bands, 사이트 '저평가' 배지와 같은 기준).
  범위 안(하단~상단)·고평가(상단 초과)도 함께 계산해 비교한다.
- 수익률: 매수일 종가 → 최근 종가, 동일 가중, 배당 제외. 비교 지수는 KOSPI.
- 시세: 네이버 일별 종가(api.stock.naver.com chart). 우선주는 보통주와 겹쳐 뺀다.

부수 효과: 분기별 마감일 매수가·현재가를 data/earnings_prices.json에 쓰고 earnings/<분기>.html을 다시 만든다.

사용: python valuation/backtest_undervalued.py
"""
import datetime as dt, glob, html, json, os, re, statistics as st, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import earnings_review as ER  # noqa: E402  (page()·STYLE 재사용, ROOT로 chdir)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
GROUPS = [('under', '저평가', '하단 미만'), ('in', '범위 안', '하단~상단'), ('over', '고평가', '상단 초과')]


def get_json(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=20) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:  # noqa: BLE001
            if i == 2:
                print(f'WARNING 시세 조회 실패 {url}: {e}', file=sys.stderr)
            time.sleep(1 + i)
    return None


def daily(path, start, end):
    j = get_json(f'https://api.stock.naver.com/chart/domestic/{path}/day?startDateTime={start:%Y%m%d}0000&endDateTime={end:%Y%m%d}2359')
    time.sleep(0.08)
    return {x['localDate']: float(x['closePrice']) for x in (j or []) if x.get('closePrice')}


def period_info(period):
    """'1Q26' → (분기 말 'YYYY-MM', 법정 마감일, 보고서 이름)."""
    q, yy = int(period[0]), 2000 + int(period[2:])
    m = q * 3
    qend = dt.date(yy, m, 30 if m in (6, 9) else 31)
    days = 90 if q == 4 else 45
    name = {1: '1분기보고서', 2: '반기보고서', 3: '3분기보고서', 4: '사업보고서'}[q]
    return f'{yy}-{m:02d}', qend + dt.timedelta(days=days), name


def load_universe():
    out = []
    for p in sorted(glob.glob('stocks/[0-9]*_*.html')):
        t = open(p, encoding='utf-8').read()
        m = re.search(r"data-bands='([^']*)'", t)
        if not m:
            continue
        nm = re.search(r'<h1[^>]*>([^<]+)', t)
        name = html.unescape(nm.group(1).strip()) if nm else '?'
        if re.search(r'\d?우B?$', name):
            continue
        b = os.path.basename(p)
        out.append(dict(code=b.split('_', 1)[1][:-5], name=name, href='../stocks/' + b,
                        bands={x[0]: x for x in json.loads(m.group(1))}))
    return out


def ffill_ratio(px, dates, d0):
    """d0 종가 대비 각 날짜 비율(휴장·거래정지일은 직전 값)."""
    base, last, out = px[d0], px[d0], []
    for d in dates:
        last = px.get(d, last)
        out.append(last / base)
    return out


def chart_svg(series, dates):
    """선은 늘어나는 SVG(높이 고정), 축 글자는 HTML로 얹어 화면 폭과 관계없이 같은 크기."""
    W, H = 1000, 200
    vals = [v for _, _, s in series for v in s]
    lo, hi = min(vals + [1]), max(vals + [1])
    pad = (hi - lo) * 0.08 or 0.05
    lo, hi = lo - pad, hi + pad
    n = len(dates)
    X = lambda i: W * (i / max(n - 1, 1))
    Y = lambda v: H * (hi - v) / (hi - lo)
    svg = [f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="매수일 대비 누적 수익률">']
    ylab = []
    step = 0.05 if hi - lo < 0.4 else 0.1
    v = round(lo / step) * step
    while v <= hi + 1e-9:
        if v >= lo:
            svg.append(f'<line x1="0" x2="{W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="{"bt-zero" if abs(v - 1) < 1e-9 else "bt-grid"}"/>')
            ylab.append(f'<span style="top:{Y(v) / H * 100:.2f}%">{(v - 1) * 100:+.0f}%</span>')
        v += step
    for cls, _, s in series:
        pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(s))
        svg.append(f'<polyline class="bt-l {cls}" points="{pts}"/>')
    svg.append('</svg>')
    xlab = ''.join(f'<span style="left:{X(i) / W * 100:.2f}%" class="{"s" if i == 0 else "e" if i == n - 1 else "m"}">{dates[i][4:6]}.{dates[i][6:]}</span>'
                   for i in sorted({0, n - 1, n // 2}))
    return (f'<div class="bt-chart"><div class="bt-y">{"".join(ylab)}</div>'
            f'<div class="bt-plot">{"".join(svg)}</div><div class="bt-x">{xlab}</div></div>')


def fmt_pct(r, cls=True):
    if r is None:
        return '-'
    s = f'{r * 100:+.1f}%'
    return f'<span class="{"up" if r > 0 else "dn" if r < 0 else ""}">{s}</span>' if cls else s


STYLE_BT = '''
.bt-tbl{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}
.bt-wrap{overflow-x:auto;background:var(--t-card);border:1px solid var(--t-line);border-radius:12px}
.bt-tbl th,.bt-tbl td{padding:10px 12px;text-align:right;border-bottom:1px solid var(--t-line);white-space:nowrap}
.bt-tbl th:first-child,.bt-tbl td:first-child{text-align:left}
.bt-tbl thead th{font-size:12px;color:var(--t-mute);font-weight:600;background:var(--t-card2)}
.bt-tbl tbody tr:last-child td{border-bottom:0}
.bt-tbl td.hl{font-weight:800}
.bt-tbl small{display:block;font-size:11px;color:var(--t-mute);font-weight:500}
.bt-q{background:var(--t-card);border:1px solid var(--t-line);border-radius:14px;padding:16px 18px;margin-top:14px;scroll-margin-top:16px}
.bt-q-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
.bt-q-h h3{font-size:17px;font-weight:800}
.bt-q-h span{font-size:12.5px;color:var(--t-mute)}
.bt-q-h a{font-size:12.5px;color:var(--t-accent);text-decoration:none;margin-left:auto}
.bt-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
.bt-stat{background:var(--t-bg);border-radius:10px;padding:10px 12px}
.bt-stat dt{font-size:11.5px;color:var(--t-mute)}
.bt-stat dd{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums}
.bt-stat small{display:block;font-size:11px;color:var(--t-mute)}
.bt-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--t-fg2);margin-top:6px}
.bt-legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.bt-chart{display:grid;grid-template-columns:44px 1fr;grid-template-rows:200px 22px;margin-top:10px}
.bt-y{position:relative}
.bt-y span,.bt-x span{position:absolute;font-size:11px;color:var(--t-mute);font-variant-numeric:tabular-nums;white-space:nowrap}
.bt-y span{right:8px;transform:translateY(-50%)}
.bt-plot svg{width:100%;height:100%;display:block;overflow:visible}
.bt-x{position:relative;grid-column:2}
.bt-x span{top:5px}.bt-x .m{transform:translateX(-50%)}.bt-x .e{transform:translateX(-100%)}
.bt-grid{stroke:var(--t-line);stroke-width:1;vector-effect:non-scaling-stroke}
.bt-zero{stroke:var(--t-edge);stroke-width:1.2;stroke-dasharray:4 3;vector-effect:non-scaling-stroke}
.bt-l{fill:none;stroke-width:2.2;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.bt-l.under,.bt-legend .under{stroke:var(--t-accent);background:var(--t-accent)}
.bt-l.over,.bt-legend .over{stroke:var(--t-down);background:var(--t-down)}
.bt-l.kospi,.bt-legend .kospi{stroke:var(--t-mute);background:var(--t-mute);stroke-dasharray:5 4}
.bt-plist{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 22px;margin-top:12px;padding-top:6px;border-top:1px solid var(--t-line)}
.bt-ptbl{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;align-self:start}
.bt-ptbl th{font-size:11px;color:var(--t-mute);font-weight:600;text-align:right;padding:7px 6px;border-bottom:1px solid var(--t-line);white-space:nowrap}
.bt-ptbl td{text-align:right;padding:5px 6px;border-bottom:1px solid var(--t-line);white-space:nowrap;color:var(--t-fg2)}
.bt-ptbl th:first-child,.bt-ptbl td:first-child{text-align:left;padding-left:0}
.bt-ptbl th:last-child,.bt-ptbl td:last-child{padding-right:0}
.bt-ptbl tbody tr:last-child td{border-bottom:0}
.bt-ptbl td:first-child{max-width:130px;overflow:hidden;text-overflow:ellipsis}
.bt-ptbl a{text-decoration:none;font-weight:700;color:var(--t-fg)}
.bt-ptbl a:hover{color:var(--t-accent)}
.bt-ptbl td.r{font-weight:800}
.bt-ptbl td.m{color:var(--t-mute);font-size:12px}
.bt-short{font-size:12.5px;color:var(--t-mute);margin-top:8px}
.bt-notes{margin-top:10px;padding-left:18px;font-size:13px;color:var(--t-fg2);line-height:1.7}
@media (max-width:900px){.bt-plist{grid-template-columns:1fr}}
@media (max-width:640px){.bt-stats{grid-template-columns:repeat(2,1fr)}}
'''


def main():
    t0 = time.time()
    cfgs = []
    for f in sorted(glob.glob('data/earnings_review/*.json')):
        c = json.load(open(f, encoding='utf-8'))
        qe, dl, rep = period_info(c['period'])
        cfgs.append(dict(slug=os.path.basename(f)[:-5], period=c['period'], qend=qe, deadline=dl, report=rep))
    if not cfgs:
        print('WARNING 분기 설정 없음')
        return
    uni = load_universe()
    start = min(c['deadline'] for c in cfgs) - dt.timedelta(days=7)
    end = dt.date.today()
    kospi = daily('index/KOSPI', start, end)
    if not kospi:
        print('ERROR KOSPI 시세 없음 — 중단')
        sys.exit(1)
    kdates = sorted(kospi)
    last = kdates[-1]
    px = {}
    for u in uni:
        px[u['code']] = daily(f'item/{u["code"]}', start, end)
    # 실적 리뷰 카드(매수가·현재가)용: 내재가치 밴드가 없는 종목 페이지도 시세를 받는다
    for b in sorted(glob.glob('stocks/[0-9]*_*.html')):
        code = os.path.basename(b).split('_', 1)[1][:-5]
        if code not in px:
            px[code] = daily(f'item/{code}', start, end)

    quarters = []
    for c in cfgs:
        dstr = f'{c["deadline"]:%Y%m%d}'
        entry = next((d for d in kdates if d >= dstr), None)
        if not entry or entry > last:
            continue  # 마감일이 아직 안 왔다
        dates = [d for d in kdates if d >= entry]
        g = {k: [] for k, _, _ in GROUPS}
        for u in uni:
            b = u['bands'].get(c['qend'])
            p = px.get(u['code']) or {}
            if not b or b[1] is None or entry not in p or last not in p:
                continue
            p0 = p[entry]
            k = 'under' if p0 < b[1] else ('over' if p0 > b[2] else 'in')
            g[k].append(dict(u, p0=p0, p1=p[last], ret=p[last] / p0 - 1, low=b[1], high=b[2],
                             disc=(p0 / b[1] - 1) if b[1] else None, path=ffill_ratio(p, dates, entry)))
        kr = kospi[last] / kospi[entry] - 1
        allr = [x['ret'] for k in g for x in g[k]]
        stats = {}
        for k, _, _ in GROUPS:
            rs = [x['ret'] for x in g[k]]
            stats[k] = dict(n=len(rs), mean=st.mean(rs) if rs else None, med=st.median(rs) if rs else None,
                            win=(sum(r > 0 for r in rs) / len(rs)) if rs else None,
                            beat=(sum(r > kr for r in rs) / len(rs)) if rs else None)
        kpath = [kospi[d] / kospi[entry] for d in dates]
        series = [('kospi', 'KOSPI', kpath)]
        for k in ('over', 'under'):
            if g[k]:
                series.append((k, k, [st.mean(x['path'][i] for x in g[k]) for i in range(len(dates))]))
        quarters.append(dict(c, entry=entry, dates=dates, g=g, stats=stats, kospi=kr,
                             all_mean=st.mean(allr) if allr else None, n_all=len(allr), series=series,
                             days=len(dates) - 1, k0=kospi[entry], k1=kospi[last]))

    # 분기 실적 리뷰 카드에 넣을 마감일 매수가·현재가 → data/earnings_prices.json, 리뷰 페이지 재생성
    ep = {}
    for q in quarters:
        ep[q['slug']] = dict(entry=q['entry'], last=last,
                             px={c: [p[q['entry']], p[last]] for c, p in px.items() if q['entry'] in p and last in p})
    json.dump(ep, open('data/earnings_prices.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    for q in quarters:
        ER.build(q['slug'])

    e = html.escape
    fwon = lambda v: f'{v:,.0f}'
    fd = lambda d: f'{d[:4]}.{d[4:6]}.{d[6:]}'
    # 요약 표
    trs = ''
    for q in quarters:
        s = q['stats']
        cells = ''.join(
            f'<td class="{"hl" if k == "under" else ""}">{fmt_pct(s[k]["mean"])}<small>{s[k]["n"]}개 · KOSPI 초과 {s[k]["beat"] * 100:.0f}%</small></td>'
            if s[k]['n'] else '<td>-</td>' for k, _, _ in GROUPS)
        trs += (f'<tr><td><a href="#{q["slug"]}">{e(q["period"])}</a><small>{e(q["report"])} · 매수 {fd(q["entry"])}</small></td>'
                f'<td>{fmt_pct(q["kospi"])}<small>{fwon(q["k0"])} → {fwon(q["k1"])}</small></td><td>{fmt_pct(q["all_mean"])}<small>{q["n_all"]}개</small></td>{cells}</tr>')
    table = ('<div class="bt-wrap"><table class="bt-tbl"><thead><tr><th>분기 (매수일)</th><th>KOSPI</th><th>전체 평균</th>'
             + ''.join(f'<th>{n}<small>{d}</small></th>' for _, n, d in GROUPS) + f'</tr></thead><tbody>{trs}</tbody></table></div>')
    # 분기별 상세
    secs = ''
    for q in reversed(quarters):
        s, u = q['stats'], q['stats']['under']
        diff = (u['mean'] - q['kospi']) if u['mean'] is not None else None
        stats = f'''<dl class="bt-stats">
  <div class="bt-stat"><dt>저평가 평균</dt><dd>{fmt_pct(u["mean"])}</dd><small>중앙값 {fmt_pct(u["med"], False)} · {u["n"]}개</small></div>
  <div class="bt-stat"><dt>KOSPI 대비</dt><dd>{fmt_pct(diff)}</dd><small>KOSPI {fmt_pct(q["kospi"], False)} ({fwon(q["k0"])} → {fwon(q["k1"])})</small></div>
  <div class="bt-stat"><dt>오른 종목 비율</dt><dd>{(u["win"] or 0) * 100:.0f}%</dd><small>KOSPI보다 나은 비율 {(u["beat"] or 0) * 100:.0f}%</small></div>
  <div class="bt-stat"><dt>고평가 평균</dt><dd>{fmt_pct(s["over"]["mean"])}</dd><small>{s["over"]["n"]}개 · 범위 안 {fmt_pct(s["in"]["mean"], False)}</small></div>
</dl>'''
        legend = ('<div class="bt-legend"><span><i class="under"></i>저평가 (동일 가중)</span>'
                  '<span><i class="over"></i>고평가 (동일 가중)</span><span><i class="kospi"></i>KOSPI</span></div>')
        chart = chart_svg(q['series'], q['dates']) if len(q['dates']) > 1 else ''
        rows = [f'<tr><td><a href="{e(x["href"])}">{e(x["name"])}</a></td><td>{fwon(x["p0"])}</td><td>{fwon(x["p1"])}</td>'
                f'<td class="r">{fmt_pct(x["ret"])}</td><td class="m">{x["disc"] * 100:+.0f}%</td></tr>'
                for x in sorted(q['g']['under'], key=lambda x: -x['ret'])]
        half = (len(rows) + 1) // 2
        thead = ('<thead><tr><th>종목</th><th>매수가</th><th>현재가</th><th>수익률</th>'
                 '<th title="매수가가 내재가치 하단보다 낮았던 정도">하단 대비</th></tr></thead>')
        items = ''.join(f'<table class="bt-ptbl">{thead}<tbody>{"".join(part)}</tbody></table>'
                        for part in (rows[:half], rows[half:]) if part)
        short = f'<p class="bt-short">보유 기간이 {q["days"]}거래일뿐이라 아직 판단하기 이릅니다.</p>' if q['days'] < 20 else ''
        secs += f'''<section class="bt-q" id="{q["slug"]}">
<div class="bt-q-h"><h3>{e(q["period"])} · {e(q["report"])}</h3><span>마감일 {q["deadline"]:%Y.%m.%d} → 매수 {fd(q["entry"])} 종가 · {q["days"]}거래일 보유</span><a href="{e(q["slug"])}.html">실적 리뷰 →</a></div>
{stats}{short}{legend}{chart}
<div class="bt-plist">{items}</div>
</section>
'''
    body = f'''<a class="er-back" href="index.html">← 분기 실적 리뷰 목록</a>
<div class="er-eyebrow">백테스트 · {fd(last)} 종가 기준 자동 갱신</div>
<h1>분기보고서 저평가 종목 백테스트</h1>
<p class="er-sub">분기보고서 제출 마감일에 사이트 기준 '저평가' 종목을 사서 지금까지 들고 있었다면?</p>
<div class="er-sec good" id="summary"><h2>분기별 결과</h2><p>매수일 종가 → {fd(last)} 종가, 동일 가중 평균 수익률. KOSPI 아래 작은 글씨는 매수일 → 현재 지수, 그룹 아래는 종목 수와 KOSPI보다 나은 종목 비율.</p></div>
{table}
<div class="er-sec" id="detail"><h2>분기별 상세</h2><p>저평가 종목 표의 매수가는 매수일 종가, 현재가는 최근 종가. '하단 대비 −20%'는 매수가가 내재가치 하단보다 20% 낮았다는 뜻.</p></div>
{secs}
<div class="er-sec" id="method"><h2>계산 방식과 한계</h2></div>
<ul class="bt-notes">
<li>매수일: 분기·반기보고서는 분기 말 + 45일, 사업보고서는 결산 후 90일인 법정 제출 마감일. 휴장일이면 다음 거래일 종가.</li>
<li>저평가: 매수일 종가가 그 분기 말 재무제표로 계산한 내재가치 하단보다 낮은 종목(종목 페이지 '내재가치 평가'의 저평가 배지와 같은 기준). 고평가는 상단 초과.</li>
<li>수익률은 동일 가중 단순 보유 수익률이며 배당·거래비용·세금은 넣지 않았다. 시세는 네이버 일별 종가.</li>
<li>대상은 현재 KOSPI 시가총액 상위 종목 페이지(우선주 제외)라, 그 사이 순위에서 밀려난 종목은 빠져 있다(생존 편향).</li>
<li>분기별 내재가치는 그 분기 재무제표로 계산하지만 계산 방식은 현재 기준이라, 당시 사이트에 표시됐던 값과 다를 수 있다.</li>
<li>과거 성과가 미래 수익을 보장하지 않으며 투자 권고가 아니다.</li>
</ul>'''
    page = ER.page('분기보고서 저평가 종목 백테스트', '분기보고서 마감일 기준 저평가 종목을 지금까지 보유했을 때의 수익률', body)
    page = page.replace('</style>', STYLE_BT + '</style>', 1)
    os.makedirs('earnings', exist_ok=True)
    open('earnings/backtest.html', 'w', encoding='utf-8', newline='\n').write(page)
    summ = ', '.join(f'{q["period"]} 저평가 {fmt_pct(q["stats"]["under"]["mean"], False)}/KOSPI {fmt_pct(q["kospi"], False)}' for q in quarters)
    print(f'완료: {len(quarters)}개 분기, 기준 {last}, {summ}, 소요 {time.time() - t0:.0f}초')


if __name__ == '__main__':
    main()
