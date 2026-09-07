"""entry_desirability.py 단위 테스트 — 특히 경계값 정확성에 집중 (눌림목매매 기준)."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import entry_desirability as ed


def _rsi_series(*values: float) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(list(values), index=idx)


class TestRsiPullbackBaseScoreBoundaries:
    """RSI 반등 기본점수 — 경계값을 모두 검증해 겹치거나 비는 구간이 없는지 확인."""

    @pytest.mark.parametrize(
        "rsi,expected_score",
        [
            (29.9, 1.0),
            (30.0, 8.0),
            (34.9, 8.0),
            (35.0, 10.0),
            (44.9, 10.0),
            (45.0, 6.0),
            (54.9, 6.0),
            (55.0, 3.0),
            (64.9, 3.0),
            (65.0, 1.0),
            (100.0, 1.0),
        ],
    )
    def test_boundary(self, rsi: float, expected_score: float):
        score, _band = ed._rsi_pullback_base_score(rsi)
        assert score == pytest.approx(expected_score)

    def test_no_gap_no_overlap_across_full_range(self):
        step = 0.01
        rsi = 0.0
        while rsi <= 100.0:
            score, band = ed._rsi_pullback_base_score(rsi)
            assert 0.0 <= score <= 10.0
            assert band
            rsi += step


class TestRsiPullbackAdjustment:
    def test_up_in_30_55_gives_plus1(self):
        vals = [38.0, 40.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_pullback_rebound(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "30~55 구간에서 전일 대비 상승(반등 확인)" in labels

    def test_down_in_30_55_gives_minus1(self):
        vals = [40.0, 38.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_pullback_rebound(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "30~55 구간에서 전일 대비 추가 하락(반등 미확인)" in labels

    def test_score_clamped_to_10_max(self):
        vals = [39.0, 40.0]  # base=10(35~45) + up(+1) = 11 -> clamp 10
        s = _rsi_series(*vals)
        result = ed.score_rsi_pullback_rebound(s)
        assert result["score"] <= 10.0

    def test_score_clamped_to_0_min(self):
        vals = [200.0]  # 사실상 base만 확인(음수로 갈 극단 케이스는 없음) -- 최소 1점 유지
        s = _rsi_series(*vals)
        result = ed.score_rsi_pullback_rebound(s)
        assert result["score"] >= 0.0

    def test_none_when_missing(self):
        s = pd.Series([], dtype=float)
        result = ed.score_rsi_pullback_rebound(s)
        assert result["computable"] is False


class TestSupportDistance:
    """지지선 이격도 경계값(0/3/6/10/15%) 검증."""

    @pytest.mark.parametrize(
        "distance_pct,expected_score",
        [
            (-1.0, 0.0),  # 종가 < 지지선
            (0.0, 12.0),
            (2.99, 12.0),
            (3.0, 10.0),
            (5.99, 10.0),
            (6.0, 6.0),
            (9.99, 6.0),
            (10.0, 3.0),
            (15.0, 3.0),
            (15.01, 0.0),
            (30.0, 0.0),
        ],
    )
    def test_boundary(self, distance_pct: float, expected_score: float):
        support = 100.0
        close_val = support * (1 + distance_pct / 100.0)
        result = ed.score_support_distance(close_val, support)
        assert result["score"] == pytest.approx(expected_score)

    def test_none_when_data_missing(self):
        result = ed.score_support_distance(None, None)
        assert result["computable"] is False


class TestRetracePosition:
    def _impulse(self, peak_price: float) -> dict:
        return {"start_index": 0, "start_price": peak_price * 0.5, "peak_index": 10, "peak_price": peak_price}

    @pytest.mark.parametrize(
        "retrace_pct,expected_score",
        [
            (9.0, 0.0),
            (10.0, 5.0),
            (19.9, 5.0),
            (20.0, 8.0),
            (35.0, 8.0),
            (35.1, 5.0),
            (45.0, 5.0),
            (45.1, 2.0),
            (61.8, 2.0),
            (61.9, 0.0),
        ],
    )
    def test_boundary(self, retrace_pct: float, expected_score: float):
        peak = 100.0
        close_val = peak * (1 - retrace_pct / 100.0)
        result = ed.score_retrace_position(self._impulse(peak), close_val)
        assert result["score"] == pytest.approx(expected_score, abs=0.01)

    def test_none_when_no_impulse(self):
        result = ed.score_retrace_position(None, 100.0)
        assert result["computable"] is False


class TestVolumeDryUpVsImpulse:
    def _impulse(self, start_index: int, peak_index: int) -> dict:
        return {"start_index": start_index, "start_price": 50.0, "peak_index": peak_index, "peak_price": 100.0}

    @pytest.mark.parametrize(
        "ratio_pct,expected_score",
        [
            (40.0, 12.0),
            (40.01, 10.0),
            (60.0, 10.0),
            (60.01, 7.0),
            (80.0, 7.0),
            (80.01, 3.0),
            (100.0, 3.0),
            (100.01, 0.0),
        ],
    )
    def test_boundary(self, ratio_pct: float, expected_score: float):
        # 임펄스 구간(0~9, 평균 100) 대비 조정 구간(10~19, 평균 ratio_pct) 비율.
        idx = pd.date_range("2024-01-01", periods=20, freq="B")
        volumes = [100.0] * 10 + [ratio_pct] * 10
        volume = pd.Series(volumes, index=idx)
        impulse = self._impulse(start_index=0, peak_index=9)
        result = ed.score_volume_dry_up_vs_impulse(impulse, volume)
        assert result["score"] == pytest.approx(expected_score, abs=0.01)

    def test_none_when_no_impulse(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="B")
        volume = pd.Series([100.0] * 20, index=idx)
        result = ed.score_volume_dry_up_vs_impulse(None, volume)
        assert result["computable"] is False


class TestReversalCandle:
    @pytest.mark.parametrize(
        "position,expected_score",
        [
            (0.9, 8.0),
            (0.7, 8.0),
            (0.69, 5.0),
            (0.5, 5.0),
            (0.49, 2.0),
            (0.3, 2.0),
            (0.29, 0.0),
            (0.0, 0.0),
        ],
    )
    def test_boundary(self, position: float, expected_score: float):
        # close_position_in_range = (close-low)/(high-low) = position이 되도록 구성.
        low, high = 100.0, 200.0
        close_val = low + position * (high - low)
        close = pd.Series([close_val])
        high_s = pd.Series([high])
        low_s = pd.Series([low])
        result = ed.score_reversal_candle(close, high_s, low_s)
        assert result["score"] == pytest.approx(expected_score, abs=0.01)

    def test_none_when_high_equals_low(self):
        close = pd.Series([100.0])
        high_s = pd.Series([100.0])
        low_s = pd.Series([100.0])
        result = ed.score_reversal_candle(close, high_s, low_s)
        assert result["computable"] is False
