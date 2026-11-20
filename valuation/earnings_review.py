"""분기 실적 리뷰 페이지 생성.

종목 페이지(stocks/*.html)의 const FUND 분기 데이터에서 특이사항(흑자·적자 전환, 이익 급증·급감,
큰 영업외 손익, 8개 분기 최대·최저)을 자동으로 골라 earnings/<slug>.html을 만들고,
earnings/index.html(분기 목록)과 홈(index.html)의 '실적 리뷰' 버튼 링크를 갱신한다.

분기보고서가 새로 나오면:
  1) 종목 페이지를 새 분기로 갱신한다(q3_update.py 등).
  2) data/earnings_review/<slug>.json을 만든다(period, title, themes, notes, exclude). notes는 종목별 한 줄 해설로, 없으면 숫자만 나온다.
  3) python valuation/earnings_review.py <slug>   예: python valuation/earnings_review.py 2026q3
"""
import glob, html, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
os.chdir(ROOT)

MIN_NONOP = 3e10  # 영업외 손익 특이 판정 최소 규모(300억)


def won(v):
    if v is None:
        return '-'
    a = abs(v)
    s = '-' if v < 0 else ''
    if a >= 1e12:
        jo, eok = divmod(round(a / 1e8), 10000)
        return f'{s}{jo}조 {eok:,}억' if eok else f'{s}{jo}조'
    return f'{s}{a / 1e8:,.0f}억'


def pct(cur, base):
    if cur is None or base is None or base <= 0 or cur <= 0:
        return None
    return cur / base - 1


def load_stocks(period):
    out = []
    for p in sorted(glob.glob('stocks/[0-9]*_*.html')):
        t = open(p, encoding='utf-8').read()
        m = re.search(r'const FUND=(\{.*?\});', t)
        if not m:
            continue
        F = json.loads(m.group(1))
        L, q = F.get('qLabels') or [], F.get('q') or {}
        if not L or L[-1] != period or len(L) < 5:
            continue
        nm = re.search(r'<h1[^>]*>([^<]+)', t)
        name = html.unescape(nm.group(1).strip()) if nm else '?'
        if re.search(r'\d?우B?$', name):  # 우선주는 보통주와 실적이 같아 뺀다
            continue
        b = os.path.basename(p)
        code = b.split('_', 1)[1][:-5]

        def g(k, i):
            a = q.get(k) or []
            return a[i] if len(a) >= abs(i) else None
        out.append(dict(code=code, name=name, href='../stocks/' + b, L=L,
                        oi=g('oi', -1), oi_y=g('oi', -5), oi_q=g('oi', -2),
                        rev=g('rev', -1), rev_y=g('rev', -5),
                        pt=g('pretax', -1), nip=g('nip', -1), nip_y=g('nip', -5),
                        ois=[x for x in (q.get('oi') or []) if x is not None]))
    return out


CATS = [
    ('surge', '이익 급증', '영업이익이 전년 같은 분기의 2배 이상'),
    ('turn_loss', '영업 적자 전환', '전년 같은 분기 흑자 → 이번 분기 영업손실'),
    ('nonop_loss', '본업은 버텼지만 영업 밖에서 손실', '영업이익의 50% 이상 영업외 손실'),
    ('nonop_gain', '영업 밖에서 큰 이익', '영업이익의 50% 이상 영업외 이익'),
    ('drop', '이익 급감', '영업이익이 전년 같은 분기의 절반 이하'),
    ('turn_profit', '흑자 전환', '전년 같은 분기 영업손실 → 이번 분기 흑자'),
    ('loss', '적자 지속', '전년·이번 분기 모두 영업손실'),
]


TONE = {'surge': 'good', 'turn_loss': 'bad', 'nonop_loss': 'bad', 'nonop_gain': 'good',
        'drop': 'bad', 'turn_profit': 'good', 'loss': 'bad'}


def classify(s):
    oi, oy, pt = s['oi'], s['oi_y'], s['pt']
    if oi is None or oy is None:
        return None
    nonop = (pt - oi) if pt is not None else 0
    s['nonop'] = nonop
    if oy > 0 > oi:
        return 'turn_loss'
    if oy < 0 < oi:
        return 'turn_profit'
    if oi > 0 and nonop <= -0.5 * oi and -nonop >= MIN_NONOP:
        return 'nonop_loss'
    if nonop >= 0.5 * abs(oi) and nonop >= MIN_NONOP:
        return 'nonop_gain'
    if oi < 0 and oy < 0:
        return 'loss'
    if oy > 0 and oi / oy >= 2:
        return 'surge'
    if oy > 0 and oi / oy <= 0.5:
        return 'drop'
    return None


def badges(s):
    b = []
    o = s['ois']
    if len(o) >= 8 and s['oi'] == max(o) and s['oi'] > 0:
        b.append(('hi', '8분기 최대'))
    if len(o) >= 8 and s['oi'] == min(o):
        b.append(('lo', '8분기 최저'))
    if s['nip'] is not None and s['nip_y'] is not None:
        if s['nip_y'] > 0 > s['nip']:
            b.append(('lo', '순이익 적자 전환'))
        elif s['nip_y'] < 0 < s['nip']:
            b.append(('hi', '순이익 흑자 전환'))
    return b


def yoy_pill(cur, base):
    """영업이익 옆 전년 대비 꼬리표: 배수·증감률, 부호가 바뀌면 전환으로 표시."""
    if cur is None or base is None:
        return ''
    if base < 0 < cur:
        return '<span class="er-chg up">흑자 전환</span>'
    if cur < 0 < base:
        return '<span class="er-chg dn">적자 전환</span>'
    if cur < 0 and base < 0:
        return f'<span class="er-chg {"up" if cur > base else "dn"}">적자 {"축소" if cur > base else "확대"}</span>'
    r = pct(cur, base)
    if r is None:
        return ''
    if r >= 1:
        return f'<span class="er-chg up">{cur / base:.1f}배</span>'
    return f'<span class="er-chg {"up" if r >= 0 else "dn"}">{"▲" if r >= 0 else "▼"} {abs(r) * 100:.1f}%</span>'


def row_html(s, note, period):
    e = html.escape
    bd = ''.join(f'<span class="er-bd {k}">{e(t)}</span>' for k, t in badges(s))
    nonop = s.get('nonop') or 0
    nonop_cls = 'up' if nonop > 0 else 'dn'
    note_html = f'<p class="er-note">{e(note)}</p>' if note else ''
    oi_cls = 'dn' if (s['oi'] or 0) < 0 else ''
    nip_cls = 'dn' if (s['nip'] or 0) < 0 else ''
    return f'''<li class="er-row">
  <div class="er-row-h"><a href="{e(s['href'])}">{e(s['name'])}</a></div>{f'<div class="er-bds">{bd}</div>' if bd else ''}
  <div class="er-hero"><span class="er-hero-l">{e(period)} 영업이익</span><span class="er-hero-v {oi_cls}">{won(s['oi'])}</span>{yoy_pill(s['oi'], s['oi_y'])}</div>
  <dl class="er-m">
    <div><dt>전년 동기 영업이익</dt><dd>{won(s['oi_y'])}</dd></div>
    <div><dt>영업외 손익</dt><dd class="{nonop_cls}">{"+" if nonop > 0 else ""}{won(nonop)}</dd></div>
    <div><dt>지배주주 순이익</dt><dd class="{nip_cls}">{won(s['nip'])}</dd></div>
  </dl>{note_html}
</li>'''


def list_html(rows, period):
    return f'<ul class="er-list">\n{rows}\n</ul>\n'


STYLE = '''
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--t-bg,#14131c);color:var(--t-fg,#eee);font-family:var(--t-font,'Noto Sans KR',sans-serif);line-height:1.6}
a{color:inherit}
.er{max-width:1280px;margin:0 auto;padding:20px 16px 60px}
.er-back{display:inline-block;font-size:13px;font-weight:700;color:var(--t-accent);text-decoration:none;margin-bottom:18px}
.er-eyebrow{font-size:12px;color:var(--t-accent);font-weight:700;letter-spacing:.04em}
.er h1{font-size:26px;font-weight:900;letter-spacing:-.03em;line-height:1.25;margin:4px 0 6px}
.er-sub{font-size:13px;color:var(--t-mute)}
.er-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0}
.er-kpi{background:var(--t-card);border:1px solid var(--t-line);border-radius:12px;padding:12px 14px}
.er-kpi dt{font-size:12px;color:var(--t-mute)}
.er-kpi dd{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:2px}
.er-kpi small{display:block;font-size:11.5px;color:var(--t-mute);font-weight:500}
.er h2{font-size:19px;font-weight:800;letter-spacing:-.02em;margin:40px 0 12px;scroll-margin-top:64px}
.er-h2-sub{font-size:12.5px;color:var(--t-mute);font-weight:500;margin-left:8px}
.er-sec{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px;margin:44px 0 14px;padding-left:12px;border-left:4px solid var(--t-edge);scroll-margin-top:64px}
.er-sec.good{border-left-color:var(--t-up)}.er-sec.bad{border-left-color:var(--t-down)}
.er-sec h2{margin:0}
.er-sec .n{font-size:13px;font-weight:800;color:var(--t-fg2);font-variant-numeric:tabular-nums}
.er-sec p{flex-basis:100%;font-size:13px;color:var(--t-mute)}
.er-themes{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.er-theme{background:var(--t-card);border:1px solid var(--t-line);border-radius:12px;padding:14px 16px}
.er-theme b{display:block;font-size:14.5px;margin-bottom:4px}
.er-theme p{font-size:13.5px;color:var(--t-fg2)}
.er-nav{position:sticky;top:0;z-index:5;background:var(--t-bg);padding:10px 0;border-bottom:1px solid var(--t-line)}
.er-chips{display:flex;flex-wrap:wrap;gap:6px}
.er-chips a{font-size:13px;text-decoration:none;padding:6px 12px;border:1px solid var(--t-edge);border-radius:999px;color:var(--t-fg2)}
.er-chips a:hover{border-color:var(--t-accent);color:var(--t-fg)}
.er-chips span{color:var(--t-mute);margin-left:4px;font-variant-numeric:tabular-nums}
.er-list{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.er-row{display:flex;flex-direction:column;background:var(--t-card);border:1px solid var(--t-line);border-radius:14px;padding:14px 16px;min-width:0}
.er-row:hover{border-color:var(--t-edge)}
.er-row-h a{font-size:16px;font-weight:800;letter-spacing:-.02em;text-decoration:none;line-height:1.35}
.er-row-h a:hover{color:var(--t-accent)}
.er-bds{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
.er-bd{font-size:10.5px;font-weight:700;padding:0 7px;border-radius:999px;border:1px solid;white-space:nowrap;line-height:1.6}
.er-bd.hi{color:var(--t-up);border-color:currentColor}
.er-bd.lo{color:var(--t-down);border-color:currentColor}
.er-hero{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;margin-top:10px}
.er-hero-l{flex-basis:100%;font-size:11.5px;color:var(--t-mute)}
.er-hero-v{font-size:21px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.25}
.er-chg{font-size:12px;font-weight:800;padding:1px 8px;border-radius:6px;background:var(--t-card2);white-space:nowrap}
.er-m{margin-top:10px;padding-top:8px;border-top:1px solid var(--t-line);display:grid;gap:3px}
.er-m div{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.er-m dt{font-size:12px;color:var(--t-mute);white-space:nowrap}
.er-m dd{font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.er-note{font-size:13px;color:var(--t-fg2);margin-top:10px;padding:9px 11px;background:var(--t-bg);border-radius:8px;line-height:1.6}
.up{color:var(--t-up)}.dn{color:var(--t-down)}
.er-foot{font-size:12px;color:var(--t-mute);margin-top:36px;line-height:1.7}
.er-hub{list-style:none;display:grid;gap:10px;margin-top:18px}
.er-hub a{display:block;background:var(--t-card);border:1px solid var(--t-line);border-radius:12px;padding:16px 18px;text-decoration:none}
.er-hub a:hover{border-color:var(--t-accent)}
.er-hub b{font-size:16px}
.er-hub span{display:block;font-size:13px;color:var(--t-mute);margin-top:2px}
@media (max-width:1180px){.er-list{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:880px){.er-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){
  .er h1{font-size:22px}
  .er-kpis{grid-template-columns:repeat(2,1fr)}
  .er-themes{grid-template-columns:1fr}
  .er-kpi dd{font-size:17px}
  .er-chips{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
  .er-chips::-webkit-scrollbar{display:none}
  .er-chips a{flex:0 0 auto;white-space:nowrap}
}
@media (max-width:520px){.er-list{grid-template-columns:1fr}}
'''


def page(title, desc, body):
    e = html.escape
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)} — 가치를말하다</title>
<meta name="description" content="{e(desc)}">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4973537494905596" crossorigin="anonymous"></script>
<style>{STYLE}</style>
<link rel="stylesheet" href="../css/theme.css">
</head>
<body>
<main class="er">
{body}
</main>
</body>
</html>
'''


def build(slug):
    cfg = json.load(open(f'data/earnings_review/{slug}.json', encoding='utf-8'))
    period = cfg['period']
    excl = cfg.get('exclude', {})
    notes = cfg.get('notes', {})
    stocks = [s for s in load_stocks(period) if s['code'] not in excl]
    groups = {k: [] for k, _, _ in CATS}
    for s in stocks:
        c = classify(s)
        if c:
            groups[c].append(s)
    for k in groups:
        groups[k].sort(key=lambda s: -abs(s['oi'] or 0))
    n_flag = sum(len(v) for v in groups.values())

    both = [s for s in stocks if s['oi'] is not None and s['oi_y'] is not None]
    tot, tot_y = sum(s['oi'] for s in both), sum(s['oi_y'] for s in both)
    big = {'005930', '000660'}
    ex, ex_y = sum(s['oi'] for s in both if s['code'] not in big), sum(s['oi_y'] for s in both if s['code'] not in big)
    up = sum(1 for s in both if s['oi'] > s['oi_y'])

    e = html.escape
    kpis = f'''<dl class="er-kpis">
  <div class="er-kpi"><dt>집계 종목</dt><dd>{len(both)}개</dd><small>특이사항 {n_flag}개</small></div>
  <div class="er-kpi"><dt>합산 영업이익</dt><dd>{won(tot)}</dd><small>전년 동기 {won(tot_y)} · {tot / tot_y:.1f}배</small></div>
  <div class="er-kpi"><dt>삼성전자·하이닉스 제외</dt><dd>{won(ex)}</dd><small>전년 동기 대비 {"▲" if ex >= ex_y else "▼"}{abs(ex / ex_y - 1) * 100:.1f}%</small></div>
  <div class="er-kpi"><dt>영업이익 증가</dt><dd>{up}개</dd><small>감소 {len(both) - up}개</small></div>
</dl>'''
    themes = ''.join(f'<div class="er-theme"><b>{e(a)}</b><p>{e(b)}</p></div>' for a, b in cfg.get('themes', []))
    chips = ''.join(f'<a href="#{k}">{e(n)}<span>{len(groups[k])}</span></a>' for k, n, _ in CATS if groups[k])
    secs = ''
    for k, n, d in CATS:
        if not groups[k]:
            continue
        rows = '\n'.join(row_html(s, notes.get(s['code']), period) for s in groups[k])
        secs += (f'<div class="er-sec {TONE[k]}" id="{k}"><h2>{e(n)}</h2><span class="n">{len(groups[k])}개</span><p>{e(d)}</p></div>\n'
                 + list_html(rows, period))
    ex_txt = ' '.join(f'{e(c)}: {e(v)}.' for c, v in excl.items())
    body = f'''<a class="er-back" href="index.html">← 분기 실적 리뷰 목록</a>
<div class="er-eyebrow">{e(cfg.get('report', ''))} · {e(cfg.get('range', ''))}</div>
<h1>{e(cfg['title'])}</h1>
<p class="er-sub">KOSPI 시가총액 상위 종목 · DART 연결 재무제표 3개월 실적 기준 · {e(cfg.get('published', ''))} 작성</p>
{kpis}
<h2>이번 분기 큰 흐름</h2>
<div class="er-themes">{themes}</div>
<h2>유형별 특이 종목</h2>
<nav class="er-nav" aria-label="유형 바로가기"><div class="er-chips">{chips}</div></nav>
{secs}
<p class="er-foot">영업이익·영업외 손익·지배주주 순이익은 {e(period)} 3개월(분기 단독) 값이고, 전년 동기는 1년 전 같은 분기다. 영업외 손익은 세전이익에서 영업이익을 뺀 값이다. 우선주는 보통주와 실적이 같아 뺐다. 종목은 유형당 하나로만 분류했고(위 순서가 우선), 유형 안에서는 영업이익 규모 순이다. 해설의 "~로 보인다"는 공시 주석으로 확인하지 않은 추정이다. 제외: {ex_txt} 투자 권고가 아니다.</p>'''
    os.makedirs('earnings', exist_ok=True)
    desc = f'{cfg["title"]}: 이익 급증·적자 전환·영업외 손익 등 특이 종목 {n_flag}개'
    open(f'earnings/{slug}.html', 'w', encoding='utf-8', newline='\n').write(page(cfg['title'], desc, body))
    return cfg, n_flag


def build_hub():
    items = []
    for f in sorted(glob.glob('data/earnings_review/*.json'), reverse=True):
        slug = os.path.basename(f)[:-5]
        if not os.path.exists(f'earnings/{slug}.html'):
            continue
        cfg = json.load(open(f, encoding='utf-8'))
        items.append((slug, cfg))
    e = html.escape
    lis = ''.join(f'<li><a href="{slug}.html"><b>{e(c["title"])}</b><span>{e(c.get("report", ""))} · {e(c.get("range", ""))} · {e(c.get("published", ""))} 작성</span></a></li>' for slug, c in items)
    body = f'''<a class="er-back" href="../index.html">← 홈으로</a>
<h1>분기 실적 리뷰</h1>
<p class="er-sub">분기·반기·사업보고서가 나올 때마다 KOSPI 상위 종목의 실적 특이사항을 정리합니다.</p>
<ul class="er-hub">{lis}</ul>'''
    open('earnings/index.html', 'w', encoding='utf-8', newline='\n').write(page('분기 실적 리뷰', '분기보고서마다 정리하는 KOSPI 상위 종목 실적 특이사항', body))
    return items


def update_home(slug, cfg):
    p = 'index.html'
    raw = open(p, 'rb').read().decode('utf-8')
    new = f"const EARNINGS_LATEST = {json.dumps({'label': cfg['period'], 'href': f'earnings/{slug}.html'}, ensure_ascii=False)};"
    s, n = re.subn(r'const EARNINGS_LATEST = \{.*?\};', new, raw)
    if n != 1:
        print('WARN index.html: EARNINGS_LATEST 없음 — 홈 버튼 미갱신')
        return
    if s != raw:
        open(p, 'wb').write(s.encode('utf-8'))


if __name__ == '__main__':
    slug = sys.argv[1] if len(sys.argv) > 1 else sorted(os.path.basename(f)[:-5] for f in glob.glob('data/earnings_review/*.json'))[-1]
    cfg, n = build(slug)
    items = build_hub()
    update_home(items[0][0], items[0][1])
    print(f'earnings/{slug}.html 특이 종목 {n}개, 목록 {len(items)}개 분기')
