"""run_daily.py 단위 테스트 — 특히 부분 실행(--limit/--code)의 파일 병합 동작.

2026-09-07 실측 버그: --limit/--code로 일부 종목만 평가해도 항상 출력 파일 전체를
"이번에 평가한 종목만" 담은 내용으로 덮어써서 나머지 전 종목 데이터가 통째로
사라지는 사고가 있었음(운영 세션에서 --limit 30 테스트 중 79개 종목 데이터를 날릴
뻔함). 네트워크 호출 없이 ``evaluate_batch``/``load_kospi10000_universe``를 모두
스텁으로 대체해 파일 쓰기 로직만 검증한다.
"""

from __future__ import annotations

import json

import pytest

from technical_score import run_daily
from technical_score.batch import TickerSpec


def _stub_universe(specs: list[TickerSpec]):
    def _loader(index_html_path=None):
        return specs

    return _loader


def _stub_evaluate_batch(specs: list[TickerSpec]):
    def _evaluate(specs_arg):
        return [
            {
                "ticker": f"{s.code}.KS",
                "name": s.name,
                "as_of_date": "2024-01-01",
                "data_status": "ok",
                "technical_score": 50.0,
            }
            for s in specs_arg
        ]

    return _evaluate


class TestPartialRunMergesWithExisting:
    def test_limit_run_preserves_untouched_codes(self, tmp_path, monkeypatch):
        output_path = tmp_path / "technical_score.json"
        existing = {
            "AAAAAA": {"name": "기존종목A", "technical_score": 10.0},
            "BBBBBB": {"name": "기존종목B", "technical_score": 20.0},
        }
        output_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

        all_specs = [TickerSpec(code="AAAAAA", market="KOSPI", name="기존종목A")]
        monkeypatch.setattr(run_daily, "load_kospi10000_universe", _stub_universe(all_specs))
        monkeypatch.setattr(run_daily, "evaluate_batch", _stub_evaluate_batch(all_specs))

        run_daily.run(limit=1, output_path=output_path)

        saved = json.loads(output_path.read_text(encoding="utf-8"))
        # 이번에 평가한 AAAAAA는 새 값으로 갱신되고, 평가 대상이 아니었던 BBBBBB는 그대로 남아야 함.
        assert saved["AAAAAA"]["technical_score"] == pytest.approx(50.0)
        assert saved["BBBBBB"]["technical_score"] == pytest.approx(20.0)

    def test_code_run_preserves_other_codes(self, tmp_path, monkeypatch):
        output_path = tmp_path / "technical_score.json"
        existing = {"CCCCCC": {"name": "기존종목C", "technical_score": 30.0}}
        output_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

        all_specs = [
            TickerSpec(code="CCCCCC", market="KOSPI", name="기존종목C"),
            TickerSpec(code="DDDDDD", market="KOSPI", name="종목D"),
        ]
        monkeypatch.setattr(run_daily, "load_kospi10000_universe", _stub_universe(all_specs))
        monkeypatch.setattr(run_daily, "evaluate_batch", _stub_evaluate_batch(all_specs))

        run_daily.run(only_code="DDDDDD", output_path=output_path)

        saved = json.loads(output_path.read_text(encoding="utf-8"))
        assert "CCCCCC" in saved  # 평가 대상이 아니었던 기존 종목이 사라지지 않아야 함
        assert saved["DDDDDD"]["technical_score"] == pytest.approx(50.0)

    def test_partial_run_with_no_existing_file_does_not_crash(self, tmp_path, monkeypatch):
        output_path = tmp_path / "technical_score.json"  # 아직 존재하지 않음
        specs = [TickerSpec(code="EEEEEE", market="KOSPI", name="종목E")]
        monkeypatch.setattr(run_daily, "load_kospi10000_universe", _stub_universe(specs))
        monkeypatch.setattr(run_daily, "evaluate_batch", _stub_evaluate_batch(specs))

        run_daily.run(limit=1, output_path=output_path)

        saved = json.loads(output_path.read_text(encoding="utf-8"))
        assert saved["EEEEEE"]["technical_score"] == pytest.approx(50.0)


class TestFullRunReplacesEntireFile:
    def test_full_run_drops_codes_no_longer_in_universe(self, tmp_path, monkeypatch):
        """인자 없는 전체 실행은 의도적으로 완전 교체 — 상장폐지 등으로 현재 유니버스에
        없는 종목의 잔여 데이터를 자연스럽게 정리하기 위함(부분 실행과의 차이점)."""
        output_path = tmp_path / "technical_score.json"
        existing = {"ZZZZZZ": {"name": "상장폐지종목", "technical_score": 5.0}}
        output_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

        current_specs = [TickerSpec(code="FFFFFF", market="KOSPI", name="종목F")]
        monkeypatch.setattr(run_daily, "load_kospi10000_universe", _stub_universe(current_specs))
        monkeypatch.setattr(run_daily, "evaluate_batch", _stub_evaluate_batch(current_specs))

        run_daily.run(output_path=output_path)  # limit=0, only_code=None -> 전체 실행

        saved = json.loads(output_path.read_text(encoding="utf-8"))
        assert "ZZZZZZ" not in saved
        assert saved["FFFFFF"]["technical_score"] == pytest.approx(50.0)
