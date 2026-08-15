"""yfinance 기반 일봉 데이터 수집.

계산 로직(``indicators.py`` 등)과 분리되어 있으며, 이 모듈이 아는 것은
"티커 → 정제된 OHLCV DataFrame"을 만드는 방법뿐이다. 재시도/캐시/호출 제한을
포함한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

MIN_TRADING_DAYS = 200
"""이보다 적으면 데이터 부족(insufficient_data) 상태로 표시."""

RECOMMENDED_TRADING_DAYS = 252
"""1년(52주) 지표를 온전히 계산하기 위해 권장되는 최소 거래일수."""

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class DataStatus:
    """``FetchResult.status`` 값 상수."""

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    FETCH_ERROR = "fetch_error"
    EMPTY = "empty"


@dataclass
class FetchResult:
    """단일 티커에 대한 수집 결과."""

    ticker: str
    status: str
    data: Optional[pd.DataFrame] = None
    as_of_date: Optional[str] = None
    trading_days: int = 0
    error_message: Optional[str] = None


def kr_stock_ticker(code: str, market: str) -> str:
    """한국 종목코드 → yfinance 티커.

    :param code: 6자리 종목코드(예: "005930").
    :param market: "KOSPI" 또는 "KOSDAQ" (대소문자 무관).
    :raises ValueError: market이 알 수 없는 값일 때.
    """
    m = market.strip().upper()
    if m == "KOSPI":
        return f"{code}.KS"
    if m == "KOSDAQ":
        return f"{code}.KQ"
    raise ValueError(f"알 수 없는 시장 구분: {market!r} (KOSPI/KOSDAQ만 지원)")


def index_ticker_for_market(market: str) -> str:
    """시장 구분에 대응하는 기준지수 티커. 코스피=^KS11, 코스닥=^KQ11."""
    m = market.strip().upper()
    if m == "KOSPI":
        return "^KS11"
    if m == "KOSDAQ":
        return "^KQ11"
    raise ValueError(f"알 수 없는 시장 구분: {market!r} (KOSPI/KOSDAQ만 지원)")


def _clean_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """yfinance 원본 응답을 정제.

    - 컬럼이 MultiIndex(복수 티커 응답)면 첫 레벨만 사용.
    - 날짜 오름차순 정렬, 중복 날짜 제거(마지막 값 유지).
    - OHLC가 전부 NaN이거나 거래량이 없고 시가=고가=저가=종가인(거래정지성)
      행은 지표 계산을 왜곡하므로 제거한다(단, 실제 상장폐지 직전처럼 저거래
      정상 데이터까지 과도하게 지우지 않도록 "OHLC 전부 동일 + 거래량 0"인
      경우로 조건을 좁힘).
    """
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[[c for c in REQUIRED_COLUMNS if c in df.columns]]
    df = df.dropna(how="all")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    if {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
        halted = (
            (df["Open"] == df["High"])
            & (df["High"] == df["Low"])
            & (df["Low"] == df["Close"])
            & (df["Volume"] == 0)
        )
        df = df[~halted]

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


def fetch_ohlcv(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
    max_retries: int = 3,
    retry_delay_sec: float = 2.0,
) -> FetchResult:
    """단일 티커의 일봉 데이터를 수집하고 품질을 판정한다.

    - ``auto_adjust=True``: 액면분할/배당을 반영한 수정주가를 전체 계산에서
      일관되게 사용(스펙 요구사항).
    - ``repair=True``: yfinance의 알려진 데이터 오류(분할 인식 실패 등)를
      자동 보정.
    - 실패 시 지수 백오프 없이 고정 지연으로 ``max_retries``번 재시도.
    """
    last_error: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                repair=True,
                progress=False,
                threads=False,
            )
            if raw is None or raw.empty:
                last_error = "빈 응답"
                logger.warning("%s: 빈 응답(시도 %d/%d)", ticker, attempt, max_retries)
            else:
                cleaned = _clean_ohlcv(raw)
                if cleaned.empty:
                    return FetchResult(ticker=ticker, status=DataStatus.EMPTY, trading_days=0)
                n = len(cleaned)
                as_of = cleaned.index[-1].strftime("%Y-%m-%d")
                status = DataStatus.OK if n >= MIN_TRADING_DAYS else DataStatus.INSUFFICIENT_DATA
                return FetchResult(
                    ticker=ticker,
                    status=status,
                    data=cleaned,
                    as_of_date=as_of,
                    trading_days=n,
                )
        except Exception as exc:  # noqa: BLE001 - 외부 API 호출이라 광범위하게 잡아 재시도
            last_error = str(exc)
            logger.warning("%s: 수집 실패(시도 %d/%d) - %s", ticker, attempt, max_retries, exc)
        if attempt < max_retries:
            time.sleep(retry_delay_sec)

    return FetchResult(
        ticker=ticker,
        status=DataStatus.FETCH_ERROR,
        trading_days=0,
        error_message=last_error,
    )


@dataclass
class DiskCache:
    """일봉 데이터를 로컬에 Parquet으로 캐시(같은 날 재실행 시 재수집 방지).

    장 마감 후 하루 한 번 갱신하는 운영 방식에 맞춰, 캐시 파일에 저장된
    날짜와 오늘 날짜가 같으면 네트워크 호출 없이 캐시를 반환한다.
    """

    cache_dir: Path
    _mem: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticker: str) -> Path:
        safe = ticker.replace("^", "_IDX_")
        return self.cache_dir / f"{safe}.parquet"

    def get(self, ticker: str, today: str) -> Optional[pd.DataFrame]:
        if ticker in self._mem:
            cached_today, df = self._mem[ticker]
            if cached_today == today:
                return df
        p = self._path(ticker)
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if not df.empty and df.attrs.get("as_of") == today:
                    self._mem[ticker] = (today, df)
                    return df
            except Exception:  # noqa: BLE001 - 캐시 손상 시 그냥 재수집
                logger.warning("%s: 캐시 파일 손상, 재수집", ticker)
        return None

    def put(self, ticker: str, today: str, df: pd.DataFrame) -> None:
        df = df.copy()
        df.attrs["as_of"] = today
        self._mem[ticker] = (today, df)
        try:
            df.to_parquet(self._path(ticker))
        except Exception:  # noqa: BLE001 - 캐시 쓰기 실패는 치명적이지 않음
            logger.warning("%s: 캐시 저장 실패", ticker)


def fetch_ohlcv_cached(
    ticker: str,
    cache: DiskCache,
    today: str,
    period: str = "2y",
    interval: str = "1d",
    max_retries: int = 3,
    retry_delay_sec: float = 2.0,
    request_delay_sec: float = 0.3,
) -> FetchResult:
    """캐시를 우선 조회하고, 없으면 수집 후 캐시에 적재.

    :param today: "YYYY-MM-DD" — 캐시 유효성 판단 기준일(장 마감 후 1회 갱신 전제).
    :param request_delay_sec: 실제 네트워크 호출 시에만 적용하는 호출 간 지연
        (배치 수집 시 API 호출 제한 대응).
    """
    cached = cache.get(ticker, today)
    if cached is not None:
        n = len(cached)
        as_of = cached.index[-1].strftime("%Y-%m-%d")
        status = DataStatus.OK if n >= MIN_TRADING_DAYS else DataStatus.INSUFFICIENT_DATA
        return FetchResult(ticker=ticker, status=status, data=cached, as_of_date=as_of, trading_days=n)

    result = fetch_ohlcv(
        ticker,
        period=period,
        interval=interval,
        max_retries=max_retries,
        retry_delay_sec=retry_delay_sec,
    )
    time.sleep(request_delay_sec)
    if result.status in (DataStatus.OK, DataStatus.INSUFFICIENT_DATA) and result.data is not None:
        cache.put(ticker, today, result.data)
    return result
