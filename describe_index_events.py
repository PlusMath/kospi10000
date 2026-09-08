#!/usr/bin/env python3
"""data/index_events/{KEY}.json 갱신 헬퍼 (Python) — 감지된 이벤트에 대한 한국어 설명 생성부터
기존 파일과의 병합, 최종 JSON 저장까지 전부 담당한다.

2026-09-09 실측: 이 저장소가 지금까지 시도한 모든 PowerShell 5.1(.NET Framework) 기반 방식
(ConvertTo-Json/Out-File/WriteAllText/WriteAllBytes/StringBuilder, claude CLI를 Start-Job/
Process 직접 호출/cmd.exe 파일 리다이렉션으로 부르는 방식 등)에서 — 그리고 Python이 claude
CLI를 subprocess로 직접 부르는 방식에서도 — 40~60개 항목짜리 한글 텍스트 배열을 만들어
디스크에 저장하면 결과 파일이 항상 mojibake로 깨지는 걸 반복 확인함. 심지어 "동일한, 손 하나
안 댄 스크립트 파일"을 같은 방식으로 두 번 파싱해도 한 번은 성공하고 한 번은 실패하는 등
(PowerShell 자체의 문법 파싱조차) 이 환경에서 근본적으로 신뢰할 수 없는 상태였음(실측 당시
여유 메모리 1.4GB/16GB로 심각한 메모리 압박 확인 — 다른 활성 세션(claude.exe --resume)이
정상적으로 실행 중이라 종료할 수 없었음). AI(claude) 생성 서술문에 대한 신뢰할 수 있는 저장
경로를 이 환경에서 찾지 못해, "실제 가격 데이터로 감지된 사건"이라는 핵심 요구사항은
지키면서 서술문 생성 자체를 AI 호출 없이 이 Python 스크립트가 결정적(deterministic)으로
직접 조립하는 방식으로 대체함 — PowerShell은 순수 숫자·ASCII 날짜(한글 전혀 없음)만 다루고,
한글이 들어가는 모든 처리(서술문 조립·병합·최종 JSON 저장)는 이 세션 내내 신뢰성이 검증된
Python이 전담한다.

사용법:
    python describe_index_events.py --key KOSPI --capped-events <path.json> \
        --archive-path <path.json>

표준출력에 다음 중 하나를 마지막 줄로 출력(호출부가 파싱):
    OK <신규건수> <총건수>
    NOCHANGE
    FAIL <이유>
종료 코드: 성공 0, 실패 1.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 잘 알려진 실제 금융·경제 사건과 날짜가 명확히 일치할 때만 짧게 이름을 덧붙임(추측 금지 —
# 이 목록에 없는 날짜는 절대 원인을 지어내지 않고 수치만으로 서술).
KNOWN_EVENTS = {
    '1929-10-28': '1929년 대공황 발 폭락',
    '1929-10-29': '1929년 대공황 발 폭락',
    '1987-10-19': '1987년 블랙먼데이',
    '1987-10-20': '1987년 블랙먼데이 여파',
    '1997-10-27': '1997년 아시아 금융위기',
    '2000-04-14': '2000년 닷컴버블 붕괴',
    '2001-09-17': '2001년 9·11 테러 여파',
    '2008-09-15': '2008년 글로벌 금융위기(리먼브라더스)',
    '2008-10-13': '2008년 글로벌 금융위기',
    '2008-10-24': '2008년 글로벌 금융위기',
    '2008-10-28': '2008년 글로벌 금융위기',
    '2020-03-09': '2020년 코로나19 팬데믹 급락',
    '2020-03-12': '2020년 코로나19 팬데믹 급락',
    '2020-03-16': '2020년 코로나19 팬데믹 급락',
}


def get_even_sample(items: list, max_count: int) -> list:
    """정렬된 목록에서 앞뒤로 고르게 퍼진 최대 max_count개만 골라냄(신고가/신저점처럼 유의도가
    다 같은 이벤트를 최신 편향 없이 전체 기간에 걸쳐 대표적으로 남기기 위함)."""
    n = len(items)
    if n <= max_count:
        return items
    if max_count <= 0:
        return []
    step = n / max_count
    seen = set()
    picked = []
    for k in range(max_count):
        idx = min(n - 1, int(k * step))
        if idx not in seen:
            seen.add(idx)
            picked.append(items[idx])
    return picked


def select_top_events(events: list, max_big_move: int = 30, max_new_high: int = 20, max_new_low: int = 15) -> list:
    """종류별로 상한을 두고 골라냄 — big_move는 등락률 절대값(significance) 기준 상위 N개,
    new_high/new_low는 균등샘플링. new_high/new_low는 값 자체가 다 "유의미(=상한 없음)"해서
    상위 N개 정렬이 의미 없어, 시기가 몰리지 않게 고르게 뽑는다."""
    big_moves = sorted(
        (e for e in events if e.get('type') == 'big_move'),
        key=lambda e: e.get('significance') or 0,
        reverse=True,
    )[:max_big_move]
    new_highs_all = sorted((e for e in events if e.get('type') == 'new_high'), key=lambda e: e['date'])
    new_lows_all = sorted((e for e in events if e.get('type') == 'new_low'), key=lambda e: e['date'])
    new_highs = get_even_sample(new_highs_all, max_new_high)
    new_lows = get_even_sample(new_lows_all, max_new_low)
    merged = big_moves + new_highs + new_lows
    merged.sort(key=lambda e: e['date'])
    return merged


def fmt_num(v) -> str:
    if v is None:
        return '?'
    v = float(v)
    if abs(v - round(v)) < 1e-9:
        return f'{v:,.0f}'
    return f'{v:,.2f}'


def describe_event(e: dict) -> str:
    """실제 가격 데이터(date/close/changePct)만 근거로 한 문장 생성. 알려진 실제 사건과
    날짜가 일치할 때만 그 이름을 덧붙이고, 그 외에는 절대 원인을 추측하지 않는다."""
    date = e['date']
    close = fmt_num(e.get('close'))
    known = KNOWN_EVENTS.get(date)
    if e['type'] == 'big_move':
        pct = e.get('changePct') or 0
        direction = '급등' if pct >= 0 else '급락'
        pct_str = f'{abs(pct):.2f}%'
        if known:
            return f'{date} 하루 {pct_str} {direction}({known}), 종가 {close}.'
        return f'{date} 하루 {pct_str} {direction}, 종가 {close}.'
    if e['type'] == 'new_high':
        return f'{date} 종가 {close}로 사상 최고치를 경신했다.'
    if e['type'] == 'new_low':
        return f'{date} 종가 {close}로 사상 최저치를 기록했다.'
    return f'{date} 종가 {close}.'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', required=True)
    ap.add_argument('--capped-events', required=True, help='감지·상한 적용까지 마친 이벤트 배열(JSON, 순수 숫자·날짜)')
    ap.add_argument('--archive-path', required=True, help='기존 아카이브(있으면 병합) + 최종 저장 경로')
    args = ap.parse_args()

    with open(args.capped_events, encoding='utf-8-sig') as f:
        capped = json.load(f)
    if not isinstance(capped, list):
        capped = [capped]

    archive_path = Path(args.archive_path)
    existing = []
    if archive_path.exists():
        try:
            with open(archive_path, encoding='utf-8-sig') as f:
                existing = json.load(f).get('events', [])
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_keys = {(e.get('date'), e.get('type')) for e in existing}
    new_ones = [e for e in capped if (e.get('date'), e.get('type')) not in existing_keys]

    if not new_ones:
        print('NOCHANGE')
        return 0

    described = []
    for event in new_ones:
        described.append({
            'date': event['date'], 'type': event['type'], 'close': event.get('close'),
            'changePct': event.get('changePct'), 'significance': event.get('significance'),
            'description': describe_event(event),
        })

    merged = select_top_events(existing + described)
    out = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'events': merged,
    }
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'OK {len(new_ones)} {len(merged)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
