"""가격 데이터로부터 지표를 계산하는 순수 함수 모음.

이 모듈은 데이터 수집(``data_collection.py``)과 완전히 분리되어 있다. 모든
함수는 ``pandas.Series``/``DataFrame``을 입력받아 결과를 반환할 뿐, 네트워크
호출이나 부수효과가 없다. 미래 시점의 데이터를 참조하지 않도록(룩어헤드 편향
방지) 모든 롤링 계산은 과거 방향으로만(``min_periods`` 지정, 뒤쪽을 보지
않는 인덱싱)이루어진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """단순이동평균(SMA). 유효 표본이 window보다 적은 구간은 NaN을 반환한다."""
    return series.rolling(window=window, min_periods=window).mean()


def sma_as_of(series: pd.Series, window: int, offset: int = 0) -> Optional[float]:
    """``offset`` 거래일 전 시점 기준의 SMA(window) 값을 반환.

    offset=0이면 가장 최근 값. 데이터가 부족해 계산할 수 없으면 None.
    ``offset``만큼 뒤로 이동한 위치를 기준으로만 계산하므로 미래 데이터를
    참조하지 않는다.
    """
    s = sma(series, window)
    idx = len(s) - 1 - offset
    if idx < 0 or idx >= len(s):
        return None
    val = s.iloc[idx]
    return None if pd.isna(val) else float(val)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range = max(고가-저가, |고가-전일종가|, |저가-전일종가|).

    첫 행은 전일 종가가 없어 고가-저가만 사용한다(전일 비교값 NaN 처리).
    """
    prev_close = close.shift(1)
    a = (high - low).abs()
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    tr = pd.concat([a, b, c], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """ATR(Average True Range) — Wilder smoothing(RMA) 방식."""
    tr = true_range(high, low, close)
    return wilder_smooth(tr, window)


def atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """ATR% = ATR(window) / 종가 × 100."""
    return atr(high, low, close, window) / close * 100.0


def wilder_smooth(series: pd.Series, window: int) -> pd.Series:
    """Wilder의 지수평활(RMA). RSI/ATR 계산에 공통으로 쓰이는 평활 방식.

    초기값은 첫 window개의 단순평균이며, 이후 항은
    RMA_t = (RMA_(t-1) * (window-1) + value_t) / window 로 갱신한다.
    """
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=series.index)

    # 초기 구간에 NaN이 있으면(예: true_range 첫 행) 그 뒤부터 window개로 초기화.
    first_valid = 0
    while first_valid < n and np.isnan(values[first_valid]):
        first_valid += 1
    start = first_valid + window - 1
    if start >= n:
        return pd.Series(out, index=series.index)

    seed = np.nanmean(values[first_valid:first_valid + window])
    out[start] = seed
    prev = seed
    for i in range(start + 1, n):
        prev = (prev * (window - 1) + values[i]) / window
        out[i] = prev
    return pd.Series(out, index=series.index)


def rsi_wilder(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder 방식 RSI(window). 상승분/하락분을 Wilder smoothing으로 평활한다."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = wilder_smooth(gain, window)
    avg_loss = wilder_smooth(loss, window)

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # 평균 하락분이 0이면(전부 상승) RSI는 100.
    rsi = rsi.where(avg_loss != 0, 100.0)
    # 평균 상승분과 하락분이 모두 계산 불가(NaN)면 그대로 NaN 유지.
    rsi = rsi.where(~(avg_gain.isna() | avg_loss.isna()), np.nan)
    return rsi


@dataclass(frozen=True)
class SwingPoint:
    """스윙 고점/저점 하나."""

    index: int  # 0-based, 데이터프레임 내 위치
    price: float
    kind: str  # "high" 또는 "low"


def find_swing_points(
    high: pd.Series,
    low: pd.Series,
    order: int = 5,
) -> list[SwingPoint]:
    """좌우 ``order``개 봉보다 고가/저가가 더 극단적인 지점을 스윙 고점/저점으로 판단.

    scipy 의존성 없이 단순 국소 극값 탐색으로 구현. 데이터 끝의 ``order``개
    구간은 아직 우측 비교 대상이 확정되지 않았으므로(향후 데이터가 있어야
    "고점이었다"고 확정 가능) 스윙으로 판정하지 않는다 — 룩어헤드 방지.
    """
    n = len(high)
    points: list[SwingPoint] = []
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    for i in range(order, n - order):
        window_h = h[i - order : i + order + 1]
        window_l = l[i - order : i + order + 1]
        if np.isnan(window_h).any() or np.isnan(window_l).any():
            continue
        if h[i] == window_h.max() and h[i] >= window_h[np.argmax(window_h)]:
            # 동일 최댓값이 여러 개면 가장 처음(왼쪽) 것만 인정해 중복 방지.
            if np.argmax(window_h) == order:
                points.append(SwingPoint(index=i, price=float(h[i]), kind="high"))
        if l[i] == window_l.min():
            if np.argmin(window_l) == order:
                points.append(SwingPoint(index=i, price=float(l[i]), kind="low"))
    return points


def recent_pullback_depths(
    high: pd.Series,
    low: pd.Series,
    order: int = 5,
    max_pullbacks: int = 2,
) -> list[float]:
    """가장 최근의 확정된 조정폭(스윙고점→다음스윙저점, % 하락)들을 최신순으로 반환.

    스윙 고점 뒤에 나오는 첫 스윙 저점을 그 고점에 대응하는 조정 저점으로
    삼는다. 신뢰성 있게 판단할 스윙이 2개 미만이면 그만큼만 반환(호출부에서
    개수 부족을 "데이터 부족"으로 처리).
    """
    swings = find_swing_points(high, low, order=order)
    depths: list[float] = []
    i = 0
    while i < len(swings) and len(depths) < max_pullbacks:
        if swings[i].kind == "high":
            # 이 고점 뒤에 나오는 첫 저점을 찾는다.
            for j in range(i + 1, len(swings)):
                if swings[j].kind == "low":
                    peak = swings[i].price
                    trough = swings[j].price
                    if peak > 0:
                        depths.append((peak - trough) / peak * 100.0)
                    i = j
                    break
            else:
                break
        i += 1
    # 최신(가장 최근) 조정이 앞에 오도록 스윙 리스트를 뒤에서부터 훑었어야 하므로 뒤집는다.
    return list(reversed(depths))


def pct_change_over(series: pd.Series, lookback_days: int) -> Optional[float]:
    """가장 최근 값과 ``lookback_days`` 거래일 전 값 사이의 수익률(%)."""
    if len(series) <= lookback_days:
        return None
    end = series.iloc[-1]
    start = series.iloc[-1 - lookback_days]
    if pd.isna(end) or pd.isna(start) or start == 0:
        return None
    return float((end / start - 1.0) * 100.0)


def percentile_rank(values: Sequence[Optional[float]], target: Optional[float]) -> Optional[float]:
    """``target``이 ``values`` 분포에서 차지하는 백분위(0~100, 높을수록 상위).

    None/NaN 값은 모집단에서 제외한다. target이 None이면 계산 불가로 None.
    동률은 해당 값 이하인 표본 비율로 처리(표준적인 percentile-of-score,
    'weak' 방식).
    """
    if target is None or (isinstance(target, float) and np.isnan(target)):
        return None
    clean = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not clean:
        return None
    n = len(clean)
    le_count = sum(1 for v in clean if v <= target)
    return le_count / n * 100.0


def rolling_high_low(
    high: pd.Series, low: pd.Series, window: int = 252
) -> tuple[Optional[float], Optional[float]]:
    """최근 ``window`` 거래일(기본 52주≈252거래일) 구간의 최고가/최저가.

    보유 데이터가 window보다 적으면 있는 만큼만 사용한다(대신 호출부에서
    데이터 충분성을 별도로 검사해야 함 — 이 함수 자체는 부족 여부를
    판정하지 않는다).
    """
    n = len(high)
    if n == 0:
        return None, None
    w = min(window, n)
    return float(high.iloc[-w:].max()), float(low.iloc[-w:].min())


def close_position_in_range(close: float, high: float, low: float) -> Optional[float]:
    """당일 가격 범위에서 종가의 상대 위치. (종가-저가)/(고가-저가), 0~1.

    고가==저가(거래정지 등)이면 0으로 나누지 않도록 None을 반환한다.
    """
    if high == low:
        return None
    return (close - low) / (high - low)
