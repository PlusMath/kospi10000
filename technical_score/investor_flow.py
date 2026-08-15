"""네이버 금융 종목별 매매동향(개인/외국인/기관) 스크래핑 + 수급 점수(0~10, 별도 트랙).

기술적 매력도 100점 체계와는 분리된 별도 신호다. 외국인·기관 순매매는
"스마트머니" 신호로 취급해 점수화하고, 개인(근사치) 순매매는 점수에 직접
반영하지 않는 대신 위험 감점 쪽의 경계 신호(개인 단독 매수 지속)로만
사용한다 — 근거 두 가지:
  1) 한국 시장에서 개인 순매수는 오히려 역신호로 읽히는 경우가 많다는 통념
     (외국인·기관과 반대로 개인만 사는 구간은 상투 근처인 경우가 잦음).
  2) 개인 순매매 자체가 (외국인+기관)의 잔차 근사치라 오차가 누적된다 —
     근사치를 점수의 직접 인풋으로 쓰기보다 "경계 신호" 정도로만 활용.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

NAVER_FRGN_URL = "https://finance.naver.com/item/frgn.naver?code={code}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

SUPPLY_DEMAND_LOOKBACK_DAYS = 5
"""수급 점수 계산에 쓰는 최근 거래일 수(외국인+기관 합산 순매매)."""

VOLUME_NORMALIZE_WINDOW_DAYS = 20
"""순매매량을 정규화(종목 규모 무관 비교)할 때 나누는 평균거래량 구간."""

INDIVIDUAL_DOMINANT_LOOKBACK_DAYS = 5
INDIVIDUAL_DOMINANT_MIN_DAYS = 4
"""최근 5거래일 중 이 일수 이상 "개인만 순매수, 외국인+기관은 순매도"이면 경계 신호."""

MAX_SCORE = 10.0


@dataclass(frozen=True)
class DailyInvestorFlow:
    """하루치 기관/외국인 순매매량(주). 개인은 원본에 없어 잔차로 근사."""

    date: str  # "YYYY.MM.DD" (네이버 표기 그대로)
    institution_net: int
    foreign_net: int

    @property
    def individual_net_approx(self) -> int:
        return -(self.institution_net + self.foreign_net)


_ROW_PATTERN = re.compile(
    r'<span class="tah p10 gray03">([\d.]+)</span>.*?'  # 날짜
    r'<span class="tah p11">([\d,]+)</span>.*?'  # 종가
    r'<span class="tah p11 ?(?:red01|red02|nv01|nv02)?">\s*([+-]?[\d,]+)\s*</span>.*?'  # 전일비
    r'<span class="tah p11 ?(?:red01|nv01)?">\s*([+-][\d.]+%)\s*</span>.*?'  # 등락률
    r'<span class="tah p11">([\d,]+)</span>.*?'  # 거래량
    r'<span class="tah p11 ?(?:nv01|red01)?">\s*([+-]?[\d,]+)\s*</span>.*?'  # 기관 순매매량
    r'<span class="tah p11 ?(?:nv01|red01)?">\s*([+-]?[\d,]+)\s*</span>',  # 외국인 순매매량
    re.S,
)


def fetch_investor_flow(
    code: str, days: int = 10, timeout: int = 15, max_retries: int = 2, retry_delay_sec: float = 1.5
) -> list[DailyInvestorFlow]:
    """네이버 금융에서 최근 ``days``거래일치 기관/외국인 순매매량을 가져온다.

    페이지는 <meta charset=utf-8>이라고 잘못 표기하지만 실제 HTTP 응답은
    EUC-KR — ``requests``는 Content-Type 헤더 기준으로 정확히 디코딩하므로
    별도 인코딩 변환이 불필요하다(확인됨).

    실패(네트워크 오류, 페이지 구조 변경 등) 시 빈 리스트를 반환하고 로그만
    남긴다 — 이 신호는 별도 트랙이라 실패해도 기술적 매력도 본점수에는
    영향을 주지 않아야 하므로, 예외를 전파하지 않고 "계산 불가"로 처리한다.
    """
    url = NAVER_FRGN_URL.format(code=code)
    html: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            resp.raise_for_status()
            html = resp.text
            break
        except Exception as exc:  # noqa: BLE001 - 외부 스크래핑은 광범위하게 잡아 재시도
            logger.warning("%s: 투자자별 매매동향 호출 실패(시도 %d/%d) - %s", code, attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(retry_delay_sec)

    if html is None:
        return []

    start = html.find("<caption>외국인 기관 순매매 거래량</caption>")
    if start < 0:
        logger.warning("%s: 투자자별 매매동향 테이블을 찾을 수 없음(페이지 구조 변경 가능성)", code)
        return []
    end = html.find("<!--- 추정기관 끝--->", start)
    if end < 0:
        end = len(html)
    table_html = html[start:end]

    results: list[DailyInvestorFlow] = []
    for m in _ROW_PATTERN.finditer(table_html):
        if len(results) >= days:
            break
        date_s, _close, _chg, _pct, _vol, inst_s, frgn_s = m.groups()
        try:
            inst = int(inst_s.replace(",", "").replace("+", ""))
            frgn = int(frgn_s.replace(",", "").replace("+", ""))
        except ValueError:
            continue
        results.append(DailyInvestorFlow(date=date_s, institution_net=inst, foreign_net=frgn))

    if not results:
        logger.warning("%s: 투자자별 매매동향 행을 하나도 파싱하지 못함(페이지 구조 변경 가능성)", code)
    return results


def _band_for_intensity(intensity: float) -> tuple[float, str]:
    if intensity >= 15.0:
        return 10.0, "강한 동반 순매수"
    if intensity >= 5.0:
        return 7.0, "순매수 우위"
    if intensity >= -5.0:
        return 4.0, "중립"
    if intensity >= -15.0:
        return 2.0, "순매도 우위"
    return 0.0, "강한 동반 순매도"


def score_supply_demand(flows: list[DailyInvestorFlow], volume: pd.Series) -> dict[str, Any]:
    """외국인+기관 합산 수급 강도를 0~10점 별도 트랙으로 채점.

    수급강도(%) = 최근 ``SUPPLY_DEMAND_LOOKBACK_DAYS``거래일 (외국인+기관)
    순매매량 합 / 최근 ``VOLUME_NORMALIZE_WINDOW_DAYS``일 평균거래량 × 100.
    종목 규모(유동주식수)와 무관하게 비교 가능하도록 정규화한 값이다.

    :param flows: ``fetch_investor_flow``의 결과(최신순, 0번째가 가장 최근).
    :param volume: 종목의 일별 거래량(시간순 정렬) — 기술적 매력도 계산에
        이미 쓰는 것과 동일한 시리즈를 재사용(별도 스크래핑 불필요).
    """
    if not flows:
        return {
            "score": 0.0,
            "max_score": MAX_SCORE,
            "value": None,
            "band": "N/A",
            "computable": False,
            "reason": "투자자별 매매동향 데이터 없음(스크래핑 실패 또는 페이지 구조 변경)",
        }
    if len(volume) < VOLUME_NORMALIZE_WINDOW_DAYS:
        return {
            "score": 0.0,
            "max_score": MAX_SCORE,
            "value": None,
            "band": "N/A",
            "computable": False,
            "reason": f"{VOLUME_NORMALIZE_WINDOW_DAYS}거래일 평균거래량 계산에 필요한 데이터 부족",
        }

    recent = flows[:SUPPLY_DEMAND_LOOKBACK_DAYS]
    institution_net_sum = sum(f.institution_net for f in recent)
    foreign_net_sum = sum(f.foreign_net for f in recent)
    combined_net = institution_net_sum + foreign_net_sum

    avg_vol_20d = float(volume.iloc[-VOLUME_NORMALIZE_WINDOW_DAYS:].mean())
    if avg_vol_20d == 0:
        return {
            "score": 0.0,
            "max_score": MAX_SCORE,
            "value": None,
            "band": "N/A",
            "computable": False,
            "reason": "최근 20일 평균거래량이 0",
        }

    intensity = round(combined_net / avg_vol_20d * 100.0, 8)
    score, band = _band_for_intensity(intensity)

    return {
        "score": score,
        "max_score": MAX_SCORE,
        "value": intensity,
        "band": band,
        "computable": True,
        "reason": None,
        "days_used": len(recent),
        "institution_net_sum": institution_net_sum,
        "foreign_net_sum": foreign_net_sum,
        "avg_volume_20d": avg_vol_20d,
    }


def evaluate_individual_dominant_buying(flows: list[DailyInvestorFlow]) -> dict[str, Any]:
    """개인 단독 매수 경계 신호: 최근 5거래일 중 4일 이상 "개인(근사)은 순매수,
    외국인+기관 합산은 순매도"이면 위험 감점 -5점.

    감점 폭을 최소 단계(-5)로 제한한 이유: 개인 수치 자체가 근사치이고,
    이 신호는 어디까지나 통념 기반 경계 신호이지 확정적 위험 신호가 아니기
    때문 — 다른 위험 감점(-10~-15)만큼 강하게 벌점을 주지 않는다.
    """
    label = "개인 단독 매수 지속(외국인·기관 동반 순매도 중 개인만 순매수)"
    if len(flows) < INDIVIDUAL_DOMINANT_LOOKBACK_DAYS:
        return {"label": label, "triggered": None, "points": 0.0, "computable": False, "reason": "데이터 부족", "value": None}

    recent = flows[:INDIVIDUAL_DOMINANT_LOOKBACK_DAYS]
    dominant_days = sum(1 for f in recent if f.individual_net_approx > 0 and (f.institution_net + f.foreign_net) < 0)
    triggered = dominant_days >= INDIVIDUAL_DOMINANT_MIN_DAYS
    return {
        "label": label,
        "triggered": triggered,
        "points": -5.0 if triggered else 0.0,
        "computable": True,
        "reason": None,
        "value": {"dominant_days": dominant_days, "of_days": len(recent)},
    }
