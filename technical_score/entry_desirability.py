"""진입 매력도(60점) — 7개 하위 항목.

각 하위 점수는 독립 함수로 구현하며, 구간 경계는 스펙에 명시된 값을 그대로
사용한다(겹치거나 비는 구간이 없도록 부등호 방향에 주의). 스펙에 정확한
수치가 없는 두 가지 "품질 저하 방지" 규칙은 이 모듈 상단 상수로 명시적으로
드러내 두었다(호출부에서 조정 가능):

- ``PRICE_TIGHTNESS_MIN_VOLUME_RATIO``: 가격 밀집도가 좋아 보여도 거래량이
  비정상적으로 말라붙어(거래정지성) 좁아진 경우 긍정 평가하지 않기 위한 기준.
- ``VOLUME_DRYUP_MAX_DECLINE_PCT``: 거래량 고갈이 급락 동반이면 긍정 평가하지
  않기 위한 최근 10일 하락률 기준.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind

MAX_SCORE = 60.0

PRICE_TIGHTNESS_MIN_VOLUME_RATIO = 0.20
"""최근 10일 평균거래량이 50일 평균거래량의 이 비율 미만이면 '거래정지성 밀집'으로
간주하고 가격 밀집도 점수를 0으로 처리(사유 기록). 근거: 스펙 4-4 "거래정지나
거래량 부족 때문에 범위가 좁아진 종목은 긍정적으로 평가하지 않는다" — 구체적
수치가 스펙에 없어 합리적 기본값으로 채택, 조정 가능."""

VOLUME_DRYUP_MAX_DECLINE_PCT = -8.0
"""최근 10거래일 수익률이 이보다 낮으면(급락 동반) 거래량 고갈을 긍정 평가하지
않음. 근거: 스펙 4-5 "가격 급락이 동반되면 높은 점수를 부여하지 않는다" —
구체적 수치가 스펙에 없어 합리적 기본값으로 채택, 조정 가능."""


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


# ── 4-1. 50일선 이격도(8점) ──────────────────────────────────────────────
def score_ma50_distance(close_val: Optional[float], sma50: Optional[float]) -> dict[str, Any]:
    """이격도 = (종가/50일선 - 1) × 100."""
    if close_val is None or sma50 is None or sma50 == 0:
        return _bucket("50일선 이격도", None, 0.0, 8.0, "N/A", reason="50일선 계산에 필요한 데이터 부족")
    if close_val < sma50:
        return _bucket("50일선 이격도", None, 0.0, 8.0, "종가 < 50일선")

    # round(): 부동소수점 오차로 정확히 경계값(예: 3.0000000001)에 걸리는 걸 방지.
    dist = round((close_val / sma50 - 1.0) * 100.0, 8)
    if dist < 3.0:
        score, band = 8.0, "0%~3% 미만"
    elif dist < 6.0:
        score, band = 7.0, "3%~6% 미만"
    elif dist < 10.0:
        score, band = 4.0, "6%~10% 미만"
    elif dist <= 15.0:
        score, band = 2.0, "10%~15%"
    else:
        score, band = 0.0, "15% 초과"
    return _bucket("50일선 이격도", dist, score, 8.0, band)


# ── 4-2. 52주 고점 접근도(8점) ───────────────────────────────────────────
def score_high_52w_distance(close_val: Optional[float], high_52w: Optional[float]) -> dict[str, Any]:
    """고점 대비 하락률 = (1 - 종가/52주고가) × 100."""
    if close_val is None or high_52w is None or high_52w == 0:
        return _bucket("52주 고점 접근도", None, 0.0, 8.0, "N/A", reason="52주 고가 계산에 필요한 데이터 부족")

    drawdown = round((1.0 - close_val / high_52w) * 100.0, 8)
    if drawdown < 0.0:
        # 52주 고가 갱신 당일 등 이론상 0% 미만(신고가)은 0~5% 구간과 동일하게 취급.
        drawdown = max(drawdown, 0.0)
    if drawdown < 5.0:
        score, band = 7.0, "0%~5% 미만"
    elif drawdown < 10.0:
        score, band = 8.0, "5%~10% 미만"
    elif drawdown < 15.0:
        score, band = 6.0, "10%~15% 미만"
    elif drawdown < 20.0:
        score, band = 3.0, "15%~20% 미만"
    elif drawdown <= 25.0:
        score, band = 1.0, "20%~25%"
    else:
        score, band = 0.0, "25% 초과"
    return _bucket("52주 고점 접근도", drawdown, score, 8.0, band)


# ── 4-3. 변동성 축소(12점 = 4점 × 3) ─────────────────────────────────────
def score_volatility_contraction(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_order: int = 5
) -> dict[str, Any]:
    """세 가지 축소 신호(각 4점): ATR% 20일 추세, ATR% 10일 추세, 조정폭 축소."""
    atr_pct_series = ind.atr_pct(high, low, close, window=14)

    recent_20 = float(atr_pct_series.iloc[-20:].mean()) if len(atr_pct_series) >= 20 else None
    prior_20 = (
        float(atr_pct_series.iloc[-40:-20].mean()) if len(atr_pct_series) >= 40 else None
    )
    recent_10 = float(atr_pct_series.iloc[-10:].mean()) if len(atr_pct_series) >= 10 else None

    # float() 변환 후에도 NaN은 파이썬 float('nan')으로 남으므로 별도로 걸러낸다
    # (pd.isna는 파이썬 float NaN에도 정상 동작).
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
                "points": 4.0 if met else 0.0,
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
                "points": 4.0 if met else 0.0,
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
        "max_score": 12.0,
        "sub_conditions": sub_conditions,
    }


# ── 4-4. 가격 밀집도(8점) ────────────────────────────────────────────────
def score_price_tightness(
    high: pd.Series, low: pd.Series, volume: pd.Series, window: int = 10
) -> dict[str, Any]:
    """10일 가격범위 = (10일 최고가-10일 최저가)/10일 최저가 × 100.

    거래정지성 저거래로 범위가 좁아진 경우는 긍정 평가하지 않는다
    (``PRICE_TIGHTNESS_MIN_VOLUME_RATIO`` 기준).
    """
    if len(high) < window or len(volume) < 50:
        return _bucket("가격 밀집도(10일)", None, 0.0, 8.0, "N/A", reason="10일 가격범위 또는 50일 평균거래량 계산에 필요한 데이터 부족")

    recent_high = float(high.iloc[-window:].max())
    recent_low = float(low.iloc[-window:].min())
    if recent_low == 0:
        return _bucket("가격 밀집도(10일)", None, 0.0, 8.0, "N/A", reason="최근 10일 최저가가 0")

    range_pct = round((recent_high - recent_low) / recent_low * 100.0, 8)

    recent_10d_vol = float(volume.iloc[-window:].mean())
    recent_50d_vol = float(volume.iloc[-50:].mean())
    if recent_50d_vol > 0 and recent_10d_vol / recent_50d_vol < PRICE_TIGHTNESS_MIN_VOLUME_RATIO:
        return _bucket(
            "가격 밀집도(10일)",
            range_pct,
            0.0,
            8.0,
            "거래정지성 저거래로 판단(긍정 평가 제외)",
            reason=f"최근10일 거래량이 50일 평균의 {recent_10d_vol / recent_50d_vol * 100:.1f}%로 지나치게 낮음",
        )

    if range_pct <= 5.0:
        score, band = 8.0, "5% 이하"
    elif range_pct <= 8.0:
        score, band = 6.0, "5% 초과~8% 이하"
    elif range_pct <= 12.0:
        score, band = 4.0, "8% 초과~12% 이하"
    elif range_pct <= 16.0:
        score, band = 2.0, "12% 초과~16% 이하"
    else:
        score, band = 0.0, "16% 초과"
    return _bucket("가격 밀집도(10일)", range_pct, score, 8.0, band)


# ── 4-5. 거래량 고갈(7점) ────────────────────────────────────────────────
def score_volume_dry_up(volume: pd.Series, close: pd.Series) -> dict[str, Any]:
    """거래량비율 = 최근5일 평균거래량 / 최근50일 평균거래량 × 100.

    급락(최근 10거래일 수익률 < ``VOLUME_DRYUP_MAX_DECLINE_PCT``) 동반 시
    긍정 평가하지 않는다.
    """
    if len(volume) < 50:
        return _bucket("거래량 고갈", None, 0.0, 7.0, "N/A", reason="50일 평균거래량 계산에 필요한 데이터 부족")

    recent_5d_vol = float(volume.iloc[-5:].mean())
    recent_50d_vol = float(volume.iloc[-50:].mean())
    if recent_50d_vol == 0:
        return _bucket("거래량 고갈", None, 0.0, 7.0, "N/A", reason="최근 50일 평균거래량이 0")

    ratio = round(recent_5d_vol / recent_50d_vol * 100.0, 8)

    decline_10d = ind.pct_change_over(close, 10)
    if decline_10d is not None and decline_10d < VOLUME_DRYUP_MAX_DECLINE_PCT:
        return _bucket(
            "거래량 고갈",
            ratio,
            0.0,
            7.0,
            "가격 급락 동반(긍정 평가 제외)",
            reason=f"최근 10거래일 수익률 {decline_10d:.1f}% (급락 동반으로 거래량 고갈을 긍정 신호로 보지 않음)",
        )

    if ratio <= 40.0:
        score, band = 7.0, "40% 이하"
    elif ratio <= 60.0:
        score, band = 6.0, "40% 초과~60% 이하"
    elif ratio <= 80.0:
        score, band = 4.0, "60% 초과~80% 이하"
    elif ratio <= 100.0:
        score, band = 2.0, "80% 초과~100% 이하"
    else:
        score, band = 0.0, "100% 초과"
    return _bucket("거래량 고갈", ratio, score, 7.0, band)


# ── 4-6. 시장 상대강도(7점, 6개월 기준) ─────────────────────────────────
def score_relative_strength(percentile: Optional[float]) -> dict[str, Any]:
    """6개월 상대수익률(종목-지수)의 배치 내 백분위(0~100, 높을수록 상위)."""
    if percentile is None:
        return _bucket("시장 상대강도(6개월)", None, 0.0, 7.0, "N/A", reason="배치 백분위 계산 불가(비교 대상 종목 부족 등)")

    if percentile >= 90.0:
        score, band = 7.0, "상위 10%"
    elif percentile >= 80.0:
        score, band = 6.0, "상위 10~20%"
    elif percentile >= 70.0:
        score, band = 4.0, "상위 20~30%"
    elif percentile >= 50.0:
        score, band = 2.0, "상위 30~50%"
    else:
        score, band = 0.0, "하위 50%"
    return _bucket("시장 상대강도(6개월)", percentile, score, 7.0, band)


# ── 4-7. RSI 모멘텀(10점) ────────────────────────────────────────────────
def _rsi_base_score(rsi_now: float) -> tuple[float, str]:
    if 55.0 <= rsi_now < 65.0:
        return 10.0, "55~65 미만"
    if 50.0 <= rsi_now < 55.0:
        return 8.0, "50~55 미만"
    if 65.0 <= rsi_now < 70.0:
        return 7.0, "65~70 미만"
    if 45.0 <= rsi_now < 50.0:
        return 5.0, "45~50 미만"
    if 70.0 <= rsi_now < 75.0:
        return 4.0, "70~75 미만"
    if 40.0 <= rsi_now < 45.0:
        return 2.0, "40~45 미만"
    if rsi_now >= 75.0:
        return 1.0, "75 이상"
    return 0.0, "40 미만"


def score_rsi_momentum(rsi_series: pd.Series) -> dict[str, Any]:
    """RSI(14) 구간 기본점수 + 방향성 보정(합산 후 0~10 클램프)."""
    if len(rsi_series) < 1 or pd.isna(rsi_series.iloc[-1]):
        return _bucket("RSI 모멘텀", None, 0.0, 10.0, "N/A", reason="RSI 계산에 필요한 데이터 부족")

    rsi_now = float(rsi_series.iloc[-1])
    base_score, band = _rsi_base_score(rsi_now)

    adjustments: list[dict[str, Any]] = []
    total = base_score

    rsi_5d_ago = None
    if len(rsi_series) > 5 and not pd.isna(rsi_series.iloc[-6]):
        rsi_5d_ago = float(rsi_series.iloc[-6])
    rsi_prev = None
    if len(rsi_series) > 1 and not pd.isna(rsi_series.iloc[-2]):
        rsi_prev = float(rsi_series.iloc[-2])

    if rsi_5d_ago is not None and 50.0 <= rsi_now <= 70.0 and rsi_now > rsi_5d_ago:
        adjustments.append({"label": "RSI 50~70 구간에서 5거래일 전 대비 상승", "delta": 1.0})
        total += 1.0

    if rsi_prev is not None:
        if rsi_prev < 50.0 <= rsi_now:
            adjustments.append({"label": "RSI가 50 상향 돌파", "delta": 2.0})
            total += 2.0
        if rsi_prev >= 70.0 > rsi_now:
            adjustments.append({"label": "RSI가 70 하향 이탈", "delta": -1.0})
            total -= 1.0
        if rsi_prev >= 50.0 > rsi_now:
            adjustments.append({"label": "RSI가 50 하향 이탈", "delta": -2.0})
            total -= 2.0

    total_clamped = max(0.0, min(10.0, total))
    return {
        "label": "RSI 모멘텀",
        "value": rsi_now,
        "base_score": base_score,
        "base_band": band,
        "adjustments": adjustments,
        "score": total_clamped,
        "max_score": 10.0,
        "computable": True,
    }


def evaluate_entry_desirability(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    relative_strength_6m_percentile: Optional[float],
) -> dict[str, Any]:
    """7개 하위 항목을 모두 평가해 진입 매력도(0~60)와 상세 내역을 반환."""
    close_val = float(close.iloc[-1]) if len(close) else None
    sma50 = ind.sma_as_of(close, 50)
    high_52w, _ = ind.rolling_high_low(high, low, window=252)
    rsi_series = ind.rsi_wilder(close, 14)

    ma50_distance = score_ma50_distance(close_val, sma50)
    high_52w_distance = score_high_52w_distance(close_val, high_52w)
    volatility_contraction = score_volatility_contraction(high, low, close)
    price_tightness = score_price_tightness(high, low, volume)
    volume_dry_up = score_volume_dry_up(volume, close)
    relative_strength = score_relative_strength(relative_strength_6m_percentile)
    rsi = score_rsi_momentum(rsi_series)

    total = (
        ma50_distance["score"]
        + high_52w_distance["score"]
        + volatility_contraction["score"]
        + price_tightness["score"]
        + volume_dry_up["score"]
        + relative_strength["score"]
        + rsi["score"]
    )

    return {
        "score": total,
        "max_score": MAX_SCORE,
        "ma50_distance": ma50_distance,
        "high_52w_distance": high_52w_distance,
        "volatility_contraction": volatility_contraction,
        "price_tightness": price_tightness,
        "volume_dry_up": volume_dry_up,
        "relative_strength": relative_strength,
        "rsi": rsi,
    }
