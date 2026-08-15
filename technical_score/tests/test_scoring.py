"""scoring.py 단위 테스트 — 등급 분류, 클램프, 데이터 부족/유동성 제외 처리."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from technical_score import scoring
from technical_score.data_collection import DataStatus, FetchResult


class TestClassifyGrade:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (100, "최상급 진입 후보"),
            (85, "최상급 진입 후보"),
            (84.6, "최상급 진입 후보"),  # round(84.6)=85
            (84, "기술적 매력 우수"),
            (75, "기술적 매력 우수"),
            (74, "관심 종목"),
            (65, "관심 종목"),
            (64, "추세 양호·진입 위치 불리"),
            (50, "추세 양호·진입 위치 불리"),
            (49, "기술적 부적격"),
            (0, "기술적 부적격"),
        ],
    )
    def test_grade_boundaries(self, score: float, expected: str):
        assert scoring.classify_grade(score) == expected


class TestEvaluateTechnicalScoreDataStatus:
    def test_fetch_error_returns_none_score(self):
        fr = FetchResult(ticker="000000.KS", status=DataStatus.FETCH_ERROR, error_message="boom")
        result = scoring.evaluate_technical_score("000000.KS", "테스트종목", fr, None, None)
        assert result["data_status"] == DataStatus.FETCH_ERROR
        assert result["technical_score"] is None
        assert result["grade"] is None

    def test_insufficient_data_returns_none_score(self):
        fr = FetchResult(ticker="000000.KS", status=DataStatus.INSUFFICIENT_DATA, trading_days=50)
        result = scoring.evaluate_technical_score("000000.KS", "테스트종목", fr, None, None)
        assert result["data_status"] == DataStatus.INSUFFICIENT_DATA
        assert result["technical_score"] is None

    def test_low_liquidity_excluded(self):
        n = 260
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        close = pd.Series([100.0] * n, index=idx)
        high = close * 1.01
        low = close * 0.99
        volume = pd.Series([10.0] * n, index=idx)  # 거래대금 극소(100*10=1000원 수준)
        df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume})
        fr = FetchResult(ticker="000000.KS", status=DataStatus.OK, data=df, as_of_date="2024-01-01", trading_days=n)
        result = scoring.evaluate_technical_score("000000.KS", "테스트종목", fr, 50.0, 50.0)
        assert result["data_status"] == "excluded_low_liquidity"
        assert result["technical_score"] is None


class TestEvaluateTechnicalScoreHappyPath:
    def _healthy_fetch_result(self) -> FetchResult:
        n = 300
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        prices = [100 + i * 0.3 for i in range(n)]
        close = pd.Series(prices, index=idx)
        high = close * 1.01
        low = close * 0.99
        volume = pd.Series([20_000_000.0] * n, index=idx)  # 거래대금 충분(유동성 기준 여유 있게 상회)
        df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume})
        return FetchResult(ticker="005930.KS", status=DataStatus.OK, data=df, as_of_date="2024-01-01", trading_days=n)

    def test_score_is_clamped_0_100(self):
        fr = self._healthy_fetch_result()
        result = scoring.evaluate_technical_score("005930.KS", "삼성전자", fr, 90.0, 90.0)
        assert 0.0 <= result["technical_score"] <= 100.0

    def test_result_is_json_serializable(self):
        """실제 소비 형태(파일 저장, API 응답)와 동일하게 numpy 타입 누락이 없는지 확인."""
        fr = self._healthy_fetch_result()
        result = scoring.evaluate_technical_score("005930.KS", "삼성전자", fr, 90.0, 90.0)
        s = json.dumps(result, ensure_ascii=False)  # 실패하면 numpy 타입이 섞여 있다는 뜻
        assert len(s) > 0

    def test_grade_matches_score(self):
        fr = self._healthy_fetch_result()
        result = scoring.evaluate_technical_score("005930.KS", "삼성전자", fr, 90.0, 90.0)
        assert result["grade"] == scoring.classify_grade(result["technical_score"])

    def test_summary_is_non_empty_list_of_strings(self):
        fr = self._healthy_fetch_result()
        result = scoring.evaluate_technical_score("005930.KS", "삼성전자", fr, 90.0, 90.0)
        assert isinstance(result["summary"], list)
        assert all(isinstance(x, str) for x in result["summary"])

    def test_output_has_all_spec_top_level_keys(self):
        fr = self._healthy_fetch_result()
        result = scoring.evaluate_technical_score("005930.KS", "삼성전자", fr, 90.0, 90.0)
        expected_keys = {
            "ticker", "name", "as_of_date", "data_status", "technical_score", "grade",
            "trend_qualified", "trend_score", "entry_score", "risk_penalty",
            "breakout_signal", "summary",
        }
        assert expected_keys.issubset(result.keys())
