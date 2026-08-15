"""risk_penalty.py 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import risk_penalty as rp


def _flat_df(n: int, price: float = 100.0, volume: float = 1000.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series([price] * n, index=idx)
    high = close * 1.01
    low = close * 0.99
    volume_s = pd.Series([volume] * n, index=idx)
    return close, high, low, volume_s


class TestMa50DistancePenalty:
    def test_triggers_above_15pct(self):
        r = rp.penalty_ma50_distance_over_15(close_val=116.0, sma50=100.0)
        assert r["triggered"] is True
        assert r["points"] == pytest.approx(-10.0)

    def test_no_trigger_at_exactly_15pct(self):
        r = rp.penalty_ma50_distance_over_15(close_val=115.0, sma50=100.0)
        assert r["triggered"] is False

    def test_no_trigger_when_below_ma(self):
        r = rp.penalty_ma50_distance_over_15(close_val=90.0, sma50=100.0)
        assert r["triggered"] is False


class TestSharpDropWithVolume:
    def test_triggers_on_drop_with_high_volume(self):
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        prices = [100.0] * (n - 1) + [94.0]  # 마지막 날 -6%
        close = pd.Series(prices, index=idx)
        volumes = [1000.0] * (n - 1) + [5000.0]  # 거래량 급증
        volume = pd.Series(volumes, index=idx)
        r = rp.penalty_sharp_drop_with_volume(close, volume)
        assert r["triggered"] is True
        assert len(r["value"]["hits"]) == 1

    def test_no_trigger_on_drop_with_normal_volume(self):
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        prices = [100.0] * (n - 1) + [94.0]
        close = pd.Series(prices, index=idx)
        volume = pd.Series([1000.0] * n, index=idx)  # 평균과 동일(초과 아님)
        r = rp.penalty_sharp_drop_with_volume(close, volume)
        assert r["triggered"] is False


class TestCloseBelowMa50:
    def test_triggers(self):
        r = rp.penalty_close_below_ma50(95.0, 100.0)
        assert r["triggered"] is True
        assert r["points"] == pytest.approx(-15.0)

    def test_no_trigger(self):
        r = rp.penalty_close_below_ma50(105.0, 100.0)
        assert r["triggered"] is False


class TestMa50Falling:
    def test_triggers_when_falling(self):
        r = rp.penalty_ma50_falling(sma50_now=95.0, sma50_22d_ago=100.0)
        assert r["triggered"] is True

    def test_no_trigger_when_rising(self):
        r = rp.penalty_ma50_falling(sma50_now=105.0, sma50_22d_ago=100.0)
        assert r["triggered"] is False


class TestAtrExpansion:
    def test_triggers_on_expansion(self):
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        # 앞 20일은 저변동성, 최근 20일은 고변동성.
        import numpy as np

        base = 100.0
        highs, lows, closes = [], [], []
        rng = np.random.default_rng(42)
        for i in range(n):
            vola = 0.2 if i < n - 20 else 3.0
            c = base + rng.normal(0, 0.05)
            highs.append(c + vola)
            lows.append(c - vola)
            closes.append(c)
        close = pd.Series(closes, index=idx)
        high = pd.Series(highs, index=idx)
        low = pd.Series(lows, index=idx)
        r = rp.penalty_atr_expansion(high, low, close)
        assert r["triggered"] is True
        assert r["points"] == pytest.approx(-5.0)


class TestPivotReentryFailure:
    def test_triggers_when_broke_out_then_reentered(self):
        n = 35
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        # 피벗 기준 구간(재이탈 확인 10일보다 이전, 20일): 박스권 고가 110으로 평탄.
        # 재이탈 확인 구간(최근 10거래일, 오늘 제외): 첫날 돌파(118) 후 유지.
        # 오늘: 피벗(110) 아래로 재진입(104).
        highs = [110.0] * 24 + [120.0] + [115.0] * 9 + [105.0]
        closes = [108.0] * 24 + [118.0] + [115.0] * 9 + [104.0]
        assert len(highs) == n and len(closes) == n
        high = pd.Series(highs, index=idx)
        close = pd.Series(closes, index=idx)
        r = rp.penalty_pivot_breakout_failure(close, high)
        assert r["triggered"] is True

    def test_no_trigger_when_pivot_itself_still_holds(self):
        n = 35
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        highs = [110.0] * 24 + [120.0] + [115.0] * 10
        closes = [108.0] * 24 + [118.0] + [115.0] * 10  # 오늘도 피벗(110) 위에 유지
        high = pd.Series(highs, index=idx)
        close = pd.Series(closes, index=idx)
        r = rp.penalty_pivot_breakout_failure(close, high)
        assert r["triggered"] is False


class TestEvaluateRiskPenaltyAggregate:
    def test_no_penalties_on_healthy_flat_data(self):
        close, high, low, volume = _flat_df(260)
        result = rp.evaluate_risk_penalty(close, high, low, volume)
        # 완전히 평탄한 데이터는 위험 신호가 없어야 함(또는 계산불가로 0 처리).
        assert result["score"] <= 0.0
