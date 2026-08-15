"""trend_qualification.py 단위 테스트."""

from __future__ import annotations

import pytest

from technical_score import trend_qualification as tq


class TestIndividualConditions:
    def test_cond_close_above_150_200ma_true(self):
        r = tq.cond_close_above_150_200ma(110, 100, 100)
        assert r["met"] is True
        assert r["points"] == pytest.approx(5.0)

    def test_cond_close_above_150_200ma_false_when_below_either(self):
        r = tq.cond_close_above_150_200ma(105, 110, 100)
        assert r["met"] is False
        assert r["points"] == pytest.approx(0.0)

    def test_cond_none_when_missing_data(self):
        r = tq.cond_close_above_150_200ma(None, 100, 100)
        assert r["met"] is None
        assert r["computable"] is False
        assert r["points"] == pytest.approx(0.0)
        assert r["reason"]

    def test_cond_200ma_rising(self):
        assert tq.cond_200ma_rising(105, 100)["met"] is True
        assert tq.cond_200ma_rising(100, 105)["met"] is False

    def test_cond_above_52w_low_125pct_boundary(self):
        low_52w = 100.0
        # 정확히 1.25배 -> met True (>=)
        assert tq.cond_above_52w_low_125pct(125.0, low_52w)["met"] is True
        assert tq.cond_above_52w_low_125pct(124.99, low_52w)["met"] is False

    def test_cond_above_52w_high_75pct_boundary(self):
        high_52w = 100.0
        assert tq.cond_above_52w_high_75pct(75.0, high_52w)["met"] is True
        assert tq.cond_above_52w_high_75pct(74.99, high_52w)["met"] is False

    def test_cond_relative_strength_top30_boundary(self):
        # 상위 30% == 백분위 70 이상
        assert tq.cond_relative_strength_52w_top30(70.0)["met"] is True
        assert tq.cond_relative_strength_52w_top30(69.99)["met"] is False
        assert tq.cond_relative_strength_52w_top30(None)["met"] is None


class TestEvaluateTrendQualification:
    def test_all_conditions_met_gives_40(self):
        import pandas as pd

        n = 260
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        # 꾸준히 우상향하는 가격(200일선도 22거래일 전보다 높아지도록).
        prices = [100 + i * 0.5 for i in range(n)]
        close = pd.Series(prices, index=idx)
        high = close * 1.01
        low = close * 0.99

        result = tq.evaluate_trend_qualification(close, high, low, relative_strength_52w_percentile=90.0)
        assert result["score"] == pytest.approx(40.0)
        assert result["qualified"] is True
        assert result["mandatory_conditions_met"] is True
        assert result["warning"] is None

    def test_downtrend_fails_mandatory_and_warns(self):
        import pandas as pd

        n = 260
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        prices = [200 - i * 0.5 for i in range(n)]
        close = pd.Series(prices, index=idx)
        high = close * 1.01
        low = close * 0.99

        result = tq.evaluate_trend_qualification(close, high, low, relative_strength_52w_percentile=10.0)
        assert result["mandatory_conditions_met"] is False
        assert result["warning"] == "추세 부적격"

    def test_qualified_threshold_is_35(self):
        assert tq.QUALIFIED_THRESHOLD == 35.0

    def test_insufficient_data_conditions_are_not_computable(self):
        import pandas as pd

        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        close = pd.Series([100.0] * 10, index=idx)
        high = close * 1.01
        low = close * 0.99
        result = tq.evaluate_trend_qualification(close, high, low, relative_strength_52w_percentile=None)
        # 이동평균(50/150/200일) 기반 조건들은 데이터 부족으로 계산 불가여야 한다.
        # 52주 고/저가 기반 조건(6,7)은 보유 데이터만으로도 값을 낼 수 있어(rolling_high_low
        # 설계상) 계산 자체는 가능 — 그래서 검사 대상에서 제외한다.
        ma_dependent_labels = {
            "종가 > 150일선 & 종가 > 200일선",
            "150일선 > 200일선",
            "200일선 상승(22거래일 전 대비)",
            "50일선 > 150일선 & 50일선 > 200일선",
            "종가 > 50일선",
        }
        for c in result["details"]:
            if c["label"] in ma_dependent_labels:
                assert c["computable"] is False
                assert c["reason"] is not None
        assert result["mandatory_conditions_met"] is None
