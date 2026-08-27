# vscore 테스트 실행기. 대상 .ps1들을 UTF-8 BOM으로 강제 재저장한 뒤(Windows PowerShell 5.1이
# BOM 없는 UTF-8을 -File로 읽으면 한글이 깨지는 문제 회피) 실행한다.
# 사용: powershell -ExecutionPolicy Bypass -File tests\vscore\run.ps1
$ErrorActionPreference = 'Stop'
$targets = @('Import-VscoreFunctions.ps1', 'vscore.tests.ps1', 'dividend.tests.ps1')
foreach ($t in $targets) {
    $p = Join-Path $PSScriptRoot $t
    if (-not (Test-Path $p)) { continue }
    $txt = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($p, $txt, (New-Object System.Text.UTF8Encoding($true)))
}
& (Join-Path $PSScriptRoot 'vscore.tests.ps1')
Write-Output ""
& (Join-Path $PSScriptRoot 'dividend.tests.ps1')
