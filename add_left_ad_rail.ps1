$ErrorActionPreference = 'Stop'
$stocksDir = "C:\Users\h24795\claude\kospi10000\stocks"

$cssBlock = @"

    #left-ad-rail{position:fixed;left:16px;top:50%;transform:translateY(-50%);z-index:40;}
    @media (max-width:1400px){#left-ad-rail{display:none;}}
"@

$adBlock = @"


<div id="left-ad-rail">
  <ins class="adsbygoogle"
       style="display:inline-block;width:160px;height:600px"
       data-ad-client="ca-pub-4973537494905596"
       data-ad-slot="7003099996"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>
"@

$anchor = '</style>'

$files = Get-ChildItem -Path $stocksDir -Filter "*.html"
$okCount = 0; $skipCount = 0
foreach ($f in $files) {
    $rawBytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $hasBom = ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF)
    $content = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)

    if ($content -match [regex]::Escape('id="left-ad-rail"')) {
        Write-Output "SKIP $($f.Name): 이미 삽입됨"
        $skipCount++
        continue
    }
    $idx = $content.IndexOf($anchor)
    if ($idx -lt 0) {
        Write-Output "SKIP $($f.Name): </style> 앵커 없음"
        $skipCount++
        continue
    }
    $newContent = $content.Substring(0, $idx) + $cssBlock + "`r`n" + $anchor + $adBlock + $content.Substring($idx + $anchor.Length)
    [System.IO.File]::WriteAllText($f.FullName, $newContent, (New-Object System.Text.UTF8Encoding($hasBom)))
    Write-Output "OK   $($f.Name)"
    $okCount++
}
Write-Output "=== 완료: $okCount / 건너뜀 $skipCount (총 $($files.Count)) ==="
