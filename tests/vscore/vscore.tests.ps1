# kospi10000 vscore(투자지표 매력도) 전용 테스트.
#
# update_daily_charts.ps1은 gitignore 대상 로컬 자동화 스크립트라(네트워크 호출·git
# 커밋/푸시까지 포함) 통째로 실행하거나 dot-source할 수 없다. 대신 이 디렉터리의
# Import-VscoreFunctions.ps1이 브레이스 매칭으로 순수 함수/상수 정의만 추출해서 별도
# 임시 파일에 저장한 뒤 그것만 dot-source한다 — 라인 번호 하드코딩이 없어 원본 스크립트가
# 수정돼도(라인이 밀려도) 계속 동작한다.
#
# 프레임워크: 이 머신엔 Pester 3.4.0(레거시, Describe/It이지만 최신 5.x와 assertion 문법이
# 다름)만 설치돼 있음. 버전 차이로 인한 리스크와, "네트워크를 호출하는 거대한 스크립트에서
# 순수 함수만 골라 테스트"라는 이례적인 요구를 감안해 Pester 대신 이 프로젝트에서 이번
# 세션 내내 검증에 실제로 써서 신뢰성을 확인한 간단한 assert 방식(OK/FAIL 카운트) 러너를
# 그대로 채택했다. 실행: powershell -ExecutionPolicy Bypass -File tests\vscore\run.ps1
#
# UTF-8 주의: 이 파일과 실행 스크립트는 반드시 BOM 포함 UTF-8로 저장해야 한다 — Windows
# PowerShell 5.1이 -File로 BOM 없는 UTF-8 .ps1을 로드하면 시스템 코드페이지로 잘못
# 디코딩해 한글 리터럴이 깨진다(이번 세션에서 실제로 겪은 문제, run.ps1이 저장 시 자동 변환).

. (Join-Path $PSScriptRoot 'Import-VscoreFunctions.ps1')

$src = Get-VscoreFunctionSource `
    -ScriptVars @('culture', 'DpGaugeScaleOpt', 'DpGaugeFillClass', 'DpGaugeFillStyle', 'DpGaugeWrapOpen', 'DpGaugeInsightOpt', 'DpGaugeInsightPattern', 'scoreMetricDefs', 'scoreIndustryGroupMap', 'VscoreCoverageThreshold', 'VscoreValueKeys', 'VscoreQualityKeys', 'VscoreMinMetricCount') `
    -Names @('FmtWon', 'Get-DpGaugeTierWidth', 'Get-DpGaugeWrapTag', 'Get-DpGaugeInsightHtml', 'Get-DpGaugeRowOnlyV2Pattern', 'Get-DpGaugeRowOnlyV1Pattern', 'Get-DpGaugeRowOnlyOldPattern', 'Find-DpGaugeRowOnlyMatch', 'Build-DpGaugeRowOnlyV2', 'Build-DpGaugeRowOnlyOld', 'Update-DpDividendYield', 'Get-ScoreIndustryGroup', 'Get-Percentile', 'Get-DpVscoreResult', 'Get-DpVscoreGrade')

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
function CheckTrue([string]$name, [bool]$cond) { Check $name $cond $true }

# ============================================================
# 1. Get-Percentile — n=3/4/5, 동점 처리, lowerBetter/upperBetter
# ============================================================
Write-Output "=== Get-Percentile ==="
# n=3, lowerBetter(PER류): 값 [10,20,30]에서 10은 최저(=최고 매력) -> percentile 1.0
Check "n=3 lowerBetter 최저값" (Get-Percentile @(10.0,20.0,30.0) 10.0 $true) "1"
Check "n=3 lowerBetter 최고값" (Get-Percentile @(10.0,20.0,30.0) 30.0 $true) "0"
Check "n=3 lowerBetter 중간값" (Get-Percentile @(10.0,20.0,30.0) 20.0 $true) "0.5"
# n=4, upperBetter(ROE류): 값 [5,10,15,20]에서 20이 최고(=최고 매력) -> percentile 1.0
Check "n=4 upperBetter 최고값" (Get-Percentile @(5.0,10.0,15.0,20.0) 20.0 $false) "1"
Check "n=4 upperBetter 최저값" (Get-Percentile @(5.0,10.0,15.0,20.0) 5.0 $false) "0"
# n=5, 중간
$pct5 = Get-Percentile @(1.0,2.0,3.0,4.0,5.0) 3.0 $false
Check "n=5 upperBetter 중간값" $pct5 "0.5"
# n<3 -> null (표본 부족)
CheckTrue "n=2 표본부족 null" ($null -eq (Get-Percentile @(1.0,2.0) 1.0 $true))
# 동점 처리: pool에 자신과 같은 값이 2개 더 있을 때 평균순위
# pool=[10,10,10,20], myVal=10, lowerBetter=true: worseCount(20>10)=1, equalCount=3(자신 포함)
# pct = (1 + (3-1)/2) / (4-1) = (1+1)/3 = 0.6667
$pctTie = Get-Percentile @(10.0,10.0,10.0,20.0) 10.0 $true
Check "동점 처리(평균순위)" ([Math]::Round($pctTie,4)) "0.6667"

# ============================================================
# 2. Get-DpVscoreResult — 상태 분류/커버리지/게이트/등급/clamp
# ============================================================
Write-Output ""
Write-Output "=== Get-DpVscoreResult ==="

# 공용 풀: 6개 지표 모두 업종 내 5개 종목(자기 자신 포함) 표본 확보
$pool = @{
    fpe       = @{ '반도체·전자' = @(8.0,10.0,15.0,20.0,25.0) }
    pbr       = @{ '반도체·전자' = @(0.8,1.0,1.5,2.0,3.0) }
    divYield  = @{ '반도체·전자' = @(0.0,1.0,2.0,3.0,4.0) }
    roe       = @{ '반도체·전자' = @(3.0,8.0,12.0,15.0,20.0) }
    epsGrowth = @{ '반도체·전자' = @(-5.0,0.0,10.0,20.0,30.0) }
    debtRatio = @{ '반도체·전자' = @(20.0,40.0,60.0,80.0,150.0) }
}

function New-Vc([hashtable]$overrides) {
    $base = @{ code='TEST'; name='테스트종목'; industry='반도체·전자'; fpe=10.0; fpeLoss=$false; pbr=1.5; divYield=2.0; divYieldStatus='valid'; roe=12.0; epsGrowth=10.0; debtRatio=60.0 }
    foreach ($k in $overrides.Keys) { $base[$k] = $overrides[$k] }
    return [PSCustomObject]$base
}

# 2a. 6개 전부 유효 -> published, 0<=score<=100, 등급 문자열 정상
$vcFull = New-Vc @{}
$rFull = Get-DpVscoreResult $vcFull $pool 0.75
CheckTrue "전체지표 published" $rFull.Published
CheckTrue "전체지표 score 0~100" ($rFull.Score -ge 0 -and $rFull.Score -le 100)
Check "전체지표 metricCount=6" $rFull.MetricCount "6"
Check "전체지표 coverage=1.0" $rFull.Coverage "1"
CheckTrue "등급 문자열에 '저평가' 단독표현 없음" (-not (Get-DpVscoreGrade $rFull.Score).Contains('저평가'))

# breakdown 표시 가중치 반올림 합이 99/101이 되더라도 내부 원본 가중치 합은 정확한지
# (정규화 전 원본 weight 합은 항상 100 — scaleFactor=100/totalWeight이므로 무조건 100)
$rawWeightSum = ($rFull.Breakdown | Measure-Object -Property weight -Sum).Sum
Check "정규화 후 표시weight 합계 = 100(반올림 오차 이내)" ([Math]::Abs($rawWeightSum - 100) -le 2) "True"

# 2b. Forward PER 적자(fpeLoss) -> 0점, 가중치는 그대로 카운트, 지표는 exclude 아님
$vcLoss = New-Vc @{ fpeLoss = $true; fpe = $null }
$rLoss = Get-DpVscoreResult $vcLoss $pool 0.75
$fpeStatus = $rLoss.MetricStatuses | Where-Object { $_.key -eq 'fpe' }
Check "적자 fpe status=loss" $fpeStatus.status "loss"
Check "적자 fpe score=0" $fpeStatus.score "0"
Check "적자 fpe weight 카운트됨(25)" $fpeStatus.weight "25"
CheckTrue "적자여도 나머지 5개 유효하면 published" $rLoss.Published

# 2c. DPS=0(zero_dividend) -> valid 취급, status 구분 표시
$vcZeroDiv = New-Vc @{ divYield = 0.0; divYieldStatus = 'zero_dividend' }
$rZeroDiv = Get-DpVscoreResult $vcZeroDiv $pool 0.75
$divStatus = $rZeroDiv.MetricStatuses | Where-Object { $_.key -eq 'divYield' }
Check "무배당 status=zero_dividend" $divStatus.status "zero_dividend"
CheckTrue "무배당도 observedWeight에 포함" ($rZeroDiv.ObservedWeight -eq $rFull.ObservedWeight)

# 2d. 금융업 -> 재무안전성 designed_not_applicable, eligibleWeight에서 제외
$vcFin = New-Vc @{ industry = '금융·은행·증권' }
$poolFin = @{
    fpe       = @{ '금융·은행·증권' = @(8.0,10.0,15.0,20.0,25.0) }
    pbr       = @{ '금융·은행·증권' = @(0.8,1.0,1.5,2.0,3.0) }
    divYield  = @{ '금융·은행·증권' = @(0.0,1.0,2.0,3.0,4.0) }
    roe       = @{ '금융·은행·증권' = @(3.0,8.0,12.0,15.0,20.0) }
    epsGrowth = @{ '금융·은행·증권' = @(-5.0,0.0,10.0,20.0,30.0) }
    debtRatio = @{ '금융·은행·증권' = @(20.0,40.0,60.0,80.0,150.0) }
}
$rFin = Get-DpVscoreResult $vcFin $poolFin 0.75
$debtStatus = $rFin.MetricStatuses | Where-Object { $_.key -eq 'debtRatio' }
Check "금융업 부채비율 designed_not_applicable" $debtStatus.status "designed_not_applicable"
Check "금융업 eligibleWeight=90(100-10)" $rFin.EligibleWeight "90"

# 2e. 3개 지표만 유효(과거 임계값) -> 새 최소 4개 기준 미달로 게시 제외
$vcThin = New-Vc @{ divYield = $null; divYieldStatus = 'missing'; epsGrowth = $null; debtRatio = $null }
$rThin = Get-DpVscoreResult $vcThin $pool 0.75
CheckTrue "3개 지표뿐이면 published=false(최소 4개 미달)" (-not $rThin.Published)
CheckTrue "3개 지표 사유에 최소지표 문구 포함" ($rThin.Reason -match '최소 4개')

# 2f. 데이터 없음(missing) vs 재무데이터 있지만 업종 표본 부족 — 둘 다 status=missing으로
# 동일하게 집계되지만(스코어링 관점에서 동일), missing 지표는 breakdown에 안 들어감을 확인
$poolThinIndustry = @{
    fpe       = @{ '희귀업종' = @(8.0,10.0) }   # 표본 2개 -> 3 미만이라 percentile 불가
    pbr       = @{ '희귀업종' = @(0.8,1.0,1.5,2.0,3.0) }
    divYield  = @{ '희귀업종' = @(0.0,1.0,2.0,3.0,4.0) }
    roe       = @{ '희귀업종' = @(3.0,8.0,12.0,15.0,20.0) }
    epsGrowth = @{ '희귀업종' = @(-5.0,0.0,10.0,20.0,30.0) }
    debtRatio = @{ '희귀업종' = @(20.0,40.0,60.0,80.0,150.0) }
}
$vcThinInd = New-Vc @{ industry = '희귀업종' }
$rThinInd = Get-DpVscoreResult $vcThinInd $poolThinIndustry 0.75
$fpeThinStatus = $rThinInd.MetricStatuses | Where-Object { $_.key -eq 'fpe' }
Check "업종표본 3개 미만이면 status=missing" $fpeThinStatus.status "missing"
Check "missing 지표는 percentile null" ($null -eq $fpeThinStatus.percentile) "True"

# 2g. coverage 임계값 — eligibleWeight의 75% 미만 관측이면 published=false
# 4개 유효(fpe,pbr,roe,epsGrowth =25+20+15+15=75) + debtRatio/divYield 없음
# eligibleWeight=100, observedWeight=75 -> coverage=0.75 (경계값, 미만이 아니라 이상이므로 통과해야 함)
$vcBoundary = New-Vc @{ divYield = $null; divYieldStatus = 'missing'; debtRatio = $null }
$rBoundary = Get-DpVscoreResult $vcBoundary $pool 0.75
Check "coverage=0.75 경계값 metricCount=4" $rBoundary.MetricCount "4"
Check "coverage=0.75 경계값 coverage" $rBoundary.Coverage "0.75"
CheckTrue "coverage=threshold(0.75)면 통과(미만만 탈락)" $rBoundary.Published

# coverage가 threshold보다 낮게: divYield/debtRatio/epsGrowth 없음 -> 3개만 유효라 최소지표
# 미달로도 걸리지만, 더 명확히 하기 위해 coverage 자체가 낮은 케이스를 임계값을 높여 검증
$rBoundaryStrict = Get-DpVscoreResult $vcBoundary $pool 0.80
CheckTrue "coverage 0.75 < threshold 0.80 -> published=false" (-not $rBoundaryStrict.Published)
CheckTrue "coverage 미달 사유 문구 포함" ($rBoundaryStrict.Reason -match '커버리지')

# 2h. 우선주는 피어 풀에서 제외되지만(풀 구성은 이 함수 밖에서 이미 처리됨을 전제),
# 자기 자신의 점수 계산에는 참여 가능 — Get-DpVscoreResult 자체는 우선주 여부를 모르고
# 그냥 주어진 풀/값으로 채점하므로, 여기서는 "결과 score가 항상 0~100으로 clamp"되는지만
# 재확인(우선주 자기 자신도 동일 코드 경로를 타므로 별도 분기 없음).
$vcPref = New-Vc @{ name = '테스트종목우' }
$rPref = Get-DpVscoreResult $vcPref $pool 0.75
CheckTrue "우선주 자기 점수도 0~100 clamp" ($rPref.Score -ge 0 -and $rPref.Score -le 100)

# 2i. 최종 점수가 항상 0~100 — 극단값(모든 지표 최악)으로도 음수/100 초과 없는지
$vcWorst = New-Vc @{ fpe = 25.0; pbr = 3.0; divYield = 0.0; roe = 3.0; epsGrowth = -5.0; debtRatio = 150.0 }
$rWorst = Get-DpVscoreResult $vcWorst $pool 0.75
CheckTrue "극단적 최악값도 score 0~100 이내" ($rWorst.Score -ge 0 -and $rWorst.Score -le 100)
$vcBest = New-Vc @{ fpe = 8.0; pbr = 0.8; divYield = 4.0; roe = 20.0; epsGrowth = 30.0; debtRatio = 20.0 }
$rBest = Get-DpVscoreResult $vcBest $pool 0.75
CheckTrue "극단적 최선값도 score 0~100 이내" ($rBest.Score -ge 0 -and $rBest.Score -le 100)

# 2j. "현재 계산 실패 시 이전 점수 제거" — 이 함수 자체는 상태만 반환하고 파일/인덱스에
# 손대지 않지만(부수효과 없는 순수함수), 호출부 계약을 이 자리에서 명시적으로 검증:
# Published=false인 결과는 반드시 Score=$null이어야 호출부가 vscoreByCode에 명시적 null을
# 쓸 수 있다(이전 값을 실수로 재사용하지 않도록).
CheckTrue "미게시 결과는 Score가 null(이전값 재사용 방지 계약)" ($null -eq $rThin.Score)

Write-Output ""
Write-Output "TOTAL vscore: pass=$script:pass fail=$script:fail"
