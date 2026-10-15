"""내재가치 평가 일일 배치: 데이터 증분 수집 → 분기별 내재가치 계산 → stocks/*.html 박스·그래프 갱신.

update_daily_charts.ps1이 매일 호출한다. 새 분기·반기·사업보고서가 공시되면 자동으로 다음 밴드가 추가되고,
월간 주가는 매일 갱신된다.

사용: python valuation/run_daily.py [--code 005930 ...] [--skip-fetch]
"""
import os, sys, re, glob, json, time, argparse, logging

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

import fetch  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('valuation')


def stock_pages():
    out = []
    for f in sorted(glob.glob(os.path.join(REPO, 'stocks', '[0-9][0-9][0-9]_*.html'))):
        no, code = os.path.basename(f)[:-5].split('_', 1)
        out.append({'no': no, 'code': code, 'file': f})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', nargs='*', help='이 종목만 처리')
    ap.add_argument('--skip-fetch', action='store_true', help='캐시만으로 계산·반영')
    a = ap.parse_args()
    t0 = time.time()
    stocks = stock_pages()
    if a.code:
        stocks = [s for s in stocks if s['code'] in a.code]
    types = json.load(open(os.path.join(ROOT, 'types.json'), encoding='utf-8'))
    pref, hold = types['우선주'], set(types['지주·투자'])
    codes = sorted({pref.get(s['code'], s['code']) for s in stocks})

    if not a.skip_fetch:
        cm = fetch.corp_map()['map']
        new_reports = 0
        for i, c in enumerate(codes, 1):
            corp = (cm.get(c) or [None])[0]
            if not corp:
                log.warning('DART 고유번호 없음: %s', c)
                continue
            new_reports += fetch.refresh_fs(c, corp, log=log.warning)
            fetch.refresh_alot(c, corp)
            if c in hold:
                fetch.refresh_fs(c, corp, fs_div_dir='ofs', fs_div='OFS', log=log.warning)
                fetch.refresh_inv(c, corp)
            if i % 20 == 0:
                log.info('DART 수집 %d/%d', i, len(codes))
        # 지주사 보유 상장사(NAV용) 종목코드
        import engine as _e
        investees = set()
        for c in codes:
            if c in hold:
                for d in (fetch._load(os.path.join(fetch.CACHE, 'inv', f'{c}.json'), {}) or {}).values():
                    for x in d.get('list') or []:
                        lc = _e.listed_code(x.get('inv_prm', ''))
                        if lc:
                            investees.add(lc)
        px_codes = sorted(set(s['code'] for s in stocks) | set(codes) | investees | {'USDKRW'})
        miss = [c for c in px_codes if not fetch.refresh_px(c)]
        if miss:
            log.warning('월간 주가 수집 실패: %s', ' '.join(miss))
        fetch.refresh_naver(sorted(set(codes) | investees))
        log.info('수집 완료: 새 공시 %d건, 주가 %d종목', new_reports, len(px_codes))

    import importlib, engine, render
    importlib.reload(engine)   # 갱신된 naver.json 반영
    importlib.reload(render)
    res = engine.run_all(stocks)
    counts = {}
    for s in stocks:
        st = render.apply(s['file'], s['code'], res.get(s['code']))
        counts[st] = counts.get(st, 0) + 1
        r = res.get(s['code']) or {}
        if 'error' in r:
            log.warning('%s %s 평가 불가: %s', s['no'], s['code'], r['error'])
    summary = {s['code']: ({'type': r['type'], 'q': r['quarters'][-1]['q'],
                            'low': round(r['quarters'][-1]['low']), 'high': round(r['quarters'][-1]['high'])}
                           if 'quarters' in (r := res.get(s['code']) or {}) else {'error': r.get('error')})
               for s in stocks}
    json.dump(summary, open(os.path.join(fetch.CACHE, 'last_result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    log.info('완료: %d종목 %s, %.0f초 소요', len(stocks), ' '.join(f'{k}={v}' for k, v in sorted(counts.items())), time.time() - t0)


if __name__ == '__main__':
    main()
