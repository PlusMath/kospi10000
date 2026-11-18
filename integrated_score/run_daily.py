"""QRI 통합 매력도 일일 배치: 저장된 기본지표·내재가치 결과만 읽어 data/integrated_score.json 생성.

네트워크 수집을 하지 않는다(--skip-fetch는 다른 배치와 옵션을 맞추기 위한 무동작 플래그).
기술적 점수 파일은 읽지 않는다. update_daily_charts.ps1이 내재가치 배치 뒤에 호출한다.

사용:
  python -m integrated_score.run_daily [--dry-run] [--out PATH] [--snapshot-dir DIR] [--repo DIR]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys

from . import config as C
from . import scoring

PKG = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(PKG)

KEYMAP = {'roe': 'roe', 'epsGrowth': 'growth', 'debtRatio': 'safety', 'fpe': 'fpe', 'pbr': 'pbr', 'divYield': 'div'}
INPUTS = {'fundamental': 'data/fundamental_score.json', 'intrinsic': 'data/intrinsic_value.json',
          'peers': 'data/peer_universe.json', 'types': 'valuation/types.json', 'index': 'index.html'}


class InputChanged(RuntimeError):
    pass


def read_snapshot(repo: str) -> dict:
    """입력 파일을 한 번만 읽어 (원문 해시, 파싱 결과)로 고정 — 처리 중 파일이 바뀌면 게시하지 않기 위함."""
    snap = {}
    for k, rel in INPUTS.items():
        p = os.path.join(repo, rel)
        try:
            raw = open(p, 'rb').read()
        except OSError:
            snap[k] = {'path': p, 'sha': None, 'data': None}
            continue
        txt = raw.decode('utf-8-sig')
        snap[k] = {'path': p, 'sha': hashlib.sha256(raw).hexdigest(), 'data': txt if k == 'index' else json.loads(txt)}
    return snap


def verify_unchanged(snap: dict):
    for k, v in snap.items():
        try:
            sha = hashlib.sha256(open(v['path'], 'rb').read()).hexdigest()
        except OSError:
            sha = None
        if sha != v['sha']:
            raise InputChanged(f'입력 파일이 실행 중 바뀜: {v["path"]}')


# ── 구 스키마(qri_status 없는 fundamental_score.json) 호환 ────────────────────
# 2026-11-17 이전 파일에는 업종 중앙값·EPS 원값이 없다. 같은 업종 그룹에서 점수가 상·하한에 걸리지 않은 종목의
# 백분위로 그룹 중앙값을 정확히 역산할 수 있다(PER·PBR: p = 0.5 − ln(v/m)/(2ln3), ROE: p = 0.5 + (v−m)/20).
# 적자 여부는 사유 문장을 파싱해야만 알 수 있어 구 스키마에서는 결측으로 둔다(새 스키마의 qri_status로만 판정).

def _legacy_medians(records: list) -> dict:
    out = collections.defaultdict(list)
    for s in records:
        for m in s.get('metrics') or []:
            p, v = m.get('percentile'), m.get('value')
            if m.get('status') != 'valid' or not isinstance(p, (int, float)) or not isinstance(v, (int, float)) or not (0 < p < 1):
                continue
            if m['key'] in ('fpe', 'pbr') and v > 0:
                out[(s['peer_group'], m['key'])].append(v / math.exp((0.5 - p) * 2 * math.log(3)))
            elif m['key'] == 'roe':
                out[(s['peer_group'], 'roe')].append(v - (p - 0.5) * 20)
    return {k: sorted(v)[len(v) // 2] for k, v in out.items()}


def adapt_metrics(rec: dict, legacy_med: dict, peers_stale: bool) -> tuple[dict, bool]:
    """fundamental_score.json 종목 레코드 → {roe, growth, safety, fpe, pbr, div} 정규화 입력. 반환 (metrics, legacy여부)."""
    ms = {m['key']: m for m in rec.get('metrics') or []}
    legacy = not any('qri_status' in m for m in ms.values())
    out = {}
    for k, m in ms.items():
        key = KEYMAP.get(k)
        if not key:
            continue
        if not legacy:
            d = {'status': m.get('qri_status', 'missing'), 'value': m.get('value'), 'median': m.get('median'),
                 'peer_n': m.get('peer_n'), 'percentile': m.get('percentile')}
            if key == 'growth':
                d.update(cns_eps=m.get('cns_eps'), eps_last=m.get('eps_last'), eps_last_year=m.get('eps_last_year'))
        else:
            st = m.get('status')
            d = {'status': 'missing', 'value': m.get('value'), 'percentile': m.get('percentile'), 'peer_n': None}
            if key in ('fpe', 'pbr', 'roe') and st == 'valid':
                med = legacy_med.get((rec['peer_group'], k))
                d.update(status='valid' if med is not None else 'insufficient_peers', median=med)
            elif key == 'growth' and st == 'valid':
                d.update(status='turnaround', cns_eps=1.0) if m.get('value') is None else d.update(status='valid', growth_pct=m['value'])
            elif key in ('safety', 'div') and st in ('valid', 'zero_dividend'):
                d['status'] = st
        if peers_stale and key in ('fpe', 'pbr', 'roe') and d['status'] == 'valid':
            d['status'] = 'stale'
        out[key] = d
    return out, legacy


def legacy_prices(index_html: str) -> tuple[dict, str | None]:
    """구 스키마 전용: index.html stockLive 가격과 그 기준일('.daily-movers-date' 문구). 날짜를 못 읽으면 None."""
    prices = {m.group(1): float(m.group(2)) for m in re.finditer(r'"(\d{6})": \{ price: ([\d.]+)', index_html or '')}
    m = re.search(r'class="daily-movers-date">(\d{4})년 (\d{1,2})월 (\d{1,2})일', index_html or '')
    date = f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None
    return prices, date


def pref_adjustment(pref: str, common: str, p_pref, p_common, as_of: str):
    """우선주 R 보정 = (현재 우선주/보통주 가격 비율) ÷ (직전 60개월 평균 비율). 평균은 내재가치 엔진과 같은 함수."""
    if not scoring.finite_pos(p_pref, p_common):
        return None
    try:
        sys.path.insert(0, os.path.join(REPO, 'valuation'))
        import engine  # noqa: WPS433 — 내재가치 엔진의 우선주 할인율 함수를 그대로 재사용
        avg = engine.pref_ratio(pref, common, as_of[:7])
    except Exception:  # noqa: BLE001 — 캐시 없음 등은 보정 불가로 처리
        return None
    return (p_pref / p_common) / avg if avg else None


def build_inputs(snap: dict) -> tuple[list, str, dict]:
    fund = snap['fundamental']['data'] or {}
    recs = fund.get('stocks') or []
    if not recs:
        raise RuntimeError('fundamental_score.json에 종목이 없음')
    iv = snap['intrinsic']['data'] or {}
    iv_stocks, iv_err = iv.get('stocks') or {}, iv.get('errors') or {}
    types = snap['types']['data'] or {}
    FIN, PREF = set(types.get('금융', [])), types.get('우선주', {})
    dates = collections.Counter(r.get('price_as_of') for r in recs if r.get('price_as_of'))
    as_of = dates.most_common(1)[0][0]
    peers = snap['peers']['data'] or {}
    peers_age = None
    if peers.get('updatedAt'):
        peers_age = (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(peers['updatedAt'])).days
    peers_stale = peers_age is None or peers_age >= C.PEER_CACHE_MAX_AGE_DAYS
    legacy_med = _legacy_medians(recs)
    lp, lp_date = legacy_prices(snap['index']['data'])
    by = {r['code']: r for r in recs}
    price_of = {}
    for r in recs:
        if isinstance(r.get('price'), (int, float)):
            price_of[r['code']] = (r['price'], r.get('price_as_of'), False)
        elif r['code'] in lp and lp_date and lp_date == r.get('price_as_of'):
            price_of[r['code']] = (lp[r['code']], lp_date, True)     # 날짜를 대조한 경우에만 사용
        else:
            price_of[r['code']] = (None, None, False)
    stocks, legacy_n = [], 0
    for r in recs:
        code = r['code']
        issuer = PREF.get(code, code)
        base = by.get(issuer, r)
        qm, legacy = adapt_metrics(base, legacy_med, peers_stale)
        own, _ = adapt_metrics(r, legacy_med, peers_stale)
        legacy_n += legacy
        price, pdate, from_index = price_of[code]
        warns = []
        if legacy:
            warns.append('구 형식 기본지표(업종 중앙값 역산·적자 상태 미구분)')
        if from_index:
            warns.append('가격은 메인 페이지 시세(기준일 대조)')
        adj = 1.0
        rm = {'fpe': qm.get('fpe'), 'pbr': qm.get('pbr')}
        if issuer != code:
            adj = pref_adjustment(code, issuer, price, price_of[issuer][0], as_of)
            if adj is None:
                rm = {'fpe': {'status': 'missing'}, 'pbr': {'status': 'missing'}}
                warns.append('우선주 할인율 이력 없음')
                adj = 1.0
        ive = iv_stocks.get(code) or (dict(iv_err[code], error=iv_err[code].get('error')) if code in iv_err else None)
        stocks.append({
            'code': code, 'name': r.get('name'), 'industry': r.get('peer_group'), 'issuer_code': issuer,
            'financial': issuer in FIN, 'preferred': issuer != code, 'price': price, 'price_date': pdate,
            'q_metrics': {k: qm.get(k) for k in ('roe', 'growth', 'safety')},
            'r_metrics': rm, 'div_metric': own.get('div'), 'pref_adj': adj, 'iv_entry': ive, 'warnings': warns,
            'financial_data_as_of': base.get('financial_data_as_of'),
        })
    meta = {
        'as_of_date': as_of, 'price_dates': dict(dates), 'peer_universe_updated': peers.get('updatedAt'),
        'peer_universe_age_days': peers_age, 'peer_universe_stale': peers_stale, 'legacy_records': legacy_n,
        'fundamental_calculated_at': (recs[0] or {}).get('calculated_at'), 'intrinsic_generated_at': iv.get('generated_at'),
    }
    return stocks, as_of, meta


def _clean(x):
    """JSON 직렬화 전 NaN/Infinity 제거(있으면 None)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def to_output(result: dict, meta: dict, snap: dict, generated_at: str) -> dict:
    stocks = {}
    for code, x in sorted(result['stocks'].items()):
        s = x['input']
        q, r, i = x['q'], x['r'], x['i']
        ax = lambda a: {'raw': a['raw'], 'normalized': a['normalized'], 'contribution': a['contribution'],
                        'coverage': a['coverage'], 'observed_count': a['observed_count'],
                        'eligible_weight': a['eligible_weight'], 'observed_weight': a['observed_weight'],
                        'metrics': a['items']}
        iv_keys = ('low', 'high', 'midpoint', 'price', 'price_to_value', 'margin_of_safety_mid', 'margin_of_safety_low',
                   'upside_to_mid', 'range_ratio', 'method_coverage', 'method_weights', 'methods', 'missing_methods',
                   'spread', 'model_type', 'required_return', 'financial_period', 'calc_date')
        stocks[code] = {
            'name': s['name'], 'industry': s['industry'], 'issuer_code': s['issuer_code'],
            'financial': s['financial'], 'preferred': s['preferred'],
            'status': 'published' if x['published'] else 'hold', 'published': x['published'],
            'reason_codes': [c for c, _ in x['reasons']], 'reasons': [t for _, t in x['reasons']],
            'score': x['score'], 'score_unrounded': x['score_unrounded'], 'grade': x['grade'], 'rank': x['rank'],
            'q': ax(q), 'r': dict(ax(r), pref_adjustment=s['pref_adj'] if s['preferred'] else None),
            'i': dict({'raw': i['raw'], 'normalized': i['normalized'], 'contribution': i['contribution']},
                      **{k: i.get(k) for k in iv_keys}),
            'source_dates': {'price': s['price_date'], 'financial': s.get('financial_data_as_of'),
                             'intrinsic_period': i.get('financial_period'), 'intrinsic_calc': i.get('calc_date')},
            'warnings': x['warnings'],
        }
    return _clean({
        'schema_version': C.SCHEMA_VERSION, 'model_version': C.MODEL_VERSION, 'generated_at': generated_at,
        'as_of_date': meta['as_of_date'], 'weights': result['weights'],
        'normalization': {'method': 'midrank_percentile', 'universe_count': len(result['universe']),
                          'universe_codes': result['universe'], 'universe_min': C.UNIVERSE_MIN,
                          'universe_too_small': result['universe_too_small']},
        'input_versions': {k: (v['sha'] or '')[:12] for k, v in snap.items()},
        'source_dates': meta, 'help': C.HELP_TEXT, 'stocks': stocks,
    })


def summarize(out: dict) -> str:
    st = out['stocks'].values()
    pub = [s for s in st if s['published']]
    reasons = collections.Counter(c.split('_')[0] for s in st if not s['published'] for c in s['reason_codes'][:1])
    return (f"QRI 기준일 {out['as_of_date']}: 종목 {len(out['stocks'])}, 게시 {len(pub)}, 보류 {len(out['stocks']) - len(pub)}, "
            f"모집단 {out['normalization']['universe_count']} (보류 첫 사유 축별 {dict(reasons)})")


def write_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    os.replace(tmp, path)


def run(repo: str = REPO, out_path: str | None = None, dry_run: bool = False, snapshot_dir: str | None = None,
        now: str | None = None) -> dict:
    snap = read_snapshot(repo)
    stocks, as_of, meta = build_inputs(snap)
    result = scoring.compute(stocks, as_of)
    out = to_output(result, meta, snap, now or dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    verify_unchanged(snap)
    if not dry_run:
        write_atomic(out_path or os.path.join(repo, 'data', 'integrated_score.json'), out)
        if snapshot_dir:
            write_atomic(os.path.join(snapshot_dir, f"{as_of}_{C.MODEL_VERSION}.json"), out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='QRI 통합 매력도 일일 배치')
    ap.add_argument('--dry-run', action='store_true', help='계산·요약만 출력하고 파일은 저장하지 않음')
    ap.add_argument('--skip-fetch', action='store_true', help='무동작(이 배치는 원래 수집하지 않음)')
    ap.add_argument('--out', help='출력 경로(기본 data/integrated_score.json)')
    ap.add_argument('--snapshot-dir', help='날짜별 결과 스냅샷 저장 폴더(로컬 보관용)')
    ap.add_argument('--repo', default=REPO)
    a = ap.parse_args(argv)
    try:
        out = run(a.repo, a.out, a.dry_run, a.snapshot_dir)
    except InputChanged as e:
        print(f'QRI FAIL: {e} — 게시하지 않음', file=sys.stderr)
        return 2
    print(summarize(out) + (' [dry-run, 저장 안 함]' if a.dry_run else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
