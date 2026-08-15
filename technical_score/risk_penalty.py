"""위험 감점 — 최종 기술적 매력도에서 차감할 항목들.

동일 위험이 여러 항목에서 중복 감지되더라도(예: 50일선 이격도 초과가
다른 조건과 동시에 발생) 각각 별도로 기록해 사용자가 사유를 모두 확인할
수 있게 한다(스펙 5절 요구사항). 유동성 기준 미달은 "감점"이 아니라
평가 자체를 제외하는 별도 게이트이므로 이 모듈이 아니라 ``scoring``/
``batch``에서 처리한다.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind
from .breakout_signal import PIVOT_LOOKBACK_DAYS, detect_pivot_price

TWENTY_TWO_DAYS = 22
PIVOT_REENTRY_LOOKBACK_DAYS = 10
"""돌파 후 재이탈 감점 판단 시, 최근 며칠 안의 종가를 피벗과 비교할지. 스펙에
구체 수치가 없어 합리적 기본값으로 채택(조정 가능)."""

SHARP_DROP_LOOKBACK_DAYS = 10
SHARP_DROP_THRESHOLD_PCT = -5.0


def _penalty(label: str, triggered: Optional[bool], points: float, reason: Optional[str] = None, value: Any = None) -> dict[str, Any]:
    return {
        "label": label,
        "triggered": triggered,
        "points": points if triggered else 0.0,
        "computable": triggered is not None,
        "reason": reason,
        "value": value,
    }


def penalty_ma50_distance_over_15(close_val: Optional[float], sma50: Optional[float]) -> dict[str, Any]:
    """50일선 이격도 15% 초과: -10점."""
    if close_val is None or sma50 is None or sma50 == 0 or close_val < sma50:
        return _penalty("50일선 이격도 15% 초과", False, -10.0)
    dist = round((close_val / sma50 - 1.0) * 100.0, 8)
    triggered = dist > 15.0
    return _penalty("50일선 이격도 15% 초과", triggered, -10.0, value={"distance_pct": dist})


def penalty_sharp_drop_with_volume(close: pd.Series, volume: pd.Series) -> dict[str, Any]:
    """최근 10일 중, 전일대비 -5% 이상 하락하면서 거래량이 50일 평균 초과한 날이 존재: -10점.

    각 날짜의 "50일 평균 거래량"은 그 날짜까지의 데이터로만 계산해
    미래 데이터를 참조하지 않는다.
    """
    if len(close) < SHARP_DROP_LOOKBACK_DAYS + 1 or len(volume) < 51:
        return _penalty("최근10일 내 급락+거래량 급증", None, -10.0, reason="데이터 부족")

    daily_return = close.pct_change() * 100.0
    avg_vol_50d = volume.rolling(window=50, min_periods=50).mean()

    hits: list[dict[str, Any]] = []
    for i in range(len(close) - SHARP_DROP_LOOKBACK_DAYS, len(close)):
        if i < 1 or pd.isna(daily_return.iloc[i]) or pd.isna(avg_vol_50d.iloc[i]):
            continue
        if daily_return.iloc[i] <= SHARP_DROP_THRESHOLD_PCT and volume.iloc[i] > avg_vol_50d.iloc[i]:
            hits.append(
                {
                    "date": str(close.index[i].date()) if hasattr(close.index[i], "date") else str(close.index[i]),
                    "daily_return_pct": float(daily_return.iloc[i]),
                    "volume": float(volume.iloc[i]),
                    "avg_volume_50d": float(avg_vol_50d.iloc[i]),
                }
            )

    triggered = len(hits) > 0
    return _penalty("최근10일 내 급락+거래량 급증", triggered, -10.0, value={"hits": hits})


def penalty_close_below_ma50(close_val: Optional[float], sma50: Optional[float]) -> dict[str, Any]:
    """종가가 50일선 아래: -15점."""
    if close_val is None or sma50 is None:
        return _penalty("종가 < 50일선", None, -15.0, reason="50일선 계산에 필요한 데이터 부족")
    triggered = close_val < sma50
    return _penalty("종가 < 50일선", triggered, -15.0, value={"close": close_val, "sma50": sma50})


def penalty_ma50_falling(sma50_now: Optional[float], sma50_22d_ago: Optional[float]) -> dict[str, Any]:
    """현재 50일선 < 22거래일 전 50일선(하락 기울기): -10점."""
    if sma50_now is None or sma50_22d_ago is None:
        return _penalty("50일선 하락 기울기", None, -10.0, reason="50일선 계산에 필요한 데이터 부족")
    triggered = sma50_now < sma50_22d_ago
    return _penalty("50일선 하락 기울기", triggered, -10.0, value={"sma50_now": sma50_now, "sma50_22d_ago": sma50_22d_ago})


def penalty_pivot_breakout_failure(close: pd.Series, high: pd.Series) -> dict[str, Any]:
    """피벗 돌파 후 종가가 피벗 아래로 재진입: -10점.

    피벗은 "재이탈 확인 구간(최근 ``PIVOT_REENTRY_LOOKBACK_DAYS``거래일)보다
    이전"의 ``PIVOT_LOOKBACK_DAYS``거래일 데이터로 계산한다. 만약 오늘 기준
    피벗을 그대로 썼다면, 돌파가 재이탈 확인 구간 안(예: 10거래일 이내)에서
    일어난 경우 그 돌파 자체가 피벗 계산에 섞여 기준선이 부풀려지고, 재이탈을
    놓치게 된다 — 그래서 피벗의 기준 구간을 재이탈 확인 구간보다 앞으로
    분리했다.
    """
    reentry_window_start = -(PIVOT_REENTRY_LOOKBACK_DAYS + 1)
    if len(close) < PIVOT_REENTRY_LOOKBACK_DAYS + PIVOT_LOOKBACK_DAYS + 2:
        return _penalty("피벗 돌파 후 재이탈", None, -10.0, reason="피벗 산정에 필요한 데이터 부족")

    pivot_base_high = high.iloc[:reentry_window_start]
    pivot_price = detect_pivot_price(pivot_base_high, lookback=PIVOT_LOOKBACK_DAYS)
    if pivot_price is None:
        return _penalty("피벗 돌파 후 재이탈", None, -10.0, reason="피벗 산정에 필요한 데이터 부족")

    close_val = float(close.iloc[-1])
    recent_window = close.iloc[reentry_window_start:-1]
    had_breakout = bool((recent_window > pivot_price).any())
    reentered_below = close_val < pivot_price
    triggered = had_breakout and reentered_below
    return _penalty(
        "피벗 돌파 후 재이탈",
        triggered,
        -10.0,
        value={"pivot_price": pivot_price, "close": close_val, "had_recent_breakout": had_breakout},
    )


def penalty_atr_expansion(high: pd.Series, low: pd.Series, close: pd.Series) -> dict[str, Any]:
    """최근20일 평균 ATR% > 이전20일 평균 ATR%(변동성 확대): -5점."""
    atr_pct_series = ind.atr_pct(high, low, close, window=14)
    if len(atr_pct_series) < 40:
        return _penalty("최근 변동성 확대(ATR% 증가)", None, -5.0, reason="40거래일 이상의 ATR 데이터 부족")

    recent_20 = float(atr_pct_series.iloc[-20:].mean())
    prior_20 = float(atr_pct_series.iloc[-40:-20].mean())
    if pd.isna(recent_20) or pd.isna(prior_20):
        return _penalty("최근 변동성 확대(ATR% 증가)", None, -5.0, reason="ATR% 계산 불가")

    triggered = bool(recent_20 > prior_20)
    return _penalty(
        "최근 변동성 확대(ATR% 증가)",
        triggered,
        -5.0,
        value={"recent_20d_atr_pct": float(recent_20), "prior_20d_atr_pct": float(prior_20)},
    )


def evaluate_risk_penalty(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    investor_flows: Optional[list] = None,
) -> dict[str, Any]:
    """모든 위험 감점 항목을 평가해 합계(음수 또는 0)와 사유 목록을 반환.

    :param investor_flows: ``investor_flow.fetch_investor_flow``의 결과(선택).
        전달되면 "개인 단독 매수 지속" 경계 신호도 함께 평가한다 — 이 모듈이
        네이버 스크래핑에 직접 의존하지 않도록 호출부에서 미리 가져온 데이터를
        전달받는 방식(계산과 수집의 분리 원칙 유지).
    """
    close_val = float(close.iloc[-1]) if len(close) else None
    sma50 = ind.sma_as_of(close, 50)
    sma50_22d_ago = ind.sma_as_of(close, 50, offset=TWENTY_TWO_DAYS)

    penalties = [
        penalty_ma50_distance_over_15(close_val, sma50),
        penalty_sharp_drop_with_volume(close, volume),
        penalty_close_below_ma50(close_val, sma50),
        penalty_ma50_falling(sma50, sma50_22d_ago),
        penalty_pivot_breakout_failure(close, high),
        penalty_atr_expansion(high, low, close),
    ]
    if investor_flows is not None:
        from .investor_flow import evaluate_individual_dominant_buying

        penalties.append(evaluate_individual_dominant_buying(investor_flows))

    total = sum(p["points"] for p in penalties)
    triggered_reasons = [p["label"] for p in penalties if p["triggered"]]
    return {
        "score": total,
        "reasons": triggered_reasons,
        "details": penalties,
    }
