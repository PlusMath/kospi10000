"""QRI 순수 계산 테스트 — docs/qri-integrated-score.md 검증 기준 1~13, 17 대응."""
from __future__ import annotations

import math

import pytest

from integrated_score import config as C
from integrated_score import scoring as S


# ── 픽스처 ──────────────────────────────────────────────────────────────────

def q_metrics(roe=12.0, roe_med=10.0, growth=('valid', 110.0, 100.0), safety=('valid', 50.0, 0.6)):
    g = {'status': growth[0], 'cns_eps': growth[1], 'eps_last': growth[2]} if growth else {'status': 'missing'}
    s = {'status': safety[0], 'value': safety[1], 'percentile': safety[2], 'peer_n': 10} if safety else {'status': 'missing'}
    r = {'status': 'valid', 'value': roe, 'median': roe_med, 'peer_n': 10} if roe is not None else {'status': 'missing'}
    return {'roe': r, 'growth': g, 'safety': s}


def r_metrics(fpe=10.0, pbr=1.0, med_f=10.0, med_b=1.0):
    f = {'status': 'valid', 'value': fpe, 'median': med_f, 'peer_n': 10} if fpe is not None else {'status': 'missing'}
    b = {'status': 'valid', 'value': pbr, 'median': med_b, 'peer_n': 10} if pbr is not None else {'status': 'missing'}
    return {'fpe': f, 'pbr': b}


def iv(low=80.0, high=125.0, **detail):
    d = {'method_coverage': 1.0, 'methods_ok': ['DCF', 'RIM', '정상화 PER'], 'missing_methods': [], 'spread': 1.3,
         'single_method_design': False, 'model_type': '안정', 'financial_period': '2026-09'}
    d.update(detail)
    return {'low': low, 'high': high, 'hold': False, 'q': '2026-09', 'detail': d}


def stock(code, **kw):
    s = {'code': code, 'name': code, 'industry': 'X', 'issuer_code': code, 'financial': False, 'preferred': False,
         'price': 100.0, 'price_date': '2026-11-17', 'q_metrics': q_metrics(), 'r_metrics': r_metrics(),
         'div_metric': {'status': 'valid', 'value': 2.0, 'percentile': 0.5, 'peer_n': 100}, 'pref_adj': 1.0, 'iv_entry': iv()}
    s.update(kw)
    return s


# ── 1) 내부 가중치·coverage·부분 결측 재분배 ────────────────────────────────

def test_q_weights_and_partial_missing_redistribution():
    items = S.build_q_items(q_metrics(safety=None), financial=False)
    ax = S.q_axis(items, False)
    assert ax['eligible_weight'] == 40 and ax['observed_weight'] == 30
    assert ax['coverage'] == pytest.approx(0.75) and ax['published']
    roe_s, g_s = items[0]['score'], items[1]['score']
    assert ax['raw'] == pytest.approx((15 * roe_s + 15 * g_s) / 30)
    assert items[2]['status'] == 'missing' and items[2]['effective_weight'] == 0


def test_q_requires_roe_and_coverage():
    # ROE + 재무안전성만(25/40=0.625) → 커버리지 미달
    ax = S.q_axis(S.build_q_items(q_metrics(growth=None), False), False)
    assert ax['raw'] is None and any(c == 'Q_LOW_COVERAGE' for c, _ in ax['reasons'])
    ax = S.q_axis(S.build_q_items(q_metrics(roe=None), False), False)
    assert ax['raw'] is None and any(c.startswith('Q_ROE') for c, _ in ax['reasons'])


def test_r_dividend_missing_only_passes_at_075():
    items = S.build_r_items(r_metrics(), {'status': 'missing'})
    ax = S.r_axis(items)
    assert ax['coverage'] == pytest.approx(45 / 60) and ax['published']


# ── 2) missing vs 확인된 loss / zero_dividend ──────────────────────────────

def test_missing_and_loss_are_different():
    loss = S.build_q_items(q_metrics(growth=('loss', -5.0, 10.0)), False)[1]
    miss = S.build_q_items(q_metrics(growth=('missing', None, None)), False)[1]
    assert loss['status'] == 'loss' and loss['score'] == 0.0
    assert miss['status'] == 'missing' and miss['score'] is None
    zd = S.build_r_items(r_metrics(), {'status': 'zero_dividend'})[2]
    md = S.build_r_items(r_metrics(), {'status': 'missing'})[2]
    assert zd['status'] == 'zero_dividend' and zd['score'] == 0.0
    assert md['status'] == 'missing' and md['score'] is None
    fl = S.build_r_items({'fpe': {'status': 'loss'}, 'pbr': r_metrics()['pbr']}, {'status': 'missing'})
    assert fl[0]['status'] == 'loss' and S.r_axis(fl)['published']   # 확인된 예상 적자는 관측


# ── 3) 금융업: 일반 부채비율 미적용 + 표시 ────────────────────────────────

def test_financial_excludes_debt_ratio_and_warns():
    items = S.build_q_items(q_metrics(safety=('valid', 900.0, 0.0)), financial=True)
    ax = S.q_axis(items, True)
    assert items[2]['status'] == S.NOT_APPLICABLE
    assert ax['eligible_weight'] == 30 and ax['coverage'] == 1.0
    res = S.compute([stock('F1', financial=True)] + [stock(f'A{i:02d}') for i in range(40)], '2026-11-17')
    assert '금융업 건전성 지표 미반영' in res['stocks']['F1']['warnings']
    # 금융업은 ROE와 성장률 둘 다 필요
    ax2 = S.q_axis(S.build_q_items(q_metrics(growth=None), True), True)
    assert ax2['raw'] is None


# ── 4) ROE·성장률 경계 ─────────────────────────────────────────────────────

def test_roe_boundaries():
    assert S.score_roe(10, 10) == 50 and S.score_roe(20, 10) == 100 and S.score_roe(0, 10) == 0
    assert S.score_roe(-5, 10) == 0   # 음수 ROE도 관측값으로 채점


def test_growth_log_scale_and_special_cases():
    assert S.score_growth(1, 3) == pytest.approx(0)
    assert S.score_growth(1, 1) == pytest.approx(50)
    assert S.score_growth(3, 1) == pytest.approx(100)
    assert S.score_growth(100, 1) == 100   # 상한 클램프, 원 성장률은 value에 보존
    it = S.build_q_items(q_metrics(growth=('valid', 690.0, 100.0)), False)[1]
    assert it['value'] == pytest.approx(590) and it['score'] == 100
    tr = S.build_q_items(q_metrics(growth=('turnaround', 10.0, -5.0)), False)[1]
    assert tr['status'] == 'turnaround' and tr['score'] == 50
    lo = S.build_q_items(q_metrics(growth=('loss', -1.0, 5.0)), False)[1]
    assert lo['score'] == 0 and lo['status'] == 'loss'


# ── 5) 상대배수 1/3·1·3 ─────────────────────────────────────────────────────

def test_relative_multiple_boundaries():
    assert S.score_multiple(1 / 3) == pytest.approx(100)
    assert S.score_multiple(1) == pytest.approx(50)
    assert S.score_multiple(3) == pytest.approx(0)
    bad = S.build_r_items({'fpe': r_metrics()['fpe'], 'pbr': {'status': 'valid', 'value': -0.5, 'median': 1, 'peer_n': 9}}, {})
    assert bad[1]['status'] == 'invalid'   # PBR<=0은 저PBR 우량주가 아님
    few = S.build_r_items({'fpe': {'status': 'valid', 'value': 5, 'median': 10, 'peer_n': 4}, 'pbr': r_metrics()['pbr']}, {})
    assert few[0]['status'] == 'insufficient_peers'


def test_preferred_adjustment():
    base = S.build_r_items(r_metrics(fpe=10, med_f=10), {}, adj=1.0)[0]['score']
    cheaper = S.build_r_items(r_metrics(fpe=10, med_f=10), {}, adj=0.74)[0]['score']
    assert base == pytest.approx(50) and cheaper > base
    assert cheaper == pytest.approx(S.score_multiple(0.74))


# ── 6) 무배당 다수 동점이어도 0점 ──────────────────────────────────────────

def test_zero_dividend_is_zero_even_with_high_midrank():
    it = S.build_r_items(r_metrics(), {'status': 'zero_dividend', 'value': 0.0, 'percentile': 0.4})[2]
    assert it['score'] == 0.0


# ── 7) 8) I 경계, 안전마진 vs 상승여력 ──────────────────────────────────────

@pytest.mark.parametrize('ptv,expect', [(0.5, 100), (1, 50), (2, 25), (4, 0)])
def test_intrinsic_boundaries(ptv, expect):
    v = 100.0
    assert S.score_intrinsic(v * ptv, v, v)['raw'] == pytest.approx(expect)


def test_margin_of_safety_vs_upside():
    r = S.score_intrinsic(80.0, 100.0, 100.0)
    assert r['margin_of_safety_mid'] == pytest.approx(0.20)
    assert r['upside_to_mid'] == pytest.approx(0.25)
    neg = S.score_intrinsic(120.0, 100.0, 100.0)
    assert neg['margin_of_safety_low'] == pytest.approx(-0.2)   # 음수 그대로 보존


# ── 9) 평가방법 커버리지 ────────────────────────────────────────────────────

def test_method_coverage_uses_original_weights():
    low = S.i_axis(iv(method_coverage=0.6, methods_ok=['DCF', 'RIM'], missing_methods=['정상화 PER']), 100.0)
    assert low['raw'] is None and low['reasons'][0][0] == 'I_LOW_METHOD_COVERAGE'
    ok = S.i_axis(iv(method_coverage=0.7, methods_ok=['DCF', 'RIM'], missing_methods=['정상화 PER']), 100.0)
    assert ok['raw'] is not None and any('일부 평가방법 누락' in w for w in ok['warnings'])


def test_single_method_design_vs_missing():
    design = S.i_axis(iv(method_coverage=1.0, methods_ok=['이익환원'], single_method_design=True), 100.0)
    assert design['raw'] is not None and '단일 평가방법' in design['warnings']
    by_missing = S.i_axis(iv(method_coverage=0.7, methods_ok=['RIM'], single_method_design=False), 100.0)
    assert by_missing['raw'] is None and by_missing['reasons'][0][0] == 'I_SINGLE_BY_MISSING'


# ── 10) hold, 음수/0 가치, 역전, NaN, 날짜 불일치, 비교군 만료 ─────────────

@pytest.mark.parametrize('entry,code', [
    (dict(iv(), hold=True), 'I_HOLD'),
    (iv(low=0, high=100), 'I_BAD_RANGE'),
    (iv(low=-5, high=100), 'I_BAD_RANGE'),
    (iv(low=150, high=100), 'I_BAD_RANGE'),
    (iv(low=float('nan'), high=100), 'I_BAD_RANGE'),
    (iv(low=80, high=float('inf')), 'I_BAD_RANGE'),
    ({'low': 80, 'high': 120, 'hold': False, 'q': '2026-09'}, 'I_NO_METHOD_INFO'),
    (iv(period_mismatch=True), 'I_PERIOD_MISMATCH'),
    ({'error': '평가 대상 아님', 'excluded': True}, 'I_EXCLUDED'),
    (None, 'I_MISSING'),
])
def test_intrinsic_hold_cases(entry, code):
    r = S.i_axis(entry, 100.0)
    assert r['raw'] is None and r['reasons'][0][0] == code


def test_price_date_mismatch_excluded_from_universe():
    stocks = [stock(f'A{i:02d}') for i in range(35)] + [stock('OLD', price_date='2026-11-14')]
    res = S.compute(stocks, '2026-11-17')
    assert 'OLD' not in res['universe'] and res['stocks']['OLD']['score'] is None
    assert res['stocks']['OLD']['reasons'][0][0] == 'PRICE_DATE_MISMATCH'


def test_stale_peer_input_is_not_scored():
    it = S.build_r_items({'fpe': {'status': 'stale'}, 'pbr': r_metrics()['pbr']}, {})[0]
    assert it['status'] == 'stale' and it['score'] is None


# ── 11) 평균 동순위, 전원 동점, n<30 ────────────────────────────────────────

def test_midrank_ties_and_all_equal():
    p = S.midrank_percentiles({'a': 1.0, 'b': 2.0, 'c': 2.0, 'd': 3.0})
    assert p['a'] == 0 and p['d'] == 100 and p['b'] == p['c'] == pytest.approx(50)
    assert set(S.midrank_percentiles({k: 7.0 for k in 'abcde'}).values()) == {50.0}
    # 부동소수 잔차는 동점으로
    p2 = S.midrank_percentiles({'a': 0.1 + 0.2, 'b': 0.3, 'c': 1.0})
    assert p2['a'] == p2['b']


def test_universe_below_30_holds_composite():
    res = S.compute([stock(f'A{i:02d}') for i in range(29)], '2026-11-17')
    assert res['universe_too_small']
    s = res['stocks']['A00']
    assert s['score'] is None and s['q']['raw'] is not None and s['grade'] == C.HOLD_GRADE
    assert any(c == 'UNIVERSE_TOO_SMALL' for c, _ in s['reasons'])


# ── 12) 13) 통합 산식·기여도, 축 하나라도 null이면 null ─────────────────────

def test_composite_example_and_contributions():
    W = {'q': 0.40, 'r': 0.20, 'i': 0.40}
    assert 0.40 * 80 + 0.20 * 65 + 0.40 * 70 == pytest.approx(73.0)
    res = S.compute([stock(f'A{i:02d}', q_metrics=q_metrics(roe=5 + i)) for i in range(40)], '2026-11-17', W)
    for x in res['stocks'].values():
        assert sum(x[a]['contribution'] for a in 'qri') == pytest.approx(x['score_unrounded'])
        assert x['score'] == S.round1(x['score_unrounded'])


def test_any_axis_null_means_composite_null_without_reweighting():
    stocks = [stock(f'A{i:02d}') for i in range(35)] + [stock('NOI', iv_entry=dict(iv(), hold=True))]
    res = S.compute(stocks, '2026-11-17')
    x = res['stocks']['NOI']
    assert x['score'] is None and x['q']['raw'] is not None and x['r']['raw'] is not None
    assert x['q']['contribution'] is None


def test_grade_boundaries_use_display_score():
    assert S.grade(80.0) == '통합 매력 매우 높음' and S.grade(79.9) == '통합 매력 높음'
    assert S.grade(65.0) == '통합 매력 높음' and S.grade(45.0) == '통합 매력 보통'
    assert S.grade(30.0) == '통합 매력 낮음' and S.grade(29.9) == '통합 매력 매우 낮음'
    assert S.grade(None) == '평가 보류'
    assert S.round1(79.95) == 80.0 and S.grade(S.round1(79.95)) == '통합 매력 매우 높음'


# ── 17) 정렬: 반올림 전 합계, 동점은 종목코드 ──────────────────────────────

def test_rank_by_unrounded_then_code():
    stocks = [stock(f'A{i:02d}', q_metrics=q_metrics(roe=5 + i % 20)) for i in range(40)]
    res = S.compute(stocks, '2026-11-17')
    ranked = sorted((x for x in res['stocks'].values() if x['rank']), key=lambda x: x['rank'])
    keys = [(-x['score_unrounded'], x['input']['code']) for x in ranked]
    assert keys == sorted(keys)
    same = [x for x in ranked if x['input']['code'] in ('A00', 'A20')]
    assert same[0]['score_unrounded'] == same[1]['score_unrounded'] and same[0]['input']['code'] == 'A00'


def test_no_nan_in_outputs():
    res = S.compute([stock(f'A{i:02d}') for i in range(35)], '2026-11-17')
    for x in res['stocks'].values():
        for a in 'qri':
            v = x[a]['raw']
            assert v is None or math.isfinite(v)
