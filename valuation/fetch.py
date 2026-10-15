"""내재가치 평가용 원천 데이터 수집 (증분).

.cache/ 아래에 저장하고, 이미 받은 공시는 다시 받지 않는다.
- fs/{code}.json      DART 전체 재무제표(연결 우선, 없으면 별도): 2015~작년 사업보고서 + 2020~올해 분기·반기
- ofs/{code}.json     지주·투자회사의 별도 재무제표(NAV용)
- inv/{code}.json     지주·투자회사의 타법인 출자현황(사업·반기보고서)
- alot/{code}.json    전체 재무제표가 없는 해(금융사 2015~2020 등)의 배당에 관한 사항
- px/{code}.json      Yahoo 월간 종가(분할 조정), USDKRW 포함
- naver.json          네이버 현재 주식 수·BPS (매일 갱신)
- corp.json           DART 고유번호 ↔ 종목코드 (30일마다 갱신)
"""
import os, io, re, json, time, zipfile, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, '.cache')
RC = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
UA = {'User-Agent': 'Mozilla/5.0'}


def _p(*a):
    return os.path.join(CACHE, *a)


def _get(url, timeout=30, tries=3):
    err = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            err = e
            time.sleep(2)
    raise err


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    json.dump(obj, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, path)


def key():
    k = os.environ.get('DART_API_KEY')
    if not k:
        raise RuntimeError('DART_API_KEY 환경변수가 없음')
    return k


def corp_map(max_age_days=30):
    """{stock_code: [corp_code, corp_name]} plus a name index for listed companies."""
    path = _p('corp.json')
    d = _load(path, None)
    if d and time.time() - d.get('ts', 0) < max_age_days * 86400:
        return d
    z = zipfile.ZipFile(io.BytesIO(_get('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + key(), timeout=120)))
    x = z.read(z.namelist()[0]).decode('utf-8')
    m = {}
    for blk in re.findall(r'<list>(.*?)</list>', x, re.S):
        sc = re.search(r'<stock_code>\s*(\w*)\s*</stock_code>', blk).group(1)
        if sc:
            m[sc] = [re.search(r'<corp_code>(\d+)</corp_code>', blk).group(1),
                     re.search(r'<corp_name>(.*?)</corp_name>', blk).group(1)]
    d = {'ts': time.time(), 'map': m}
    _save(path, d)
    return d


def dart(api, **params):
    q = '&'.join(f'{k}={v}' for k, v in params.items())
    try:
        return json.loads(_get(f'https://opendart.fss.or.kr/api/{api}.json?crtfc_key={key()}&{q}').decode('utf-8'))
    except Exception as e:
        return {'status': 'ERR', 'message': str(e)}


def report_jobs(today=None):
    """(year, reprt_code) pairs that may exist by now. 2015~ annual, 2020~ quarterly."""
    today = today or datetime.date.today()
    jobs = [(y, '11011') for y in range(2015, 2020)]
    for y in range(2020, today.year + 1):
        for q in (1, 2, 3, 4):
            # 공시 기한: 분기·반기 +45일, 사업보고서 +90일. 기한 전이라도 일찍 내는 회사가 있어 마감 다음날부터 조회
            end = datetime.date(y, q * 3, 28)
            if today >= end + datetime.timedelta(days=1):
                jobs.append((y, RC[q]))
    return jobs


def _recent(y, rc, today):
    """013(미제출)을 다시 조회할 가치가 있는 최근 공시인지 — 기한 + 20일까지만 재시도."""
    q = {v: k for k, v in RC.items()}[rc]
    end = datetime.date(y, q * 3, 28)
    deadline = end + datetime.timedelta(days=110 if q == 4 else 65)
    return today <= deadline


def refresh_fs(code, corp, fs_div_dir='fs', fs_div='CFS', today=None, log=print):
    today = today or datetime.date.today()
    path = _p(fs_div_dir, f'{code}.json')
    out = _load(path, {})
    changed = 0
    for y, rc in report_jobs(today):
        k = f'{y}_{rc}'
        old = out.get(k)
        if old and old.get('status') == '000':
            continue
        if old and old.get('status') == '013' and not _recent(y, rc, today):
            continue
        if old and old.get('checked') == str(today):
            continue
        d = dart('fnlttSinglAcntAll', corp_code=corp, bsns_year=y, reprt_code=rc, fs_div=fs_div)
        if d.get('status') == '013' and fs_div == 'CFS':
            o = dart('fnlttSinglAcntAll', corp_code=corp, bsns_year=y, reprt_code=rc, fs_div='OFS')
            if o.get('status') == '000':
                o['fs_div'] = 'OFS'
                d = o
        if d.get('status') not in ('000', '013'):
            log(f'WARN DART {code} {k}: {d.get("status")} {d.get("message", "")[:80]}')
            continue
        d['checked'] = str(today)
        if d.get('status') == '000':
            changed += 1
        out[k] = d
        time.sleep(0.12)
    _save(path, out)
    return changed


def refresh_alot(code, corp):
    """전체 재무제표가 없는 2015~2020년의 순이익·EPS·배당 (한 번만 받음)."""
    path = _p('alot', f'{code}.json')
    if os.path.exists(path):
        return
    d = _load(_p('fs', f'{code}.json'), {})
    have = {y for y in range(2015, 2021) if (d.get(f'{y}_11011') or {}).get('status') == '000'}
    for y in (2021, 2022):
        if (d.get(f'{y}_11011') or {}).get('status') == '000':
            have |= {y - 1, y - 2}
    need = [y for y in range(2015, 2021) if y not in have]
    if not need:
        return
    out = {str(y): dart('alotMatter', corp_code=corp, bsns_year=y, reprt_code='11011') for y in need}
    _save(path, out)


def refresh_inv(code, corp, today=None):
    """타법인 출자현황(사업·반기보고서). 수량·지분율·장부가."""
    today = today or datetime.date.today()
    path = _p('inv', f'{code}.json')
    out = _load(path, {})
    for y, rc in report_jobs(today):
        if y < 2020 or rc not in ('11011', '11012'):
            continue
        k = f'{y}_{rc}'
        old = out.get(k)
        if old and (old.get('status') == '000' or (old.get('status') == '013' and not _recent(y, rc, today))
                    or old.get('checked') == str(today)):
            continue
        d = dart('otrCprInvstmntSttus', corp_code=corp, bsns_year=y, reprt_code=rc)
        if d.get('status') in ('000', '013'):
            d['checked'] = str(today)
            out[k] = d
        time.sleep(0.12)
    _save(path, out)


def refresh_px(code, max_age_hours=20):
    """Yahoo 월간 종가. 매일 한 번 갱신(이번 달 값이 바뀌므로)."""
    path = _p('px', f'{code}.json')
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_hours * 3600:
        return True
    sym = ['KRW=X'] if code == 'USDKRW' else [f'{code}.KS', f'{code}.KQ']
    for s in sym:
        try:
            r = json.loads(_get(f'https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=15y&interval=1mo'))['chart']['result'][0]
            _save(path, {'ts': r['timestamp'], 'c': r['indicators']['quote'][0]['close']})
            return True
        except Exception:
            continue
    return False


def _krw(s):
    s = str(s).replace(',', '')
    tot = 0.0
    m = re.search(r'([\d.]+)조', s)
    tot += float(m.group(1)) * 1e12 if m else 0
    m = re.search(r'([\d.]+)억', s)
    tot += float(m.group(1)) * 1e8 if m else 0
    if not tot:
        v = re.sub(r'[^\d.-]', '', s)
        tot = float(v) if v not in ('', '-', '.') else 0.0
    return tot


def refresh_naver(codes):
    """네이버 현재 주식 수(시총/종가)와 BPS. 액면분할 보정·지분가치 계산에 사용."""
    path = _p('naver.json')
    out = _load(path, {})
    today = str(datetime.date.today())
    for c in codes:
        if out.get(c, {}).get('date') == today and out[c].get('v') == 2:
            continue
        try:
            d = json.loads(_get(f'https://m.stock.naver.com/api/stock/{c}/integration', timeout=20))
            ti = {x['code']: x['value'] for x in d.get('totalInfos', [])}
            # integration의 marketValue는 현재 시세 기준이고 lastClosePrice는 전일 종가라 둘을 나누면
            # 하루 등락만큼 주식 수가 틀어짐 → 같은 시점의 현재가(basic.closePrice)로 나눔
            basic = json.loads(_get(f'https://m.stock.naver.com/api/stock/{c}/basic', timeout=20))
            close = _krw(basic.get('closePrice', ''))
            out[c] = {'v': 2, 'date': today, 'shares': _krw(ti['marketValue']) / close if close else None,
                      'bps': _krw(ti.get('bps', '')) or None}
        except Exception:
            pass
        time.sleep(0.08)
    _save(path, out)
    return out
