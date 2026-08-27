# update_daily_charts.ps1(gitignore 대상, 네트워크 호출 포함)에서 순수 함수/상수 정의만
# 이름으로 뽑아내 별도 프로세스에서 dot-source 가능한 텍스트로 반환한다. 라인 번호를
# 하드코딩하지 않고 매번 브레이스 매칭으로 찾기 때문에, 원본 스크립트가 수정돼 라인이
# 밀려도 테스트가 깨지지 않는다(라인 번호 기반 sed 추출은 스크립트가 바뀔 때마다 다시
# 잡아야 해서 깨지기 쉬움 — 이 프로젝트에서 여러 번 겪은 문제).
#
# 사용법:
#   $src = Get-VscoreFunctionSource -Names @('Get-Percentile','Get-DpVscoreResult') `
#                                    -ScriptVars @('scoreMetricDefs','VscoreCoverageThreshold')
#   $src | Out-File $tempPath -Encoding utf8   # 반드시 BOM 포함(UTF8Encoding($true))으로 저장
#   . $tempPath

function Get-VscoreScriptPath {
    Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'update_daily_charts.ps1'
}

# 지정된 이름의 "function Name(...) { ... }" 블록 전체를 브레이스 매칭으로 추출.
function Get-FunctionSource([string]$fullText, [string]$name) {
    $sigPattern = "(?m)^function\s+$([regex]::Escape($name))\b"
    $m = [regex]::Match($fullText, $sigPattern)
    if (-not $m.Success) { throw "function '$name' not found in source" }
    $openBraceIdx = $fullText.IndexOf('{', $m.Index)
    if ($openBraceIdx -lt 0) { throw "no opening brace found for function '$name'" }
    $depth = 0
    $i = $openBraceIdx
    while ($i -lt $fullText.Length) {
        $ch = $fullText[$i]
        if ($ch -eq '{') { $depth++ }
        elseif ($ch -eq '}') {
            $depth--
            if ($depth -eq 0) { return $fullText.Substring($m.Index, $i - $m.Index + 1) }
        }
        $i++
    }
    throw "unbalanced braces for function '$name'"
}

# 지정된 이름의 "$Name = ..." 또는 "$script:Name = ..." 대입문을 추출. 값이 @(...)/@{...}처럼
# 여는 괄호로 시작하면(예: $scoreMetricDefs = @( ... 여러 줄 ... )) 괄호 매칭으로 끝을 찾고,
# 아니면(한 줄짜리 문자열/숫자 리터럴) 그 줄 끝까지만 취한다 — 첫 줄만 잘라내면 배열/해시
# 상수가 중간에 끊겨 이후 dot-source 전체가 깨지는 사고가 실제로 났었음.
function Get-ScriptVarSource([string]$fullText, [string]$name) {
    $pattern = "(?m)^\`$(?:script:)?$([regex]::Escape($name))\s*="
    $m = [regex]::Match($fullText, $pattern)
    if (-not $m.Success) { throw "script var '$name' not found in source" }
    $valueStart = $m.Index + $m.Length
    # 값 시작 직후의 공백을 건너뛰고 첫 비공백 문자(들)를 확인
    $i = $valueStart
    while ($i -lt $fullText.Length -and ($fullText[$i] -eq ' ' -or $fullText[$i] -eq "`t")) { $i++ }
    $bracketStart = -1
    $openCh = ''; $closeCh = ''
    if ($i -lt $fullText.Length -and $fullText[$i] -eq '@' -and ($i + 1) -lt $fullText.Length -and ($fullText[$i + 1] -eq '(' -or $fullText[$i + 1] -eq '{')) {
        # @( ... ) 배열 또는 @{ ... } 해시 리터럴 — 실제 깊이 매칭 대상은 '@' 다음 문자
        $bracketStart = $i + 1
        $openCh = $fullText[$bracketStart]
        $closeCh = if ($openCh -eq '(') { ')' } else { '}' }
    } elseif ($i -lt $fullText.Length -and ($fullText[$i] -eq '(' -or $fullText[$i] -eq '{')) {
        # 주의: '['는 여기 포함하지 않음 — "[System.Type]::Member" 같은 정적 멤버 접근 표현이
        # 흔해서 배열 리터럴로 오인해 첫 ']'에서 잘라버리면 뒤의 "::Member"가 통째로 잘려나감.
        # 이 프로젝트 상수 중 순수 배열 리터럴은 전부 @(...) 형태라 '['를 못 다뤄도 문제 없음.
        $bracketStart = $i
        $openCh = $fullText[$i]
        $closeCh = if ($openCh -eq '(') { ')' } else { '}' }
    }
    if ($bracketStart -ge 0) {
        # 여러 줄 허용 — 괄호 깊이가 0으로 돌아오는 지점까지 통째로 추출
        $depth = 0
        $j = $bracketStart
        while ($j -lt $fullText.Length) {
            $ch = $fullText[$j]
            if ($ch -eq $openCh) { $depth++ }
            elseif ($ch -eq $closeCh) {
                $depth--
                if ($depth -eq 0) { return $fullText.Substring($m.Index, $j - $m.Index + 1) }
            }
            $j++
        }
        throw "unbalanced brackets for script var '$name'"
    }
    # 괄호로 시작하지 않는 단순 대입(문자열/숫자 리터럴 등) -> 해당 줄 끝까지만
    $lineEnd = $fullText.IndexOf("`n", $valueStart)
    if ($lineEnd -lt 0) { $lineEnd = $fullText.Length }
    return $fullText.Substring($m.Index, $lineEnd - $m.Index).TrimEnd("`r")
}

function Get-VscoreFunctionSource {
    param(
        [string[]]$Names = @(),
        [string[]]$ScriptVars = @()
    )
    $scriptPath = Get-VscoreScriptPath
    if (-not (Test-Path $scriptPath)) { throw "update_daily_charts.ps1 not found at $scriptPath (gitignored local-only file — must exist on this machine to run tests)" }
    $fullText = [System.IO.File]::ReadAllText($scriptPath, [System.Text.Encoding]::UTF8)

    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($v in $ScriptVars) { $parts.Add((Get-ScriptVarSource $fullText $v)) }
    foreach ($n in $Names) { $parts.Add((Get-FunctionSource $fullText $n)) }
    return ($parts -join "`r`n`r`n")
}
