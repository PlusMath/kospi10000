"""추세 적격성(40점) — Minervini Trend Template의 8개 조건.

각 조건은 독립 함수로 구현하고, ``evaluate_trend_qualification``이 이를
모아 합산 점수/필수조건 충족 여부/상세 내역을 만든다. 결측(계산 불가)과
조건 미충족을 구분하기 위해 각 조건 결과는
``{"met": bool | None, "points": float, "computable": bool, "reason": str | None}``
형태를 따른다 — met이 None이면 데이터 부족으로 판정 불가(0점, 사유 기록).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind

POINTS_PER_CONDITION = 5.0
MAX_SCORE = 40.0
QUALIFIED_THRESHOLD = 35.0
"""35점 이상이면 '우수'로 분류."""

TWENTY_TWO_DAYS = 22
FIFTY_TWO_WEEK_WINDOW = 252


def _condition(
    label: str, met: Optional[bool], value: Any = None, reason: Optional[str] = None
) -> dict[str, Any]:
    computable = met is not None
    points = POINTS_PER_CONDITION if met else 0.0
    return {
        "label": label,
        "met": met,
        "value": value,
        "points": points if computable else 0.0,
        "max_points": POINTS_PER_CONDITION,
        "computable": computable,
        "reason": reason,
    }


def cond_close_above_150_200ma(
    close_val: Optional[float], sma150: Optional[float], sma200: Optional[float]
) -> dict[str, Any]:
    """1) 종가 > 150일선이고 종가 > 200일선."""
    if close_val is None or sma150 is None or sma200 is None:
        return _condition("종가 > 150일선 & 종가 > 200일선", None, reason="150일/200일선 계산에 필요한 데이터 부족")
    met = close_val > sma150 and close_val > sma200
    return _condition(
        "종가 > 150일선 & 종가 > 200일선", met, value={"close": close_val, "sma150": sma150, "sma200": sma200}
    )


def cond_150_above_200ma(sma150: Optional[float], sma200: Optional[float]) -> dict[str, Any]:
    """2) 150일선 > 200일선."""
    if sma150 is None or sma200 is None:
        return _condition("150일선 > 200일선", None, reason="150일/200일선 계산에 필요한 데이터 부족")
    return _condition("150일선 > 200일선", sma150 > sma200, value={"sma150": sma150, "sma200": sma200})


def cond_200ma_rising(sma200_now: Optional[float], sma200_22d_ago: Optional[float]) -> dict[str, Any]:
    """3) 현재 200일선 > 22거래일 전 200일선(상승 기울기)."""
    if sma200_now is None or sma200_22d_ago is None:
        return _condition(
            "200일선 상승(22거래일 전 대비)", None, reason="200일선 또는 22거래일 전 200일선 계산에 필요한 데이터 부족"
        )
    return _condition(
        "200일선 상승(22거래일 전 대비)",
        sma200_now > sma200_22d_ago,
        value={"sma200_now": sma200_now, "sma200_22d_ago": sma200_22d_ago},
    )


def cond_50ma_above_150_200(
    sma50: Optional[float], sma150: Optional[float], sma200: Optional[float]
) -> dict[str, Any]:
    """4) 50일선 > 150일선이고 50일선 > 200일선."""
    if sma50 is None or sma150 is None or sma200 is None:
        return _condition("50일선 > 150일선 & 50일선 > 200일선", None, reason="50/150/200일선 계산에 필요한 데이터 부족")
    met = sma50 > sma150 and sma50 > sma200
    return _condition(
        "50일선 > 150일선 & 50일선 > 200일선", met, value={"sma50": sma50, "sma150": sma150, "sma200": sma200}
    )


def cond_close_above_50ma(close_val: Optional[float], sma50: Optional[float]) -> dict[str, Any]:
    """5) 종가 > 50일선."""
    if close_val is None or sma50 is None:
        return _condition("종가 > 50일선", None, reason="50일선 계산에 필요한 데이터 부족")
    return _condition("종가 > 50일선", close_val > sma50, value={"close": close_val, "sma50": sma50})


def cond_above_52w_low_125pct(close_val: Optional[float], low_52w: Optional[float]) -> dict[str, Any]:
    """6) 종가 >= 52주 저가 × 1.25."""
    if close_val is None or low_52w is None:
        return _condition("52주 저가 대비 25%+ 상승", None, reason="52주 저가 계산에 필요한 데이터 부족")
    threshold = low_52w * 1.25
    return _condition(
        "52주 저가 대비 25%+ 상승",
        close_val >= threshold,
        value={"close": close_val, "low_52w": low_52w, "threshold": threshold},
    )


def cond_above_52w_high_75pct(close_val: Optional[float], high_52w: Optional[float]) -> dict[str, Any]:
    """7) 종가 >= 52주 고가 × 0.75."""
    if close_val is None or high_52w is None:
        return _condition("52주 고가 대비 25% 이내", None, reason="52주 고가 계산에 필요한 데이터 부족")
    threshold = high_52w * 0.75
    return _condition(
        "52주 고가 대비 25% 이내",
        close_val >= threshold,
        value={"close": close_val, "high_52w": high_52w, "threshold": threshold},
    )


def cond_relative_strength_52w_top30(percentile: Optional[float]) -> dict[str, Any]:
    """8) 52주 시장 상대수익률이 전체(평가 배치) 종목 상위 30%.

    percentile은 0~100(높을수록 상위) 척도로, 배치 단위 사전 계산 결과를
    ``batch.py``에서 전달받는다(단일 종목만으로는 계산 불가).
    """
    if percentile is None:
        return _condition("52주 상대수익률 상위 30%", None, reason="배치 백분위 계산 불가(비교 대상 종목 부족 등)")
    met = percentile >= 70.0  # 상위 30% == 백분위 70 이상
    return _condition("52주 상대수익률 상위 30%", met, value={"percentile": percentile})


def evaluate_trend_qualification(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    relative_strength_52w_percentile: Optional[float],
) -> dict[str, Any]:
    """8개 조건을 모두 평가해 추세 적격성 점수(0~40)와 상세 내역을 반환.

    :param close/high/low: 시간순 정렬된 종가/고가/저가 시리즈(수정주가 기준).
    :param relative_strength_52w_percentile: 배치 내 52주 상대수익률 백분위(0~100).
    """
    close_val = float(close.iloc[-1]) if len(close) else None
    sma50 = ind.sma_as_of(close, 50)
    sma150 = ind.sma_as_of(close, 150)
    sma200 = ind.sma_as_of(close, 200)
    sma200_22d_ago = ind.sma_as_of(close, 200, offset=TWENTY_TWO_DAYS)
    high_52w, low_52w = ind.rolling_high_low(high, low, window=FIFTY_TWO_WEEK_WINDOW)

    conditions = [
        cond_close_above_150_200ma(close_val, sma150, sma200),
        cond_150_above_200ma(sma150, sma200),
        cond_200ma_rising(sma200, sma200_22d_ago),
        cond_50ma_above_150_200(sma50, sma150, sma200),
        cond_close_above_50ma(close_val, sma50),
        cond_above_52w_low_125pct(close_val, low_52w),
        cond_above_52w_high_75pct(close_val, high_52w),
        cond_relative_strength_52w_top30(relative_strength_52w_percentile),
    ]
    score = sum(c["points"] for c in conditions)

    mandatory_close_above_200 = close_val is not None and sma200 is not None and close_val > sma200
    mandatory_50_above_200 = sma50 is not None and sma200 is not None and sma50 > sma200
    mandatory_200_rising = sma200 is not None and sma200_22d_ago is not None and sma200 > sma200_22d_ago
    mandatory_computable = None not in (close_val, sma50, sma200, sma200_22d_ago)
    mandatory_all_met = mandatory_computable and mandatory_close_above_200 and mandatory_50_above_200 and mandatory_200_rising

    return {
        "score": score,
        "max_score": MAX_SCORE,
        "qualified": score >= QUALIFIED_THRESHOLD,
        "mandatory_conditions_met": mandatory_all_met if mandatory_computable else None,
        "mandatory_details": {
            "close_above_200ma": mandatory_close_above_200 if mandatory_computable else None,
            "ma50_above_ma200": mandatory_50_above_200 if mandatory_computable else None,
            "ma200_rising": mandatory_200_rising if mandatory_computable else None,
        },
        "details": conditions,
        "warning": None if (mandatory_all_met or not mandatory_computable) else "추세 부적격",
    }
