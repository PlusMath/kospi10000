"""눌림목 셋업 적격성(40점) — "이 조정이 매수할 만한 눌림목인가"를 가리는 5개 조건.

2026-09-07 개편: 기존 미너비니 SEPA/Trend Template(52주 신고가 근접·정배열 요구)을
눌림목매매 기준으로 전면 교체. 눌림목은 "이미 한 번 오른 종목이 건강하게 쉬어가는
구간"을 찾는 전략이라, 오히려 신고가에서 일정 폭 떨어져 있는 게 정상이다 — 그래서
"52주 고점 근접"류 조건은 전부 폐기하고, "선행 상승이 있었는가 → 그 상승 대비 적당히
되돌렸는가 → 그 되돌림 중에도 지지선을 지키고 있는가"를 순서대로 검증하는 구조로
바꿨다.

각 조건은 독립 함수로 구현하고, ``evaluate_setup_qualification``이 이를 모아 합산
점수/필수조건 충족 여부/상세 내역을 만든다. 결측(계산 불가)과 조건 미충족을
구분하기 위해 각 조건 결과는 trend_qualification.py 시절과 동일한 형태
(``{"met": bool | None, "points": float, "computable": bool, "reason": str | None}``)를
따른다.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import indicators as ind

MAX_SCORE = 40.0
QUALIFIED_THRESHOLD = 35.0
"""35점 이상이면 '우수 셋업'으로 분류(기존 임계값 그대로 유지)."""

IMPULSE_LOOKBACK_DAYS = 60
SWING_ORDER = 5
MIN_IMPULSE_GAIN_PCT = 20.0
"""선행 상승(임펄스)이 눌림목으로 인정받으려면 최소 이 정도는 올랐어야 함."""

RETRACE_MIN_PCT = 10.0
RETRACE_MAX_PCT = 61.8
"""되돌림이 이 구간 밖이면 눌림목 셋업으로 보지 않음 — 10% 미만은 "거의 안 빠짐"(진짜
눌림목이 아직 아님), 61.8% 초과는 추세 훼손 의심.

2026-09-07 실측 조정: 처음엔 서구식 피보나치 되돌림 관행을 따라 30%로 잡았으나, 실제
코스피 대형주 30종목 실측 결과 임펄스 직후 되돌림이 대부분 0~25%대에 머물러(최대
24.1%) 30%를 넘는 경우가 하나도 없었음 — 30% 기준으로는 사실상 항상 전종목 부적격
판정이 나옴. 한국 대형주가 서구 성장주만큼 깊게 되돌리지 않는 경향을 반영해 10%로
하향(사용자 확인 후 반영)."""

MIN_PULLBACK_DAYS = 3
MAX_PULLBACK_DAYS = 20
"""조정 기간이 이 범위 밖이면(너무 짧거나 너무 김) 눌림목 셋업으로서의 신뢰도가 낮음."""

IMPULSE_VOLUME_RATIO_MIN = 1.5
"""임펄스 구간 평균거래량이 그 직전 구간 평균거래량의 이 배수 이상이어야 '관심을 받은
상승'으로 인정 — 거래량 없는 상승엔 돌아올 매수세를 기대하기 어려움."""


def _condition(
    label: str, met: Optional[bool], points: float, max_points: float, value: Any = None, reason: Optional[str] = None
) -> dict[str, Any]:
    computable = met is not None
    return {
        "label": label,
        "met": met,
        "value": value,
        "points": points if (computable and met) else 0.0,
        "max_points": max_points,
        "computable": computable,
        "reason": reason,
    }


def support_level(impulse_start_price: Optional[float]) -> Optional[float]:
    """지지선 = 임펄스 시작가(돌파 전 저항선 — "옛 저항선이 새 지지선" 원칙).

    2026-09-07 실측 조정: 처음엔 "60일선과 임펄스 시작가 중 더 높은 값"이었으나, 코스피
    대형주 30종목 실측 결과 임펄스가 대개 최근(5~20거래일 전)이라 60일선이 아직 급등 전
    저가를 충분히 반영 못 해 거의 항상 임펄스 시작가보다 높게 나오고, 그 결과 사실상
    "60일선"이 지지선을 대신하며 30개 중 25개가 부당하게 지지선 이탈로 걸림(임펄스
    시작가만 쓰면 29개 통과). 60일선 자체의 추세 신호는 risk_penalty의
    ``penalty_support_ma_falling``에서 별도로 여전히 쓰인다.
    """
    return impulse_start_price


def cond_impulse_exists(impulse: Optional[dict]) -> dict[str, Any]:
    """1) 최근 60거래일 내 확정된 상승 임펄스가 있고, 상승폭이 20% 이상."""
    if impulse is None:
        return _condition(
            "선행 상승(임펄스) 확인", None, 0.0, 10.0,
            reason="최근 60거래일 내 확정된 스윙저점→스윙고점 임펄스를 찾지 못함",
        )
    met = impulse["gain_pct"] >= MIN_IMPULSE_GAIN_PCT
    return _condition("선행 상승(임펄스) 확인", met, 10.0, 10.0, value={"gain_pct": impulse["gain_pct"]})


def cond_retrace_in_range(impulse: Optional[dict], close_val: Optional[float]) -> dict[str, Any]:
    """2) 임펄스 고점 대비 되돌림이 30~61.8% 구간."""
    if impulse is None or close_val is None or impulse["peak_price"] <= 0:
        return _condition("되돌림 비율 30~61.8%", None, 0.0, 10.0, reason="임펄스 또는 현재가 계산 불가")
    retrace_pct = (impulse["peak_price"] - close_val) / impulse["peak_price"] * 100.0
    met = RETRACE_MIN_PCT <= retrace_pct <= RETRACE_MAX_PCT
    return _condition("되돌림 비율 30~61.8%", met, 10.0, 10.0, value={"retrace_pct": retrace_pct})


def cond_support_held(close_val: Optional[float], support: Optional[float], impulse: Optional[dict]) -> dict[str, Any]:
    """3) 조정 중에도 종가가 지지선(임펄스 시작가) 위 유지.

    임펄스 자체가 없으면 "조정 중 지지선 유지"라는 판정 자체가 성립하지 않으므로(눌림목이
    아예 아닌데 우연히 종가>60일선인 것과는 다른 얘기), 임펄스가 없으면 계산 불가로 처리한다
    — 그렇지 않으면 임펄스 없는 종목도 이 조건만으로 10점을 챙기는 허점이 생긴다.
    """
    if close_val is None or support is None or impulse is None:
        return _condition("지지선 유지", None, 0.0, 10.0, reason="임펄스 또는 지지선 계산에 필요한 데이터 부족")
    met = close_val >= support
    return _condition("지지선 유지", met, 10.0, 10.0, value={"close": close_val, "support": support})


def cond_pullback_duration(impulse: Optional[dict], total_len: int) -> dict[str, Any]:
    """4) 임펄스 고점 이후 경과일이 3~20거래일."""
    if impulse is None:
        return _condition("조정 기간 적정성(3~20거래일)", None, 0.0, 5.0, reason="임펄스를 찾지 못해 경과일 계산 불가")
    days_since_peak = (total_len - 1) - impulse["peak_index"]
    met = MIN_PULLBACK_DAYS <= days_since_peak <= MAX_PULLBACK_DAYS
    return _condition("조정 기간 적정성(3~20거래일)", met, 5.0, 5.0, value={"days_since_peak": days_since_peak})


def cond_impulse_volume(impulse: Optional[dict], volume: pd.Series) -> dict[str, Any]:
    """5) 임펄스 구간 평균거래량이 그 직전 구간 평균거래량의 150% 이상."""
    if impulse is None:
        return _condition("임펄스 구간 거래량 증가", None, 0.0, 5.0, reason="임펄스를 찾지 못해 거래량 비교 불가")
    start_idx, peak_idx = impulse["start_index"], impulse["peak_index"]
    impulse_len = peak_idx - start_idx + 1
    prior_start = start_idx - impulse_len
    if prior_start < 0 or impulse_len <= 0:
        return _condition(
            "임펄스 구간 거래량 증가", None, 0.0, 5.0,
            reason="임펄스 직전 비교 구간 데이터 부족(상장 초기 등)",
        )
    impulse_vol = float(volume.iloc[start_idx : peak_idx + 1].mean())
    prior_vol = float(volume.iloc[prior_start:start_idx].mean())
    if prior_vol <= 0 or pd.isna(impulse_vol) or pd.isna(prior_vol):
        return _condition("임펄스 구간 거래량 증가", None, 0.0, 5.0, reason="거래량 데이터 결측 또는 0")
    ratio = impulse_vol / prior_vol
    met = ratio >= IMPULSE_VOLUME_RATIO_MIN
    return _condition(
        "임펄스 구간 거래량 증가", met, 5.0, 5.0,
        value={"impulse_avg_volume": impulse_vol, "prior_avg_volume": prior_vol, "ratio": ratio},
    )


def evaluate_setup_qualification(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> dict[str, Any]:
    """5개 조건을 모두 평가해 눌림목 셋업 적격성 점수(0~40)와 상세 내역을 반환."""
    close_val = float(close.iloc[-1]) if len(close) else None
    impulse = ind.find_recent_impulse(high, low, order=SWING_ORDER, lookback_days=IMPULSE_LOOKBACK_DAYS)
    support = support_level(impulse["start_price"] if impulse else None)

    conditions = [
        cond_impulse_exists(impulse),
        cond_retrace_in_range(impulse, close_val),
        cond_support_held(close_val, support, impulse),
        cond_pullback_duration(impulse, len(close)),
        cond_impulse_volume(impulse, volume),
    ]
    score = sum(c["points"] for c in conditions)

    # 필수조건: 임펄스 존재 + 되돌림 구간 내 + 지지선 유지. 셋 중 하나라도 확정적으로
    # 깨지면(계산 가능한데 met=False) "셋업 부적격" 경고 — 나머지 두 조건(기간/거래량)은
    # 있으면 가점이지만 없다고 눌림목 자체가 아니라고 보진 않는다.
    mandatory = [conditions[0], conditions[1], conditions[2]]
    mandatory_computable = all(c["computable"] for c in mandatory)
    mandatory_all_met = mandatory_computable and all(c["met"] for c in mandatory)

    return {
        "score": score,
        "max_score": MAX_SCORE,
        "qualified": score >= QUALIFIED_THRESHOLD,
        "mandatory_conditions_met": mandatory_all_met if mandatory_computable else None,
        "impulse": impulse,
        "support_level": support,
        "details": conditions,
        "warning": None if (mandatory_all_met or not mandatory_computable) else "셋업 부적격",
    }
