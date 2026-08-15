"""돌파 신호(별도 10점, 기술적 매력도 100점에는 포함하지 않음).

피벗(박스권 상단) 가격은 "오늘을 제외한 최근 ``PIVOT_LOOKBACK_DAYS``거래일의
최고가"로 자동 탐지한다 — 오늘 데이터를 피벗 산정에 포함하면 스스로를
기준으로 돌파를 판정하는 순환 논리(및 룩어헤드 성격의 왜곡)가 되므로 제외.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind

MAX_SCORE = 10.0
PIVOT_LOOKBACK_DAYS = 20
PIVOT_METHOD_DESC = f"최근 {PIVOT_LOOKBACK_DAYS}거래일(당일 제외) 최고가를 박스권 상단(피벗)으로 사용"
BREAKOUT_VOLUME_MULTIPLE = 1.5
CLOSE_POSITION_THRESHOLD = 0.70


def detect_pivot_price(high: pd.Series, lookback: int = PIVOT_LOOKBACK_DAYS) -> Optional[float]:
    """오늘을 제외한 최근 ``lookback``거래일 최고가를 피벗(저항선)으로 반환."""
    if len(high) <= lookback:
        return None
    window = high.iloc[-(lookback + 1) : -1]
    if window.isna().all():
        return None
    return float(window.max())


def evaluate_breakout_signal(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    pivot_lookback: int = PIVOT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """돌파 신호 3개 항목(4/4/2점)을 평가."""
    details: list[dict[str, Any]] = []

    if len(close) < 1 or len(volume) < 50:
        return {
            "score": 0.0,
            "max_score": MAX_SCORE,
            "pivot_price": None,
            "pivot_method": PIVOT_METHOD_DESC,
            "pivot_lookback_days": pivot_lookback,
            "details": [
                {"label": "박스권/피벗 돌파", "met": None, "points": 0.0, "computable": False, "reason": "데이터 부족"}
            ],
        }

    close_val = float(close.iloc[-1])
    high_val = float(high.iloc[-1])
    low_val = float(low.iloc[-1])
    volume_val = float(volume.iloc[-1])

    pivot_price = detect_pivot_price(high, lookback=pivot_lookback)
    if pivot_price is None:
        details.append(
            {"label": "박스권/피벗 돌파", "met": None, "points": 0.0, "computable": False, "reason": f"피벗 산정에 필요한 {pivot_lookback}거래일 데이터 부족"}
        )
        broke_out = False
    else:
        broke_out = close_val > pivot_price
        details.append(
            {
                "label": "박스권/피벗 돌파",
                "met": broke_out,
                "points": 4.0 if broke_out else 0.0,
                "computable": True,
                "reason": None,
                "value": {"close": close_val, "pivot_price": pivot_price},
            }
        )

    avg_vol_50d = float(volume.iloc[-50:].mean())
    vol_met = avg_vol_50d > 0 and volume_val >= avg_vol_50d * BREAKOUT_VOLUME_MULTIPLE
    details.append(
        {
            "label": f"돌파일 거래량 >= 50일 평균의 {int(BREAKOUT_VOLUME_MULTIPLE * 100)}%",
            "met": vol_met if avg_vol_50d > 0 else None,
            "points": 4.0 if vol_met else 0.0,
            "computable": avg_vol_50d > 0,
            "reason": None if avg_vol_50d > 0 else "50일 평균거래량 계산 불가",
            "value": {"volume": volume_val, "avg_volume_50d": avg_vol_50d},
        }
    )

    close_pos = ind.close_position_in_range(close_val, high_val, low_val)
    if close_pos is None:
        details.append(
            {
                "label": "당일 종가 위치 상단 30% 이내",
                "met": None,
                "points": 0.0,
                "computable": False,
                "reason": "당일 고가=저가(거래정지 등)로 계산 불가",
            }
        )
        pos_met = False
    else:
        pos_met = close_pos >= CLOSE_POSITION_THRESHOLD
        details.append(
            {
                "label": "당일 종가 위치 상단 30% 이내",
                "met": pos_met,
                "points": 2.0 if pos_met else 0.0,
                "computable": True,
                "reason": None,
                "value": {"close_position": close_pos},
            }
        )

    score = sum(d["points"] for d in details)
    return {
        "score": score,
        "max_score": MAX_SCORE,
        "pivot_price": pivot_price,
        "pivot_method": PIVOT_METHOD_DESC,
        "pivot_lookback_days": pivot_lookback,
        "breakout_today": broke_out,
        "details": details,
    }
