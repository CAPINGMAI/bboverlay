# 下载本程序需要的两个第三方 exe 到 tools/ 目录
#   ffmpeg.exe          视频编解码
#   blackbox_decode.exe Betaflight 黑匣子解码器
# 用法： powershell -ExecutionPolicy Bypass -File tools/download-tools.ps1
param([switch]$Force)

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tmp = Join-Path $env:TEMP ("bboverlay-tools-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Say($t, $c = "White") { Write-Host $t -ForegroundColor $c }

function Get-File($url, $out) {
    Say "  下载 $url"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 900
        if ((Test-Path $out) -and ((Get-Item $out).Length -gt 1MB)) { return $true }
    } catch {
        Say ("  失败：" + $_.Exception.Message) "Yellow"
    }
    return $false
}

# ---------------------------------------------------------------- ffmpeg
$ff = Join-Path $here "ffmpeg.exe"
if ((Test-Path $ff) -and -not $Force) {
    Say "ffmpeg.exe 已存在，跳过（要重下加 -Force）" "Green"
} else {
    Say "[1/2] ffmpeg" "Cyan"
    $urls = @(
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    )
    foreach ($u in $urls) {
        $zip = Join-Path $tmp "ffmpeg.zip"
        if (Get-File $u $zip) {
            try {
                Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "ff") -Force
                $exe = Get-ChildItem -Path (Join-Path $tmp "ff") -Filter "ffmpeg.exe" -Recurse |
                    Select-Object -First 1
                if ($exe) { Copy-Item $exe.FullName $ff -Force; break }
            } catch {
                Say ("  解压失败：" + $_.Exception.Message) "Yellow"
            }
        }
    }
    if (Test-Path $ff) { Say "  ok -> $ff" "Green" }
    else { Say "  ffmpeg 没下成功，请手动下载后放到 tools\ffmpeg.exe（见 tools/README.md）" "Red" }
}

# ---------------------------------------------------------------- blackbox_decode
$bd = Join-Path $here "blackbox_decode.exe"
if ((Test-Path $bd) -and -not $Force) {
    Say "blackbox_decode.exe 已存在，跳过（要重下加 -Force）" "Green"
} else {
    Say "[2/2] blackbox_decode" "Cyan"
    $got = $false
    try {
        Say "  查询 blackbox-tools 最新 release ..."
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/betaflight/blackbox-tools/releases" `
            -UseBasicParsing -TimeoutSec 60 -Headers @{ "User-Agent" = "bboverlay-setup" }
        foreach ($r in $rel) {
            foreach ($a in $r.assets) {
                if ($a.name -match "win" -and $a.name -match "\.zip$") {
                    $zip = Join-Path $tmp $a.name
                    if (Get-File $a.browser_download_url $zip) {
                        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "bb") -Force
                        $exe = Get-ChildItem -Path (Join-Path $tmp "bb") -Filter "blackbox_decode.exe" -Recurse |
                            Select-Object -First 1
                        if ($exe) { Copy-Item $exe.FullName $bd -Force; $got = $true; break }
                    }
                }
            }
            if ($got) { break }
        }
    } catch {
        Say ("  自动下载失败：" + $_.Exception.Message) "Yellow"
    }
    if (Test-Path $bd) { Say "  ok -> $bd" "Green" }
    else {
        Say "  blackbox_decode 需要手动下载：" "Yellow"
        Say "    https://github.com/betaflight/blackbox-tools/releases" "Yellow"
        Say "    解压后把 blackbox_decode.exe 放进 tools\\" "Yellow"
    }
}

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
Say ""
Say "检查结果：" "Cyan"
$ff = Join-Path $here "ffmpeg.exe"
$bd = Join-Path $here "blackbox_decode.exe"
Say ("  ffmpeg.exe          " + $(if (Test-Path $ff) { "OK" } else { "缺失" }))
Say ("  blackbox_decode.exe " + $(if (Test-Path $bd) { "OK" } else { "缺失" }))
Say ""
Say "然后可以跑： python bboverlay.py --selftest"