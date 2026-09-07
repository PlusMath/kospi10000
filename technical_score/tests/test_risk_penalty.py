"""risk_penalty.py 단위 테스트 (눌림목매매 기준)."""

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


class TestCloseBelowSupport:
    def test_triggers(self):
        r = rp.penalty_close_below_support(95.0, 100.0)
        assert r["triggered"] is True
        assert r["points"] == pytest.approx(-20.0)

    def test_no_trigger(self):
        r = rp.penalty_close_below_support(105.0, 100.0)
        assert r["triggered"] is False

    def test_none_when_missing(self):
        r = rp.penalty_close_below_support(None, 100.0)
        assert r["computable"] is False


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


class TestSupportMaFalling:
    def test_triggers_when_falling(self):
        r = rp.penalty_support_ma_falling(sma60_now=95.0, sma60_22d_ago=100.0)
        assert r["triggered"] is True

    def test_no_trigger_when_rising(self):
        r = rp.penalty_support_ma_falling(sma60_now=105.0, sma60_22d_ago=100.0)
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


class TestEvaluateRiskPenaltyAggregate:
    def test_no_penalties_on_healthy_flat_data(self):
        close, high, low, volume = _flat_df(260)
        result = rp.evaluate_risk_penalty(close, high, low, volume)
        # 완전히 평탄한 데이터는 위험 신호가 없어야 함(또는 계산불가로 0 처리).
        assert result["score"] <= 0.0

    def test_close_below_impulse_start_triggers_via_support(self):
        close, high, low, volume = _flat_df(70, price=40.0)
        impulse = {"start_index": 0, "start_price": 100.0, "peak_index": 10, "peak_price": 150.0}
        result = rp.evaluate_risk_penalty(close, high, low, volume, impulse=impulse)
        assert "종가 < 지지선" in result["reasons"]
