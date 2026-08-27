# 배당수익률 파서(Update-DpDividendYield) 전용 테스트. 실제 stocks/*.html에서 그대로
# 발췌한 블록(V2/Old 포맷, 5개년 배당표+insight 포함)과 실측된 note 텍스트 변형들을 검증한다.

. (Join-Path $PSScriptRoot 'Import-VscoreFunctions.ps1')

$src = Get-VscoreFunctionSource `
    -ScriptVars @('culture', 'DpGaugeScaleOpt', 'DpGaugeFillClass', 'DpGaugeFillStyle', 'DpGaugeWrapOpen', 'DpGaugeInsightOpt', 'DpGaugeInsightPattern') `
    -Names @('FmtWon', 'Get-DpGaugeTierWidth', 'Get-DpGaugeWrapTag', 'Get-DpGaugeInsightHtml', 'Get-DpGaugeRowOnlyV2Pattern', 'Get-DpGaugeRowOnlyV1Pattern', 'Get-DpGaugeRowOnlyOldPattern', 'Find-DpGaugeRowOnlyMatch', 'Build-DpGaugeRowOnlyV2', 'Build-DpGaugeRowOnlyOld', 'Update-DpDividendYield')

$tmpPath = [System.IO.Path]::GetTempFileName() + '.ps1'
[System.IO.File]::WriteAllText($tmpPath, $src, (New-Object System.Text.UTF8Encoding($true)))
. $tmpPath
Remove-Item $tmpPath -Force

function Log([string]$m) { [Console]::Out.WriteLine("  [LOG] $m") }

$script:pass = 0; $script:fail = 0
function Check([string]$name, $actual, $expected) {
    if ("$actual" -eq "$expected") { $script:pass++; Write-Output "OK   $name" }
    else { $script:fail++; Write-Output "FAIL $name : expected=[$expected] actual=[$actual]" }
}

Write-Output "=== Update-DpDividendYield ==="

# 실제 001_005930.html 배당 블록(V2, insight+5개년 배당표 포함) 그대로 발췌
$case1 = @'
        <div class="dp-gauge dp-metric-detail" data-metric="div">
          <div class="dp-gauge-row">
            <div class="dp-gauge-nm">배당수익률</div>
            <div class="dp-gauge-note">DPS 1,668원 ÷ 247,500원 · 성장주 성격상 배당보다 이익 성장에 방점.</div>
            <div class="dp-gauge-val">0.67%</div>
            <div class="dp-gauge-bar">
              <div class="dp-gauge-scale"><span>0%</span><span>2%</span><span>4%</span></div>
              <div class="dp-gauge-track"><div class="dp-gauge-fill tier-mid" style="width:17%;background:oklch(0.545 0.19 62.9);"></div></div>
            </div>
          </div>
          <div class="dp-insight" style="margin-top:12px;">
            <div class="dp-insight-t">해석</div>
            <div class="dp-insight-b">시중금리 대비 낮은 수준이며, 배당보다 재투자를 통한 이익 성장에 무게를 두는 성장주 성격을 반영.</div>
          </div>
          <div style="margin-top:14px;">
            <div class="dp-metrics-right-h" style="margin-bottom:6px;">최근 5개년 배당금 (보통주, 분기배당 4회 합산)</div>
            <table style="width:100%;border-collapse:collapse;">
              <tbody>
                <tr><td class="dp-cons-td">2025</td><td class="dp-cons-td">1,668원</td></tr>
              </tbody>
            </table>
          </div>
        </div>
'@
$c, $y, $s = Update-DpDividendYield $case1 266000 "001_005930.html"
Check "V2+표 실제블록 yield" ([Math]::Round($y,2)) "0.63"
Check "V2+표 실제블록 status" $s "valid"
Check "V2+표 5개년표 보존" ($c -match '최근 5개년 배당금') "True"
Check "V2+표 insight 보존" ($c -match '시중금리 대비 낮은 수준') "True"
Check "V2+표 현재가 최신화" ($c -match '266,000원') "True"
Check "V2+표 과거가 제거됨" ($c -notmatch '247,500') "True"
Check "V2+표 tail 보존" ($c -match '성장주 성격상 배당보다 이익 성장에 방점') "True"

# 실제 002_000660.html 배당 블록(Old 포맷, insight+5개년 배당표 포함), DPS(보통주)
$case2 = @'
        <div class="dp-gauge dp-metric-detail" data-metric="div">
              <div class="dp-gauge-h"><span>배당수익률</span><span>0.18%</span></div>
              <div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:4%;"></div></div>
              <div class="dp-gauge-note">DPS(보통주) 3,000원 ÷ 1,668,000원 · 배당성향 4.90%로 이익 규모 대비 매우 보수적.</div>
              <div class="dp-insight" style="margin-top:12px;">
                <div class="dp-insight-t">해석</div>
                <div class="dp-insight-b">배당수익률이 낮은 편으로, 배당보다는 재투자를 통한 이익 성장에 무게를 두는 성향으로 해석됨.</div>
              </div>
              <div style="margin-top:14px;">
                <div class="dp-metrics-right-h" style="margin-bottom:6px;">최근 5개년 배당금 (보통주)</div>
                <table style="width:100%;border-collapse:collapse;">
                  <tbody>
                    <tr><td class="dp-cons-td">2025</td><td class="dp-cons-td">3,000원</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
'@
$c, $y, $s = Update-DpDividendYield $case2 1688000 "002_000660.html"
Check "Old+표 실제블록 status" $s "valid"
Check "Old+표 라벨주석 보존" ($c -match 'DPS\(보통주\)') "True"
Check "Old+표 5개년표 보존" ($c -match '최근 5개년 배당금') "True"
Check "Old+표 insight 보존" ($c -match '배당수익률이 낮은 편으로') "True"
Check "Old+표 현재가 최신화" ($c -match '1,688,000원') "True"

# DPS 0원 (나눗셈 표기 있음, 유효한 무배당)
$case3 = '<div class="dp-gauge dp-metric-detail" data-metric="div"><div class="dp-gauge-row"><div class="dp-gauge-nm">배당수익률</div><div class="dp-gauge-note">DPS 0원 ÷ 429,000원 · 2025년 순손실로 배당 중단.</div><div class="dp-gauge-val">0.00%</div><div class="dp-gauge-bar"><div class="dp-gauge-scale"><span>0%</span><span>2%</span><span>4%</span></div><div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:2%;"></div></div></div></div></div>'
$c, $y, $s = Update-DpDividendYield $case3 400000 "test.html"
Check "DPS 0원(÷있음) yield" $y "0"
Check "DPS 0원(÷있음) status=zero_dividend" $s "zero_dividend"

# DPS 0원 (나눗셈 표기 없음)
$case4 = '<div class="dp-gauge dp-metric-detail" data-metric="div"><div class="dp-gauge-h"><span>배당수익률</span><span>0.00%</span></div><div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:0%;"></div></div><div class="dp-gauge-note">DPS 0원 - 무배당, 이익 전액 재투자·유보 기조.</div></div>'
$c, $y, $s = Update-DpDividendYield $case4 50000 "test.html"
Check "DPS 0원(÷없음) status=zero_dividend" $s "zero_dividend"
Check "DPS 0원(÷없음) tail 보존" ($c -match '무배당, 이익 전액 재투자') "True"

# DPS 100원(구주 기준)
$case5 = '<div class="dp-gauge dp-metric-detail" data-metric="div"><div class="dp-gauge-row"><div class="dp-gauge-nm">배당수익률</div><div class="dp-gauge-note">DPS 100원(구주 기준) ÷ 155,100원 · 시세차익 중심 종목.</div><div class="dp-gauge-val">0.06%</div><div class="dp-gauge-bar"><div class="dp-gauge-scale"><span>0%</span><span>2%</span><span>4%</span></div><div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:2%;"></div></div></div></div></div>'
$c, $y, $s = Update-DpDividendYield $case5 160000 "test.html"
Check "DPS 값 뒤 괄호주석 status" $s "valid"
Check "DPS 값 뒤 괄호주석 보존" ($c -match '100원\(구주 기준\)') "True"

# DPS(보통주) N원 / 현재가 접두
$case6 = '<div class="dp-gauge dp-metric-detail" data-metric="div"><div class="dp-gauge-row"><div class="dp-gauge-nm">배당수익률</div><div class="dp-gauge-note">DPS(보통주) 19,500원 ÷ 현재가 648,000원 · 배당성향 41.1%로 3년 연속 증가 기조.</div><div class="dp-gauge-val">3.01%</div><div class="dp-gauge-bar"><div class="dp-gauge-scale"><span>0%</span><span>2%</span><span>4%</span></div><div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:75%;"></div></div></div></div></div>'
$c, $y, $s = Update-DpDividendYield $case6 660000 "test.html"
Check "라벨주석+현재가접두 status" $s "valid"
Check "라벨주석+현재가접두 라벨 보존" ($c -match 'DPS\(보통주\)') "True"

# 게이지 자체가 없음 -> missing (데이터없음/파싱실패 구분: 게이지 자체 부재는 missing)
$case7 = '<div class="dp-gauge" data-metric="roe"><div class="dp-gauge-row"><div class="dp-gauge-nm">ROE</div></div></div>'
$c, $y, $s = Update-DpDividendYield $case7 100000 "test.html"
Check "게이지 없음 status=missing" $s "missing"
Check "게이지 없음 value=null" ($null -eq $y) "True"

# note 형식 자체를 인식 못하는 경우 -> parse_error (missing과 구분)
$case8 = '<div class="dp-gauge dp-metric-detail" data-metric="div"><div class="dp-gauge-row"><div class="dp-gauge-nm">배당수익률</div><div class="dp-gauge-note">알 수 없는 형식의 텍스트입니다.</div><div class="dp-gauge-val">-</div><div class="dp-gauge-bar"><div class="dp-gauge-scale"><span>0%</span><span>2%</span><span>4%</span></div><div class="dp-gauge-track"><div class="dp-gauge-fill" style="width:2%;"></div></div></div></div></div>'
$c, $y, $s = Update-DpDividendYield $case8 100000 "test.html"
Check "인식불가 note status=parse_error" $s "parse_error"

Write-Output ""
Write-Output "TOTAL dividend: pass=$script:pass fail=$script:fail"
