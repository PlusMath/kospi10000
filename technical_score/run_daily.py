"""kospi10000 유니버스 전체를 기술적 매력도 평가해 data/technical_score.json에 저장.

index.html의 stocks 배열에서 종목코드·종목명을 읽어와 배치 평가하고, 결과를
"종목코드 → 평가결과" 딕셔너리 하나로 묶어 저장한다(홈페이지 정렬 탭에서
한 번의 fetch로 전 종목을 다룰 수 있도록). update_daily_charts.ps1(PowerShell)과는
완전히 분리된 별도 예약 작업으로 실행한다 — 하나가 실패해도 다른 하나는
영향받지 않는다.

사용법:
    python run_daily.py                 # kospi10000 전체 종목 평가
    python run_daily.py --limit 5        # 앞 5종목만(테스트용)
    python run_daily.py --code 005930    # 특정 종목만
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from technical_score.batch import TickerSpec, evaluate_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
OUTPUT_PATH = REPO_ROOT / "data" / "technical_score.json"

_STOCK_ENTRY_PATTERN = re.compile(
    r'"rank":\s*(\d+),\s*"name":\s*"([^"]+)",\s*"code":\s*"([^"]+)"'
)


def load_kospi10000_universe(index_html_path: Path = INDEX_HTML_PATH) -> list[TickerSpec]:
    """index.html의 stocks 배열에서 종목 리스트를 추출.

    kospi10000 프로젝트는 코스피 상위 종목만 다루므로 market은 항상 "KOSPI"로 고정.
    """
    raw = index_html_path.read_text(encoding="utf-8")
    seen_codes: set[str] = set()
    specs: list[TickerSpec] = []
    for m in _STOCK_ENTRY_PATTERN.finditer(raw):
        _rank, name, code = m.groups()
        if code in seen_codes:
            continue
        seen_codes.add(code)
        specs.append(TickerSpec(code=code, market="KOSPI", name=name))
    return specs


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"JSON으로 직렬화할 수 없는 타입: {type(obj)}")


def run(limit: int = 0, only_code: str | None = None, output_path: Path = OUTPUT_PATH) -> None:
    specs = load_kospi10000_universe()
    logger.info("index.html에서 종목 %d개 로드", len(specs))

    if only_code:
        specs = [s for s in specs if s.code == only_code]
        if not specs:
            logger.error("코드 %s를 index.html에서 찾을 수 없음", only_code)
            return
    elif limit > 0:
        specs = specs[:limit]

    logger.info("평가 대상 %d개 종목, 시작", len(specs))
    t0 = time.time()
    results = evaluate_batch(specs)
    elapsed = time.time() - t0

    ok_count = sum(1 for r in results if r["data_status"] == "ok")
    fail_count = len(results) - ok_count
    logger.info("완료: %.1f초 소요, 성공 %d / 실패·제외 %d (총 %d)", elapsed, ok_count, fail_count, len(results))
    for r in results:
        if r["data_status"] != "ok":
            logger.warning("%s(%s): %s - %s", r["ticker"], r["name"], r["data_status"], r.get("error_message"))

    by_code = {}
    for spec, r in zip(specs, results):
        by_code[spec.code] = r

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(by_code, f, ensure_ascii=False, indent=2, default=_json_default)
    logger.info("저장 완료: %s (%d종목)", output_path, len(by_code))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="앞 N종목만 평가(테스트용, 0=전체)")
    parser.add_argument("--code", type=str, default=None, help="특정 종목코드 하나만 평가")
    args = parser.parse_args()
    run(limit=args.limit, only_code=args.code)
