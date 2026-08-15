"""indicators.py 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from technical_score import indicators as ind


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx)


class TestSma:
    def test_sma_insufficient_data_is_nan(self):
        s = _series([1, 2, 3])
        result = ind.sma(s, window=5)
        assert result.isna().all()

    def test_sma_basic(self):
        s = _series([1, 2, 3, 4, 5])
        result = ind.sma(s, window=5)
        assert result.iloc[-1] == pytest.approx(3.0)

    def test_sma_as_of_offset(self):
        s = _series(list(range(1, 21)))  # 1..20
        # SMA(5) as of 0 offset: mean(16..20)=18
        assert ind.sma_as_of(s, window=5, offset=0) == pytest.approx(18.0)
        # SMA(5) as of 5 offset(즉 5거래일 전 시점): mean(11..15)=13
        assert ind.sma_as_of(s, window=5, offset=5) == pytest.approx(13.0)

    def test_sma_as_of_none_when_insufficient(self):
        s = _series([1, 2])
        assert ind.sma_as_of(s, window=5) is None


class TestTrueRangeAtr:
    def test_true_range_first_row_no_prev_close(self):
        high = _series([10, 12])
        low = _series([8, 9])
        close = _series([9, 11])
        tr = ind.true_range(high, low, close)
        # 첫 행은 전일 종가가 없어 고가-저가만 사용
        assert tr.iloc[0] == pytest.approx(2.0)

    def test_atr_pct_positive(self):
        n = 30
        rng = np.linspace(100, 110, n)
        high = _series(rng + 1)
        low = _series(rng - 1)
        close = _series(rng)
        result = ind.atr_pct(high, low, close, window=14)
        assert (result.dropna() > 0).all()


class TestWilderRsi:
    def test_all_gains_gives_rsi_100(self):
        s = _series(list(range(1, 40)))  # 계속 상승
        rsi = ind.rsi_wilder(s, window=14)
        assert rsi.iloc[-1] == pytest.approx(100.0)

    def test_all_losses_gives_rsi_0(self):
        s = _series(list(range(40, 1, -1)))  # 계속 하락
        rsi = ind.rsi_wilder(s, window=14)
        assert rsi.iloc[-1] == pytest.approx(0.0)

    def test_flat_prices_give_rsi_100_no_losses(self):
        # 변화가 전혀 없으면 avg_loss=0 → RSI=100 (구현 정의: 손실 없음은 100 처리)
        s = _series([100.0] * 30)
        rsi = ind.rsi_wilder(s, window=14)
        assert rsi.iloc[-1] == pytest.approx(100.0)

    def test_rsi_no_lookahead(self):
        """앞부분 데이터가 같다면 뒤에 어떤 값이 오든 앞부분 RSI는 변하지 않아야 한다."""
        base = [100 + i * 0.5 for i in range(30)]
        s1 = _series(base + [200.0])
        s2 = _series(base + [50.0])
        rsi1 = ind.rsi_wilder(s1, window=14)
        rsi2 = ind.rsi_wilder(s2, window=14)
        # 마지막 값을 제외한 모든 위치는 두 시리즈가 동일해야 함(룩어헤드 없음).
        pd.testing.assert_series_equal(rsi1.iloc[:-1], rsi2.iloc[:-1])


class TestPercentileRank:
    def test_percentile_rank_basic(self):
        values = [10, 20, 30, 40, 50]
        assert ind.percentile_rank(values, 50) == pytest.approx(100.0)
        assert ind.percentile_rank(values, 10) == pytest.approx(20.0)
        assert ind.percentile_rank(values, 30) == pytest.approx(60.0)

    def test_percentile_rank_none_target(self):
        assert ind.percentile_rank([1, 2, 3], None) is None

    def test_percentile_rank_ignores_none_in_population(self):
        values = [10, None, 30, None, 50]
        # 유효 표본 3개 중 30 이하는 2개(10, 30) → 2/3*100
        assert ind.percentile_rank(values, 30) == pytest.approx(66.66666666, rel=1e-4)

    def test_percentile_rank_empty_population(self):
        assert ind.percentile_rank([], 10) is None


class TestClosePosition:
    def test_normal_case(self):
        assert ind.close_position_in_range(close=9, high=10, low=8) == pytest.approx(0.5)

    def test_close_at_high(self):
        assert ind.close_position_in_range(close=10, high=10, low=8) == pytest.approx(1.0)

    def test_high_equals_low_returns_none(self):
        assert ind.close_position_in_range(close=10, high=10, low=10) is None


class TestRollingHighLow:
    def test_basic(self):
        high = _series([10, 12, 9, 15, 11])
        low = _series([5, 6, 4, 7, 8])
        h, l = ind.rolling_high_low(high, low, window=5)
        assert h == pytest.approx(15)
        assert l == pytest.approx(4)

    def test_window_larger_than_data_uses_all(self):
        high = _series([10, 12])
        low = _series([5, 6])
        h, l = ind.rolling_high_low(high, low, window=252)
        assert h == pytest.approx(12)
        assert l == pytest.approx(5)


class TestSwingPoints:
    def test_finds_obvious_peak_and_trough(self):
        # 명확한 V자 + 역V자 패턴
        high = _series([10, 11, 12, 20, 12, 11, 10, 9, 8, 15, 20, 21])
        low = _series([9, 10, 11, 18, 10, 9, 8, 6, 5, 13, 18, 19])
        points = ind.find_swing_points(high, low, order=2)
        kinds = [(p.index, p.kind) for p in points]
        assert any(k == "high" for _, k in kinds)

    def test_pullback_depths_reasonable_range(self):
        high = _series([10, 12, 20, 15, 10, 8, 6, 12, 18, 25, 20, 15, 12, 10, 14, 20])
        low = _series([9, 11, 18, 13, 8, 6, 5, 10, 16, 22, 18, 13, 10, 8, 12, 18])
        depths = ind.recent_pullback_depths(high, low, order=2, max_pullbacks=2)
        assert all(0 <= d <= 100 for d in depths)
