"""오늘의 투자논리: 매일 뉴스·시장 데이터로 투자논리를 세우고, 그 논리에 맞는 코스피 종목을 데이터로 찾는다.

흐름
  1) 유니버스: 네이버 모바일 API로 코스피 전 종목(ETF·ETN 제외) 가격·등락률·시총·업종.
  2) 뉴스: 시장·거시 키워드 뉴스(네이버 검색 API) + 사이트 종목 뉴스 아카이브(data/news)의 최근 기사.
  3) 투자논리: claude CLI(헤드리스)가 뉴스·업종 등락만 근거로 3~5개 논리와 수혜 조건(업종·키워드)을 JSON으로 작성.
     종목은 고르지 않는다(지어낸 종목 방지) — 종목 선정은 4)의 코드가 한다.
  4) 매칭: 논리마다 근거 기사 + 키워드 재검색 기사에서 종목명 언급 수, 업종 일치, 당일 업종 동조, 사이트 보유
     종목은 내재가치·기술적 점수를 더해 점수화 → 상위 종목.
  5) 추적: 과거 논리의 종목을 제시일 종가 대비 수익률로 추적(코스피 대비 초과수익).
출력: data/theses/latest.json, data/theses/history/YYYY-MM-DD.json
투자 권고가 아니며, 뉴스와 공개 데이터로 만든 참고 자료다.
"""
import datetime, glob, html, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'data', 'theses')
HIST = os.path.join(OUT, 'history')
UA = {'User-Agent': 'Mozilla/5.0'}
CLAUDE = os.environ.get('CLAUDE_CLI', r'C:\Users\h24795\.local\bin\claude.exe')
MODEL = os.environ.get('THESES_MODEL', 'claude-opus-5')
NEWS_API = 'https://naverapihub.apigw.ntruss.com/search/v1/news'
MIN_CAP_EOK = 1000          # 시총 1,000억 미만은 후보에서 제외(유동성·정보 부족)
PICKS = 6                   # 논리당 종목 수
MARKET_QUERIES = ['코스피 증시', '외국인 순매수', '금리 인하', '원달러 환율', '수출 실적', '반도체 업황', 'AI 데이터센터',
                  '2차전지 배터리', '조선 수주', '방산 수출', '원전', '바이오 신약 기술수출', '유가 정유', '관세 무역',
                  '정부 정책 지원', '자사주 소각 밸류업', '실적 서프라이즈', '목표주가 상향']
LOW_VALUE = re.compile(r'^\[(인사|부고|동정|게시판|알림|부음|오늘의 주요일정)\]|포토|화보')


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def num(s):
    try:
        return float(str(s).replace(',', ''))
    except (TypeError, ValueError):
        return None


def load(path, default=None):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


# ── 1) 유니버스 ──────────────────────────────────────────────────────────────
def universe():
    out = {}
    page = 1
    while True:
        r = get_json(f'https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page={page}&pageSize=100')
        st = r.get('stocks') or []
        if not st:
            break
        for s in st:
            if s.get('stockEndType') != 'stock':
                continue
            out[s['itemCode']] = {'code': s['itemCode'], 'name': s['stockName'], 'price': num(s.get('closePrice')),
                                  'chg': num(s.get('fluctuationsRatio')), 'capEok': num(s.get('marketValue')), 'ind': '기타'}
        page += 1
        if page > 40:
            break
    # 업종: 업종 목록 → 업종별 종목
    groups, pg = [], 1
    while True:
        r = get_json(f'https://m.stock.naver.com/api/stocks/industry?page={pg}&pageSize=50')
        g = r.get('groups') or []
        groups += g
        if len(g) < 50:
            break
        pg += 1
    for g in groups:
        p = 1
        while True:
            r = get_json(f"https://m.stock.naver.com/api/stocks/industry/{g['no']}?page={p}&pageSize=100")
            st = r.get('stocks') or []
            for s in st:
                if s.get('itemCode') in out:
                    out[s['itemCode']]['ind'] = g['name']
            if len(st) < 100:
                break
            p += 1
        time.sleep(0.05)
    return out


def site_meta():
    """사이트 종목(상세 페이지·내재가치·기술적 점수 보유)."""
    t = open(os.path.join(REPO, 'index.html'), encoding='utf-8').read()
    pages = {m.group(2): m.group(1) for m in re.finditer(r'"page": "(stocks/\d{3}_(\d{6})\.html)"', t)}
    iv = (load(os.path.join(REPO, 'data', 'intrinsic_value.json'), {}) or {}).get('stocks', {})
    ts = load(os.path.join(REPO, 'data', 'technical_score.json'), {}) or {}
    tsm = {c: v.get('technical_score') for c, v in ts.items() if isinstance(v, dict) and v.get('data_status') == 'ok'}
    return pages, iv, tsm


# ── 2) 뉴스 ─────────────────────────────────────────────────────────────────
def news_search(q, n=30):
    kid, ksec = os.environ.get('NAVER_API_HUB_CLIENT_ID'), os.environ.get('NAVER_API_HUB_CLIENT_SECRET')
    if not (kid and ksec):
        return []
    url = f'{NEWS_API}?query={urllib.parse.quote(q)}&display={n}&start=1&sort=date&format=json'
    try:
        r = get_json(url, {'X-NCP-APIGW-API-KEY-ID': kid, 'X-NCP-APIGW-API-KEY': ksec})
    except Exception as e:
        log('WARN 뉴스 검색 실패', q, e)
        return []
    out = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for it in r.get('items') or []:
        title = html.unescape(re.sub(r'</?b>', '', it.get('title', '')))
        desc = html.unescape(re.sub(r'</?b>', '', it.get('description', '')))
        if LOW_VALUE.search(title):
            continue
        try:
            pub = datetime.datetime.strptime(it['pubDate'], '%a, %d %b %Y %H:%M:%S %z')
        except (KeyError, ValueError):
            continue
        if (now - pub).total_seconds() > 36 * 3600:
            continue
        link = it.get('originallink') or it.get('link')
        out.append({'title': title, 'desc': desc, 'link': link, 'pub': pub.astimezone().strftime('%m-%d %H:%M'),
                    'domain': urllib.parse.urlparse(link).netloc.replace('www.', '')})
    return out


def dedup(items):
    seen, out = [], []
    for it in items:
        k = set(re.findall(r'\w{2,}', it['title']))
        if any(len(k & s) / max(1, len(k | s)) > 0.5 for s in seen):
            continue
        seen.append(k)
        out.append(it)
    return out


def site_news(today):
    """사이트 종목 뉴스 아카이브에서 최근 이틀치 대표 기사."""
    days = {today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()}
    out = []
    for f in glob.glob(os.path.join(REPO, 'data', 'news', '*.json')):
        d = load(f, {}) or {}
        for day, items in d.items():
            if day not in days:
                continue
            for it in (items if isinstance(items, list) else [])[:3]:
                if isinstance(it, dict) and it.get('title'):
                    out.append({'title': it['title'], 'desc': '', 'link': it.get('link'), 'pub': it.get('time') or day[5:],
                                'domain': it.get('source', '')})
    return out


# ── 3) 투자논리(claude CLI) ─────────────────────────────────────────────────
def ask_claude(prompt, timeout=300):
    path = os.path.join(OUT, f'.tmp_prompt_{uuid.uuid4().hex}.txt')
    os.makedirs(OUT, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(prompt)
    trig = (f'Read the file at {path} completely (UTF-8 encoded). It contains [SYSTEM INSTRUCTIONS] and [DATA] '
            'sections. Follow the instructions exactly using only the data given, and respond with ONLY the requested '
            'JSON object - no markdown code fences, no other text before or after.')
    try:
        r = subprocess.run([CLAUDE, '-p', trig, '--output-format', 'json', '--add-dir', OUT, '--model', MODEL],
                           capture_output=True, timeout=timeout, cwd=REPO)
        res = json.loads(r.stdout.decode('utf-8', 'replace'))
        if res.get('is_error'):
            raise RuntimeError(res.get('result'))
        txt = res.get('result', '').strip()
        # 이 PC에서 claude CLI 큰 한글 응답이 깨져(mojibake) 들어온 적이 있음(2026-09, update_daily_charts.ps1 주석) —
        # 깨진 응답은 저장하지 않고 실패 처리해 전날 카드를 유지한다.
        letters = [ch for ch in txt if ch.isalpha()]
        hangul = sum('가' <= ch <= '힣' for ch in letters)
        if '�' in txt or (letters and hangul / len(letters) < 0.3):
            raise RuntimeError(f'claude 응답 인코딩 이상(한글 비율 {hangul}/{len(letters)})')
        txt = re.sub(r'^```(?:json)?|```$', '', txt).strip()
        return json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def build_prompt(today, news, ind_moves, industries):
    lines = [f'[{i}] ({n["pub"]} {n["domain"]}) {n["title"]}' + (f' — {n["desc"][:120]}' if n['desc'] else '')
             for i, n in enumerate(news)]
    mv = ', '.join(f'{k} {v:+.2f}%' for k, v in ind_moves)
    return f"""[SYSTEM INSTRUCTIONS]
당신은 한국 주식시장 리서치 애널리스트입니다. 아래 [DATA]의 오늘 뉴스 헤드라인과 업종별 등락률만 근거로,
지금 시장에서 데이터로 뒷받침되는 투자논리(테마) 3~5개를 세우세요.
규칙:
- 각 논리는 여러 기사(서로 다른 매체 우선)로 뒷받침되어야 한다. 기사 1건짜리 논리는 만들지 않는다.
- 근거 기사는 [번호]로만 인용한다(evidence). 데이터에 없는 사실·수치·전망을 지어내지 않는다.
- 개별 종목을 추천하거나 종목명을 고르지 않는다. 대신 수혜를 판단할 조건을 준다:
  industries = 아래 [업종 목록]에 있는 업종명만(정확히 같은 문자열), keywords = 뉴스에서 수혜 기업을 찾을 검색어 2~4개.
- 반대 근거·리스크도 반드시 쓴다(risks). 매수·매도 권유 표현은 쓰지 않는다.
- direction: 'positive'(수혜) 또는 'negative'(피해). 피해 논리도 데이터가 뒷받침하면 포함한다.
다음 JSON 형식으로만 응답: {{"theses": [{{"title": "20자 내외 제목", "summary": "논리 2~3문장",
"evidence": [기사번호...], "industries": ["업종명", ...], "keywords": ["검색어", ...],
"direction": "positive|negative", "horizon": "단기|중기", "risks": "리스크 1~2문장"}}]}}

[DATA]
날짜: {today.isoformat()}
[업종 목록] {' / '.join(industries)}
[오늘 업종별 평균 등락률(시총 가중)] {mv}
[뉴스]
""" + '\n'.join(lines)


# ── 4) 매칭 ─────────────────────────────────────────────────────────────────
def name_index(uni):
    """종목명 → 코드. 짧거나 흔한 단어와 겹치는 이름은 오매칭을 막으려 제외."""
    bad = {'대상', '한진', '동방', '대원', '삼양', '신성', '태양', '세방', '한일', '대한', '동양', '조선', '미래', '현대', '신세계'}
    idx = {}
    for c, s in uni.items():
        n = s['name']
        if len(n) < 2 or n in bad or n.endswith('우') and len(n) > 2 and c[-1] != '0':
            continue
        idx[n] = c
    return idx


def mentions(texts, idx):
    """기사별로 언급된 종목 코드 집합. 이름 뒤에 다른 글자가 붙으면(다른 고유명사의 일부) 제외."""
    out = []
    for t in texts:
        hit = set()
        for n, c in idx.items():
            i = t.find(n)
            while i >= 0:
                nxt = t[i + len(n):i + len(n) + 1]
                if not nxt or not re.match(r'[가-힣A-Za-z0-9]', nxt) or nxt in '은는이가을를의와과도에로':
                    hit.add(c)
                    break
                i = t.find(n, i + 1)
        out.append(hit)
    return out


def match(th, news, uni, idx, pages, iv, tsm, ind_chg, base):
    """base: 오늘 시장 뉴스 전체에서 종목별 언급 기사 수(대형주가 모든 논리에 끼는 것을 막는 기준선)."""
    ev = [news[i] for i in th.get('evidence', []) if isinstance(i, int) and 0 <= i < len(news)]
    extra = []
    for k in (th.get('keywords') or [])[:4]:
        extra += news_search(k, 30)
        time.sleep(0.1)
    extra = dedup(extra)
    toks = {w for k in (th.get('keywords') or []) for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', k)}
    # 키워드 재검색 기사는 논리 키워드가 실제로 들어 있는 것만 근거로 인정(검색 결과의 무관한 기사 배제)
    rel = ev + [n for n in extra if any(w in n['title'] + n.get('desc', '') for w in toks)]
    hits = mentions([n['title'] + ' ' + n.get('desc', '') for n in rel], idx)
    cnt = {}
    for h in hits:
        for c in h:
            cnt[c] = cnt.get(c, 0) + 1
    inds = set(th.get('industries') or [])
    neg = th.get('direction') == 'negative'
    rows = []
    for c, s in uni.items():
        if not s['capEok'] or s['capEok'] < MIN_CAP_EOK:
            continue
        m = cnt.get(c, 0)
        in_ind = s['ind'] in inds
        if not m and not in_ind:
            continue
        if s['ind'] == '증권' and '증권' not in inds:
            continue                                     # 기사 출처로 인용된 증권사 이름이 종목으로 잡히는 것 방지
        if not in_ind and (neg or m < 3):
            continue                                     # 업종 밖 종목은 관련 기사 3건 이상일 때만, 피해 논리는 업종 안에서만
        lift = min(1.0, (8 / max(base.get(c, 0), 1)) ** 0.5)   # 시장 기사 전반에 늘 나오는 종목은 언급 가중치 축소
        sc = min(m, 6) * 10 * lift * (1 if in_ind else 0.6) + (15 if in_ind else 0)
        if m and in_ind:
            sc += 10
        if s['chg'] is not None:                         # 당일 논리 방향과 같은 방향으로 움직였으면 가점(시장이 반영 중)
            sc += max(-5, min(5, (-s['chg'] if neg else s['chg'])))
        why = []
        if m:
            why.append(f'관련 기사 {m}건')
        why.append(f'업종 {s["ind"]}' if in_ind else '업종 외 · 기사 언급')
        v = iv.get(c)
        if v and v.get('low', 0) > 0 and not v.get('hold') and s['price']:
            ratio = s['price'] / ((v['low'] * v['high']) ** 0.5)
            sc += max(-8, min(8, (1 - ratio) * 10)) * (-1 if neg else 1)
            why.append(f'주가/내재가치 {ratio:.2f}배')
        t = tsm.get(c)
        if isinstance(t, (int, float)):
            sc += (t - 50) / 10 * (-1 if neg else 1)
            why.append(f'기술적 {t:.0f}점')
        if not m:
            sc *= 0.6                                    # 기사 언급 없이 업종만 맞는 종목은 감점
        rows.append({'code': c, 'name': s['name'], 'score': round(sc, 1), 'mentions': m, 'ind': s['ind'],
                     'price': s['price'], 'chg': s['chg'], 'capEok': s['capEok'], 'page': pages.get(c), 'why': ' · '.join(why)})
    rows.sort(key=lambda r: (-r['score'], -(r['capEok'] or 0)))
    out, per = [], {}
    for r in rows:                                       # 같은 업종 쏠림 완화: 업종당 최대 3종목
        if per.get(r['ind'], 0) >= 3 or (not r['mentions'] and len(out) >= 3):
            continue                                     # 기사 언급 없는 종목은 3개가 안 찰 때만 보충
        per[r['ind']] = per.get(r['ind'], 0) + 1
        out.append(r)
        if len(out) >= PICKS:
            break
    return out, ev


# ── 5) 추적 ─────────────────────────────────────────────────────────────────
def track(uni, today, kospi_now):
    res = []
    for f in sorted(glob.glob(os.path.join(HIST, '*.json')))[-30:]:
        d = load(f, {})
        if not d or d.get('date') == today.isoformat():
            continue
        for th in d.get('theses', []):
            rets = []
            for p in th.get('picks', []):
                cur = (uni.get(p['code']) or {}).get('price')
                if cur and p.get('price'):
                    rets.append(cur / p['price'] - 1)
            if not rets:
                continue
            avg = sum(rets) / len(rets)
            if th.get('direction') == 'negative':
                avg = -avg
            k0 = d.get('kospi')
            bench = (kospi_now / k0 - 1) if (k0 and kospi_now) else None
            res.append({'date': d['date'], 'title': th['title'], 'direction': th.get('direction'), 'n': len(rets),
                        'ret': round(avg * 100, 2), 'excess': round((avg - (bench if th.get('direction') != 'negative' else -bench)) * 100, 2) if bench is not None else None})
    return res


def kospi_index():
    try:
        r = get_json('https://m.stock.naver.com/api/index/KOSPI/basic')
        return num(r.get('closePrice'))
    except Exception:
        return None


def main():
    today = datetime.date.today()
    if len(sys.argv) > 1:
        today = datetime.date.fromisoformat(sys.argv[1])
    log('유니버스 수집')
    uni = universe()
    log(f'코스피 {len(uni)}종목')
    pages, iv, tsm = site_meta()
    # 업종별 시총 가중 등락률
    agg = {}
    for s in uni.values():
        if s['ind'] and s['capEok'] and s['chg'] is not None:
            a = agg.setdefault(s['ind'], [0.0, 0.0])
            a[0] += s['chg'] * s['capEok']
            a[1] += s['capEok']
    ind_chg = {k: v[0] / v[1] for k, v in agg.items() if v[1]}
    ind_moves = sorted(ind_chg.items(), key=lambda x: -abs(x[1]))
    log('뉴스 수집')
    news = []
    for q in MARKET_QUERIES:
        news += news_search(q, 40)
        time.sleep(0.1)
    news += site_news(today)
    news = dedup(news)[:260]
    log(f'뉴스 {len(news)}건')
    if len(news) < 20:
        log('뉴스가 부족해 생성 생략')
        return 1
    raw_path = os.path.join(OUT, '.raw', f'{today.isoformat()}.json')
    cached = load(raw_path) if os.environ.get('THESES_REUSE') else None
    if cached:                                           # 매칭 로직만 다시 돌릴 때: 같은 날 뉴스·논리 재사용
        news, res = cached['news'], cached['res']
        log('저장된 논리 재사용')
    else:
        log('투자논리 생성(claude)')
        prompt = build_prompt(today, news, ind_moves, sorted(ind_chg))
        try:
            res = ask_claude(prompt)
        except (ValueError, RuntimeError) as e:          # 응답 JSON 깨짐(따옴표 미이스케이프 등)·인코딩 이상은 1회 재시도
            log(f'WARN claude 응답 처리 실패, 재시도: {e}')
            res = ask_claude(prompt)
        save(raw_path, {'news': news, 'res': res})
    theses = []
    idx = name_index(uni)
    base = {}
    for h in mentions([n['title'] + ' ' + n.get('desc', '') for n in news], idx):
        for c in h:
            base[c] = base.get(c, 0) + 1
    for th in (res.get('theses') or [])[:5]:
        th['industries'] = [i for i in th.get('industries') or [] if i in ind_chg]
        picks, ev = match(th, news, uni, idx, pages, iv, tsm, ind_chg, base)
        if len(ev) < 2 or not picks:
            log('제외(근거·종목 부족):', th.get('title'))
            continue
        theses.append({**{k: th.get(k) for k in ('title', 'summary', 'direction', 'horizon', 'risks', 'industries', 'keywords')},
                       'evidence': [{'title': n['title'], 'link': n['link'], 'domain': n['domain'], 'pub': n['pub']} for n in ev][:6],
                       'indChg': {i: round(ind_chg[i], 2) for i in th['industries']},
                       'picks': picks})
    kospi = kospi_index()
    out = {'date': today.isoformat(), 'generatedAt': time.strftime('%Y-%m-%d %H:%M'), 'kospi': kospi,
           'newsCount': len(news), 'theses': theses, 'track': track(uni, today, kospi),
           'note': '뉴스 헤드라인과 공개 시장 데이터로 자동 생성한 참고 자료이며 투자 권고가 아닙니다. 종목은 AI가 고르지 않고 '
                   '관련 기사 언급 수·업종·내재가치·기술적 점수로 계산해 선정합니다.'}
    save(os.path.join(HIST, f'{today.isoformat()}.json'), out)
    save(os.path.join(OUT, 'latest.json'), out)
    # 날짜 선택용 목록(최신순): 메인 패널이 이 목록으로 history/{date}.json을 불러온다
    dates = sorted((os.path.basename(f)[:-5] for f in glob.glob(os.path.join(HIST, '*.json'))), reverse=True)
    save(os.path.join(OUT, 'dates.json'), {'dates': dates})
    log(f'완료: 논리 {len(theses)}개')
    return 0


if __name__ == '__main__':
    sys.exit(main())
