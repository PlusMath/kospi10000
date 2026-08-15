"""전체 기술적 매력도 평가를 조합하는 오케스트레이션 모듈.

데이터 수집(``data_collection``)과 완전히 분리되어 있다 — 이 모듈은 이미
수집된 ``FetchResult``와 배치 단위로 미리 계산된 상대강도 백분위만 입력받아
순수 계산만 수행한다. 최종 점수 = clamp(추세적격성 + 진입매력도 - 위험감점, 0, 100).
"""

from __future__ import annotations

from typing import Any, Optional

from .breakout_signal import evaluate_breakout_signal
from .data_collection import DataStatus, FetchResult
from .entry_desirability import evaluate_entry_desirability
from .investor_flow import DailyInvestorFlow, score_supply_demand
from .risk_penalty import evaluate_risk_penalty
from .trend_qualification import evaluate_trend_qualification

MIN_AVG_TRADING_VALUE_KRW = 500_000_000.0
"""최근 20거래일 평균 거래대금(종가×거래량)이 이 미만이면 평가 제외. 스펙에
구체 수치가 없어 합리적 기본값(5억원)으로 채택 — 필요 시 조정 가능."""

LIQUIDITY_WINDOW_DAYS = 20


GRADE_BANDS: list[tuple[int, int, str]] = [
    (85, 100, "최상급 진입 후보"),
    (75, 84, "기술적 매력 우수"),
    (65, 74, "관심 종목"),
    (50, 64, "추세 양호·진입 위치 불리"),
    (0, 49, "기술적 부적격"),
]


def classify_grade(score: float) -> str:
    """최종 점수(0~100)를 등급 문자열로 변환."""
    rounded = round(score)
    for low, high, label in GRADE_BANDS:
        if low <= rounded <= high:
            return label
    # 이론상 도달 불가(0~100 클램프 이후 호출되므로) — 안전망.
    return "기술적 부적격"


def _avg_trading_value(close, volume, window: int = LIQUIDITY_WINDOW_DAYS) -> Optional[float]:
    if len(close) < window or len(volume) < window:
        return None
    value = (close.iloc[-window:] * volume.iloc[-window:]).mean()
    return float(value)


def build_summary(
    trend_result: dict[str, Any],
    entry_result: dict[str, Any],
    risk_result: dict[str, Any],
    supply_demand_result: Optional[dict[str, Any]] = None,
) -> list[str]:
    """항목별 결과에서 사람이 읽을 수 있는 요약 문장 목록을 만든다."""
    lines: list[str] = []

    md = trend_result.get("mandatory_details", {})
    if md.get("close_above_200ma") and md.get("ma50_above_ma200"):
        lines.append("50일선이 200일선 위, 종가도 200일선 위(정배열 유지)")
    elif md.get("close_above_200ma") is False:
        lines.append("종가가 200일선 아래(추세 부적격 위험)")

    hd = entry_result.get("high_52w_distance", {})
    if hd.get("computable") and hd.get("value") is not None:
        lines.append(f"52주 고점 대비 {hd['value']:.1f}% 하락")

    rsi = entry_result.get("rsi", {})
    if rsi.get("computable") and rsi.get("value") is not None:
        lines.append(f"RSI {rsi['value']:.1f}로 {rsi.get('base_band', '')} 구간")

    vc = entry_result.get("volatility_contraction", {})
    contracting = [c for c in vc.get("sub_conditions", []) if c.get("met")]
    if len(contracting) >= 2:
        lines.append("변동성 축소 신호 다수 확인")
    elif len(contracting) == 0 and vc.get("sub_conditions"):
        lines.append("변동성 축소 신호 없음")

    vd = entry_result.get("volume_dry_up", {})
    if vd.get("computable") and vd.get("value") is not None:
        lines.append(f"최근 5일 거래량이 50일 평균의 {vd['value']:.0f}%")

    if risk_result.get("reasons"):
        lines.append("위험 감점 사유: " + ", ".join(risk_result["reasons"]))

    if supply_demand_result and supply_demand_result.get("computable"):
        lines.append(f"최근 5일 수급: {supply_demand_result['band']}(외국인+기관 {supply_demand_result['value']:+.1f}%)")

    return lines


def _insufficient_result(ticker: str, name: str, fetch_result: FetchResult) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name,
        "as_of_date": fetch_result.as_of_date,
        "data_status": fetch_result.status,
        "technical_score": None,
        "grade": None,
        "trend_qualified": None,
        "trend_score": None,
        "entry_score": None,
        "risk_penalty": None,
        "breakout_signal": None,
        "supply_demand_score": None,
        "summary": [],
        "error_message": fetch_result.error_message,
    }


def evaluate_technical_score(
    ticker: str,
    name: str,
    fetch_result: FetchResult,
    relative_strength_52w_percentile: Optional[float],
    relative_strength_6m_percentile: Optional[float],
    min_avg_trading_value_krw: float = MIN_AVG_TRADING_VALUE_KRW,
    investor_flows: Optional[list[DailyInvestorFlow]] = None,
) -> dict[str, Any]:
    """단일 종목의 최종 기술적 매력도 결과(스펙 8절 JSON 형식)를 계산.

    :param fetch_result: ``data_collection.fetch_ohlcv``(또는 캐시 버전)의 결과.
    :param relative_strength_52w_percentile: 배치 내 52주 상대수익률 백분위(0~100).
    :param relative_strength_6m_percentile: 배치 내 6개월 상대수익률(지수 대비 초과분) 백분위(0~100).
    :param investor_flows: ``investor_flow.fetch_investor_flow``의 결과(선택). 전달되면
        "수급 점수"(0~10, 100점 체계와 별도 트랙)와 "개인 단독 매수" 위험 감점을 함께 계산한다.
        전달하지 않으면 두 신호 모두 계산 불가(None)로 표시되고 기존 100점 로직은 그대로 동작한다.
    """
    if fetch_result.status != DataStatus.OK or fetch_result.data is None:
        return _insufficient_result(ticker, name, fetch_result)

    df = fetch_result.data
    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]

    avg_value = _avg_trading_value(close, volume)
    if avg_value is not None and avg_value < min_avg_trading_value_krw:
        result = _insufficient_result(ticker, name, fetch_result)
        result["data_status"] = "excluded_low_liquidity"
        result["error_message"] = (
            f"최근 {LIQUIDITY_WINDOW_DAYS}거래일 평균 거래대금 {avg_value:,.0f}원이 "
            f"기준({min_avg_trading_value_krw:,.0f}원) 미달로 평가 제외"
        )
        return result

    trend_result = evaluate_trend_qualification(close, high, low, relative_strength_52w_percentile)
    entry_result = evaluate_entry_desirability(close, high, low, volume, relative_strength_6m_percentile)
    risk_result = evaluate_risk_penalty(close, high, low, volume, investor_flows=investor_flows)
    breakout_result = evaluate_breakout_signal(close, high, low, volume)
    supply_demand_result = score_supply_demand(investor_flows or [], volume)

    raw_total = trend_result["score"] + entry_result["score"] + risk_result["score"]
    final_score = max(0.0, min(100.0, raw_total))

    return {
        "ticker": ticker,
        "name": name,
        "as_of_date": fetch_result.as_of_date,
        "data_status": DataStatus.OK,
        "technical_score": round(final_score, 1),
        "grade": classify_grade(final_score),
        "trend_qualified": trend_result["mandatory_conditions_met"],
        "trend_score": {
            "score": trend_result["score"],
            "max_score": trend_result["max_score"],
            "qualified_excellent": trend_result["qualified"],
            "mandatory_conditions_met": trend_result["mandatory_conditions_met"],
            "warning": trend_result["warning"],
            "details": trend_result["details"],
        },
        "entry_score": entry_result,
        "risk_penalty": risk_result,
        "breakout_signal": breakout_result,
        "supply_demand_score": supply_demand_result,
        "summary": build_summary(trend_result, entry_result, risk_result, supply_demand_result),
    }
