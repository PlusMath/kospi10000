"""investor_flow.py 단위 테스트 — 수급 점수 경계값, 개인 단독 매수 경계 신호."""

from __future__ import annotations

import pandas as pd
import pytest

from technical_score.investor_flow import (
    DailyInvestorFlow,
    evaluate_individual_dominant_buying,
    score_supply_demand,
)


def _flows(*net_pairs: tuple[int, int]) -> list[DailyInvestorFlow]:
    """(institution_net, foreign_net) 튜플들로 최신순 flow 리스트를 만든다."""
    return [
        DailyInvestorFlow(date=f"2024.01.{10 - i:02d}", institution_net=inst, foreign_net=frgn)
        for i, (inst, frgn) in enumerate(net_pairs)
    ]


def _volume_series(avg: float, n: int = 30) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series([avg] * n, index=idx)


class TestDailyInvestorFlow:
    def test_individual_net_approx_is_residual(self):
        f = DailyInvestorFlow(date="2024.01.10", institution_net=100, foreign_net=200)
        assert f.individual_net_approx == -300

    def test_zero_sum_across_three_categories(self):
        f = DailyInvestorFlow(date="2024.01.10", institution_net=-50, foreign_net=30)
        assert f.institution_net + f.foreign_net + f.individual_net_approx == 0


class TestScoreSupplyDemand:
    """수급강도(%) 경계값(15/5/-5/-15) 검증. 5일 합산 순매매 / 20일 평균거래량 × 100."""

    @pytest.mark.parametrize(
        "intensity_pct,expected_score,expected_band",
        [
            (20.0, 10.0, "강한 동반 순매수"),
            (15.0, 10.0, "강한 동반 순매수"),
            (14.99, 7.0, "순매수 우위"),
            (5.0, 7.0, "순매수 우위"),
            (4.99, 4.0, "중립"),
            (-5.0, 4.0, "중립"),
            (-5.01, 2.0, "순매도 우위"),
            (-15.0, 2.0, "순매도 우위"),
            (-15.01, 0.0, "강한 동반 순매도"),
            (-30.0, 0.0, "강한 동반 순매도"),
        ],
    )
    def test_boundary(self, intensity_pct: float, expected_score: float, expected_band: str):
        # avg_volume_20d=1,000,000 기준으로 원하는 intensity_pct%가 되도록 5일 합산 순매매를 역산.
        avg_vol = 1_000_000.0
        combined_net_5d = intensity_pct / 100.0 * avg_vol
        # 5일에 고르게 분배(기관에 전부 배정, 외국인 0 — 합산만 맞으면 됨).
        per_day = combined_net_5d / 5.0
        flows = _flows(*[(int(per_day), 0) for _ in range(5)])
        volume = _volume_series(avg_vol)
        result = score_supply_demand(flows, volume)
        assert result["score"] == pytest.approx(expected_score)
        assert result["band"] == expected_band

    def test_no_flows_not_computable(self):
        result = score_supply_demand([], _volume_series(1000))
        assert result["computable"] is False

    def test_insufficient_volume_history_not_computable(self):
        flows = _flows((100, 100), (100, 100), (100, 100), (100, 100), (100, 100))
        short_volume = _volume_series(1000, n=5)
        result = score_supply_demand(flows, short_volume)
        assert result["computable"] is False

    def test_only_uses_most_recent_5_days(self):
        # 앞쪽(오래된) 데이터에 극단값을 넣어도 결과에 영향 없어야 함.
        recent_5 = [(100, 100)] * 5  # 합산 200*5=1000
        old_extreme = [(999999, 999999)] * 5
        flows = _flows(*recent_5, *old_extreme)
        volume = _volume_series(100_000)  # avg=100000 -> intensity = 1000/100000*100 = 1%
        result = score_supply_demand(flows, volume)
        assert result["value"] == pytest.approx(1.0)
        assert result["days_used"] == 5


class TestIndividualDominantBuying:
    def test_triggers_when_4_of_5_days_individual_alone_buys(self):
        # institution+foreign 순매도(개인 순매수)인 날이 4일, 나머지 1일은 동반매수.
        dominant_day = (-100, -50)  # inst+frgn = -150 (매도) -> individual = +150 (매수)
        non_dominant_day = (50, 50)  # inst+frgn = +100 (매수) -> individual = -100
        flows = _flows(dominant_day, dominant_day, dominant_day, dominant_day, non_dominant_day)
        result = evaluate_individual_dominant_buying(flows)
        assert result["triggered"] is True
        assert result["points"] == pytest.approx(-5.0)
        assert result["value"]["dominant_days"] == 4

    def test_no_trigger_when_only_3_of_5_days(self):
        dominant_day = (-100, -50)
        non_dominant_day = (50, 50)
        flows = _flows(dominant_day, dominant_day, dominant_day, non_dominant_day, non_dominant_day)
        result = evaluate_individual_dominant_buying(flows)
        assert result["triggered"] is False
        assert result["points"] == pytest.approx(0.0)

    def test_insufficient_data(self):
        flows = _flows((10, 10), (10, 10))
        result = evaluate_individual_dominant_buying(flows)
        assert result["computable"] is False
        assert result["triggered"] is None
