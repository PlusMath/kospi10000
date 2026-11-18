"""QRI 배치 입출력 테스트 — 검증 기준 14(기술점수 무관), 16(재실행 동일), dry-run, 입력 변경 감지, 구 스키마 호환."""
from __future__ import annotations

import json
import os
import shutil

import pytest

from integrated_score import run_daily as RD

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _metric(key, qri, value=None, **kw):
    d = {'key': key, 'status': 'valid' if qri in ('valid', 'turnaround') else ('zero_dividend' if qri == 'zero_dividend' else 'unavailable'),
         'qri_status': qri, 'value': value, 'percentile': kw.pop('percentile', None)}
    d.update(kw)
    return d


def make_repo(tmp_path, n=40, with_technical=True):
    """합성 저장소: 새 스키마 fundamental_score.json + intrinsic_value.json + 최소 types/peers/index."""
    root = tmp_path / 'repo'
    (root / 'data').mkdir(parents=True)
    (root / 'valuation').mkdir()
    recs, ivs = [], {}
    for i in range(n):
        code = f'{100000 + i:06d}'
        recs.append({
            'code': code, 'name': f'종목{i}', 'peer_group': '반도체·전자', 'price_as_of': '2026-11-17', 'price': 1000.0 + i,
            'calculated_at': '2026-11-17', 'financial_data_as_of': '2021~2025',
            'metrics': [
                _metric('fpe', 'valid', 8 + i % 7, median=10.0, peer_n=20),
                _metric('pbr', 'valid', 0.8 + (i % 5) / 10, median=1.0, peer_n=20),
                _metric('divYield', 'valid' if i % 4 else 'zero_dividend', 2.0 if i % 4 else 0.0, percentile=(i % 10) / 10, peer_n=150),
                _metric('roe', 'valid', 5 + i % 13, median=10.0, peer_n=20),
                _metric('epsGrowth', 'valid', None, cns_eps=110.0 + i, eps_last=100.0, eps_last_year=2025),
                _metric('debtRatio', 'valid', 40 + i, percentile=(i % 9) / 9, peer_n=15),
            ]})
        ivs[code] = {'low': 900 + i * 3, 'high': 1400 + i * 2, 'hold': False, 'q': '2026-09',
                     'detail': {'method_coverage': 1.0, 'methods_ok': ['DCF', 'RIM', '정상화 PER'], 'missing_methods': [],
                                'spread': 1.4, 'single_method_design': False, 'model_type': '안정', 'financial_period': '2026-09',
                                'required_return': 0.12, 'calc_date': '2026-11-17'}}
    (root / 'data' / 'fundamental_score.json').write_text(json.dumps({'stocks': recs}, ensure_ascii=False), encoding='utf-8')
    (root / 'data' / 'intrinsic_value.json').write_text(json.dumps({'generated_at': 'x', 'stocks': ivs, 'errors': {}}, ensure_ascii=False), encoding='utf-8')
    (root / 'data' / 'peer_universe.json').write_text(json.dumps({'updatedAt': '2026-11-15', 'stocks': []}), encoding='utf-8')
    (root / 'valuation' / 'types.json').write_text(json.dumps({'금융': [], '우선주': {}}, ensure_ascii=False), encoding='utf-8')
    (root / 'index.html').write_text('<html></html>', encoding='utf-8')
    if with_technical:
        (root / 'data' / 'technical_score.json').write_text(json.dumps({'100000': {'technical_score': 99}}), encoding='utf-8')
    return str(root)


def strip_meta(out):
    o = json.loads(json.dumps(out))
    o.pop('generated_at', None)
    return o


def test_rerun_is_identical_except_generated_at(tmp_path):
    repo = make_repo(tmp_path)
    a = RD.run(repo, dry_run=True, now='2026-11-17 16:30:00')
    b = RD.run(repo, dry_run=True, now='2026-11-17 17:45:00')
    assert strip_meta(a) == strip_meta(b)
    assert a['normalization']['universe_count'] == 40


def test_technical_score_has_no_effect(tmp_path):
    with_t = RD.run(make_repo(tmp_path / 'a', with_technical=True), dry_run=True, now='t')
    without = RD.run(make_repo(tmp_path / 'b', with_technical=False), dry_run=True, now='t')
    assert strip_meta(with_t)['stocks'] == strip_meta(without)['stocks']


def test_dry_run_writes_nothing(tmp_path):
    repo = make_repo(tmp_path)
    RD.run(repo, dry_run=True)
    assert not os.path.exists(os.path.join(repo, 'data', 'integrated_score.json'))
    RD.run(repo, dry_run=False, snapshot_dir=os.path.join(repo, 'snap'))
    out = json.load(open(os.path.join(repo, 'data', 'integrated_score.json'), encoding='utf-8'))
    assert out['as_of_date'] == '2026-11-17' and os.listdir(os.path.join(repo, 'snap'))
    assert all(isinstance(k, str) for k in out['stocks'])


def test_output_is_strict_json_and_holds_have_null_score(tmp_path):
    repo = make_repo(tmp_path)
    fund = json.load(open(os.path.join(repo, 'data', 'fundamental_score.json'), encoding='utf-8'))
    fund['stocks'][0]['metrics'][4] = _metric('epsGrowth', 'missing')        # 컨센서스 없음
    fund['stocks'][0]['metrics'][0] = _metric('fpe', 'missing')
    json.dump(fund, open(os.path.join(repo, 'data', 'fundamental_score.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    RD.run(repo)
    txt = open(os.path.join(repo, 'data', 'integrated_score.json'), encoding='utf-8').read()
    assert 'NaN' not in txt and 'Infinity' not in txt
    s = json.loads(txt)['stocks']['100000']
    assert s['score'] is None and s['grade'] == '평가 보류' and s['rank'] is None and s['reasons']
    assert s['q']['raw'] is None and s['q']['normalized'] is None


def test_input_change_during_run_is_not_published(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    orig = RD.build_inputs

    def mutate(snap):
        r = orig(snap)
        with open(os.path.join(repo, 'data', 'intrinsic_value.json'), 'a', encoding='utf-8') as f:
            f.write(' ')
        return r
    monkeypatch.setattr(RD, 'build_inputs', mutate)
    with pytest.raises(RD.InputChanged):
        RD.run(repo)
    assert not os.path.exists(os.path.join(repo, 'data', 'integrated_score.json'))


def test_legacy_median_back_solve():
    import math
    med, val = 10.0, 6.0
    p = 0.5 - math.log(val / med) / (2 * math.log(3))
    recs = [{'peer_group': 'G', 'metrics': [{'key': 'fpe', 'status': 'valid', 'value': val, 'percentile': p}]}]
    assert RD._legacy_medians(recs)[('G', 'fpe')] == pytest.approx(med)
    recs = [{'peer_group': 'G', 'metrics': [{'key': 'roe', 'status': 'valid', 'value': 13.0, 'percentile': 0.65}]}]
    assert RD._legacy_medians(recs)[('G', 'roe')] == pytest.approx(10.0)


@pytest.mark.skipif(not os.path.exists(os.path.join(REPO, 'data', 'fundamental_score.json')), reason='실데이터 없음')
def test_real_data_smoke():
    out = RD.run(REPO, dry_run=True, now='t')
    st = out['stocks']
    assert len(st) >= 150
    pub = [s for s in st.values() if s['published']]
    assert out['normalization']['universe_count'] == len(pub) >= 30
    ranks = sorted(s['rank'] for s in pub)
    assert ranks == list(range(1, len(pub) + 1))
