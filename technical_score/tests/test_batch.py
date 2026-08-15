"""batch.py 단위 테스트 — 네트워크 호출 없이 백분위 계산 로직만 검증."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score import indicators as ind
from technical_score.batch import _compute_raw_relative_returns
from technical_score.data_collection import DataStatus, FetchResult


def _fetch_result_with_return(pct_return_over_252d: float, n: int = 260) -> FetchResult:
    """252거래일 동안 정확히 ``pct_return_over_252d``%가 되는 가격 시리즈를 만든다."""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    # 처음 n-252개는 시작가와 동일(변화 없음), 이후 252거래일에 걸쳐 목표 수익률로 선형 변화.
    start_price = 100.0
    end_price = start_price * (1 + pct_return_over_252d / 100.0)
    prices = [start_price] * (n - 252) + list(pd.Series([start_price, end_price]).reindex(range(252)).interpolate())
    close = pd.Series(prices[:n], index=idx)
    df = pd.DataFrame({"Close": close, "High": close, "Low": close, "Open": close, "Volume": [1000.0] * n})
    return FetchResult(ticker="TEST", status=DataStatus.OK, data=df, as_of_date="2024-01-01", trading_days=n)


class TestComputeRawRelativeReturns:
    def test_return_52w_matches_expected(self):
        fr = _fetch_result_with_return(50.0)  # 52주간 +50%
        raw = _compute_raw_relative_returns(fr, {})
        assert raw["return_52w"] == pytest.approx(50.0, rel=1e-2)

    def test_insufficient_data_gives_none(self):
        fr = FetchResult(ticker="TEST", status=DataStatus.INSUFFICIENT_DATA, trading_days=50)
        raw = _compute_raw_relative_returns(fr, {})
        assert raw["return_52w"] is None
        assert raw["excess_return_6m"] is None

    def test_excess_return_subtracts_index(self):
        fr = _fetch_result_with_return(50.0)
        # 지수는 6개월(126거래일) 동안 평탄(0% 수익) -> 초과수익률은 종목 6개월 수익률과 같아야 함.
        idx_close = pd.Series([100.0] * 260, index=fr.data.index)
        raw = _compute_raw_relative_returns(fr, {"TEST": idx_close})
        stock_6m = ind.pct_change_over(fr.data["Close"], 126)
        assert raw["excess_return_6m"] == pytest.approx(stock_6m, rel=1e-6)


class TestBatchPercentileIntegration:
    def test_percentile_rank_orders_correctly_across_batch(self):
        returns = {"A": 10.0, "B": 50.0, "C": 30.0, "D": -5.0}
        values = list(returns.values())
        percentiles = {k: ind.percentile_rank(values, v) for k, v in returns.items()}
        # B가 최고 수익률 -> 최고 백분위(100), D가 최저 -> 최저 백분위(25=1/4*100)
        assert percentiles["B"] == pytest.approx(100.0)
        assert percentiles["D"] == pytest.approx(25.0)
        assert percentiles["A"] < percentiles["C"] < percentiles["B"]
