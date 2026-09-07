"""setup_qualification.py 단위 테스트 (눌림목매매 기준, 구 test_trend_qualification.py 대체)."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import setup_qualification as sq


def _impulse(start_price: float = 50.0, peak_price: float = 100.0, start_index: int = 0, peak_index: int = 10) -> dict:
    return {
        "start_index": start_index,
        "start_price": start_price,
        "peak_index": peak_index,
        "peak_price": peak_price,
        "gain_pct": (peak_price - start_price) / start_price * 100.0,
    }


class TestSupportLevel:
    """지지선 = 임펄스 시작가(2026-09-07: 60일선 병용 방식 폐기, setup_qualification.py의
    support_level 독스트링에 실측 근거 기록됨)."""

    def test_returns_impulse_start_price(self):
        assert sq.support_level(80.0) == pytest.approx(80.0)

    def test_none_when_no_impulse(self):
        assert sq.support_level(None) is None


class TestCondImpulseExists:
    def test_met_when_gain_above_20pct(self):
        r = sq.cond_impulse_exists(_impulse(start_price=100.0, peak_price=125.0))
        assert r["met"] is True
        assert r["points"] == pytest.approx(10.0)

    def test_not_met_when_gain_below_threshold(self):
        r = sq.cond_impulse_exists(_impulse(start_price=100.0, peak_price=110.0))
        assert r["met"] is False
        assert r["points"] == pytest.approx(0.0)

    def test_none_when_no_impulse(self):
        r = sq.cond_impulse_exists(None)
        assert r["met"] is None
        assert r["computable"] is False


class TestCondRetraceInRange:
    @pytest.mark.parametrize(
        "retrace_pct,expected_met",
        [(9.9, False), (10.0, True), (61.8, True), (61.9, False)],
    )
    def test_boundary(self, retrace_pct: float, expected_met: bool):
        peak = 100.0
        close_val = peak * (1 - retrace_pct / 100.0)
        r = sq.cond_retrace_in_range(_impulse(peak_price=peak), close_val)
        assert r["met"] is expected_met

    def test_none_when_missing(self):
        assert sq.cond_retrace_in_range(None, 100.0)["met"] is None


class TestCondSupportHeld:
    def test_met_when_close_at_or_above_support(self):
        imp = _impulse()
        assert sq.cond_support_held(100.0, 100.0, imp)["met"] is True
        assert sq.cond_support_held(101.0, 100.0, imp)["met"] is True

    def test_not_met_when_below_support(self):
        assert sq.cond_support_held(99.0, 100.0, _impulse())["met"] is False

    def test_none_when_missing_data(self):
        assert sq.cond_support_held(None, 100.0, _impulse())["met"] is None

    def test_none_when_no_impulse(self):
        # 임펄스 자체가 없으면 "조정 중 지지선 유지"가 성립하지 않으므로 계산 불가여야 함.
        assert sq.cond_support_held(100.0, 100.0, None)["met"] is None


class TestCondPullbackDuration:
    @pytest.mark.parametrize(
        "days_since_peak,expected_met",
        [(2, False), (3, True), (20, True), (21, False)],
    )
    def test_boundary(self, days_since_peak: int, expected_met: bool):
        total_len = 30
        peak_index = (total_len - 1) - days_since_peak
        r = sq.cond_pullback_duration(_impulse(peak_index=peak_index), total_len)
        assert r["met"] is expected_met

    def test_none_when_no_impulse(self):
        assert sq.cond_pullback_duration(None, 30)["met"] is None


class TestCondImpulseVolume:
    def test_met_when_ratio_above_threshold(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="B")
        # 임펄스 구간(0~9) 평균 150, 직전 구간(음수 인덱스라 여기선 별도 준비 필요) -- start_index를 10으로.
        volumes = [100.0] * 10 + [150.0] * 10
        volume = pd.Series(volumes, index=idx)
        impulse = _impulse(start_index=10, peak_index=19)
        r = sq.cond_impulse_volume(impulse, volume)
        assert r["met"] is True

    def test_not_met_when_ratio_below_threshold(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="B")
        volumes = [100.0] * 10 + [120.0] * 10
        volume = pd.Series(volumes, index=idx)
        impulse = _impulse(start_index=10, peak_index=19)
        r = sq.cond_impulse_volume(impulse, volume)
        assert r["met"] is False

    def test_none_when_prior_window_unavailable(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        volume = pd.Series([100.0] * 10, index=idx)
        impulse = _impulse(start_index=0, peak_index=9)
        r = sq.cond_impulse_volume(impulse, volume)
        assert r["computable"] is False

    def test_none_when_no_impulse(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        volume = pd.Series([100.0] * 10, index=idx)
        assert sq.cond_impulse_volume(None, volume)["met"] is None


class TestEvaluateSetupQualification:
    def _build_series(self) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        """하락(0~35, 저점 60) -> 상승(35~60, 고점 100) -> 조정(61~74, 되돌림 40%로 수렴).

        동률(꺾이는 지점의 평탄 구간) 없이 매끄럽게 이어지는 하나의 함수로 구성해야
        ``find_swing_points``의 동률 처리(가장 왼쪽 값만 인정) 때문에 극값이 누락되지
        않는다 — 이전 버전(평탄 구간 + 불연속 점프)은 이 이유로 임펄스를 못 찾았음.
        """
        n = 75
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        closes: list[float] = []
        for i in range(n):
            if i <= 35:
                closes.append(75.0 - i * (15.0 / 35))  # 75 -> 60, i=35에서 저점
            elif i <= 60:
                closes.append(60.0 + (i - 35) * (40.0 / 25))  # 60 -> 100, i=60에서 고점
            else:
                retrace = (i - 60) * (40.0 / 14)  # i=74에서 되돌림 40%
                closes.append(100.0 * (1 - retrace / 100.0))
        close = pd.Series(closes, index=idx)
        high = close * 1.005
        low = close * 0.995
        volume = pd.Series([1_000_000.0] * 35 + [3_000_000.0] * 25 + [1_000_000.0] * 15, index=idx)
        return close, high, low, volume

    def test_realistic_pullback_scores_positively(self):
        close, high, low, volume = self._build_series()
        result = sq.evaluate_setup_qualification(close, high, low, volume)
        # 임펄스를 찾았고, 최소 일부 조건은 충족해 0점은 아니어야 함.
        assert result["impulse"] is not None
        assert result["score"] > 0.0
        assert result["max_score"] == pytest.approx(40.0)

    def test_qualified_threshold_is_35(self):
        assert sq.QUALIFIED_THRESHOLD == 35.0

    def test_flat_series_finds_no_impulse(self):
        idx = pd.date_range("2024-01-01", periods=70, freq="B")
        close = pd.Series([100.0] * 70, index=idx)
        high = close * 1.001
        low = close * 0.999
        volume = pd.Series([1000.0] * 70, index=idx)
        result = sq.evaluate_setup_qualification(close, high, low, volume)
        assert result["impulse"] is None
        assert result["score"] == pytest.approx(0.0)
        assert result["mandatory_conditions_met"] is None
