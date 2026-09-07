"""위험 감점 — 최종 기술적 매력도에서 차감할 항목들.

2026-09-07 개편: 눌림목매매 기준으로 교체하며 SEPA 전용 감점(50일선 이격도 15%
초과, 피벗 돌파 후 재이탈)은 폐기했다 — 눌림목에서는 지지선에 "가까움"이 오히려
핵심 긍정 신호(entry_desirability의 지지선 이격도)라 이격도 자체를 감점 대상으로
두는 게 모순이고, 피벗 돌파 개념도 SEPA 특유의 것이라 그대로 가져올 이유가 없다.
대신 "지지선 이탈"은 눌림목 실패(=추세 전환 확정) 신호라 SEPA 시절(-15)보다 감점
폭을 키웠다(-20).

동일한 위험이 여러 항목에서 중복 감지되더라도 각각 별도로 기록해 사용자가 사유를
모두 확인할 수 있게 한다. 유동성 기준 미달은 "감점"이 아니라 평가 자체를 제외하는
별도 게이트이므로 이 모듈이 아니라 ``scoring``/``batch``에서 처리한다.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind
from .setup_qualification import support_level

TWENTY_TWO_DAYS = 22
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


def penalty_close_below_support(close_val: Optional[float], support: Optional[float]) -> dict[str, Any]:
    """종가가 지지선(임펄스 시작가) 아래: -20점.

    눌림목 셋업이 실패했다(=조정이 아니라 추세 전환)는 확정적 신호라 SEPA 시절
    (종가<50일선, -15)보다 감점 폭을 키웠다.
    """
    if close_val is None or support is None:
        return _penalty("종가 < 지지선", None, -20.0, reason="지지선 계산에 필요한 데이터 부족")
    triggered = close_val < support
    return _penalty("종가 < 지지선", triggered, -20.0, value={"close": close_val, "support": support})


def penalty_sharp_drop_with_volume(close: pd.Series, volume: pd.Series) -> dict[str, Any]:
    """최근 10일 중, 전일대비 -5% 이상 하락하면서 거래량이 50일 평균 초과한 날이 존재: -10점.

    조정이 "매도 패닉"이 아니라 정상적인 눌림목이어야 하므로 그대로 유지.
    각 날짜의 "50일 평균 거래량"은 그 날짜까지의 데이터로만 계산해 미래 데이터를
    참조하지 않는다.
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


def penalty_support_ma_falling(sma60_now: Optional[float], sma60_22d_ago: Optional[float]) -> dict[str, Any]:
    """현재 60일선 < 22거래일 전 60일선(하락 기울기): -10점.

    60일선 자체가 지지선은 아니지만(지지선=임펄스 시작가, support_level 참고), 60일선이
    하락 중이면 눌림목이 아니라 더 넓은 하락추세일 가능성이 높다는 별도의 추세 건강도
    신호로 계속 쓴다(SEPA 시절 50일선 기울기 감점을 60일선 기준으로 교체).
    """
    if sma60_now is None or sma60_22d_ago is None:
        return _penalty("60일선 하락 기울기", None, -10.0, reason="60일선 계산에 필요한 데이터 부족")
    triggered = sma60_now < sma60_22d_ago
    return _penalty(
        "60일선 하락 기울기", triggered, -10.0,
        value={"sma60_now": sma60_now, "sma60_22d_ago": sma60_22d_ago},
    )


def penalty_atr_expansion(high: pd.Series, low: pd.Series, close: pd.Series) -> dict[str, Any]:
    """최근20일 평균 ATR% > 이전20일 평균 ATR%(변동성 확대): -5점.

    조정이 통제되지 않고 확산되는 중이면(패닉성) 눌림목 매수에 위험하므로 그대로 유지.
    """
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
    impulse: Optional[dict] = None,
    investor_flows: Optional[list] = None,
) -> dict[str, Any]:
    """모든 위험 감점 항목을 평가해 합계(음수 또는 0)와 사유 목록을 반환.

    :param impulse: ``setup_qualification``에서 이미 계산한 임펄스(중복 탐지 방지).
    :param investor_flows: ``investor_flow.fetch_investor_flow``의 결과(선택).
        전달되면 "개인 단독 매수 지속" 경계 신호도 함께 평가한다.
    """
    close_val = float(close.iloc[-1]) if len(close) else None
    sma60 = ind.sma_as_of(close, 60)
    sma60_22d_ago = ind.sma_as_of(close, 60, offset=TWENTY_TWO_DAYS)
    support = support_level(impulse["start_price"] if impulse else None)

    penalties = [
        penalty_close_below_support(close_val, support),
        penalty_sharp_drop_with_volume(close, volume),
        penalty_support_ma_falling(sma60, sma60_22d_ago),
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
