"""entry_desirability.py 단위 테스트 — 특히 경계값 정확성에 집중."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import entry_desirability as ed


def _rsi_series(*values: float) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(list(values), index=idx)


class TestRsiBaseScoreBoundaries:
    """스펙 4-7의 RSI 구간 기본점수 — 경계값 39.9/40/44.9/45/49.9/50/54.9/55/
    64.9/65/69.9/70/74.9/75를 모두 검증해 겹치거나 비는 구간이 없는지 확인."""

    @pytest.mark.parametrize(
        "rsi,expected_score",
        [
            (39.9, 0.0),
            (40.0, 2.0),
            (44.9, 2.0),
            (45.0, 5.0),
            (49.9, 5.0),
            (50.0, 8.0),
            (54.9, 8.0),
            (55.0, 10.0),
            (64.9, 10.0),
            (65.0, 7.0),
            (69.9, 7.0),
            (70.0, 4.0),
            (74.9, 4.0),
            (75.0, 1.0),
            (100.0, 1.0),
        ],
    )
    def test_boundary(self, rsi: float, expected_score: float):
        score, _band = ed._rsi_base_score(rsi)
        assert score == pytest.approx(expected_score)

    def test_no_gap_no_overlap_across_full_range(self):
        """0~100을 촘촘히 스캔해 항상 정확히 하나의 구간에만 속하는지 확인."""
        step = 0.01
        rsi = 0.0
        while rsi <= 100.0:
            score, band = ed._rsi_base_score(rsi)
            assert 0.0 <= score <= 10.0
            assert band  # 항상 라벨이 있어야 함
            rsi += step


class TestRsiDirectionAdjustment:
    def test_up_from_50_below_70_gives_plus1(self):
        # 현재 60, 5거래일전 55 -> 50~70 구간에서 상승 -> +1
        vals = [55.0] * 5 + [55.0, 60.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "RSI 50~70 구간에서 5거래일 전 대비 상승" in labels

    def test_cross_above_50_gives_plus2(self):
        vals = [45.0, 55.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "RSI가 50 상향 돌파" in labels

    def test_cross_below_70_gives_minus1(self):
        vals = [72.0, 68.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "RSI가 70 하향 이탈" in labels

    def test_cross_below_50_gives_minus2(self):
        vals = [55.0, 45.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        labels = [a["label"] for a in result["adjustments"]]
        assert "RSI가 50 하향 이탈" in labels

    def test_score_clamped_to_10_max(self):
        # base=10(55~65) + up-adjustment(+1) = 11 -> clamp 10
        vals = [58.0] * 5 + [58.0, 60.0]
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        assert result["score"] <= 10.0

    def test_score_clamped_to_0_min(self):
        # base=0(<40) 이고 하락 전환까지 겹치면 음수가 될 수 있으므로 0 클램프 확인.
        vals = [55.0, 35.0]  # 50 이상에서 50 미만으로: -2, base(35)=0 -> total -2 -> clamp 0
        s = _rsi_series(*vals)
        result = ed.score_rsi_momentum(s)
        assert result["score"] == pytest.approx(0.0)


class TestMa50Distance:
    """스펙 4-1 이격도 경계값(0/3/6/10/15%) 검증."""

    @pytest.mark.parametrize(
        "distance_pct,expected_score",
        [
            (-1.0, 0.0),  # 종가 < 50일선
            (0.0, 8.0),
            (2.99, 8.0),
            (3.0, 7.0),
            (5.99, 7.0),
            (6.0, 4.0),
            (9.99, 4.0),
            (10.0, 2.0),
            (15.0, 2.0),
            (15.01, 0.0),
            (30.0, 0.0),
        ],
    )
    def test_boundary(self, distance_pct: float, expected_score: float):
        sma50 = 100.0
        close_val = sma50 * (1 + distance_pct / 100.0)
        result = ed.score_ma50_distance(close_val, sma50)
        assert result["score"] == pytest.approx(expected_score)

    def test_none_when_data_missing(self):
        result = ed.score_ma50_distance(None, None)
        assert result["computable"] is False


class TestHigh52wDistance:
    """스펙 4-2 52주 고점 접근도 경계값(0/5/10/15/20/25%) 검증."""

    @pytest.mark.parametrize(
        "drawdown_pct,expected_score",
        [
            (0.0, 7.0),
            (4.99, 7.0),
            (5.0, 8.0),
            (9.99, 8.0),
            (10.0, 6.0),
            (14.99, 6.0),
            (15.0, 3.0),
            (19.99, 3.0),
            (20.0, 1.0),
            (25.0, 1.0),
            (25.01, 0.0),
            (50.0, 0.0),
        ],
    )
    def test_boundary(self, drawdown_pct: float, expected_score: float):
        high_52w = 100.0
        close_val = high_52w * (1 - drawdown_pct / 100.0)
        result = ed.score_high_52w_distance(close_val, high_52w)
        assert result["score"] == pytest.approx(expected_score)


class TestVolumeDryUp:
    @pytest.mark.parametrize(
        "ratio_pct,expected_score",
        [
            (40.0, 7.0),
            (40.01, 6.0),
            (60.0, 6.0),
            (60.01, 4.0),
            (80.0, 4.0),
            (80.01, 2.0),
            (100.0, 2.0),
            (100.01, 0.0),
        ],
    )
    def test_boundary(self, ratio_pct: float, expected_score: float):
        # volume: 최근5일 평균이 ratio_pct%가 되도록, 나머지(6~50일)는 남은 평균을 맞춤.
        recent_5d_avg = ratio_pct
        # 50일 전체 평균이 100이 되도록 나머지 45일 평균을 역산.
        target_50d_avg = 100.0
        remaining_avg = (target_50d_avg * 50 - recent_5d_avg * 5) / 45
        volumes = [recent_5d_avg] * 5 + [remaining_avg] * 45
        volumes = list(reversed(volumes))  # 최근 5일이 시리즈의 "끝"에 오도록
        idx = pd.date_range("2024-01-01", periods=50, freq="B")
        volume = pd.Series(volumes, index=idx)
        close = pd.Series([100.0] * 50, index=idx)  # 급락 없음(횡보) -> 감점 규칙 미적용
        result = ed.score_volume_dry_up(volume, close)
        assert result["score"] == pytest.approx(expected_score, abs=0.01)

    def test_sharp_decline_suppresses_score(self):
        idx = pd.date_range("2024-01-01", periods=50, freq="B")
        volume = pd.Series([100.0] * 45 + [10.0] * 5, index=idx)  # 거래량비율 40% 이하(고득점 대상)
        # close[-11](10거래일 전)=100 -> close[-1](오늘)=90: 정확히 최근10일 구간에서 -10% 하락.
        close = pd.Series([100.0] * 40 + [90.0] * 10, index=idx)
        result = ed.score_volume_dry_up(volume, close)
        assert result["score"] == pytest.approx(0.0)
        assert "급락" in (result["reason"] or "")


class TestPriceTightness:
    def test_low_volume_suppresses_score(self):
        idx = pd.date_range("2024-01-01", periods=60, freq="B")
        high = pd.Series([100.0] * 60, index=idx)
        low = pd.Series([99.0] * 60, index=idx)  # 매우 좁은 범위(1%)
        volume = pd.Series([1000.0] * 50 + [10.0] * 10, index=idx)  # 최근10일 거래량 급감
        result = ed.score_price_tightness(high, low, volume)
        assert result["score"] == pytest.approx(0.0)
        assert result["reason"] is not None
