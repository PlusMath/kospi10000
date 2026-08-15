"""배치 단위 실행 — 여러 종목을 한 번에 평가.

상대강도 백분위(52주/6개월)는 "평가하려는 배치" 내에서 계산한다(전체
한국 상장종목이 아니라, 이 함수에 넘긴 종목 리스트 기준). 이유: 실제
~2500개+ 상장종목 전체를 매번 수집하면 호출량이 지나치게 커지고, 이
프로젝트의 실사용 맥락(kospi10000 등 특정 유니버스 평가)에서는 배치가
곧 관심 있는 비교 모집단이기 때문. 필요하면 더 큰 리스트를 넘겨
모집단을 넓힐 수 있다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import indicators as ind
from .data_collection import DataStatus, DiskCache, FetchResult, fetch_ohlcv_cached, index_ticker_for_market, kr_stock_ticker
from .investor_flow import fetch_investor_flow
from .scoring import evaluate_technical_score

logger = logging.getLogger(__name__)

SIX_MONTH_TRADING_DAYS = 126
FIFTY_TWO_WEEK_TRADING_DAYS = 252
INVESTOR_FLOW_REQUEST_DELAY_SEC = 0.3
"""종목별 투자자매매동향 스크래핑 사이 지연(네이버 서버 배려용)."""


@dataclass
class TickerSpec:
    """평가 대상 종목 하나의 식별 정보."""

    code: str
    market: str  # "KOSPI" 또는 "KOSDAQ"
    name: str

    @property
    def ticker(self) -> str:
        return kr_stock_ticker(self.code, self.market)


def _compute_raw_relative_returns(
    fetch_result: FetchResult, index_close_by_market: dict[str, Any]
) -> dict[str, Optional[float]]:
    """52주 절대수익률과 6개월 지수대비 초과수익률(원시값, 백분위 계산 전)."""
    if fetch_result.status != DataStatus.OK or fetch_result.data is None:
        return {"return_52w": None, "excess_return_6m": None}

    close = fetch_result.data["Close"]
    return_52w = ind.pct_change_over(close, FIFTY_TWO_WEEK_TRADING_DAYS)
    return_6m = ind.pct_change_over(close, SIX_MONTH_TRADING_DAYS)

    excess_return_6m: Optional[float] = None
    if return_6m is not None:
        index_close = index_close_by_market.get(fetch_result.ticker)
        if index_close is not None:
            index_return_6m = ind.pct_change_over(index_close, SIX_MONTH_TRADING_DAYS)
            if index_return_6m is not None:
                excess_return_6m = return_6m - index_return_6m

    return {"return_52w": return_52w, "excess_return_6m": excess_return_6m}


def evaluate_batch(
    specs: list[TickerSpec],
    cache_dir: Optional[Path] = None,
    as_of: Optional[str] = None,
) -> list[dict[str, Any]]:
    """종목 리스트를 평가해 스펙 8절 JSON 형식 결과 리스트를 반환.

    :param specs: 평가 대상 종목들.
    :param cache_dir: 일봉 캐시 저장 위치(기본: ``technical_score/.cache``).
    :param as_of: 캐시 유효성 판단 기준일 "YYYY-MM-DD"(기본: 오늘).
    """
    today = as_of or date.today().isoformat()
    cache = DiskCache(cache_dir or (Path(__file__).parent / ".cache"))

    # 1) 필요한 기준지수(코스피/코스닥)를 먼저 한 번씩만 수집.
    needed_markets = {s.market.strip().upper() for s in specs}
    index_fetch_by_market: dict[str, FetchResult] = {}
    for market in needed_markets:
        idx_ticker = index_ticker_for_market(market)
        index_fetch_by_market[market] = fetch_ohlcv_cached(idx_ticker, cache, today)
        if index_fetch_by_market[market].status != DataStatus.OK:
            logger.warning("%s 기준지수 수집 실패/부족(status=%s)", idx_ticker, index_fetch_by_market[market].status)

    index_close_by_ticker: dict[str, Any] = {}
    for spec in specs:
        market = spec.market.strip().upper()
        idx_result = index_fetch_by_market.get(market)
        if idx_result and idx_result.data is not None:
            index_close_by_ticker[spec.ticker] = idx_result.data["Close"]

    # 2) 각 종목 일봉 수집.
    fetch_results: dict[str, FetchResult] = {}
    for spec in specs:
        fetch_results[spec.ticker] = fetch_ohlcv_cached(spec.ticker, cache, today)

    # 2b) 종목별 투자자매매동향(개인/외국인/기관) 수집 — 수급 점수(별도 트랙)용.
    #     실패해도 개별 종목의 100점 본점수에는 영향 없음(수급 점수만 계산 불가로 표시).
    investor_flows_by_ticker: dict[str, list] = {}
    for spec in specs:
        investor_flows_by_ticker[spec.ticker] = fetch_investor_flow(spec.code, days=10)
        time.sleep(INVESTOR_FLOW_REQUEST_DELAY_SEC)

    # 3) 배치 내 상대수익률 원시값 계산.
    raw_returns: dict[str, dict[str, Optional[float]]] = {
        spec.ticker: _compute_raw_relative_returns(fetch_results[spec.ticker], index_close_by_ticker)
        for spec in specs
    }

    # 4) 배치 내 백분위 계산(52주 절대수익률, 6개월 지수대비 초과수익률).
    all_52w = [v["return_52w"] for v in raw_returns.values()]
    all_excess_6m = [v["excess_return_6m"] for v in raw_returns.values()]

    percentile_52w_by_ticker = {
        t: ind.percentile_rank(all_52w, v["return_52w"]) for t, v in raw_returns.items()
    }
    percentile_6m_by_ticker = {
        t: ind.percentile_rank(all_excess_6m, v["excess_return_6m"]) for t, v in raw_returns.items()
    }

    # 5) 종목별 최종 평가.
    results: list[dict[str, Any]] = []
    for spec in specs:
        t = spec.ticker
        result = evaluate_technical_score(
            ticker=t,
            name=spec.name,
            fetch_result=fetch_results[t],
            relative_strength_52w_percentile=percentile_52w_by_ticker.get(t),
            relative_strength_6m_percentile=percentile_6m_by_ticker.get(t),
            investor_flows=investor_flows_by_ticker.get(t),
        )
        results.append(result)
    return results
