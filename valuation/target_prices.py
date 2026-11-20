"""증권사 목표주가 표(종목 페이지 '목표주가' 섹션) 매일 갱신.

- 네이버 증권 리서치 전체 목록(m.stock.naver.com/api/research/company)을 최신순으로 넘기며
  우리 종목 리포트를 모으고, 리포트 상세 API에서 증권사·투자의견·목표주가(goalPrice)를 받는다.
  받은 리포트는 data/target_prices.json에 쌓아 두고 새 리포트만 추가로 받는다.
- 표: 최근 6개월(183일) 리포트 중 목표주가가 있는 것만, 증권사별 가장 최근 1건, 최신순.
- 평균 목표주가: 에프앤가이드 컨센서스(종목 API consensusInfo.priceTargetMean)가 있으면 그 값,
  없으면 표의 단순 평균. 현재가 대비는 페이지의 오늘 종가로 매일 다시 계산한다.
- 표 행이 그대로면 손으로 쓴 설명 문구를 남기고, 행이 바뀌면 자동 문구로 바꾼다.
- 우선주 페이지와 구조가 다른 페이지(목표주가 섹션이 없거나 표가 없는 곳)는 건드리지 않는다.

사용: python valuation/target_prices.py [--dry] [--codes 000660,005930]
"""
import argparse, datetime as dt, glob, html, json, os, re, sys, time
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
os.chdir(ROOT)
CACHE = 'data/target_prices.json'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
WINDOW_DAYS = 183
KEEP_DAYS = 400
MAX_ROWS = 10

BODY_RE = re.compile(r'(<div class="dp-acc" id="dpAcc-consensus">\n  <div class="dp-acc-body">\n)(.*?)(\n  </div>\n</div>\n)', re.S)
TABLE_RE = re.compile(r'<table>.*?</table>', re.S)
SUMMARY_RE = re.compile(r'<div class="dp-cons-summary">.*?\n    </div>', re.S)
NOTE_RE = re.compile(r'<div style="margin-top:8px;font-size:11px;color:var\(--dp-text4\);">.*?</div>', re.S)
ID_RE = re.compile(r'research/company/(\d+)|company_read\.naver\?nid=(\d+)')
AUTO_MARK = '<!--cons-auto-->'


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f'WARNING 요청 실패 {url}: {e}', file=sys.stderr)
                return None
            time.sleep(1 + i)


def opinion_ko(op):
    s = (op or '').strip()
    k = re.sub(r'[\s_-]', '', s.lower())
    if not k or k in ('notrated', 'nr', 'none', '없음'):
        return '-'
    if k in ('buy', 'strongbuy', 'outperform', 'overweight', 'tradingbuy', '매수', '적극매수', 'accumulate', 'add'):
        return '매수'
    if k in ('hold', 'neutral', 'marketperform', '중립', '보유', 'marketweight', 'equalweight'):
        return '중립'
    if k in ('sell', 'reduce', 'underperform', 'underweight', '매도', 'strongsell'):
        return '매도'
    return s


def fetch_detail(rid):
    j = get_json(f'https://m.stock.naver.com/api/research/company/{rid}')
    time.sleep(0.12)
    if not j or 'researchContent' not in j:
        return None
    r = j['researchContent']
    g = re.sub(r'[^\d]', '', str(r.get('goalPrice') or ''))
    return {'code': r.get('itemCode'), 'broker': r.get('brokerName'), 'date': r.get('writeDate'),
            'opinion': r.get('opinion') or '', 'goal': int(g) if g and int(g) > 0 else None}


def load_pages(codes_filter):
    pages = []
    for p in sorted(glob.glob('stocks/[0-9]*_*.html')):
        b = os.path.basename(p)
        code = b.split('_', 1)[1][:-5]
        if codes_filter and code not in codes_filter:
            continue
        raw = open(p, 'rb').read()
        bom = raw.startswith(b'\xef\xbb\xbf')
        t = raw.decode('utf-8-sig')
        crlf = '\r\n' in t
        t = t.replace('\r\n', '\n')
        nm = re.search(r'<h1[^>]*>([^<]+)', t)
        name = html.unescape(nm.group(1).strip()) if nm else ''
        pages.append(dict(path=p, code=code, name=name, text=t, crlf=crlf, bom=bom))
    return pages


def scan_list(cache, codes, cutoff):
    """전체 리서치 목록을 최신순으로 넘기며 우리 종목 리포트 ID를 모은다."""
    last = cache.get('lastListId', 0)
    found = []
    for page in range(1, 120):
        j = get_json(f'https://m.stock.naver.com/api/research/company?page={page}&pageSize=100')
        time.sleep(0.12)
        if not j:
            break
        stop = False
        for x in j:
            rid = int(x['researchId'])
            if rid <= last or (x.get('writeDate') or '9') < cutoff:
                stop = True
                continue
            if x.get('itemCode') in codes:
                found.append(rid)
        if stop or len(j) < 100:
            break
    return found


def build_rows(cache, code, today):
    cutoff = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    best = {}
    for rid, r in cache['reports'].items():
        if r.get('code') != code or not r.get('goal') or (r.get('date') or '') < cutoff:
            continue
        b = r.get('broker') or '?'
        cur = best.get(b)
        if not cur or (r['date'], int(rid)) > (cur['date'], cur['id']):
            best[b] = dict(r, id=int(rid))
    return sorted(best.values(), key=lambda r: (r['date'], r['id']), reverse=True)[:MAX_ROWS]


def table_html(rows):
    e = html.escape
    out = ['<table>', '      <thead>', '        <tr>',
           '          <th class="dp-cons-th">증권사</th>',
           '          <th class="dp-cons-th" style="text-align:right;">목표주가</th>',
           '          <th class="dp-cons-th" style="text-align:center;">의견</th>',
           '          <th class="dp-cons-th" style="text-align:right;">작성일</th>',
           '        </tr>', '      </thead>', '      <tbody>']
    if not rows:
        out.append('        <tr><td class="dp-cons-td" colspan="4" style="text-align:center;color:var(--dp-text4);">최근 6개월 네이버 증권 리서치에 목표주가를 낸 리포트 없음</td></tr>')
    for r in rows:
        d = r['date'][2:].replace('-', '.')
        out.append(f'        <tr><td class="dp-cons-td"><a href="https://m.stock.naver.com/research/company/{r["id"]}" target="_blank" rel="noopener">{e(r["broker"])}</a></td>'
                   f'<td class="dp-cons-td" style="text-align:right;font-weight:700;">{r["goal"]:,}원</td>'
                   f'<td class="dp-cons-td" style="text-align:center;"><span class="dp-cons-badge">{e(opinion_ko(r["opinion"]))}</span></td>'
                   f'<td class="dp-cons-td" style="text-align:right;color:var(--dp-text4);">{d}</td></tr>')
    out += ['      </tbody>', '    </table>']
    return '\n'.join(out)


def summary_html(mean, label, price):
    if not mean:
        return ('<div class="dp-cons-summary">\n'
                '      <div><span style="color:var(--dp-text3);">평균 목표주가</span> <strong>없음</strong></div>\n'
                '      <div><span style="color:var(--dp-text3);">현재가 대비</span> <strong>-</strong></div>\n'
                '    </div>')
    up = ''
    if price:
        r = mean / price - 1
        up = f'<strong style="color:var(--dp-{"up" if r >= 0 else "down"});">{"+" if r >= 0 else ""}{r * 100:.1f}%</strong>'
    else:
        up = '<strong>-</strong>'
    return ('<div class="dp-cons-summary">\n'
            f'      <div><span style="color:var(--dp-text3);">평균 목표주가</span> <strong>{mean:,.0f}원</strong> <span style="color:var(--dp-text4);font-size:11px;">{html.escape(label)}</span></div>\n'
            f'      <div><span style="color:var(--dp-text3);">현재가 대비</span> {up}</div>\n'
            '    </div>')


def auto_note(rows, mean_src, today):
    s = '증권사별 가장 최근 리포트 기준(네이버 증권 리서치, 최근 6개월). 같은 증권사의 리포트가 여러 건이면 가장 최근 것만, 목표주가를 제시하지 않은 리포트는 뺐습니다.'
    if mean_src == 'fn':
        s += ' 평균 목표주가는 에프앤가이드 컨센서스 값으로, 표에 없는 증권사도 포함돼 표의 단순 평균과 다를 수 있습니다.'
    elif len(rows) == 1:
        s += ' 목표주가를 낸 곳이 1곳뿐이라 평균은 그 1건의 값입니다.'
    elif 0 < len(rows) <= 2:
        s += f' 목표주가를 낸 곳이 {len(rows)}곳뿐이라 평균의 대표성은 낮습니다.'
    s += f' {today:%Y.%m.%d} 자동 갱신.'
    return f'{AUTO_MARK}<div style="margin-top:8px;font-size:11px;color:var(--dp-text4);">{s}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--codes', default='')
    a = ap.parse_args()
    t0 = time.time()
    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    codes_filter = set(c for c in a.codes.split(',') if c)

    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    cache.setdefault('reports', {})
    cache.setdefault('means', {})
    pages = [p for p in load_pages(codes_filter) if not re.search(r'\d?우B?$', p['name'])]
    targets = []
    for p in pages:
        m = BODY_RE.search(p['text'])
        if not m:
            continue
        body = m.group(2)
        if not body.lstrip().startswith('<table>') or not SUMMARY_RE.search(body):
            continue
        p['m'] = m
        targets.append(p)
    codes = {p['code'] for p in targets}

    # 1) 새 리포트 ID: 전체 목록 + 페이지에 이미 걸린 링크(첫 실행 시드)
    new_ids = set(scan_list(cache, codes, cutoff))
    for p in targets:
        for a1, a2 in ID_RE.findall(p['m'].group(2)):
            new_ids.add(int(a1 or a2))
    # 2) 종목 API: 에프앤가이드 평균 목표주가 + 최근 리포트 5건(목록에서 놓친 것 보완)
    for p in targets:
        j = get_json(f'https://m.stock.naver.com/api/stock/{p["code"]}/integration')
        time.sleep(0.12)
        if not j:
            continue
        ci = j.get('consensusInfo') or {}
        v = re.sub(r'[^\d]', '', str(ci.get('priceTargetMean') or ''))
        cache['means'][p['code']] = {'mean': int(v) if v and int(v) > 0 else None, 'date': ci.get('createDate')}
        for x in j.get('researches') or []:
            new_ids.add(int(x['id']))
    fetched = 0
    for rid in sorted(new_ids):
        if str(rid) in cache['reports']:
            continue
        d = fetch_detail(rid)
        if d:
            cache['reports'][str(rid)] = d
            fetched += 1
    if new_ids:
        cache['lastListId'] = max([cache.get('lastListId', 0)] + [int(k) for k in cache['reports']])
    keep = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    cache['reports'] = {k: v for k, v in cache['reports'].items() if (v.get('date') or '') >= keep}

    # 3) 페이지 갱신
    n_table = n_sum = 0
    for p in targets:
        t, m = p['text'], p['m']
        body = m.group(2)
        rows = build_rows(cache, p['code'], today)
        old_ids = {int(x or y) for x, y in ID_RE.findall(TABLE_RE.search(body).group(0))}
        old_naver_only = '<a href="http' not in re.sub(r'<a href="https://(m\.stock|finance)\.naver\.com/research/[^"]*"', '', TABLE_RE.search(body).group(0))
        new_ids_p = {r['id'] for r in rows}
        mean_info = cache['means'].get(p['code']) or {}
        if mean_info.get('mean'):
            mean, label, src = mean_info['mean'], '에프앤가이드', 'fn'
        elif rows:
            mean, label, src = sum(r['goal'] for r in rows) / len(rows), f'{len(rows)}개 증권사 평균', 'rows'
        else:
            mean, label, src = None, '', None
        pm = re.search(r'<div class="dp-price">([\d,]+)원</div>', t)
        price = int(pm.group(1).replace(',', '')) if pm else None

        summ_old = SUMMARY_RE.search(body).group(0)
        if not mean and '현재가 대비' not in summ_old:
            continue  # 공모가·배당수익률 등 특수 요약은 데이터가 없으면 그대로 둔다
        new_body = body
        table_changed = new_ids_p != old_ids and (rows or old_naver_only)
        if table_changed:
            new_body = TABLE_RE.sub(lambda _: table_html(rows), new_body, 1)
            new_body = new_body.replace(AUTO_MARK, '')
            new_body = NOTE_RE.sub('', new_body)
            new_body = new_body.rstrip() + '\n    ' + auto_note(rows, src, today)
            n_table += 1
        elif AUTO_MARK in new_body:  # 자동 문구면 날짜·평균 출처만 새로
            new_body = re.sub(re.escape(AUTO_MARK) + r'<div[^>]*>.*?</div>', lambda _: auto_note(rows, src, today), new_body, count=1, flags=re.S)
        new_body = SUMMARY_RE.sub(lambda _: summary_html(mean, label, price), new_body, 1)
        if new_body != body:
            n_sum += 1
            t = t[:m.start(2)] + new_body + t[m.end(2):]
            if not a.dry:
                out = t.replace('\n', '\r\n') if p['crlf'] else t
                open(p['path'], 'wb').write((b'\xef\xbb\xbf' if p['bom'] else b'') + out.encode('utf-8'))
    if not a.dry and not codes_filter:
        os.makedirs('data', exist_ok=True)
        with open(CACHE, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(cache, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print(f'완료: 대상 {len(targets)}개 종목, 새 리포트 {fetched}건, 표 교체 {n_table}개, 페이지 변경 {n_sum}개, 소요 {time.time() - t0:.0f}초')


if __name__ == '__main__':
    main()
