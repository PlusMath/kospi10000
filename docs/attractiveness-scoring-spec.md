# KOSPI10000 — 매력도별 기준 구현 스펙 (다른 세션용 레퍼런스)

> 이 문서는 kospi10000 프로젝트(`C:\Users\h24795\claude\kospi10000`)에 **이미 구현되어 있는**
> "매력도별 기준" 4가지 축의 아키텍처를 정리한 것이다. 새 세션에서 이 시스템을 수정/확장할 때
> 코드베이스를 처음부터 다시 뒤지지 않도록, 파일 위치·산식·데이터 흐름을 그대로 프롬프트에
> 붙여넣어 쓸 수 있게 작성했다. **작성 시점 기준 스냅샷**이므로, 실제 작업 전에는 아래 명시된
> 파일·함수가 여전히 존재하는지 먼저 확인할 것(리네임/삭제됐을 수 있음).

## 요청 원문 (기준 4가지)

```
#매력도별 기준
1. 투자지표 및 밸류에이션 - 같은 업종대비 상대평가. (점수제)
2. 기술적 분석 - 마크미너비니 (SEPA) 추세추종
3. 투자자분석 (개인, 외국인, 기관)
4. 매력도별 보기 - 기술적, 기본적, 총점순으로 각 알약형태로 추가.
```

**중요: 4가지 모두 이미 구현되어 있다.** 이 문서를 참고하는 세션이 처음부터 새로 만들 필요는
없고, 기존 구조를 이해한 뒤 버그 수정·정확도 개선·중복 제거 같은 "다음 단계" 작업을 하면 된다.
아래 "알려진 갭 / 후속 작업 후보" 절 참고.

## 전체 아키텍처 한눈에 보기

| # | 기준 | 상태 | 핵심 파일 | 산출물 |
|---|------|------|-----------|--------|
| 1 | 투자지표·밸류에이션(업종 상대평가, 점수제) | ✅ 구현됨 | `update_daily_charts.ps1` (PowerShell) | 각 종목 페이지 `dp-vscore` 카드 + `index.html`의 `vscore` 필드 |
| 2 | 기술적 분석(Minervini SEPA/Trend Template) | ✅ 구현됨 | `technical_score/*.py` (Python 패키지) | `data/technical_score.json` → `js/chart-common.js`가 렌더 |
| 3 | 투자자분석(개인/외국인/기관) | ✅ 구현됨 (이중 구현) | (a) `update_daily_charts.ps1`의 `dp-investor-flow` 표 (b) `technical_score/investor_flow.py`의 수급점수 | (a) 종목 페이지 표 (b) 기술점수의 별도 트랙(10점) + 위험감점 |
| 4 | 매력도별 보기(기술·기본·총점 알약뱃지) | ✅ 구현됨 | `index.html`의 `renderScoreView()` | 홈페이지 "매력도별 보기" 탭 |

전체 파이프라인 흐름:

```
[매일 실행 — Windows 작업 스케줄러, 서로 독립적인 2개 예약 작업]

  update_daily_charts.ps1                    technical_score/run_daily.py
  ├─ Yahoo Finance 캔들 갱신                  ├─ index.html의 stocks[]에서
  ├─ PER/PBR/Forward PER/배당수익률 재계산    │   종목코드·종목명 로드
  ├─ ROE/EPS성장률/부채비율                   ├─ 종목별 OHLCV 수집(캐시)
  │   (사업보고서 연간 블록 파싱)             ├─ 배치 내 상대강도 백분위 계산
  ├─ 밸류에이션 매력도 점수(vscore) 계산      ├─ 8개 추세조건 + 7개 진입매력도
  │   (업종 내 percentile, 6개 지표)          │   + 위험감점 + 돌파신호 + 수급점수
  ├─ 종목 페이지에 dp-vscore 카드 삽입        └─ data/technical_score.json 저장
  ├─ 종목 페이지에 dp-investor-flow 표 삽입
  │   (네이버 금융 스크래핑, 표시 전용)
  └─ index.html의 stocks[].vscore 동기화

                    ↓                                      ↓
        stocks/*.html (105개 종목 페이지)      data/technical_score.json (전종목 통합)
                    ↓                                      ↓
                          index.html "매력도별 보기" 탭
                    (vscore + technical_score를 합쳐 정렬/뱃지 표시)
```

---

## 1. 투자지표 및 밸류에이션 — 업종 대비 상대평가 (점수제)

**파일**: `update_daily_charts.ps1` (PowerShell, 전 종목 순회 루프 안에서 매일 실행)

### 1-1. 점수 구성 (100점 만점, 2026-08-27 기준 — 최초 6지표에서 `per`가 `fpe`로 교체됨)

```powershell
$scoreMetricDefs = @(
    [PSCustomObject]@{ key='fpe';       label='Forward PER'; weight=25; lowerBetter=$true  }
    [PSCustomObject]@{ key='pbr';       label='PBR';        weight=20; lowerBetter=$true  }
    [PSCustomObject]@{ key='divYield';  label='배당수익률'; weight=15; lowerBetter=$false }
    [PSCustomObject]@{ key='roe';       label='ROE';        weight=15; lowerBetter=$false }
    [PSCustomObject]@{ key='epsGrowth'; label='EPS 성장률'; weight=15; lowerBetter=$false }
    [PSCustomObject]@{ key='debtRatio'; label='재무안전성'; weight=10; lowerBetter=$true  }
)
```

- **금융·보험·증권 업종은 `재무안전성`(부채비율) 지표를 제외**하고 나머지 5개로 100점 재분배
  (은행·보험은 예금·보험부채가 회계상 "부채"로 잡혀 제조업과 의미가 다르기 때문).
- **2026-08-27: 적자로 Forward PER 산출이 불가능한 것으로 확정된 종목은 `fpe` 지표를 통째로
  빼서 나머지 지표 가중치를 부풀리는 대신 0점(최저)으로 채점**(`Update-DpForwardPER`가
  note 텍스트에서 "적자/산출 불가/산정 불가" 문구를 감지해 `fpeIsLoss` 플래그 반환 →
  `valuationCandidates`의 `fpeLoss` 필드로 전달 → 스코어링 루프에서 가중치는 그대로 카운트하고
  score만 0으로 고정). 이전에는 지표 자체를 빼고 나머지로 100점 재분배해서, 만성 적자
  기업이라도 PBR·배당·ROE 등 나머지가 좋으면 총점이 부풀려질 수 있었음 — 이 왜곡을 막기 위한
  변경. 노트 텍스트 패턴이 다른(위 3개 문구가 전혀 없는) 진짜 "데이터 없음" 케이스는 여전히
  지표 제외(가중치 재분배)로 처리됨 — 확정된 적자만 0점 처리 대상.
- 함수: `Get-DpScoreMetrics`(ROE/EPS성장률/부채비율 원본 파싱), `Get-Percentile`(백분위 계산),
  `Set-DpVscoreCard`(카드 렌더링), `Get-DpVscoreGrade`(등급 문자열).

### 1-2. 백분위(percentile) 계산 — `Get-Percentile`

```powershell
function Get-Percentile([double[]]$pool, [double]$myVal, [bool]$lowerBetter) {
    $n = $pool.Count
    if ($n -lt 3) { return $null }   # 업종 내 비교 대상 3개 미만이면 그 지표 자체를 생략
    $worseCount = 0; $equalCount = 0
    foreach ($v in $pool) {
        if ($v -eq $myVal) { $equalCount++ }
        elseif ($lowerBetter -and $v -gt $myVal) { $worseCount++ }
        elseif ((-not $lowerBetter) -and $v -lt $myVal) { $worseCount++ }
    }
    $pct = ($worseCount + ($equalCount - 1) / 2.0) / ($n - 1)   # 동점은 평균 순위 처리
    return [Math]::Min(1.0, [Math]::Max(0.0, $pct))
}
```

- 지표별 점수 = `백분위(0~1) × 가중치`.
- **비교 가능한 지표가 3개 미만이면 카드 자체를 생략**(허위 정밀도 방지 원칙 — 계산 불가한
  종목은 아예 안 보여줌, 임의로 fabricate하지 않음).
- 계산 가능한 지표들의 가중치 합이 100이 안 되면(일부 지표 결측) `scaleFactor = 100 / totalWeight`로
  **비례 재분배**해서 항상 100점 기준으로 정규화.

### 1-3. 업종 그룹핑 (백분위 모집단 확보용, 표시용 업종명과는 별개)

일부 업종은 종목 수가 너무 적어(3개 미만) 백분위 계산이 불가능했던 사례가 있어, **점수 계산
전용으로만** 인접 업종을 합침(`index.html`에 보이는 업종 라벨·업종별 뷰는 그대로 유지):

```powershell
$scoreIndustryGroupMap = @{
    '보험'='금융·은행·증권'; '게임·엔터테인먼트'='인터넷·게임·엔터'; '인터넷·플랫폼'='인터넷·게임·엔터'
    '화학·정유·에너지'='소재·화학·에너지'; '철강·비철금속·소재'='소재·화학·에너지'
    '건설·인프라'='건설·인프라·기계'; '전력·기계·인프라'='건설·인프라·기계'
    '물류·운송'='무역·물류·운송'; '상사·무역'='무역·물류·운송'
    '전자·가전'='반도체·전자'; '지주·투자회사'='지주·복합기업'
}
```

### 1-4. 원본 지표 추출 방식

| 지표 | 소스 |
|------|------|
| PER / Forward PER / PBR / 배당수익률 | 당일 종가 ÷ (EPS/BPS/DPS) — 각 종목 페이지의 `dp-share4`/EPS 게이지에서 이미 파싱해둔 값 재사용 |
| ROE / EPS 성장률 / 부채비율 | **"2. 기본적 분석 — 공시 원문"의 `사업보고서(연간)` 탭**에서 라벨 매칭으로 직접 파싱 (`Get-DpAnnualBlock`으로 `dpFundAnnual` 블록만 스코프 제한 — `dpFundQuarter`(분기/반기) 블록과 라벨이 동일해서 스코프를 안 좁히면 잘못 매칭될 위험이 있었음) |
| 우선주 | 백분위 모집단에서 **제외**(`name -notmatch '우[A-Z]?$'`) — 우선주는 밸류에이션 성격이 보통주와 달라 왜곡 방지 |

ROE/EPS성장률/부채비율 계산식:
```
ROE = 지배주주 순이익 ÷ 자본총계 × 100
EPS 성장률 = (최근연도 EPS - 최초연도 EPS) ÷ |최초연도 EPS| × 100   (dp-eps-flow 3개년 추이 카드 이용)
부채비율 = 부채총계 ÷ 자본총계 × 100
```
라벨 변형이 세션마다 제각각이라(11가지 변형 실측) `$script:DpNetIncomeLabels` 등 배열에
전부 등록해 매칭 — 매칭 실패 시 조용히 `$null` 반환(허위 데이터 생성 금지).

### 1-5. 등급 경계 — `Get-DpVscoreGrade`

```
score >= 80  → "매우 저평가"
score >= 70  → "저평가"
score >= 60  → "다소 저평가"
score >= 40  → "적정 범위"
그 외         → "고평가 또는 재무위험"
```
(JS 쪽 동일 로직: `index.html`의 `vscoreGrade()`, tier는 `tier-cheap`(≥60)/`tier-mid`(40~59)/
`tier-expensive`(<40)로 매핑)

### 1-6. 렌더링 및 홈페이지 동기화

- 종목 페이지: `<!-- dp-vscore:start/end -->` 마커 안에 카드 삽입(`Set-DpVscoreCard`). 삼성전자는
  마커 체계 이전에 수동으로 넣어놔서 마커가 없어 legacy 패턴으로 별도 매칭.
- 홈페이지: `index.html`의 `const stocks = [...]` 배열 각 항목에 `"vscore": N`(또는 `null`) 필드를
  코드 앵커 기반 정규식으로 동기화. **오늘 계산에서 빠진 종목은 이전 값을 그대로 둠**(허위로 null
  덮어쓰지 않음).

---

## 2. 기술적 분석 — Minervini SEPA / Trend Template

**파일**: `technical_score/` 파이썬 패키지 (데이터 수집과 계산이 완전히 분리된 구조)

| 파일 | 역할 |
|------|------|
| `data_collection.py` | OHLCV 수집(디스크 캐시 포함), `FetchResult`/`DataStatus` 정의 |
| `indicators.py` | SMA/RSI(Wilder)/ATR%/52주 고저/조정폭 탐지 등 순수 지표 함수 |
| `trend_qualification.py` | **추세 적격성(40점)** — Minervini Trend Template 8조건 |
| `entry_desirability.py` | **진입 매력도(60점)** — 7개 하위 항목 |
| `risk_penalty.py` | **위험 감점**(음수) — 6개 항목 |
| `breakout_signal.py` | **돌파 신호**(100점 체계와 별도 10점 트랙) |
| `investor_flow.py` | 네이버 금융 스크래핑 + **수급 점수**(별도 10점 트랙) + 개인단독매수 위험감점 |
| `scoring.py` | 위 항목들을 조합하는 오케스트레이션(`evaluate_technical_score`) |
| `batch.py` | 여러 종목을 배치로 평가, 배치 내 상대강도 백분위 계산(`evaluate_batch`) |
| `run_daily.py` | kospi10000 전 종목을 평가해 `data/technical_score.json` 저장(예약 실행 진입점) |

### 2-1. 최종 점수 공식

```
raw_total = 추세적격성 점수(0~40) + 진입매력도 점수(0~60) + 위험감점(음수)
technical_score = clamp(raw_total, 0, 100)
```
돌파신호(0~10)와 수급점수(0~10)는 **100점 본점수에 포함되지 않는 별도 트랙**으로 함께 표시만 됨.

### 2-2. 추세 적격성 — 8개 조건 × 5점 (`trend_qualification.py`)

1. 종가 > 150일선 **and** 종가 > 200일선
2. 150일선 > 200일선
3. 200일선이 22거래일 전보다 높음(상승 기울기)
4. 50일선 > 150일선 **and** 50일선 > 200일선
5. 종가 > 50일선
6. 종가 ≥ 52주 저가 × 1.25
7. 종가 ≥ 52주 고가 × 0.75 (고점 대비 25% 이내)
8. 52주 상대수익률이 배치 내 상위 30%(백분위 ≥ 70)

35점 이상이면 `qualified=true`("우수"). 조건 1·4·3(200일선 상승 여부 포함 필수 3조건)이 전부
충족되지 않으면 `warning: "추세 부적격"` 플래그.

### 2-3. 진입 매력도 — 7개 하위 항목 (`entry_desirability.py`, 합 60점)

| 항목 | 배점 | 요약 산식/구간 |
|------|------|----------------|
| 50일선 이격도 | 8 | (종가/50일선-1)×100 — 0~3%:8점, 3~6%:7점, 6~10%:4점, 10~15%:2점, 초과:0점(50일선 아래면 0점) |
| 52주 고점 접근도 | 8 | (1-종가/52주고가)×100 — 0~5%:7점, 5~10%:8점, 10~15%:6점, 15~20%:3점, 20~25%:1점, 초과:0점 |
| 변동성 축소 | 12 (4×3) | ①최근20일 ATR%<이전20일 ②최근10일<최근20일 ③최근 조정폭<직전 조정폭 — 각 충족 시 4점 |
| 가격 밀집도(10일) | 8 | (10일 최고-최저)/최저×100 — 5%이하:8, ~8%:6, ~12%:4, ~16%:2, 초과:0 (단, 최근10일 거래량이 50일 평균의 20% 미만이면 "거래정지성"으로 판단해 0점 처리) |
| 거래량 고갈 | 7 | 최근5일평균/최근50일평균×100 — 40%이하:7, ~60%:6, ~80%:4, ~100%:2, 초과:0 (단, 최근10일 수익률 < -8%면 "급락 동반"으로 0점 처리) |
| 시장 상대강도(6개월) | 7 | 지수대비 초과수익률의 배치 내 백분위 — 상위10%:7, ~20%:6, ~30%:4, ~50%:2, 하위50%:0 |
| RSI 모멘텀 | 10 | RSI(14) 구간별 기본점수(55~65:10, 50~55:8, 65~70:7, 45~50:5, 70~75:4, 40~45:2, 75+:1, 40미만:0) + 방향성 보정(50~70구간 5일전보다 상승:+1, 50 상향돌파:+2, 70 하향이탈:-1, 50 하향이탈:-2), 최종 0~10 클램프 |

### 2-4. 위험 감점 (`risk_penalty.py`)

| 항목 | 감점 |
|------|------|
| 50일선 이격도 15% 초과 | -10 |
| 최근10일 내 (전일比 -5%↓ & 거래량이 50일평균 초과)인 날 존재 | -10 |
| 종가 < 50일선 | -15 |
| 50일선이 22거래일 전보다 낮음(하락 기울기) | -10 |
| 피벗(최근 20거래일 고가) 돌파 후 재이탈 | -10 |
| 최근20일 평균 ATR% > 이전20일(변동성 확대) | -5 |
| (investor_flow 연동 시) 개인 단독 매수 지속 | -5 |

### 2-5. 돌파 신호 (별도 10점, `breakout_signal.py`)

피벗가 = 오늘 제외 최근 20거래일 최고가. ①종가>피벗(4점) ②돌파일 거래량≥50일평균×1.5(4점)
③당일 종가 위치가 당일 고저 범위의 상단 30% 이내(2점).

### 2-6. 배치 백분위 (`batch.py`)

52주 상대수익률(절대), 6개월 지수대비 초과수익률 — **"평가하려는 배치"(=kospi10000 유니버스)
내에서만** 백분위 계산(전체 상장종목 대상 아님, 호출 비용 절감 목적).

### 2-7. 등급 (`scoring.py: GRADE_BANDS`)

```
85~100 최상급 진입 후보 / 75~84 기술적 매력 우수 / 65~74 관심 종목
50~64 추세 양호·진입 위치 불리 / 0~49 기술적 부적격
```

### 2-8. 유동성 게이트

최근 20거래일 평균 거래대금(종가×거래량) < 5억원이면 평가 자체를 제외(`data_status:
"excluded_low_liquidity"`).

### 2-9. 출력 & 렌더링

- `run_daily.py`가 `data/technical_score.json`에 `{종목코드: 평가결과}` 전체 저장(단일 파일,
  홈페이지가 한 번의 fetch로 전 종목을 다룰 수 있도록).
- 종목 상세 페이지: `js/chart-common.js`의 `initTechnicalScore(code)`가 이 JSON을 fetch해서
  `dp-tscore` 카드 렌더링(1번 아코디언 "기술적 분석" 상단, `dpTscoreBody` 컨테이너).
- update_daily_charts.ps1(PowerShell)과 **완전히 독립된 별도 예약 작업**으로 실행 — 하나가
  실패해도 다른 하나에 영향 없음.

---

## 3. 투자자분석 (개인/외국인/기관)

**이중 구현**이 존재한다 — 목적이 다르다.

### 3-1. 표시 전용 — `update_daily_charts.ps1`

- 네이버 금융(`finance.naver.com/item/frgn.naver?code=...`)에서 최근 10일치 스크래핑.
- 각 종목 페이지 "1. 기술적 분석" 아코디언 하단에 `<!-- dp-investor-flow:start/end -->` 마커로
  표(날짜/개인(근사)/외국인/기관) 삽입. `Get-DpInvestorFlow`, `Build-DpInvestorFlowInner`,
  `Set-DpInvestorFlowSection` 함수.
- 개인 순매매는 원본에 없어 `-(기관+외국인)` 잔차로 근사.
- **점수화되지 않음** — 순수 정보 표시용.

### 3-2. 스코어링용 — `technical_score/investor_flow.py`

- 동일한 네이버 URL을 **별도로** 스크래핑(`fetch_investor_flow`, 최근 10일).
- **수급 점수**(0~10, 별도 트랙): 최근 5거래일 (외국인+기관) 순매매 합 ÷ 최근 20일 평균거래량
  × 100 = 수급강도(%) → `_band_for_intensity`로 점수화:
  ```
  ≥15%: 10점(강한 동반 순매수)  ≥5%: 7점(순매수 우위)  ≥-5%: 4점(중립)
  ≥-15%: 2점(순매도 우위)       그 외: 0점(강한 동반 순매도)
  ```
- **개인 단독 매수 경계 신호**(위험감점 -5): 최근 5거래일 중 4일 이상 "개인(근사)만 순매수,
  외국인+기관 합산은 순매도"이면 트리거. (한국 시장에서 개인 단독 순매수는 역신호로 읽히는
  경우가 많다는 통념 + 개인 수치 자체가 근사치라는 두 가지 이유로, 점수에 직접 반영하지 않고
  "경계 신호" 수준의 약한 감점만 적용)
- 외국인·기관은 "스마트머니" 신호로 취급해 점수화, 개인은 점수에 직접 반영하지 않음.

### 3-3. 알려진 중복

두 구현이 동일한 네이버 엔드포인트를 각자 스크래핑한다 — 통합하면 요청 수를 줄일 수 있으나,
현재는 서로 다른 실행 컨텍스트(PowerShell vs Python, 서로 다른 예약 작업)라 우선순위 낮은
리팩터링 후보로만 남겨둠(아래 "알려진 갭" 참고).

---

## 4. 매력도별 보기 — 기술적·기본적·총점 알약뱃지

**파일**: `index.html` (홈페이지)

### 4-1. UI 진입점

`<button class="view-btn" id="scoreViewBtn">매력도별 보기</button>` — 순위별 보기/업종별 보기와
나란히 있는 3번째 탭 버튼.

### 4-2. 정렬 모드 3가지 — `renderScoreView()`

```js
let scoreSortMode = 'total'; // 'fundamental' | 'technical' | 'total'
```
정렬바 버튼 3개(`score-sort-btn`): **기술적 매력순 / 기본적 매력순 / 총점순**. 클릭 시
`scoreSortMode` 갱신 후 재렌더링.

- `fundamental`: `stock.vscore` 내림차순(technical_score.json 불필요 — fetch 지연 최적화로,
  기본적 매력순만 볼 때는 fetch를 미룸)
- `technical`: `technicalScoreData[code].technical_score` 내림차순
- `total`: `vscore + technical_score`(200점 만점) 내림차순
- 각 모드에서 **정렬에 필요한 점수가 없는 종목은 목록에서 제외**(허위 순위 방지), 제외된 개수를
  하단 안내 문구에 표시.

### 4-3. 알약(pill) 뱃지 구조 — `createScoreRow()`

```html
<div class="score-badge-group dual">
  <div class="score-mini {tier}" title="기본적 매력(밸류에이션)">
    <span class="score-mini-l">기본</span><span class="score-mini-v">{vscore}</span>
  </div>
  <div class="score-mini {tier}" title="기술적 매력(Minervini SEPA/Trend Template)">
    <span class="score-mini-l">기술</span><span class="score-mini-v">{technical_score}</span>
  </div>
  <div class="score-mini total" title="총점(기본+기술)">
    <span class="score-mini-l">총점</span><span class="score-mini-v">{total}</span>
  </div>
</div>
```

- tier 클래스로 색상 구분: `tier-cheap`(초록, 상대적 매력 높음) / `tier-mid`(회색) /
  `tier-expensive`(빨강, 매력 낮음).
  - 기본(vscore) tier: `vscoreGrade()` — ≥60 cheap, 40~59 mid, <40 expensive.
  - 기술(technical) tier: `tscoreGradeTier()` — grade 문자열 매핑("최상급 진입 후보"/"기술적
    매력 우수"→cheap, "관심 종목"/"추세 양호·진입 위치 불리"→mid, 그 외→expensive).
  - 총점 뱃지는 tier 없이 항상 accent 색상 고정(`.score-mini.total`).
- CSS: `.score-mini`(46px 최소폭 세로 flex 박스, 배경 `oklch(0.97 0.004 90)`, radius 8px),
  `.score-mini-l`(8.5px 라벨), `.score-mini-v`(14px 굵은 숫자). 모바일 미디어쿼리에서 각각
  8px/12.5px로 축소.

### 4-4. 행/테이블 구조

`score-table-head` + `score-row`(grid-template-areas: `rank name price change score star`,
6컬럼: 순위/종목명/현재가/등락률/점수뱃지그룹/즐겨찾기). 클릭 시 `stock.page`로 이동, 즐겨찾기
별 버튼은 `stopPropagation()`.

### 4-5. 상호작용

- 즐겨찾기만 보기(`favOnlyActive`), 검색어 필터(`matchesSearch`)와 조합 가능(먼저 필터링 후 정렬).
- 페이지네이션(`RANK_PAGE_SIZE = 10`), 정렬 모드 전환 시 1페이지로 리셋.
- `technicalScoreData`는 최초 tab 클릭 시 1회만 fetch해서 메모리 캐시(이후 재방문 시 재요청 없음).

---

## 알려진 갭 / 후속 작업 후보

이 문서를 읽는 세션이 다음 작업을 요청받았을 때 참고할 것 — **아직 구현되지 않은 게 아니라,
이미 있는 걸 개선하는 작업들**이다.

1. **투자자분석 이중 스크래핑 통합**: PowerShell(`update_daily_charts.ps1`)과
   Python(`investor_flow.py`)이 동일 네이버 URL을 독립적으로 스크래핑. 하나로 통합하거나, 최소한
   한쪽 결과를 다른 쪽이 재사용하도록 캐시 공유를 고려할 수 있음(단, 서로 다른 예약 작업/언어라
   난이도 있음 — 우선순위 낮음).
2. **vscore 산출 근거의 페이지 노출 범위**: vscore는 `dpFundAnnual`(사업보고서 연간) 블록만
   읽는다. 반기/분기 실적 갱신 세션(`stocks/*.html`의 `dpFundQuarter` 블록 갱신)은 vscore 계산에
   영향을 주지 않는다 — 이는 의도된 설계(연 1회 재무제표 기준 유지)이지, 버그가 아님. 다만
   반기보고서가 사업보고서를 대체할 시점(다음 사업연도 정기공시)이 되면 자연히 갱신됨.
3. **총점(vscore+technical_score) 정규화**: 현재 단순 합산(200점 만점). 두 점수의 분포 특성이
   다를 수 있어(예: vscore는 백분위 기반이라 이론상 고르게 분포, technical_score는 조건 충족형이라
   분포가 더 뾰족할 수 있음) 필요 시 표준화(z-score) 방식 도입을 검토할 수 있음 — 다만 현재는
   "1차 버전"으로 명시되어 있어 단순 합산이 의도된 선택일 가능성이 높음.
4. **매력도별 보기의 "SEPA" 표기**: 코드 곳곳의 주석·UI 문구는 "Minervini SEPA/Trend Template"로
   표기되어 있음(`js/chart-common.js`, `data/technical_score.json`의 `grade` 계산 로직 주석 등).
   사용자가 요청 시 "세타"라고 쓴 것은 "SEPA"의 오기로 추정됨.
5. **새 종목 추가 시 vscore/technical_score 최초 계산**: 신규 상장 등으로 `index.html`의
   `stocks[]`에 새 항목이 추가되면, 다음 날 두 예약 작업이 각각 돌 때 자동으로 채워짐(수동 개입
   불필요) — 단, 그 전까지는 `vscore: null` 상태로 "매력도별 보기"에서 제외됨.

## 관련 파일 전체 목록 (빠른 참조)

```
update_daily_charts.ps1              # PowerShell 일일 배치: 캔들/PER/PBR/vscore/투자자매매표 등
technical_score/
  ├─ __init__.py
  ├─ data_collection.py              # OHLCV 수집 + 디스크 캐시
  ├─ indicators.py                   # SMA/RSI/ATR%/52주 고저 등
  ├─ trend_qualification.py          # 추세 적격성 40점(8조건)
  ├─ entry_desirability.py           # 진입 매력도 60점(7항목)
  ├─ risk_penalty.py                 # 위험 감점(6항목)
  ├─ breakout_signal.py              # 돌파 신호 별도 10점
  ├─ investor_flow.py                # 네이버 스크래핑 + 수급점수 별도 10점
  ├─ scoring.py                      # 오케스트레이션(evaluate_technical_score)
  ├─ batch.py                        # 배치 평가 + 상대강도 백분위(evaluate_batch)
  ├─ run_daily.py                    # 실행 진입점 → data/technical_score.json
  └─ tests/                          # 각 모듈별 단위 테스트
data/
  └─ technical_score.json            # 전종목 통합 기술점수 결과(Python 배치 산출물)
js/
  └─ chart-common.js                 # initTechnicalScore() 등 종목 페이지 공통 렌더러
index.html                           # 홈페이지: renderScoreView(), vscoreGrade(), tscoreGradeTier()
stocks/*.html                        # 종목별 상세 페이지(105개) — dp-vscore/dp-tscore/dp-investor-flow 마커
```
