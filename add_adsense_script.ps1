$ErrorActionPreference = 'Stop'
$stocksDir = "C:\Users\h24795\claude\kospi10000\stocks"
$anchor = '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
$adsenseTag = "`r`n" + '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4973537494905596"' + "`r`n" + '     crossorigin="anonymous"></script>'

$files = Get-ChildItem -Path $stocksDir -Filter "*.html"
$okCount = 0; $skipCount = 0
foreach ($f in $files) {
    $rawBytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $hasBom = ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF)
    $content = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)

    if ($content -match [regex]::Escape($adsenseTag.Trim())) {
        Write-Output "SKIP $($f.Name): 이미 삽입됨"
        $skipCount++
        continue
    }
    if (-not $content.StartsWith($anchor)) {
        Write-Output "SKIP $($f.Name): 앵커 패턴 없음 (첫 줄이 viewport meta 아님)"
        $skipCount++
        continue
    }
    $newContent = $anchor + $adsenseTag + $content.Substring($anchor.Length)
    [System.IO.File]::WriteAllText($f.FullName, $newContent, (New-Object System.Text.UTF8Encoding($hasBom)))
    Write-Output "OK   $($f.Name)"
    $okCount++
}
Write-Output "=== 완료: $okCount / 건너뜀 $skipCount (총 $($files.Count)) ==="
