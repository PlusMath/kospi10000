"""종목 페이지 '기본적 분석' 탭을 DART 기준 사업보고서 5개년 · 분기 2개년(지표 버튼) 구조로 변환.

python valuation/fund_render.py [--dry] [코드 ...]
- 처음 실행: 기존 연간·분기 차트, 'EPS N개년 추이' 카드를 표준 구조로 교체(사업부문·해설·지표 행은 유지)
- 이후 실행: 마커(fund5y / fundq / fund-report) 사이만 다시 생성 → 새 분기 공시 반영용
"""
import os, re, sys, json, html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund_report import annual, quarters, src_code, TYPES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS = os.path.join(ROOT, 'stocks')
QM = [('rev', '매출액'), ('oi', '영업이익'), ('pretax', '세전이익'), ('ni', '순이익'), ('nip', '지배주주순이익')]
# 사업연도가 온전하지 않은 해 제외(SK스퀘어: 2021년 11월 분할 신설 → 2021년은 2개월치)
MIN_YEAR = {'402340': 2022}
JS_START, JS_END = '// -- fund-report:start (valuation/fund_render.py)', '// -- fund-report:end'


# ── 숫자 표기 ──
def krw(v):
    """원 → '8조 5,177억' / '3,413억' / '-1조 734억'."""
    if v is None:
        return '—'
    s = '-' if v < 0 else ''
    e = round(abs(v) / 1e8)
    jo, eok = divmod(e, 10000)
    if jo and eok:
        return f'{s}{jo}조 {eok:,}억'
    if jo:
        return f'{s}{jo}조'
    return f'{s}{eok:,}억'


def pct(a, b):
    """a→b 변화. 부호가 바뀌면 흑자/적자 전환."""
    if a is None or b is None:
        return None
    if a > 0 and b > 0:
        r = (b / a - 1) * 100
        return f'{"▲" if r >= 0 else "▼"}{abs(r):.1f}%'
    if a <= 0 < b:
        return '흑자전환'
    if a > 0 >= b:
        return '적자전환'
    return '적자지속' if b < a else '적자축소'


def won(v):
    return '—' if v is None else f'{v:,.0f}원'


# ── HTML 조각 ──
def annual_charts_html(A):
    has_rev = sum(1 for r in A.values() if r['rev'] is not None) >= max(2, len(A) - 1)
    out = ['<!-- fund5y:start -->']
    if has_rev:
        out += ['      <div class="dp-secl">매출액 추이</div>',
                '      <svg id="fundAnnualChart" viewBox="0 0 680 150" width="100%" style="display:block;margin-bottom:16px;"></svg>']
    out += ['      <div class="dp-secl">영업이익·지배주주순이익 추이</div>',
            '      <svg id="fundAnnualChart2" viewBox="0 0 680 160" width="100%" style="display:block;margin-bottom:6px;"></svg>',
            f'      <div style="font-size:10.5px;color:var(--dp-text4);margin-bottom:16px;">* DART {"연결" if all(r["fs_div"] == "CFS" for r in A.values()) else "연결(일부 연도 별도)"} 재무제표, {min(A)}~{max(A)}년 사업보고서 기준</div>',
            '<!-- fund5y:end -->']
    return '\n'.join(out)


def eps_html(code, A):
    ys = sorted(A)
    pref = code in TYPES['우선주']
    title = f'EPS {len(ys)}개년 추이' + (' (보통주 기준, 우선주와 이익 공유)' if pref else '')
    cards = []
    for i, y in enumerate(ys):
        e = A[y]['eps']
        note = pct(A[ys[i - 1]]['eps'], e) if i else f'순이익 {krw(A[y]["nip"])}'
        cls = 'dp-eps-card now' if y == ys[-1] else 'dp-eps-card'
        cards.append(f'        <div class="{cls}"><div class="dp-eps-y">{y}년</div><div class="dp-eps-v">{won(e)}</div>'
                     f'<div class="dp-eps-n">{note or "—"}</div></div>')
    return '\n'.join(['<!-- fund5y-eps:start -->', f'      <div class="dp-secl">{title}</div>',
                      '      <style>@media (max-width:640px){#dpFundAnnual .dp-eps-flow{flex-wrap:wrap;}#dpFundAnnual .dp-eps-card{flex:1 1 28%;min-width:84px;}#dpFundAnnual .dp-arrow{display:none;}}</style>',
                      '      <div class="dp-eps-flow">', '\n        <div class="dp-arrow">→</div>\n'.join(cards), '      </div>',
                      '<!-- fund5y-eps:end -->'])


def annual_sentence(A):
    ys = sorted(A)
    a, b = ys[0], ys[-1]
    parts = []
    if A[a]['rev'] and A[b]['rev']:
        n = b - a
        cagr = ((A[b]['rev'] / A[a]['rev']) ** (1 / n) - 1) * 100 if n and A[a]['rev'] > 0 and A[b]['rev'] > 0 else None
        parts.append(f'매출 {krw(A[a]["rev"])}→{krw(A[b]["rev"])}' + (f'(연평균 {cagr:+.1f}%)' if cagr is not None else ''))
    if A[a]['oi'] is not None and A[b]['oi'] is not None:
        parts.append(f'영업이익 {krw(A[a]["oi"])}→{krw(A[b]["oi"])}')
    parts.append(f'지배주주순이익 {krw(A[a]["nip"])}→{krw(A[b]["nip"])}')
    s = f'{len(ys)}개년({a}~{b}) DART 기준 ' + ', '.join(parts) + '.'
    oi = {y: A[y]['oi'] for y in ys if A[y]['oi'] is not None}
    if len(oi) >= 3:
        hi, lo = max(oi, key=oi.get), min(oi, key=oi.get)
        s += f' 영업이익은 {hi}년({krw(oi[hi])})이 최고, {lo}년({krw(oi[lo])})이 최저.'
    return s


def qtr_html(Q):
    labs = [l for l, _ in Q]
    avail = [(k, n) for k, n in QM if sum(1 for _, r in Q if r[k] is not None) >= len(Q) / 2]
    btn = []
    for i, (k, n) in enumerate(avail):
        act = ' class="active"' if i == 0 else ''
        btn.append(f'        <button type="button" data-qm="{k}"{act} onclick="dpShowQtrMetric(\'{k}\',this)">{n}</button>')
    first = avail[0][1] if avail else ''
    return '\n'.join([
        '<!-- fundq:start -->',
        f'      <div class="dp-secl">분기별 실적 ({len(labs)}개 분기, {labs[0]}~{labs[-1]})</div>',
        '      <nav class="dp-sidenav dp-metric-nav" id="dpQtrMetricNav">', *btn, '      </nav>',
        f'      <div id="fundQtrChartTitle" style="font-size:11px;font-weight:700;color:var(--dp-text3);margin-bottom:4px;">{first} — 분기 추이</div>',
        '      <svg id="fundQtrChart" viewBox="0 0 680 190" width="100%" style="display:block;margin-bottom:6px;"></svg>',
        '      <div style="font-size:10.5px;color:var(--dp-text4);margin-bottom:16px;">* DART 분기·반기·사업보고서의 3개월 단독 실적. 4분기는 사업보고서 연간 실적에서 3분기 누적을 뺀 값. 분기 이름 아래 ▲▼는 전년 동기 대비 증감.</div>',
        '<!-- fundq:end -->'])


def qtr_sentence(Q):
    labs = [l for l, _ in Q]
    k = 'oi' if all(r['oi'] is not None for _, r in Q[-5:]) else 'nip'
    nm = dict(QM)[k]
    last, prev, yoy = Q[-1][1][k], Q[-2][1][k], Q[-5][1][k] if len(Q) >= 5 else None
    s = f'최근 {len(Q)}개 분기({labs[0]}~{labs[-1]}) {nm}은 {krw(Q[0][1][k])}→{krw(last)}.'
    s += f' {labs[-1]} {nm}은 전년 동기({labs[-5]}) {krw(yoy)} 대비 {pct(yoy, last) or "—"}' if yoy is not None else ''
    s += f', 직전 분기({labs[-2]}) 대비 {pct(prev, last) or "—"}.' if prev is not None else '.'
    vals = {l: r[k] for l, r in Q if r[k] is not None}
    if len(vals) >= 4:
        hi = max(vals, key=vals.get)
        s += f' 이 기간 분기 최고는 {hi}({krw(vals[hi])}).'
    return s


def js_block(A, Q):
    ys = sorted(A)
    data = {
        'cats': [f'{y}년' for y in ys],
        'rev': [A[y]['rev'] for y in ys], 'oi': [A[y]['oi'] for y in ys], 'nip': [A[y]['nip'] for y in ys],
        'qLabels': [l for l, _ in Q], 'q': {k: [r[k] for _, r in Q] for k, _ in QM},
    }
    return JS_START + '\n' + 'const FUND=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n' + FUND_JS + JS_END


FUND_JS = r"""const qtrMetricLabel={rev:'매출액',oi:'영업이익',pretax:'세전이익',ni:'순이익(연결)',nip:'지배주주순이익'};
const qtrMetricColor={rev:'#8B93A0',oi:null,pretax:'#7C5CBF',ni:'#1D9E75',nip:'#C9622A'};
let _qtrCurrentMetric=(document.querySelector('#dpQtrMetricNav button')||{dataset:{qm:'oi'}}).dataset.qm;
function fundUnit(vals){ const m=Math.max(...vals.filter(v=>v!=null).map(Math.abs),0); return m>=1e12?[1e12,'조']:[1e8,'억']; }
function fundFmt(v,u){ if(v==null) return '—'; const x=v/u[0]; return (u[1]==='조'?(Math.abs(x)>=10?x.toFixed(1):x.toFixed(2)):Math.round(x).toLocaleString())+u[1]; }
function fundAxis(svg,W,pL,pR,py,lo,hi){
  const g=oklchGrid();
  [0,0.25,0.5,0.75,1].forEach(f=>{ const y=py(lo+(hi-lo)*f); svg.appendChild(svgEl('line',{x1:pL,x2:W-pR,y1:y,y2:y,stroke:g,'stroke-width':1})); });
  if(lo<0) svg.appendChild(svgEl('line',{x1:pL,x2:W-pR,y1:py(0),y2:py(0),stroke:'oklch(0.6 0.01 260)','stroke-width':1}));
}
function oklchGrid(){ return 'oklch(0.91 0.005 90)'; }
function fundRange(vals,padTop){ const v=vals.filter(x=>x!=null); let hi=Math.max(0,...v), lo=Math.min(0,...v); const span=(hi-lo)||1; return [lo<0?lo-span*0.12:0, hi+span*padTop]; }
function fundBars(svg,o){
  const {W,H,pL,pR,pT,pB,cats,vals,col,u,barF,maxBar,font,yoy}=o;
  const cW=W-pL-pR,cH=H-pT-pB, [lo,hi]=fundRange(o.rangeVals||vals,o.pad||0.18);
  const py=v=>pT+cH*(1-(v-lo)/(hi-lo));
  fundAxis(svg,W,pL,pR,py,lo,hi);
  const gw=cW/cats.length, bw=Math.min(gw*barF,maxBar);
  cats.forEach((c,i)=>{
    const gx=pL+i*gw+gw/2, v=vals[i];
    if(v!=null){
      const y0=py(0), y1=py(v);
      svg.appendChild(svgEl('rect',{x:gx-bw/2,y:Math.min(y0,y1),width:bw,height:Math.max(1,Math.abs(y1-y0)),fill:v<0?'#D85A30':col,rx:2}));
    }
    const ty=v==null?py(0)-6:(v>=0?py(v)-6:py(v)+12);
    const t=svgEl('text',{x:gx,y:ty,'text-anchor':'middle','font-size':font,fill:v!=null&&v<0?'#D85A30':col,'font-weight':700});
    t.textContent=fundFmt(v,u); svg.appendChild(t);
    if(yoy&&yoy[i]){ const t3=svgEl('text',{x:gx,y:H-pB+24,'text-anchor':'middle','font-size':8.5,fill:'oklch(0.55 0.02 260)'}); t3.textContent=yoy[i]; svg.appendChild(t3); }
    const t2=svgEl('text',{x:gx,y:H-pB+13,'text-anchor':'middle','font-size':10,fill:'oklch(0.5 0.02 260)'});
    t2.textContent=c; svg.appendChild(t2);
  });
  return py;
}
function fundYoy(a,b){ if(a==null||b==null) return ''; if(a>0&&b>0){ const r=(b/a-1)*100; return (r>=0?'▲':'▼')+Math.abs(r).toFixed(Math.abs(r)<10?1:0)+'%'; } if(a<=0&&b>0) return '흑전'; if(a>0&&b<=0) return '적전'; return '적지'; }
function drawAnnualChart(){
  const accent=getComputedStyle(document.querySelector('.dp')).getPropertyValue('--dp-accent').trim()||'#1428A0';
  const s1=document.getElementById('fundAnnualChart');
  if(s1){ s1.innerHTML=''; fundBars(s1,{W:680,H:150,pL:24,pR:24,pT:18,pB:26,cats:FUND.cats,vals:FUND.rev,col:'#8B93A0',u:fundUnit(FUND.rev),barF:0.4,maxBar:64,font:10}); addChartExpandButton(s1); }
  const s2=document.getElementById('fundAnnualChart2'); if(!s2) return;
  s2.innerHTML='';
  const u=fundUnit([...FUND.oi,...FUND.nip]), niCol='#1D9E75';
  const W=680,H=160,pL=24,pR=24,pT=22,pB=26, rv=[...FUND.oi,...FUND.nip];
  const py2=fundBars(s2,{W,H,pL,pR,pT,pB,cats:FUND.cats,vals:FUND.oi,col:accent,u,barF:0.3,maxBar:56,font:9,pad:0.25,rangeVals:rv});
  const gw=(W-pL-pR)/FUND.cats.length, pts=[];
  FUND.nip.forEach((v,i)=>{ if(v!=null) pts.push([pL+i*gw+gw/2+gw*0.22,py2(v),v]); });
  if(pts.length>1) s2.appendChild(svgEl('polyline',{points:pts.map(p=>p[0]+','+p[1]).join(' '),fill:'none',stroke:niCol,'stroke-width':2.5}));
  pts.forEach(p=>{ s2.appendChild(svgEl('circle',{cx:p[0],cy:p[1],r:4,fill:niCol}));
    const t=svgEl('text',{x:p[0]+6,y:p[1]-8,'text-anchor':'start','font-size':9,fill:niCol,'font-weight':600}); t.textContent=fundFmt(p[2],u); s2.appendChild(t); });
  [[accent,'영업이익'],[niCol,'지배주주순이익']].forEach((l,i)=>{ const lx=pL+i*90;
    s2.appendChild(svgEl('rect',{x:lx,y:2,width:9,height:9,fill:l[0],rx:2}));
    const t=svgEl('text',{x:lx+12,y:10,'font-size':9,fill:'oklch(0.5 0.02 260)'}); t.textContent=l[1]; s2.appendChild(t); });
  addChartExpandButton(s2);
}
function dpShowQtrMetric(id, el){
  document.querySelectorAll('#dpQtrMetricNav button').forEach(b=>b.classList.toggle('active', b===el));
  _qtrCurrentMetric=id;
  drawQtrChart();
}
function drawQtrChart(){
  const id=_qtrCurrentMetric, vals=FUND.q[id];
  const accent=getComputedStyle(document.querySelector('.dp')).getPropertyValue('--dp-accent').trim()||'#1428A0';
  const svg=document.getElementById('fundQtrChart'); if(!svg) return;
  svg.innerHTML='';
  const yoy=vals.map((v,i)=>i>=4?fundYoy(vals[i-4],v):'');
  fundBars(svg,{W:680,H:190,pL:20,pR:20,pT:22,pB:36,cats:FUND.qLabels,vals,col:qtrMetricColor[id]||accent,u:fundUnit(vals),barF:0.5,maxBar:46,font:9.5,yoy});
  const t=document.getElementById('fundQtrChartTitle'); if(t) t.textContent=qtrMetricLabel[id]+' — 분기 추이';
  addChartExpandButton(svg);
}
"""


# ── 페이지 변환 ──
def _cut_before(seg, stops):
    idx = [seg.find(s) for s in stops if seg.find(s) >= 0]
    return min(idx) if idx else -1


def _func_span(t, name):
    i = t.find(f'function {name}(')
    if i < 0:
        return None
    j = t.index('{', i)
    depth = 0
    for k in range(j, len(t)):
        if t[k] == '{':
            depth += 1
        elif t[k] == '}':
            depth -= 1
            if depth == 0:
                return i, k + 1
    return None


def transform(path, code, dry=False):
    raw = open(path, 'rb').read().decode('utf-8')
    t = raw.replace('\r\n', '\n')
    A, Q = annual(code), quarters(code)
    A = {y: r for y, r in A.items() if y >= MIN_YEAR.get(code, 0)}
    Q = [(l, r) for l, r in Q if any(v is not None for v in r.values())] if len(A) < 2 else Q
    if not A or len(Q) < 2:
        return 'skip: DART 데이터 부족'
    log = []

    a0 = t.find('<div id="dpFundAnnual"')
    q0 = t.find('<div id="dpFundQuarter"')
    e0 = t.find('<!-- 3. 투자지표')
    if min(a0, q0, e0) < 0:
        return 'skip: 기본적 분석 탭 구조 아님'
    A_sec, Q_sec = t[a0:q0], t[q0:e0]

    # 1) 연간 차트
    if '<!-- fund5y:start -->' in A_sec:
        A_sec = re.sub(r'<!-- fund5y:start -->.*?<!-- fund5y:end -->', lambda m: annual_charts_html(A), A_sec, flags=re.S)
    else:
        h = A_sec.index('>') + 1
        stop = _cut_before(A_sec[h:], ['<div class="dp-g2">', '<div class="dp-secl">사업', '<div class="dp-seg3">'])
        if stop < 0:
            return 'skip: 연간 차트 경계 못 찾음'
        cut = A_sec[h:h + stop]
        log.append('연간 제거: ' + ' | '.join(re.findall(r'class="dp-secl"[^>]*>([^<]*)<', cut)))
        resid = re.sub(r'<svg.*?</svg>|<div class="dp-secl"[^>]*>[^<]*</div>|<[^>]+>', '', cut, flags=re.S).strip()
        if resid:
            log.append('  !! 연간 잔여 텍스트: ' + resid[:120])
        A_sec = A_sec[:h] + '\n' + annual_charts_html(A) + '\n      ' + A_sec[h + stop:]

    # 2) EPS 카드
    if '<!-- fund5y-eps:start -->' in A_sec:
        A_sec = re.sub(r'<!-- fund5y-eps:start -->.*?<!-- fund5y-eps:end -->', lambda m: eps_html(code, A), A_sec, flags=re.S)
    else:
        f = A_sec.find('<div class="dp-eps-flow">')
        if f >= 0:
            s = A_sec.rfind('<div class="dp-secl">', 0, f)
            # eps-flow 닫는 위치: 다음 dp-insight 또는 섹션 끝 직전의 </div>
            nxt = A_sec.find('<div class="dp-insight">', f)
            end = A_sec.rfind('</div>', f, nxt) + len('</div>') if nxt > 0 else None
            if s < 0 or end is None or s < A_sec.rfind('</div>', 0, f - 200):
                pass
            old = A_sec[s:end]
            if old.count('<div') != old.count('</div>'):
                return 'skip: EPS 카드 div 불균형'
            log.append('EPS 교체: ' + re.findall(r'class="dp-secl"[^>]*>([^<]*)<', old)[0])
            A_sec = A_sec[:s] + eps_html(code, A) + '\n\n      ' + A_sec[end:].lstrip()
        else:
            ins = A_sec.find('<div class="dp-insight">')
            A_sec = A_sec[:ins] + eps_html(code, A) + '\n\n      ' + A_sec[ins:]
            log.append('EPS 신규 삽입')

    # 3) 사업보고서 핵심 해설 앞에 5개년 흐름 문장
    sent = annual_sentence(A)
    if '<span class="fund5y-s">' in A_sec:
        A_sec = re.sub(r'<span class="fund5y-s">.*?</span>', lambda m: f'<span class="fund5y-s">{html.escape(sent)}</span>', A_sec)
    else:
        m = re.search(r'(<div class="dp-insight">\s*<div class="dp-insight-t">[^<]*</div>\s*<div class="dp-insight-b">)', A_sec)
        if m:
            A_sec = A_sec[:m.end()] + f'<span class="fund5y-s">{html.escape(sent)}</span> ' + A_sec[m.end():]

    # 4) 분기 차트
    if '<!-- fundq:start -->' in Q_sec:
        Q_sec = re.sub(r'<!-- fundq:start -->.*?<!-- fundq:end -->', lambda m: qtr_html(Q), Q_sec, flags=re.S)
    else:
        h = Q_sec.index('>') + 1
        stop = _cut_before(Q_sec[h:], ['<div class="dp-g2">', '<div class="dp-insight">'])
        cut = Q_sec[h:h + stop]
        log.append('분기 제거: ' + ' | '.join(re.findall(r'class="dp-secl"[^>]*>([^<]*)<', cut)) + f' (svg {cut.count("<svg")})')
        resid = re.sub(r'<svg.*?</svg>|<div class="dp-secl"[^>]*>[^<]*</div>|<[^>]+>', '', cut, flags=re.S).strip()
        if resid:
            log.append('  !! 분기 잔여 텍스트: ' + resid[:160])
        Q_sec = Q_sec[:h] + '\n' + qtr_html(Q) + '\n      ' + Q_sec[h + stop:]

    # 5) 분기 2개년 흐름 해설(기존 반기 해설 앞)
    qs = qtr_sentence(Q)
    box = ('<!-- fundq-insight:start -->\n      <div class="dp-insight" style="margin-bottom:10px;">\n'
           '        <div class="dp-insight-t">분기 실적 — 2개년 흐름</div>\n'
           f'        <div class="dp-insight-b">{html.escape(qs)}</div>\n      </div>\n<!-- fundq-insight:end -->')
    if '<!-- fundq-insight:start -->' in Q_sec:
        Q_sec = re.sub(r'<!-- fundq-insight:start -->.*?<!-- fundq-insight:end -->', lambda m: box, Q_sec, flags=re.S)
    else:
        ins = Q_sec.find('<div class="dp-insight">')
        if ins < 0:
            ins = Q_sec.rfind('</div>', 0, Q_sec.rfind('</div>', 0, Q_sec.rfind('</div>')))
        Q_sec = Q_sec[:ins] + box + '\n      ' + Q_sec[ins:]

    t = t[:a0] + A_sec + Q_sec + t[e0:]

    # 6) JS
    js = js_block(A, Q)
    if JS_START in t:
        i, j = t.index(JS_START), t.index(JS_END) + len(JS_END)
        t = t[:i] + js + t[j:]
    else:
        spans = [s for s in (_func_span(t, 'drawAnnualChart'), _func_span(t, 'drawQtrChart')) if s]
        if len(spans) != 2:
            return f'skip: 차트 함수 {len(spans)}개'
        # 기존 분기 보조 정의(qtrLabels/qtrData/dpShowQtrMetric 등) 제거
        for nm in ('dpShowQtrMetric',):
            sp = _func_span(t, nm)
            if sp:
                t = t[:sp[0]] + t[sp[1]:]
        for pat in (r'\nconst qtrLabels=.*?;\n', r'\nconst qtrData=\{.*?\n\};\n', r'\nconst qtrEstimated=.*?;\n',
                    r'\nconst qtrMetricLabel=.*?;\n', r'\nconst qtrMetricColor=.*?;\n', r'\nlet _qtrCurrentMetric=.*?;\n'):
            t = re.sub(pat, '\n', t, count=1, flags=re.S)
        a, b = _func_span(t, 'drawAnnualChart'), _func_span(t, 'drawQtrChart')
        first, second = sorted([a, b])
        t = t[:second[0]] + t[second[1]:]
        t = t[:first[0]] + js + t[first[1]:]
    if not dry:
        open(path, 'wb').write(t.replace('\n', '\r\n').encode('utf-8'))
    return '\n    '.join(['ok'] + log)


# ── 예전(Chart.js) 템플릿: 079 삼양식품 · 101 농심 ──
LEGACY_ACCENT = {'003230': '#D04B20', '004370': '#E65100'}
LG_CSS = """<style>
.fundlg{--dp-accent:%s;--dp-accent-soft:color-mix(in srgb,%s 8%%,transparent);--dp-up:%s;--dp-card:var(--color-background-primary,#fff);
  --dp-border:var(--color-border-tertiary,#e5e3dc);--dp-text2:var(--color-text-secondary,#555);--dp-text3:var(--color-text-secondary,#666);--dp-text4:var(--color-text-tertiary,#888);margin-bottom:12px;}
.fundlg .dp-secl{font-size:12px;font-weight:700;color:var(--dp-text4);margin-bottom:8px;}
.fundlg .dp-eps-flow{display:flex;align-items:stretch;gap:8px;margin-bottom:12px;}
.fundlg .dp-eps-card{flex:1;text-align:center;background:var(--color-background-secondary,#f7f6f2);border:1px solid var(--dp-border);border-radius:10px;padding:10px 6px;}
.fundlg .dp-eps-card.now{background:var(--dp-accent-soft);border-color:var(--dp-accent);}
.fundlg .dp-eps-y{font-size:10.5px;color:var(--dp-text3);margin-bottom:4px;}
.fundlg .dp-eps-v{font-size:15px;font-weight:800;}
.fundlg .dp-eps-n{font-size:10px;color:var(--dp-text4);margin-top:4px;}
.fundlg .dp-arrow{display:flex;align-items:center;font-size:16px;color:var(--dp-up);font-weight:700;}
.fundlg .dp-sidenav{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;}
.fundlg .dp-sidenav button{flex:1 1 0;padding:8px 6px;font-size:12px;font-weight:700;color:var(--dp-text2);border:1px solid var(--dp-border);border-radius:8px;background:var(--dp-card);font-family:inherit;cursor:pointer;word-break:keep-all;}
.fundlg .dp-sidenav button.active{background:var(--dp-accent);border-color:var(--dp-accent);color:#fff;}
.fundlg .fundlg-s{font-size:12px;line-height:1.65;color:var(--dp-text2);background:var(--color-background-secondary,#f7f6f2);border-radius:8px;padding:9px 11px;margin-bottom:12px;}
@media (max-width:640px){.fundlg .dp-eps-flow{flex-wrap:wrap;}.fundlg .dp-eps-card{flex:1 1 28%%;min-width:84px;}.fundlg .dp-arrow{display:none;}
  .fundlg .dp-sidenav{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;}.fundlg .dp-sidenav button{padding:8px 4px;font-size:11px;}}
</style>"""


def _lg_js(A, Q, accent):
    js = js_block(A, Q)
    js = js.replace("getComputedStyle(document.querySelector('.dp')).getPropertyValue('--dp-accent').trim()||'#1428A0'", repr(accent))
    js = re.sub(r'addChartExpandButton\((\w+)\);', r"if(typeof addChartExpandButton==='function') addChartExpandButton(\1);", js)
    helper = ("function svgEl(tag,attrs){ const e=document.createElementNS('http://www.w3.org/2000/svg',tag);"
              " for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }\n")
    return js.replace(JS_START + '\n', JS_START + '\n' + helper, 1)


def _lg_sub(t, tag, body):
    """<!-- tag:start --> … <!-- tag:end --> 사이 교체(없으면 None)."""
    s, e = f'<!-- {tag}:start -->', f'<!-- {tag}:end -->'
    if s not in t:
        return None
    i, j = t.index(s), t.index(e) + len(e)
    return t[:i] + f'{s}\n{body}\n{e}' + t[j:]


def legacy(path, code, dry=False):
    raw = open(path, 'rb').read().decode('utf-8')
    t = raw.replace('\r\n', '\n')
    A, Q = annual(code), quarters(code)
    acc = LEGACY_ACCENT[code]
    css = LG_CSS % (acc, acc, acc)
    a_body = '\n'.join([f'<div class="fundlg">', annual_charts_html(A), eps_html(code, A),
                        f'      <div class="fundlg-s">{html.escape(annual_sentence(A))}</div>', '</div>'])
    q_body = '\n'.join(['<div class="fundlg">', qtr_html(Q),
                        f'      <div class="fundlg-s"><b>분기 실적 — 2개년 흐름</b> · {html.escape(qtr_sentence(Q))}</div>', '</div>'])
    js = _lg_js(A, Q, acc)

    if code == '003230':
        # 사업보고서 / 반기보고서 탭의 Chart.js 캔버스 → 표준 SVG 차트
        for tag, cid, body in (('fundlg-a', 'plChart', css + '\n' + a_body), ('fundlg-q', 'qplChart', q_body)):
            r = _lg_sub(t, tag, body)
            if r is None:
                m = re.search(rf'<div style="position:relative;[^"]*"><canvas id="{cid}"></canvas></div>', t)
                if not m:
                    return f'skip: {cid} 없음'
                r = t[:m.start()] + f'<!-- {tag}:start -->\n{body}\n<!-- {tag}:end -->' + t[m.end():]
            t = r
        if JS_START in t:
            i, j = t.index(JS_START), t.index(JS_END) + len(JS_END)
            t = t[:i] + js + t[j:]
        else:
            i = t.index('let plC, qC;')
            j = _func_span(t, 'renderQuarter')[1]
            t = t[:i] + js + '\nfunction renderAnnual(){ drawAnnualChart(); }\nfunction renderQuarter(){ drawQtrChart(); }' + t[j:]
        # 목표주가 차트가 Chart.js 로드 전에 실행되던 문제: 라이브러리를 그 앞으로
        lib = '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>\n'
        tp = t.find("<script>\n// 증권사 목표주가 차트")
        if 0 <= tp < t.find(lib):
            t = t.replace(lib, '', 1)
            t = t[:tp] + lib + t[tp:]
    elif code == '004370':
        body = css + '\n' + a_body + '\n' + q_body
        r = _lg_sub(t, 'fundlg', body)
        if r is None:
            m = re.search(r'<div style="position:relative;[^"]*">\s*<canvas id="nongRevChart"></canvas>\s*</div>', t)
            if not m:
                return 'skip: nongRevChart 없음'
            r = t[:m.start()] + f'<!-- fundlg:start -->\n{body}\n<!-- fundlg:end -->' + t[m.end():]
        t = r
        if JS_START in t:
            i, j = t.index(JS_START), t.index(JS_END) + len(JS_END)
            t = t[:i] + js + t[j:]
        else:
            i = t.index('// ── 매출/영업이익 차트')
            j = t.index('// ── OPM 피어 비교')
            t = t[:i] + js + '\ndrawAnnualChart(); drawQtrChart();\n\n' + t[j:]
    if not dry:
        open(path, 'wb').write(t.replace('\n', '\r\n').encode('utf-8'))
    return 'ok (legacy)'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    files = sorted(f for f in os.listdir(STOCKS) if re.match(r'\d{3}_\w+\.html$', f))
    for f in files:
        code = f[4:-5]
        if args and code not in args and f[:3] not in args:
            continue
        p = os.path.join(STOCKS, f)
        print(f, legacy(p, code, dry) if code in LEGACY_ACCENT else transform(p, code, dry))


if __name__ == '__main__':
    main()
