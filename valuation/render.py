"""engine 결과를 종목 페이지의 '내재가치 평가' 박스(#dpBuffettBox)와 그래프 스크립트로 반영."""
import os, re, json, html

from fetch import CACHE
from engine import px_series, THIS_YEAR, MERGED

ROOT = os.path.dirname(os.path.abspath(__file__))
CHART_JS = open(os.path.join(ROOT, 'chart.js'), encoding='utf-8').read().strip()
JS_MARKERS = ('// -- 내재가치 평가:', '// -- 버핏식 내재가치:')
LOGIC_JS_START = '// -- 핵심 투자 논리 (yes/no 토글로 1년 후 예상 주가 차트에 반영/제외) --'
LOGIC_JS_END = '\ndpRenderLogicList();'

CUSTOM_NOTE = {
    '033780': '이익이 안정적인 기업이라 세 방식의 결과가 서로 가깝게 모여 신뢰도가 높다. '
              '다만 과거 PER(9~11배)은 밸류업(자사주 소각·배당 확대) 이전 기준이라, 시장 평가 기준이 바뀌었다면 실제 적정가는 이보다 높을 수 있다. '
              'DCF 주주이익은 해외 공장 증설 투자를 성장 투자로 보고 빼지 않았다.',
    '005930': '반도체 업황에 따라 이익이 크게 출렁여 방식마다 값 차이가 크다. '
              'DCF 상단은 최근 4분기 이익이 계속된다고 가정한 값이며, 정상화 PER(최근일수록 가중한 10년 평균)·RIM은 사이클 평균으로 호황 이익을 눌러 본다. '
              '현재가가 범위 위에 있다면 지금의 호황이 오래 이어진다는 기대가 주가에 들어 있다는 뜻이다.',
}
TYPE_NOTE = {
    '안정': '이익이 안정적인 기업이라 DCF·RIM·정상화 PER을 4:3:3으로 가중했다.',
    '경기민감': '업황에 따라 이익 변동이 커 10년 이익을 최근일수록 가중 평균한 정상화 PER 비중을 높였다(DCF·RIM·정상화 PER 3:3:4). DCF 상단은 최근 4분기 이익이 계속된다고 가정한 값이다.',
    '금융': '금융회사는 영업현금흐름·설비투자 개념이 맞지 않아 DCF 대신 RIM·적정 PBR로 평가했다(6:4). '
            '배당할인은 이익을 유보해 성장하는 구조와 자사주 매입을 반영하지 못해 가치를 과소평가하므로 쓰지 않았다.',
    '지주·투자': '지주·투자회사라 보유 지분의 시장가치를 반영한 NAV(순자산가치)에 60%, RIM·정상화 PER에 20%씩 가중했다. '
              'NAV는 별도 재무제표 자본에 상장 자회사 지분의 시가와 장부가 차이를 더한 값이며, 한국 지주사의 통상적인 할인(30~50%)을 적용했다. 비상장 자회사는 장부가로 반영된다.',
    '규제·유틸리티': '요금 규제를 받는 기업이라 RIM·정상화 PER·배당할인으로 평가했다(4:3:3).',
    '저수익·회복': '장기 평균 ROE가 0 이하로 장부가치가 이익으로 이어지지 않은 성숙 기업이라, 장부가치 기반 평가(RIM·적정 PBR)는 빼고 '
              '지금의 이익이 계속된다고 보는 이익환원 방식으로만 평가했다(ROE가 요구수익률로 회복된다는 가정 없음). '
              '하단은 최근 3년 평균 순이익과 최근 4분기 순이익 중 작은 값(성장 0%), 상단은 큰 값에 영구 성장률 2.5%를 적용했다. '
              '최근 4분기가 적자였던 시점은 이익 기반 가치를 낼 수 없어 그래프를 비워 뒀다.',
    '고성장·적자': '적자이거나 이익이 아직 안정되지 않은 단계라 이익 기반 평가(DCF·PER)는 빼고 장부가치 기반(RIM·적정 PBR)만 참고용으로 계산했다. 성장 기업의 미래 가치는 반영되지 않는다.',
}
QNAME = {'03': '1분기', '06': '반기', '09': '3분기', '12': '사업'}
CONF_COLOR = {'단일 방식': 'var(--dp-text2)', '높음': 'oklch(0.55 0.15 150)', '보통': 'var(--dp-text2)', '낮음': 'oklch(0.62 0.16 60)'}

STYLE = '''  <style>
    #dpBuffettBox .dpb-sub{font-size:12px;color:var(--dp-text3);margin:-2px 0 10px;}
    #dpBuffettBox .dpb-h{font-size:12px;font-weight:700;color:var(--dp-text3);margin:14px 0 6px;padding-top:12px;border-top:1px dashed var(--dp-accent-soft2);}
    #dpBuffettBox .dpb-sub + .dpb-h{border-top:none;margin-top:4px;padding-top:0;}
    #dpBuffettBox .dpb-type{display:inline-block;font-size:11.5px;font-weight:800;border-radius:5px;padding:2px 7px;margin-right:6px;background:var(--dp-accent-soft2);color:var(--dp-accent);}
    #dpBuffettBox .dpb-m{padding:7px 0;border-bottom:1px solid var(--dp-accent-soft2);}
    #dpBuffettBox .dpb-m-top{display:flex;align-items:center;gap:8px;font-size:12.5px;}
    #dpBuffettBox .dpb-m-n{font-weight:700;width:76px;flex-shrink:0;}
    #dpBuffettBox .dpb-m-v{font-weight:700;flex:1;min-width:0;}
    #dpBuffettBox .dpb-m-w{display:flex;align-items:center;gap:5px;width:96px;flex-shrink:0;}
    #dpBuffettBox .dpb-m-w i{display:block;height:6px;border-radius:3px;background:var(--dp-accent);max-width:60px;}
    #dpBuffettBox .dpb-m-w b{font-size:11px;color:var(--dp-text3);}
    #dpBuffettBox .dpb-m-note{font-size:11.5px;color:var(--dp-text4);margin-top:3px;}
    #dpBuffettBox .dpb-nums{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:10px 0;}
    #dpBuffettBox .dpb-num{background:var(--dp-card);border:1px solid var(--dp-border);border-radius:8px;padding:8px;}
    #dpBuffettBox .dpb-num .l{font-size:10.5px;color:var(--dp-text4);}
    #dpBuffettBox .dpb-num .v{font-size:14px;font-weight:800;margin-top:2px;}
    #dpBuffettBox .dpb-chart{display:block;width:100%;height:auto;margin:4px 0 8px;touch-action:pan-y;}
    #dpBuffettBox .dpb-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:11.5px;color:var(--dp-text3);}
    #dpBuffettBox .dpb-legend i{display:inline-block;width:14px;height:8px;border-radius:2px;margin-right:4px;vertical-align:middle;}
    #dpBuffettBox .dpb-ctl{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:4px;}
    #dpBuffettBox .dpb-rng{display:flex;gap:4px;}
    #dpBuffettBox .dpb-rng button{font:inherit;font-size:12px;font-weight:700;padding:4px 10px;border-radius:6px;border:1px solid var(--dp-border);background:var(--dp-card);color:var(--dp-text3);cursor:pointer;}
    #dpBuffettBox .dpb-rng button.on{background:var(--dp-accent);border-color:var(--dp-accent);color:#fff;}
    #dpBuffettBox .dpb-readout{font-size:12.5px;color:var(--dp-text2);min-height:18px;margin:-2px 0 4px;}
    #dpBuffettBox .dpb-cap{font-size:11.5px;color:var(--dp-text4);margin-bottom:8px;}
    #dpBuffettBox .dpb-verdict{font-size:13px;font-weight:800;margin-bottom:4px;}
    @media (max-width:640px){
      #dpBuffettBox .dpb-m-top{flex-wrap:wrap;font-size:13.5px;}
      #dpBuffettBox .dpb-m-v{flex-basis:calc(100% - 180px);}
      #dpBuffettBox .dpb-m-note{font-size:12.5px;}
    }
  </style>'''

# 구 템플릿(dp-* 변수·스타일이 없는 페이지)용 변수 정의
LEGACY_STYLE = '''  <style>
    #dpBuffettBox{--dp-accent:oklch(0.32 0.09 260);--dp-accent-soft:oklch(0.32 0.09 260 / 0.06);--dp-accent-soft2:oklch(0.32 0.09 260 / 0.14);
      --dp-card:oklch(1 0 0);--dp-border:oklch(0.91 0.005 90);--dp-text:oklch(0.18 0.02 260);--dp-text2:oklch(0.4 0.02 260);
      --dp-text3:oklch(0.5 0.02 260);--dp-text4:oklch(0.55 0.02 260);--dp-up:oklch(0.55 0.2 25);--dp-down:oklch(0.52 0.14 250);
      background:var(--dp-accent-soft);border:1px solid var(--dp-accent-soft2);border-radius:12px;padding:16px 18px;margin:0 0 20px;color:var(--dp-text);}
    #dpBuffettBox .dp-summary-l{font-size:14.5px;font-weight:700;color:var(--dp-accent);margin-bottom:5px;}
    #dpBuffettBox .dp-logic-chart-note{font-size:12px;color:var(--dp-text4);margin-top:6px;line-height:1.6;}
  </style>'''

CHART = ('  <div class="dpb-ctl"><div class="dpb-legend"><span><i style="background:var(--dp-accent);height:3px"></i>월말 주가</span>'
         '<span><i style="background:oklch(0.68 0.13 150 / 0.5)"></i>1분기</span>'
         '<span><i style="background:oklch(0.68 0.13 195 / 0.5)"></i>반기</span>'
         '<span><i style="background:oklch(0.68 0.13 300 / 0.5)"></i>3분기</span>'
         '<span><i style="background:oklch(0.68 0.13 60 / 0.5)"></i>사업보고서</span></div>'
         '<div class="dpb-rng"><button type="button" data-m="12">1년</button><button type="button" data-m="36">3년</button>'
         '<button type="button" class="on" data-m="0">5년</button></div></div>\n'
         '  <svg class="dpb-chart" id="dpbChart" viewBox="0 0 600 240" role="img" aria-label="주가와 분기별 내재가치 범위"></svg>\n'
         '  <div class="dpb-readout" id="dpbReadout"></div>\n'
         '  <div class="dpb-cap">밴드 색은 내재가치 계산에 쓴 재무제표(분기 말 기준)를 나타내며, 다음 분기 말까지 유지된다. 그래프를 누르거나 마우스를 올리면 그 시점 값을 볼 수 있다.</div>\n')


def conf(spread):
    return '높음' if spread <= 1.5 else ('보통' if spread <= 2 else '낮음')


def hist(code, start_year):
    s = px_series(code)
    return [[k, round(v)] for k, v in sorted(s.items()) if int(k[:4]) >= start_year]


def fmt(v):
    return f'{v:,.0f}'


def make_box(page_code, r, legacy=False, price_sel=None, price=None):
    q = r['quarters']
    lt = q[-1]
    cf = '단일 방식' if len(lt['methods']) == 1 else conf(lt['spread'])
    note = CUSTOM_NOTE.get(page_code) or TYPE_NOTE[r['type']]
    if lt.get('missing'):
        note += f" 데이터 부족으로 {', '.join(lt['missing'])}은(는) 계산에서 빠졌고 나머지 방식의 가중치를 비례 배분했다."
    if r['code'] in MERGED:
        note += ' 합병으로 주식 수가 크게 늘어, 합병 전 연도 이익·배당은 그해 주당 기준을 유지하도록 지금 주식 수로 환산했다.'
    if cf == '낮음' and page_code not in CUSTOM_NOTE:
        note += ' 평가 방식 간 결과 차이가 커 신뢰도가 낮다.'
    if r['code'] != page_code:
        note += (f' 우선주는 보통주 주당 내재가치에 직전 5년 평균 우선주/보통주 주가 비율({lt["pref_factor"]:.2f}배)을 곱했다'
                 '(의결권·유동성 차이로 생기는 상시 할인 반영, 방식별 범위도 같은 비율로 환산, 근거 수치는 보통주 기준).'
                 if lt.get('pref_factor') else ' 우선주는 보통주와 같은 주당 내재가치를 적용했다(의결권·배당 차이 미반영).')
    qy, qm = lt['q'].split('-')
    hold = r['type'] == '고성장·적자'
    mrows = '\n'.join(
        f'  <div class="dpb-m"><div class="dpb-m-top"><span class="dpb-m-n">{html.escape(x["name"])}</span>'
        f'<span class="dpb-m-v">{fmt(x["low"])} ~ {fmt(x["high"])}원</span>'
        f'<span class="dpb-m-w"><i style="width:{x["w"]}%"></i><b>{x["w"]}%</b></span></div>'
        f'<div class="dpb-m-note">{html.escape(x["note"])}</div></div>' for x in lt['methods'])
    bands = [[v['q'], None, None] if v.get('gap') else [v['q'], round(v['low']), round(v['high'])] for v in q]
    attrs = (f" data-hist='{json.dumps(hist(page_code, THIS_YEAR - 5), separators=(',', ':'))}'"
             f" data-bands='{json.dumps(bands, separators=(',', ':'))}'"
             f' data-iv-low="{lt["low"]:.0f}" data-iv-high="{lt["high"]:.0f}"')
    if hold:
        attrs = ' data-hold="1"' + attrs
    if price_sel:
        attrs += f' data-price-sel="{html.escape(price_sel)}"'
    if price:
        attrs += f' data-price="{price:.0f}"'
    head2 = '참고용 장부가치 기준 범위와 현재가 위치' if hold else '가중 내재가치와 현재가 위치'
    return f'''<div class="dp-summary" id="dpBuffettBox"{attrs}>
{STYLE}
{LEGACY_STYLE if legacy else ''}
  <div class="dp-summary-l">내재가치 평가</div>
  <div class="dpb-sub">DART 연결 재무제표 {r["first_year"]}~{lt["fy"]}년 + {qy}년 {QNAME[qm]}보고서 기준 · 할인율 12% · 안전마진 미적용</div>
  <div class="dpb-h"><span class="dpb-type">{r['type']}형</span>평가 방식별 내재가치 <span style="font-weight:400">({html.escape(r['type_why'])})</span></div>
{mrows}
  <div class="dpb-h">{head2} · 방식 간 일치도 <span style="color:{CONF_COLOR[cf]}">{cf}</span></div>
  <div class="dpb-verdict" id="dpbVerdict"></div>
  <div class="dpb-nums">
    <div class="dpb-num"><div class="l">내재가치 하단</div><div class="v">{fmt(lt['low'])}원</div></div>
    <div class="dpb-num"><div class="l">내재가치 상단</div><div class="v">{fmt(lt['high'])}원</div></div>
    <div class="dpb-num"><div class="l">현재가</div><div class="v" id="dpbPrice">-</div></div>
  </div>
{CHART}  <div class="dp-logic-chart-note">{html.escape(note)} 가중 내재가치는 방식별 하단·상단을 종목 유형에 따른 가중치로 평균한 값이다. 주가 예측이 아니라 재무제표로 추정한 기업 가치이며, 투자 권고가 아니다.</div>
</div>'''.replace('\n\n', '\n')


def error_box(msg, legacy=False, excluded=False):
    note = (f'평가하지 않는 종목이다: {html.escape(msg)}.' if excluded else
            f'내재가치를 계산하지 못했다: {html.escape(msg)}. 상장 기간이나 DART 재무 이력이 짧은 종목은 이력이 쌓이면 평가한다.')
    return ('<div class="dp-summary" id="dpBuffettBox">\n' + (LEGACY_STYLE + '\n' if legacy else '') +
            '  <div class="dp-summary-l">내재가치 평가</div>\n'
            f'  <div class="dp-logic-chart-note">{note}</div>\n'
            '</div>')


def _box_end(t, s):
    i, depth = s, 0
    while True:
        o, c = t.find('<div', i), t.find('</div>', i)
        if o != -1 and o < c:
            depth += 1
            i = o + 4
        else:
            depth -= 1
            i = c + 6
            if depth == 0:
                return i


def apply(path, page_code, r):
    """페이지 하나에 박스·스크립트를 반영. 반환: 'ok'|'error-box'|'kept'|'skip'|'unchanged'."""
    raw = open(path, 'rb').read().decode('utf-8')
    t = raw.replace('\r\n', '\n')
    legacy = 'class="dp-price"' not in t
    price_sel = '.g4 .met .mv' if legacy else None
    # 구 템플릿은 일일 갱신 대상이 아니라 페이지의 가격이 오래됐을 수 있음 → 최신 시세(이번 달 Yahoo 종가)를 박스에 넣어 사용
    h = hist(page_code, THIS_YEAR - 1) if legacy else []
    price = h[-1][1] if h else None
    ok = bool(r) and 'error' not in r
    if not ok and 'data-bands=' in t and not (r or {}).get('permanent'):
        # 수집 실패 같은 일시적 오류로 이미 게시된 정상 평가를 오류 박스로 덮어쓰지 않음
        return 'kept'
    box = make_box(page_code, r, legacy, price_sel, price) if ok else error_box((r or {}).get('error', '데이터 없음'), legacy, (r or {}).get('excluded'))
    script = CHART_JS if ok else ''
    if 'id="dpBuffettBox"' in t:
        s = t.index('<div class="dp-summary" id="dpBuffettBox"')
        t = t[:s] + box + t[_box_end(t, s):]
    elif 'id="dpLogicBox"' in t:
        s = t.index('<div class="dp-summary" id="dpLogicBox">')
        t = t[:s] + box + t[_box_end(t, s):]
    elif legacy and '\n<!-- 1. 기술적 분석 -->' in t:
        s = t.index('\n<!-- 1. 기술적 분석 -->')
        t = t[:s] + '\n' + box + '\n' + t[s:]
    else:
        return 'skip'
    # 스크립트: 기존 내재가치 스크립트 → 교체, 핵심 투자 논리 스크립트 → 교체, 없으면 별도 <script>로 끝에 추가
    marker = next((m for m in JS_MARKERS if m in t), None)
    if marker:
        js_s = t.index(marker)
        js_e = t.index('\n})();', js_s) + len('\n})();')
        t = t[:js_s] + script + t[js_e:]
    elif LOGIC_JS_START in t:
        js_s = t.index(LOGIC_JS_START)
        js_e = t.index(LOGIC_JS_END, js_s) + len(LOGIC_JS_END)
        t = t[:js_s] + script + t[js_e:]
    elif script:
        t = t.rstrip('\n') + '\n<script>\n' + script + '\n</script>\n'
    # 저장소 규칙(core.autocrlf=true)상 작업본은 CRLF. LF로 쓰면 git이 경고를 내고, 일일 스크립트가 그 경고를
    # 병합 충돌로 오인해 커밋을 건너뛴 적이 있음(2026-10-13·14)
    out = t.replace('\n', '\r\n')
    if out == raw:
        return 'unchanged'
    open(path, 'wb').write(out.encode('utf-8'))
    return 'ok' if ok else 'error-box'
