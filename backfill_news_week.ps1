<#
.SYNOPSIS
  최근 N일치 종목별 뉴스를 소급 수집해 data/news/{code}.json 아카이브에 날짜별로
  채워 넣는 1회성 백필 스크립트.

.DESCRIPTION
  update_daily_charts.ps1의 "7. Daily 주요 뉴스" 필터링(저가치 제목/스포츠 노이즈
  제외, 독립 멘션 체크, 형제사 제외)·클러스터링(2-gram shingle 자카드 유사도)·
  스코어링(언론사 체급 + 보도 매체 수) 로직을 그대로 재사용하되, 하루치(72시간)
  대신 최근 $Days일치를 폭넓게 가져와 실제 게재일(KST 달력 기준) 단위로 나눠
  날짜마다 따로 클러스터링해서 상위 $PerDayTopN건씩 반환한다.

  네이버 뉴스 검색은 "그 날짜 시점의 주요 뉴스"를 재현하는 게 아니라 지금
  인덱스에 남아있는 기사를 최신순으로 긁어오는 것이므로, 날짜가 오래될수록
  회수율이 떨어지고 일부 종목·날짜는 기사가 안 잡힐 수 있음(최선의 근사치).

  예약 작업 대상 아님 — 수동 1회 실행용.

.PARAMETER Days
  소급 수집할 일수(기본 7일, 오늘 포함).

.PARAMETER PerDayTopN
  날짜별로 남길 최대 건수(기본 5건, 종목 페이지 표시 개수와 동일).

.PARAMETER Limit
  테스트용 — 처리할 종목 수 제한(0=전체).

.PARAMETER DryRun
  실제 파일 저장 없이 로그만 출력.
#>
param(
    [int]$Days = 7,
    [int]$PerDayTopN = 5,
    [int]$Limit = 0,
    [switch]$DryRun
)

$repoRoot = "C:\Users\h24795\claude\kospi10000"
$dataDir = Join-Path $repoRoot "data\news"
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }

function Log([string]$m) {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $m"
}

# ══════════════════════════════════════════════════════════════════════════
# ── update_daily_charts.ps1의 뉴스 필터링/클러스터링 상수·함수를 그대로 복제.
#     (일일 자동화 스크립트를 수정하지 않고 별도 1회성 스크립트로 유지하기 위함
#     — 필터 기준이 달라지면 두 곳 모두 손봐야 하지만, 매일 도는 스크립트의
#     동작을 이 백필 작업 때문에 건드리는 리스크보다 낫다고 판단.) ──
# ══════════════════════════════════════════════════════════════════════════

$script:NewsApiBase = "https://naverapihub.apigw.ntruss.com/search/v1/news"
$script:NaverApiHubKeyId = $env:NAVER_API_HUB_CLIENT_ID
$script:NaverApiHubKeySecret = $env:NAVER_API_HUB_CLIENT_SECRET

$script:NewsLowValueTitleRegex = '^\[인사\]|^\[부고\]|^\[동정\]|^\[오늘의 주요일정\]|^\[게시판\]|^\[알림\]|^\[부음\]|주가,?\s*\d+월\s*\d+일.*(상승|하락)'
$script:NewsSportsNoiseRegex = '야구|홈런|타자|투수|이닝|프로야구|KBO|안타|승리투수|완봉|불펜|타율|방어율|플레이오프|와일드카드|정규시즌|1군|2군|구단|감독|선발투수|끝내기|병살|영구결번|방망이|다승|탈삼진|직구'
$script:NewsAllowedSuffixes = @('그룹', '지주', '홀딩스')
$script:NewsBoundaryChars = " ,·""'" + [char]0x201C + [char]0x201D + [char]0x2018 + [char]0x2019 + "()[]<>-–—:;./…?!`t"
$script:NewsManualExclusions = @{
    'GS' = @('GS건설', 'GS리테일', 'GS칼텍스', 'GS글로벌', 'GS이피에스', 'GS에너지', 'GS샵', 'GS25')
}
$script:NewsOutlets = @{
    'yna.co.kr'=@{name='연합뉴스';tier=5}; 'ytn.co.kr'=@{name='YTN';tier=5}; 'kbs.co.kr'=@{name='KBS';tier=5}
    'imbc.com'=@{name='MBC';tier=5}; 'mbc.co.kr'=@{name='MBC';tier=5}; 'sbs.co.kr'=@{name='SBS';tier=5}
    'jtbc.co.kr'=@{name='JTBC';tier=5}; 'news.jtbc.co.kr'=@{name='JTBC';tier=5}; 'newsis.com'=@{name='뉴시스';tier=5}
    'news1.kr'=@{name='뉴스1';tier=5}; 'yonhapnewstv.co.kr'=@{name='연합뉴스TV';tier=5}
    'chosun.com'=@{name='조선일보';tier=3}; 'biz.chosun.com'=@{name='조선비즈';tier=3}
    'joongang.co.kr'=@{name='중앙일보';tier=3}; 'joins.com'=@{name='중앙일보';tier=3}; 'donga.com'=@{name='동아일보';tier=3}
    'hani.co.kr'=@{name='한겨레';tier=3}; 'khan.co.kr'=@{name='경향신문';tier=3}; 'hankyung.com'=@{name='한국경제';tier=3}
    'mk.co.kr'=@{name='매일경제';tier=3}; 'sedaily.com'=@{name='서울경제';tier=3}; 'mt.co.kr'=@{name='머니투데이';tier=3}
    'edaily.co.kr'=@{name='이데일리';tier=3}; 'asiae.co.kr'=@{name='아시아경제';tier=3}; 'view.asiae.co.kr'=@{name='아시아경제';tier=3}
    'fnnews.com'=@{name='파이낸셜뉴스';tier=3}; 'heraldcorp.com'=@{name='헤럴드경제';tier=3}
    'biz.heraldcorp.com'=@{name='헤럴드경제';tier=3}; 'koreaherald.com'=@{name='코리아헤럴드';tier=3}
    'seoul.co.kr'=@{name='서울신문';tier=3}; 'munhwa.com'=@{name='문화일보';tier=3}; 'segye.com'=@{name='세계일보';tier=3}
    'hankookilbo.com'=@{name='한국일보';tier=3}; 'kmib.co.kr'=@{name='국민일보';tier=3}
}

function Test-DpNewsStandaloneMention([string]$title, [string]$name) {
    $idx = 0
    while ($true) {
        $pos = $title.IndexOf($name, $idx)
        if ($pos -lt 0) { return $false }
        $endPos = $pos + $name.Length
        if ($endPos -ge $title.Length) { return $true }
        $restChar = $title.Substring($endPos, 1)
        if ($script:NewsBoundaryChars.Contains($restChar)) { return $true }
        $rest = $title.Substring($endPos)
        foreach ($suf in $script:NewsAllowedSuffixes) {
            if ($rest.StartsWith($suf)) { return $true }
        }
        $idx = $pos + 1
    }
}

function Get-DpNewsShingles([string]$title) {
    $t = [regex]::Replace($title, '\[[^\]]*\]', '')
    $t = [regex]::Replace($t, '[^\p{L}\p{N}]', '')
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if ($t.Length -lt 2) {
        if ($t.Length -gt 0) { [void]$set.Add($t) }
        return $set
    }
    for ($i = 0; $i -lt $t.Length - 1; $i++) { [void]$set.Add($t.Substring($i, 2)) }
    return $set
}

function Get-DpNewsJaccard($a, $b) {
    if ($a.Count -eq 0 -or $b.Count -eq 0) { return 0.0 }
    $interCount = 0
    foreach ($x in $a) { if ($b.Contains($x)) { $interCount++ } }
    $unionCount = $a.Count + $b.Count - $interCount
    if ($unionCount -eq 0) { return 0.0 }
    return $interCount / [double]$unionCount
}

function Get-DpNewsDomain([string]$link) {
    if (-not $link) { return '' }
    try { $h = ([Uri]$link).Host.ToLower() } catch { return '' }
    foreach ($prefix in @('www.', 'm.', 'n.', 'news.')) {
        if ($h.StartsWith($prefix) -and $h -ne "${prefix}naver.com") { $h = $h.Substring($prefix.Length) }
    }
    return $h
}

# 클러스터링(2-gram shingle 자카드 유사도) + 스코어링 후 상위 N건 반환 — Get-DpCompanyNews와 동일 로직.
function Get-DpClusteredTopN([object[]]$items, [int]$topN) {
    $clusters = New-Object System.Collections.Generic.List[object]
    foreach ($item in $items) {
        $best = $null; $bestSim = -1.0
        foreach ($c in $clusters) {
            foreach ($ms in $c.MemberShingles) {
                $sim = Get-DpNewsJaccard $item.shingles $ms
                if ($sim -ge 0.22 -and $sim -gt $bestSim) { $bestSim = $sim; $best = $c }
            }
        }
        if ($null -ne $best) {
            $best.MemberShingles.Add($item.shingles)
            [void]$best.Domains.Add($item.domain)
            if ($item.tier -gt $best.Rep.tier -or ($item.tier -eq $best.Rep.tier -and $item.pubDate -gt $best.Rep.pubDate)) {
                $best.Rep = $item
            }
        } else {
            $domains = New-Object 'System.Collections.Generic.HashSet[string]'
            [void]$domains.Add($item.domain)
            $clusters.Add([PSCustomObject]@{
                MemberShingles = [System.Collections.Generic.List[object]]@(,$item.shingles)
                Domains = $domains
                Rep = $item
            })
        }
    }
    $reps = foreach ($c in $clusters) {
        [PSCustomObject]@{
            title = $c.Rep.title; link = $c.Rep.link; domain = $c.Rep.domain
            tier = $c.Rep.tier; pubDate = $c.Rep.pubDate; coverage = $c.Domains.Count
        }
    }
    $sorted = $reps | Sort-Object -Property @{Expression={$_.tier + [Math]::Min($_.coverage - 1, 5)}; Descending=$true}, @{Expression='pubDate'; Descending=$true}
    return @($sorted | Select-Object -First $topN)
}

# 종목명으로 최근 $days일치 뉴스를 최대 200건(100건씩 2페이지)까지 가져와 필터링한 뒤,
# 실제 게재일(KST 달력 날짜) 단위로 묶어 날짜별 상위 $perDayTopN건을 반환.
# 반환: @{ 'yyyy-MM-dd' = @(reps...) }
function Get-DpCompanyNewsMultiDay([string]$companyName, [int]$days, [int]$perDayTopN) {
    if (-not $script:NaverApiHubKeyId -or -not $script:NaverApiHubKeySecret) { return @{} }

    $exclusions = New-Object System.Collections.Generic.List[string]
    if ($script:NewsManualExclusions.ContainsKey($companyName)) {
        foreach ($e in $script:NewsManualExclusions[$companyName]) { $exclusions.Add($e) }
    }
    if ($script:NewsSiblingNames.ContainsKey($companyName)) {
        foreach ($e in $script:NewsSiblingNames[$companyName]) { $exclusions.Add($e) }
    }

    $rawItems = New-Object System.Collections.Generic.List[object]
    foreach ($start in @(1, 101)) {
        try {
            $url = "$($script:NewsApiBase)?query=$([uri]::EscapeDataString($companyName))&display=100&start=$start&sort=date&format=json"
            $resp = Invoke-WebRequest -Uri $url -Headers @{
                'X-NCP-APIGW-API-KEY-ID' = $script:NaverApiHubKeyId
                'X-NCP-APIGW-API-KEY'    = $script:NaverApiHubKeySecret
            } -TimeoutSec 20 -UseBasicParsing
            $json = $resp.Content | ConvertFrom-Json
            if (-not $json.items -or $json.items.Count -eq 0) { break }
            foreach ($it in $json.items) { $rawItems.Add($it) }
            Start-Sleep -Milliseconds 250
        } catch {
            Log "WARN ${companyName}: 뉴스 API 호출 실패(start=$start) - $($_.Exception.Message)"
            break
        }
    }

    $nowUtc = [DateTime]::UtcNow
    $cutoffUtc = $nowUtc.AddDays(-$days)
    $byDate = @{}
    foreach ($it in $rawItems) {
        $title = [System.Net.WebUtility]::HtmlDecode(($it.title -replace '</?b>', ''))
        if ($title -match $script:NewsLowValueTitleRegex) { continue }
        if ($title -match $script:NewsSportsNoiseRegex) { continue }
        if (-not (Test-DpNewsStandaloneMention $title $companyName)) { continue }
        $excluded = $false
        foreach ($ex in $exclusions) { if ($title.Contains($ex)) { $excluded = $true; break } }
        if ($excluded) { continue }

        try { $pubDate = [DateTime]::Parse($it.pubDate, [System.Globalization.CultureInfo]::InvariantCulture) } catch { continue }
        $pubDateUtc = $pubDate.ToUniversalTime()
        if ($pubDateUtc -lt $cutoffUtc -or $pubDateUtc -gt $nowUtc) { continue }

        $link = if ($it.originallink) { $it.originallink } else { $it.link }
        $domain = Get-DpNewsDomain $link
        $outlet = $script:NewsOutlets[$domain]
        $tier = if ($outlet) { $outlet.tier } else { 1 }
        $dateKey = $pubDate.ToString('yyyy-MM-dd')

        if (-not $byDate.ContainsKey($dateKey)) { $byDate[$dateKey] = New-Object System.Collections.Generic.List[object] }
        $byDate[$dateKey].Add([PSCustomObject]@{
            title = $title; link = $link; domain = $domain; tier = $tier
            pubDate = $pubDate; shingles = (Get-DpNewsShingles $title)
        })
    }

    $result = @{}
    foreach ($dateKey in $byDate.Keys) {
        $result[$dateKey] = Get-DpClusteredTopN $byDate[$dateKey].ToArray() $perDayTopN
    }
    return $result
}

# data/news/{code}.json에 여러 날짜를 한 번에 병합 기록. 이번 실행 범위 밖의 기존
# 날짜는 그대로 보존, 30일 지난 항목은 정리(update_daily_charts.ps1의 보관 정책과 동일).
function Merge-DpNewsArchiveMultiDay([string]$code, [hashtable]$itemsByDate) {
    $archivePath = Join-Path $dataDir "$code.json"
    $archive = [ordered]@{}
    if (Test-Path $archivePath) {
        $raw = Get-Content $archivePath -Raw -Encoding UTF8
        if ($raw -and $raw.Trim()) {
            $parsed = $raw | ConvertFrom-Json
            foreach ($p in $parsed.PSObject.Properties) { $archive[$p.Name] = $p.Value }
        }
    }
    foreach ($dateKey in $itemsByDate.Keys) {
        $dayItems = @()
        foreach ($n in $itemsByDate[$dateKey]) {
            $outlet = $script:NewsOutlets[$n.domain]
            $displayName = if ($outlet) { $outlet.name } else { $n.domain }
            $dayItems += [PSCustomObject]@{
                title = $n.title; link = $n.link; source = $displayName; time = $n.pubDate.ToString('MM-dd HH:mm')
            }
        }
        $archive[$dateKey] = @($dayItems)
    }
    $cutoff = (Get-Date).AddDays(-30)
    $keysToRemove = @()
    foreach ($k in $archive.Keys) {
        $d = [DateTime]::MinValue
        if ([DateTime]::TryParse($k, [ref]$d) -and $d -lt $cutoff) { $keysToRemove += $k }
    }
    foreach ($k in $keysToRemove) { $archive.Remove($k) }

    if (-not $DryRun) {
        ($archive | ConvertTo-Json -Depth 6) | Out-File -FilePath $archivePath -Encoding UTF8
    }
    return $archive
}

# ── index.html에서 code -> name 매핑 + 형제사 제외어 구축 (update_daily_charts.ps1과 동일 로직) ──
$indexPath = Join-Path $repoRoot "index.html"
if (-not (Test-Path $indexPath)) { Log "FAIL index.html을 찾을 수 없음"; exit 1 }
$indexRaw = [System.IO.File]::ReadAllText($indexPath, [System.Text.Encoding]::UTF8)
$stockEntryPattern = '"rank":\s*(\d+),\s*"name":\s*"([^"]+)",\s*"code":\s*"([^"]+)",\s*"industry":\s*"([^"]+)"'
$codeMap = @{}
foreach ($sm in [regex]::Matches($indexRaw, $stockEntryPattern)) {
    $c = $sm.Groups[3].Value
    if (-not $codeMap.ContainsKey($c)) {
        $codeMap[$c] = [PSCustomObject]@{ name = $sm.Groups[2].Value }
    }
}
Log "종목 매핑 $($codeMap.Count)건 로드"

$script:NewsSiblingNames = @{}
$allCompanyNames = @($codeMap.Values | ForEach-Object { $_.name } | Sort-Object -Unique)
foreach ($nm in $allCompanyNames) {
    $siblings = @($allCompanyNames | Where-Object { $_ -ne $nm -and $_.StartsWith($nm) })
    if ($siblings.Count -gt 0) { $script:NewsSiblingNames[$nm] = $siblings }
}

if (-not $script:NaverApiHubKeyId -or -not $script:NaverApiHubKeySecret) {
    Log "FAIL NAVER_API_HUB_CLIENT_ID/SECRET 환경변수가 없음"
    exit 1
}

# ── 메인 루프 ──
$codes = @($codeMap.Keys | Sort-Object)
if ($Limit -gt 0) { $codes = $codes | Select-Object -First $Limit }
Log "=== 종목 $($codes.Count)개, 최근 ${Days}일치 뉴스 백필 시작 (일별 상위 ${PerDayTopN}건) ==="
if ($DryRun) { Log "(DryRun 모드 — 파일 미저장)" }

$okCount = 0; $failCount = 0
foreach ($code in $codes) {
    $name = $codeMap[$code].name
    try {
        $byDate = Get-DpCompanyNewsMultiDay $name $Days $PerDayTopN
        $totalItems = 0
        foreach ($v in $byDate.Values) { $totalItems += $v.Count }
        Merge-DpNewsArchiveMultiDay $code $byDate | Out-Null
        Log "OK   $code ($name): 날짜 $($byDate.Count)개, 총 $totalItems 건"
        $okCount++
    } catch {
        Log "FAIL $code ($name): $($_.Exception.Message)"
        $failCount++
    }
    Start-Sleep -Milliseconds 300
}
Log "=== 완료: 성공 $okCount / 실패 $failCount (총 $($codes.Count)) ==="
