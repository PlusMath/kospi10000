"""진입 타이밍 매력도(60점) — "지금이 눌림목 매수 타점인가"를 가리는 6개 하위 항목.

2026-09-07 개편: 미너비니 SEPA/VCP 진입 타이밍 기준(52주 고점 접근도 등)을 눌림목매매
기준으로 교체. 지지선(임펄스 시작가) 가까이 붙어 있고, 되돌림이 20~35%의
"이상적" 구간이며, 조정 중 거래량이 임펄스 구간 대비 충분히 줄었고, RSI가 눌린
구간에서 반등을 시작하는 게 핵심 신호다. 변동성 축소 로직(4-4였던 항목)은 눌림목에도
그대로 유효해 옛 구조를 거의 그대로 재사용한다.

각 하위 점수는 독립 함수로 구현하며, ``setup_qualification``이 계산한 임펄스/지지선을
그대로 받아 쓴다(임펄스 탐지 로직을 이중으로 두지 않기 위함). 스펙에 정확한 수치가
없는 부분은 이 모듈 상단 상수로 명시적으로 드러내 두었다(호출부에서 조정 가능).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind
from .setup_qualification import RETRACE_MAX_PCT, RETRACE_MIN_PCT, support_level

MAX_SCORE = 60.0


def _bucket(
    label: str, value: Optional[float], score: float, max_score: float, band: str, reason: Optional[str] = None
) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "score": score,
        "max_score": max_score,
        "band": band,
        "computable": value is not None,
        "reason": reason,
    }


# ── 1. 지지선 이격도(12점) ───────────────────────────────────────────────
def score_support_distance(close_val: Optional[float], support: Optional[float]) -> dict[str, Any]:
    """이격도 = (종가/지지선 - 1) × 100. 지지선에 가까울수록(0~3%) 만점."""
    if close_val is None or support is None or support == 0:
        return _bucket("지지선 이격도", None, 0.0, 12.0, "N/A", reason="지지선 계산에 필요한 데이터 부족")
    if close_val < support:
        return _bucket("지지선 이격도", None, 0.0, 12.0, "종가 < 지지선")

    dist = round((close_val / support - 1.0) * 100.0, 8)
    if dist < 3.0:
        score, band = 12.0, "0%~3% 미만"
    elif dist < 6.0:
        score, band = 10.0, "3%~6% 미만"
    elif dist < 10.0:
        score, band = 6.0, "6%~10% 미만"
    elif dist <= 15.0:
        score, band = 3.0, "10%~15%"
    else:
        score, band = 0.0, "15% 초과"
    return _bucket("지지선 이격도", dist, score, 12.0, band)


# ── 2. 되돌림 위치(8점) ──────────────────────────────────────────────────
def score_retrace_position(impulse: Optional[dict], close_val: Optional[float]) -> dict[str, Any]:
    """되돌림이 20~35%면 이상적(만점) — 셋업 적격성(10~61.8%) 안에서 더 세밀하게 채점.

    2026-09-07 실측 조정: 코스피 대형주 실측 결과(설정 적격성 RETRACE_MIN_PCT 주석 참고)에
    맞춰 "이상적" 구간을 서구식 피보나치(38.2~50%)에서 20~35%로 하향 조정.
    """
    if impulse is None or close_val is None or impulse["peak_price"] <= 0:
        return _bucket("되돌림 위치", None, 0.0, 8.0, "N/A", reason="임펄스 또는 현재가 계산 불가")
    retrace_pct = round((impulse["peak_price"] - close_val) / impulse["peak_price"] * 100.0, 8)
    if 20.0 <= retrace_pct <= 35.0:
        score, band = 8.0, "20%~35%(이상적)"
    elif RETRACE_MIN_PCT <= retrace_pct < 20.0 or 35.0 < retrace_pct <= 45.0:
        score, band = 5.0, "10%~20% 또는 35%~45%"
    elif 45.0 < retrace_pct <= RETRACE_MAX_PCT:
        score, band = 2.0, "45%~61.8%"
    else:
        score, band = 0.0, "10~61.8% 범위 밖"
    return _bucket("되돌림 위치", retrace_pct, score, 8.0, band)


# ── 3. 조정중 거래량 감소(12점) ──────────────────────────────────────────
def score_volume_dry_up_vs_impulse(impulse: Optional[dict], volume: pd.Series) -> dict[str, Any]:
    """조정 구간(임펄스 고점 이후~현재) 평균거래량 / 임펄스 구간 평균거래량 × 100.

    낮을수록(매도세 소진) 좋음.
    """
    if impulse is None:
        return _bucket("조정중 거래량 감소", None, 0.0, 12.0, "N/A", reason="임펄스를 찾지 못해 계산 불가")
    peak_idx = impulse["peak_index"]
    pullback_vol_series = volume.iloc[peak_idx + 1 :]
    if len(pullback_vol_series) == 0:
        return _bucket("조정중 거래량 감소", None, 0.0, 12.0, "N/A", reason="임펄스 고점 이후 거래일 없음")
    impulse_vol = float(volume.iloc[impulse["start_index"] : peak_idx + 1].mean())
    pullback_vol = float(pullback_vol_series.mean())
    if impulse_vol <= 0 or pd.isna(impulse_vol) or pd.isna(pullback_vol):
        return _bucket("조정중 거래량 감소", None, 0.0, 12.0, "N/A", reason="거래량 데이터 결측 또는 0")

    ratio = round(pullback_vol / impulse_vol * 100.0, 8)
    if ratio <= 40.0:
        score, band = 12.0, "40% 이하"
    elif ratio <= 60.0:
        score, band = 10.0, "40% 초과~60% 이하"
    elif ratio <= 80.0:
        score, band = 7.0, "60% 초과~80% 이하"
    elif ratio <= 100.0:
        score, band = 3.0, "80% 초과~100% 이하"
    else:
        score, band = 0.0, "100% 초과"
    return _bucket("조정중 거래량 감소", ratio, score, 12.0, band)


# ── 4. 변동성 축소(10점 = 4+3+3) ─────────────────────────────────────────
def score_volatility_contraction(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_order: int = 5
) -> dict[str, Any]:
    """세 가지 축소 신호: ATR% 20일 추세(4점), ATR% 10일 추세(3점), 조정폭 축소(3점).

    눌림목에서도 "조정이 통제되고 있는가"는 동일하게 유효한 긍정 신호라 옛 로직을
    그대로 재사용한다(배점만 40→60점 체계에 맞게 재조정: 4+4+4=12 → 4+3+3=10).
    """
    atr_pct_series = ind.atr_pct(high, low, close, window=14)

    recent_20 = float(atr_pct_series.iloc[-20:].mean()) if len(atr_pct_series) >= 20 else None
    prior_20 = float(atr_pct_series.iloc[-40:-20].mean()) if len(atr_pct_series) >= 40 else None
    recent_10 = float(atr_pct_series.iloc[-10:].mean()) if len(atr_pct_series) >= 10 else None

    recent_20 = None if recent_20 is not None and pd.isna(recent_20) else recent_20
    prior_20 = None if prior_20 is not None and pd.isna(prior_20) else prior_20
    recent_10 = None if recent_10 is not None and pd.isna(recent_10) else recent_10

    sub_conditions: list[dict[str, Any]] = []

    if recent_20 is not None and prior_20 is not None:
        met = recent_20 < prior_20
        sub_conditions.append(
            {
                "label": "최근20일 평균 ATR% < 이전20일 평균 ATR%",
                "met": met,
                "points": 4.0 if met else 0.0,
                "computable": True,
                "reason": None,
                "value": {"recent_20d_atr_pct": float(recent_20), "prior_20d_atr_pct": float(prior_20)},
            }
        )
    else:
        sub_conditions.append(
            {
                "label": "최근20일 평균 ATR% < 이전20일 평균 ATR%",
                "met": None,
                "points": 0.0,
                "computable": False,
                "reason": "40거래일 이상의 ATR 데이터 부족",
                "value": None,
            }
        )

    if recent_10 is not None and recent_20 is not None:
        met = recent_10 < recent_20
        sub_conditions.append(
            {
                "label": "최근10일 평균 ATR% < 최근20일 평균 ATR%",
                "met": met,
                "points": 3.0 if met else 0.0,
                "computable": True,
                "reason": None,
                "value": {"recent_10d_atr_pct": float(recent_10), "recent_20d_atr_pct": float(recent_20)},
            }
        )
    else:
        sub_conditions.append(
            {
                "label": "최근10일 평균 ATR% < 최근20일 평균 ATR%",
                "met": None,
                "points": 0.0,
                "computable": False,
                "reason": "20거래일 이상의 ATR 데이터 부족",
                "value": None,
            }
        )

    depths = ind.recent_pullback_depths(high, low, order=swing_order, max_pullbacks=2)
    if len(depths) >= 2:
        recent_pullback, prior_pullback = depths[0], depths[1]
        met = recent_pullback < prior_pullback
        sub_conditions.append(
            {
                "label": "최근 조정폭 < 직전 조정폭",
                "met": met,
                "points": 3.0 if met else 0.0,
                "computable": True,
                "reason": None,
                "value": {"recent_pullback_pct": recent_pullback, "prior_pullback_pct": prior_pullback},
            }
        )
    else:
        sub_conditions.append(
            {
                "label": "최근 조정폭 < 직전 조정폭",
                "met": None,
                "points": 0.0,
                "computable": False,
                "reason": "신뢰 가능한 스윙 고점/저점을 2쌍 이상 찾지 못함(데이터 부족)",
                "value": None,
            }
        )

    score = sum(c["points"] for c in sub_conditions)
    return {
        "label": "변동성 축소",
        "score": score,
        "max_score": 10.0,
        "sub_conditions": sub_conditions,
    }


# ── 5. RSI 반등(10점) ────────────────────────────────────────────────────
def _rsi_pullback_base_score(rsi_now: float) -> tuple[float, str]:
    if 35.0 <= rsi_now < 45.0:
        return 10.0, "35~45 미만(반등 초입, 이상적)"
    if 30.0 <= rsi_now < 35.0:
        return 8.0, "30~35 미만(깊게 눌림, 반등 미확인)"
    if 45.0 <= rsi_now < 55.0:
        return 6.0, "45~55 미만(반등 진행 중)"
    if 55.0 <= rsi_now < 65.0:
        return 3.0, "55~65 미만(반등 많이 진행, 매력 감소)"
    if rsi_now < 30.0:
        return 1.0, "30 미만(과매도, 반등 미확인)"
    return 1.0, "65 이상(이미 임펄스 재개 수준, 눌림목 기회 지남)"


def score_rsi_pullback_rebound(rsi_series: pd.Series) -> dict[str, Any]:
    """RSI(14) 구간 기본점수 + 반등 확인 보정(합산 후 0~10 클램프).

    SEPA 버전(55~65 만점, 추세 지속형 모멘텀)과 반대로, 눌림목은 눌린 RSI가 저점을
    찍고 돌아서는 구간(35~45)이 이상적이다.
    """
    if len(rsi_series) < 1 or pd.isna(rsi_series.iloc[-1]):
        return _bucket("RSI 반등", None, 0.0, 10.0, "N/A", reason="RSI 계산에 필요한 데이터 부족")

    rsi_now = float(rsi_series.iloc[-1])
    base_score, band = _rsi_pullback_base_score(rsi_now)

    adjustments: list[dict[str, Any]] = []
    total = base_score

    rsi_prev = None
    if len(rsi_series) > 1 and not pd.isna(rsi_series.iloc[-2]):
        rsi_prev = float(rsi_series.iloc[-2])

    if rsi_prev is not None and 30.0 <= rsi_now <= 55.0 and rsi_now > rsi_prev:
        adjustments.append({"label": "30~55 구간에서 전일 대비 상승(반등 확인)", "delta": 1.0})
        total += 1.0
    if rsi_prev is not None and 30.0 <= rsi_now <= 55.0 and rsi_now < rsi_prev:
        adjustments.append({"label": "30~55 구간에서 전일 대비 추가 하락(반등 미확인)", "delta": -1.0})
        total -= 1.0

    total_clamped = max(0.0, min(10.0, total))
    return {
        "label": "RSI 반등",
        "value": rsi_now,
        "base_score": base_score,
        "base_band": band,
        "adjustments": adjustments,
        "score": total_clamped,
        "max_score": 10.0,
        "computable": True,
    }


# ── 6. 반전 캔들 신호(8점) ───────────────────────────────────────────────
def score_reversal_candle(close: pd.Series, high: pd.Series, low: pd.Series) -> dict[str, Any]:
    """당일 종가가 당일 저~고가 범위에서 어디 위치하는지(0~1, 높을수록 고가 근접)로
    "하락 소진형" 마감을 근사한다.

    실제 캔들패턴(도지/망치형 등) 식별기가 아니라 단순 근사치임을 명시해둔다 — 정교한
    패턴 인식을 하는 척 하지 않고, 계산 가능한 값(당일 종가 위치)만으로 정직하게
    점수를 매긴다.
    """
    if len(close) < 1 or len(high) < 1 or len(low) < 1:
        return _bucket("반전 캔들 신호", None, 0.0, 8.0, "N/A", reason="당일 OHLC 데이터 부족")
    position = ind.close_position_in_range(float(close.iloc[-1]), float(high.iloc[-1]), float(low.iloc[-1]))
    if position is None:
        return _bucket("반전 캔들 신호", None, 0.0, 8.0, "N/A", reason="당일 고가==저가(거래정지 등)")

    if position >= 0.7:
        score, band = 8.0, "종가가 당일 고가 근접(0.7 이상)"
    elif position >= 0.5:
        score, band = 5.0, "종가가 당일 범위 상단(0.5~0.7)"
    elif position >= 0.3:
        score, band = 2.0, "종가가 당일 범위 중하단(0.3~0.5)"
    else:
        score, band = 0.0, "종가가 당일 저가 근접(0.3 미만)"
    return _bucket("반전 캔들 신호", position, score, 8.0, band)


def evaluate_entry_desirability(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    impulse: Optional[dict],
) -> dict[str, Any]:
    """6개 하위 항목을 모두 평가해 진입 타이밍 매력도(0~60)와 상세 내역을 반환.

    :param impulse: ``setup_qualification``에서 이미 계산한 임펄스(중복 탐지 방지).
    """
    close_val = float(close.iloc[-1]) if len(close) else None
    support = support_level(impulse["start_price"] if impulse else None)
    rsi_series = ind.rsi_wilder(close, 14)

    support_distance = score_support_distance(close_val, support)
    retrace_position = score_retrace_position(impulse, close_val)
    volume_dry_up = score_volume_dry_up_vs_impulse(impulse, volume)
    volatility_contraction = score_volatility_contraction(high, low, close)
    rsi = score_rsi_pullback_rebound(rsi_series)
    reversal_candle = score_reversal_candle(close, high, low)

    total = (
        support_distance["score"]
        + retrace_position["score"]
        + volume_dry_up["score"]
        + volatility_contraction["score"]
        + rsi["score"]
        + reversal_candle["score"]
    )

    return {
        "score": total,
        "max_score": MAX_SCORE,
        "support_distance": support_distance,
        "retrace_position": retrace_position,
        "volume_dry_up": volume_dry_up,
        "volatility_contraction": volatility_contraction,
        "rsi": rsi,
        "reversal_candle": reversal_candle,
    }
