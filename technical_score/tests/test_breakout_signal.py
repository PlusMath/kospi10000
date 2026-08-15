"""breakout_signal.py 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import breakout_signal as bo


class TestDetectPivotPrice:
    def test_excludes_today(self):
        idx = pd.date_range("2024-01-01", periods=25, freq="B")
        highs = [100.0] * 24 + [999.0]  # 오늘 고가는 극단값이지만 피벗엔 반영되면 안 됨
        high = pd.Series(highs, index=idx)
        pivot = bo.detect_pivot_price(high, lookback=20)
        assert pivot == pytest.approx(100.0)

    def test_none_when_insufficient_data(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        high = pd.Series([100.0] * 5, index=idx)
        assert bo.detect_pivot_price(high, lookback=20) is None


class TestEvaluateBreakoutSignal:
    def _make_df(self, n=60):
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        close = pd.Series([100.0] * n, index=idx)
        high = pd.Series([101.0] * n, index=idx)
        low = pd.Series([99.0] * n, index=idx)
        volume = pd.Series([1000.0] * n, index=idx)
        return close, high, low, volume, idx

    def test_full_breakout_scores_10(self):
        close, high, low, volume, idx = self._make_df()
        # 오늘: 피벗(101, 최근 20일 고가) 위로 강하게 돌파 + 거래량 폭증 + 종가가 당일 고점 근처.
        close.iloc[-1] = 110.0
        high.iloc[-1] = 111.0
        low.iloc[-1] = 100.0
        volume.iloc[-1] = 3000.0  # 50일 평균(1000)의 150% 이상
        result = bo.evaluate_breakout_signal(close, high, low, volume)
        assert result["score"] == pytest.approx(10.0)

    def test_no_breakout_scores_low(self):
        close, high, low, volume, idx = self._make_df()
        result = bo.evaluate_breakout_signal(close, high, low, volume)
        assert result["breakout_today"] is False
        # 종가가 피벗 위로 못 뚫었으므로 첫 항목 0점.
        assert result["details"][0]["points"] == pytest.approx(0.0)

    def test_close_position_threshold(self):
        close, high, low, volume, idx = self._make_df()
        close.iloc[-1] = 110.0
        high.iloc[-1] = 111.0
        low.iloc[-1] = 100.0  # position = (110-100)/(111-100) = 0.909 >= 0.70
        result = bo.evaluate_breakout_signal(close, high, low, volume)
        pos_detail = result["details"][2]
        assert pos_detail["met"] is True

    def test_high_equals_low_handled_without_division_by_zero(self):
        close, high, low, volume, idx = self._make_df()
        close.iloc[-1] = 100.0
        high.iloc[-1] = 100.0
        low.iloc[-1] = 100.0  # 고가==저가
        result = bo.evaluate_breakout_signal(close, high, low, volume)
        pos_detail = result["details"][2]
        assert pos_detail["computable"] is False
