<#
.SYNOPSIS
Resolve MusicBrainz Artist IDs (MBIDs) from a JSON list of artist names.

.DESCRIPTION
Reads a JSON array like:
  [ {"name": "Artist"}, {"name": "Another"} ]

Queries MusicBrainz (ws/2) and writes:
  - output/artists_with_mbid.csv
  - output/ambiguous_or_missing.csv

Uses Invoke-RestMethod (often works better with corporate SSL/proxy on Windows).

.PARAMETER Input
Path to input JSON.

.PARAMETER Country
Preferred country code to disambiguate (e.g. BR).

.PARAMETER UserAgent
User-Agent header required by MusicBrainz.

.PARAMETER SleepSeconds
Seconds to sleep between requests (default 1.1).

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/resolve_musicbrainz_ids.ps1 -Input artistas_nacionais_rock_pop.json -Country BR -UserAgent "list_music_artist/1.0 (contact: you@example.com)"
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [Alias('Input')]
  [string]$InputPath,

  [string]$Country = $env:MUSICBRAINZ_PREFERRED_COUNTRY,

  [string]$UserAgent = $(if ($env:MUSICBRAINZ_USER_AGENT) { $env:MUSICBRAINZ_USER_AGENT } else { "list_music_artist/1.0 (please set -UserAgent with contact)" }),

  [double]$SleepSeconds = $(if ($env:MUSICBRAINZ_SLEEP_SECONDS) { [double]$env:MUSICBRAINZ_SLEEP_SECONDS } else { 1.1 }),

  [string]$CacheDir = "cache/musicbrainz",
  [string]$OutputDir = "output"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Name([string]$Name) {
  return ($Name.Trim() -replace "\s+", " ")
}

function Get-CachePath([string]$Url) {
  if (-not (Test-Path $CacheDir)) { New-Item -ItemType Directory -Path $CacheDir | Out-Null }
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Url)
  $hash = $sha.ComputeHash($bytes)
  $hex = -join ($hash | ForEach-Object { $_.ToString("x2") })
  return (Join-Path $CacheDir "$hex.json")
}

function Fetch-Json([string]$Url) {
  $cacheFile = Get-CachePath $Url
  if (Test-Path $cacheFile) {
    return Get-Content -Raw -Encoding UTF8 $cacheFile | ConvertFrom-Json
  }

  $headers = @{ "User-Agent" = $UserAgent; "Accept" = "application/json" }
  $resp = Invoke-RestMethod -Uri $Url -Headers $headers -Method Get

  ($resp | ConvertTo-Json -Depth 20) | Set-Content -Encoding UTF8 $cacheFile
  return $resp
}

function Query-Artists([string]$Name) {
  $q = 'artist:"' + $Name.Replace('"','\\"') + '"'
  $params = "query=$([System.Uri]::EscapeDataString($q))&fmt=json&limit=10"
  $url = "https://musicbrainz.org/ws/2/artist?$params"
  $data = Fetch-Json $url

  function Get-OptProp($Obj, [string]$PropName) {
    $p = $Obj.PSObject.Properties[$PropName]
    if ($null -ne $p) { return $p.Value }
    return $null
  }

  $candidates = @()
  foreach ($a in @($data.artists)) {
    $candidates += [PSCustomObject]@{
      mbid = $a.id
      name = $a.name
      score = [int]$a.score
      country = (Get-OptProp $a 'country')
      type = (Get-OptProp $a 'type')
      disambiguation = (Get-OptProp $a 'disambiguation')
    }
  }

  return @($candidates | Sort-Object -Property score -Descending)
}

function Pick-Best($Candidates) {
  $Candidates = @($Candidates)
  if (-not $Candidates -or $Candidates.Count -eq 0) {
    return @{ best = $null; issue = "no_results" }
  }

  if ($Country) {
    $preferred = @($Candidates | Where-Object { ($_.country + "").ToUpper() -eq $Country.ToUpper() })
    if ($preferred -and $preferred.Count -gt 0) {
      $preferred = $preferred | Sort-Object -Property score -Descending
      if ($preferred.Count -eq 1) {
        return @{ best = $preferred[0]; issue = $null }
      }
      if (($preferred[0].score - $preferred[1].score) -ge 10) {
        return @{ best = $preferred[0]; issue = $null }
      }
      return @{ best = $preferred[0]; issue = "ambiguous_multiple_preferred" }
    }
  }

  if ($Candidates.Count -eq 1) {
    return @{ best = $Candidates[0]; issue = $null }
  }

  if (($Candidates[0].score - $Candidates[1].score) -ge 15) {
    return @{ best = $Candidates[0]; issue = $null }
  }

  return @{ best = $Candidates[0]; issue = "ambiguous" }
}

if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir | Out-Null }

# Read input JSON (support BOM)
$jsonText = Get-Content -Raw -Encoding UTF8 $InputPath
if ($jsonText.Length -gt 0 -and [int]$jsonText[0] -eq 0xFEFF) { $jsonText = $jsonText.Substring(1) }
$data = $jsonText | ConvertFrom-Json

$names = @()
foreach ($item in $data) {
  if ($null -ne $item.name) {
    $names += [string]$item.name
  } elseif ($item -is [string]) {
    $names += $item
  }
}

$names = $names | ForEach-Object { Normalize-Name $_ } | Where-Object { $_ -ne "" } | Select-Object -Unique

$resolved = @()
$ambiguous = @()

for ($i = 0; $i -lt $names.Count; $i++) {
  $name = $names[$i]

  $candidates = Query-Artists $name
  $picked = Pick-Best $candidates

  if ($null -eq $picked.best) {
    $ambiguous += [PSCustomObject]@{ name=$name; mbid=""; score=""; country=""; type=""; disambiguation=""; issue="no_results"; candidates="" }
  } elseif ($null -eq $picked.issue) {
    $b = $picked.best
    $resolved += [PSCustomObject]@{ name=$name; mbid=$b.mbid; score=$b.score; country=$b.country; type=$b.type; disambiguation=$b.disambiguation; issue=""; candidates="" }
  } else {
    $b = $picked.best
    $top = @($candidates | Select-Object -First 3)
    $candStr = ($top | ForEach-Object { "$($_.mbid)::$($_.name)::$($_.score)::$($_.country)::$($_.disambiguation)" }) -join " | "
    $ambiguous += [PSCustomObject]@{ name=$name; mbid=$b.mbid; score=$b.score; country=$b.country; type=$b.type; disambiguation=$b.disambiguation; issue=$picked.issue; candidates=$candStr }
  }

  if ($i -lt ($names.Count - 1)) { Start-Sleep -Seconds $SleepSeconds }
}

$resolvedPath = Join-Path $OutputDir "artists_with_mbid.csv"
$ambPath = Join-Path $OutputDir "ambiguous_or_missing.csv"

$resolved | Export-Csv -NoTypeInformation -Encoding UTF8 $resolvedPath
$ambiguous | Export-Csv -NoTypeInformation -Encoding UTF8 $ambPath

Write-Host "Wrote: $resolvedPath ($($resolved.Count) resolved)"
Write-Host "Wrote: $ambPath ($($ambiguous.Count) ambiguous/missing)"

if ($UserAgent -like "*please set*") {
  Write-Host "WARNING: Set a real -UserAgent (with contact) for MusicBrainz." -ForegroundColor Yellow
}
