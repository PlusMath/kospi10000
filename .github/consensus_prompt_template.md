너는 kospi10000 정적 사이트(현재 저장소 체크아웃, main 브랜치)의 종목 상세 리포트 파일들에서
"N. 애널리스트 컨센서스" 아코디언 섹션만 실제 증권사 리포트 기준으로 다시 조사해서 갱신하는
주간 루틴이다. 이 저장소를 처음 보는 상태이므로 아래 설명을 정확히 따를 것.

## 이번에 처리할 파일 목록 (총 %%BATCH_COUNT%%개, 반드시 이 순서/전체를 처리)
%%BATCH_LIST%%

## 각 파일의 구조
각 파일은 `<div class="dp-acc" id="dpAcc-consensus">` 블록 안에 다음 구조를 가진다 (없는 파일도 있음 — 커버리지가
얕아서 원래 생략된 경우):
```
<div class="dp-acc" id="dpAcc-consensus">
  <button class="dp-acc-h" onclick="dpToggle('consensus')"><span>N. 애널리스트 컨센서스</span><span class="dp-acc-chev">▾</span></button>
  <div class="dp-acc-body">
    <table>
      <thead><tr>
        <th class="dp-cons-th">증권사</th>
        <th class="dp-cons-th" style="text-align:right;">목표주가</th>
        <th class="dp-cons-th" style="text-align:center;">의견</th>
        <th class="dp-cons-th" style="text-align:right;">작성일</th>
      </tr></thead>
      <tbody>
        <tr><td class="dp-cons-td"><a href="실제 리포트/기사 URL" target="_blank" rel="noopener">증권사명</a></td><td class="dp-cons-td" style="text-align:right;font-weight:700;">NNN,NNN원</td><td class="dp-cons-td" style="text-align:center;"><span class="dp-cons-badge">매수</span></td><td class="dp-cons-td" style="text-align:right;color:var(--dp-text4);">YY.MM.DD</td></tr>
        ... (증권사 수만큼 반복 — 증권사명은 항상 <a href="..."> 로 감싸야 함, 예시 아님, 실제 규칙)
      </tbody>
    </table>
    <div class="dp-cons-summary">
      <div><span style="color:var(--dp-text3);">평균 목표주가</span> <strong>NNN,NNN원</strong></div>
      <div><span style="color:var(--dp-text3);">현재가 대비</span> <strong style="color:var(--dp-up);">+NN.N%</strong></div>
    </div>
  </div>
</div>
```
`stocks/001_005930.html`(삼성전자)을 열어서 정확한 형태를 참고할 것. 이 섹션의 `SECTION_IDS` 참조는 파일 하단
`<script>`의 `const SECTION_IDS = ['tech','fund','valuation','timeline','thesis','consensus'];` 배열에 있다
(컨센서스 섹션이 없는 파일은 이 배열에 'consensus'가 빠져 있음).

## 자료 조사 우선순위 (반드시 이 순서로, 절대 지어내지 말 것)
1. **한경컨센서스 (hkconsensus.hankyung.com)** — 종목명/코드로 검색해서 실제 리포트의 증권사명·목표주가·투자의견·
   발행일을 확인. 리포트 상세 페이지 URL을 링크로 사용.
2. **네이버증권 종목분석 탭** (`https://finance.naver.com/item/main.naver?code=CODE` 의 "투자의견"/"리포트" 섹션)
   — 1번에서 못 찾은 리포트나 교차 확인용. 리포트 링크가 있으면 그 URL을 사용.
3. **집계 서비스(Investing.com, FnGuide 등)** — 위 두 곳에서 개별 리포트를 3개 미만 찾았을 때만 보조로 사용.
   이 경우 개별 증권사 행을 지어내지 말고, "컨센서스 평균/최고/최저" 같은 집계 행으로 표시하고 그 집계 페이지로
   링크할 것 (`stocks/004_005935.html`의 삼성전자우 컨센서스 섹션이 이 패턴의 예시).

## 절대 규칙
- **모든 행의 증권사명(또는 집계 항목명)은 반드시 `<a href="실제 URL" target="_blank" rel="noopener">이름</a>`로
  감싼다. 하이퍼링크 없는 행은 절대 작성/유지하지 말 것.** 이건 부가 옵션이 아니라 이 섹션을 쓰는 이유 자체다 —
  링크 없이 숫자만 있는 행을 쓸 바엔 차라리 그 행을 빼라. 파일을 저장하기 직전 `grep -c '<a href' <파일>`로
  이번에 작성한 행 수만큼 `<a href`가 실제로 들어갔는지 반드시 확인할 것.
- 증권사명, 목표주가, 투자의견, 날짜 중 **하나라도 실제로 확인하지 못했다면 그 행 전체를 만들지 말 것**.
  날짜를 정확히 못 찾겠으면 "26.07 리포트"처럼 월 단위로만 표기하거나, 아예 그 리포트는 포함하지 말 것.
  절대로 정확한 날짜/가격/증권사명을 추측해서 채우지 말 것.
- 최신 리포트가 없거나(6개월 이상 지난 리포트뿐이거나) 종목 자체에 대한 커버리지가 거의 없으면, 억지로 채우지
  말고 그 파일은 "SKIP: 사유"로 보고하고 넘어갈 것. 기존 섹션이 이미 있었다면 건드리지 말고 그대로 둘 것
  (더 나쁜 정보로 덮어쓰지 말 것).
- 이 섹션(`dpAcc-consensus` 블록 및 필요시 `SECTION_IDS` 배열 안의 'consensus' 항목) **외의 다른 어떤 내용도
  수정하지 말 것** — 캔들 데이터, 재무 수치, 기술적분석, 투자포인트, CSS, JS 함수 등 전부 그대로 둘 것.
- 파일 하나를 완전히 끝내고(검증까지) 다음 파일로 넘어갈 것. 작업 중 중단되더라도 반쪽 상태로 저장하지 말 것 —
  못 끝냈으면 그 파일은 아예 건드리지 않은 상태로 남겨둘 것.
- **git add/commit/push는 하지 말 것** — 파일 편집까지만 하면 되고, 커밋/푸시는 이 워크플로의 이후 단계가
  자동으로 처리한다. git 상태를 바꾸는 명령은 실행하지 말 것.

## 파일별 검증 (수정 직후 매번)
- 이번에 작성/수정한 모든 `dp-cons-td` 행에 `<a href` 하이퍼링크가 실제로 들어갔는지 `grep`으로 확인. 하나라도
  빠졌으면 그 파일을 다시 고칠 것 — 이 확인을 건너뛰고 다음 파일로 넘어가지 말 것.
- `<div`/`</div>` 개수가 수정 전후로 "추가한 행 수 × 그 행 안의 div 개수"만큼만 차이 나는지 확인 (즉 의도한 부분
  외에는 balance가 깨지지 않았는지).
- `<script`/`</script>` 개수는 여전히 2/2.
- 수정한 부분 외의 다른 섹션(기술적분석/기본적분석/투자지표/시계열이벤트/투자포인트)이 한 글자도 안 바뀌었는지
  `git diff`로 확인.

## 완료 후
파일 편집을 전부 마치면(또는 스킵 판단까지 마치면), 짧은 요약을 출력하고 종료할 것: 몇 개 갱신했는지,
스킵한 파일과 사유, 사용한 출처 URL 목록. git add/commit/push는 절대 직접 하지 말 것.
