# =====================================================================
#  黑匣子叠加工具 —— 新电脑配置程序（图形版，不弹黑窗）
#  换电脑后双击「新电脑配置程序.vbs」，会弹一个进度窗口，自动：
#    1. 找 Python（没有就静默安装 3.12）
#    2. pip 装 pillow / numpy / pandas
#    3. 检查/下载 ffmpeg 与黑匣子解码器（放到 tools\）
#    4. 自检
#    5. 记录 Python 路径（启动器读它）
#    4. 把「启动黑匣子叠加工具.vbs」里的 Python 路径改成新电脑的
#  加 -NoInstall 参数只检查不安装。
# =====================================================================
param([switch]$NoInstall)

$ErrorActionPreference = "Continue"
# 让 Python / pip 的输出按 UTF-8 解码，不然中文会乱码
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $env:PYTHONIOENCODING = "utf-8"
} catch {}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try { [System.Windows.Forms.Application]::EnableVisualStyles() } catch {}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $dir "配置日志.txt"
$startTime = Get-Date
$script:failed = $false

# ------------------------------------------------------------------ 窗口
$form = New-Object System.Windows.Forms.Form
$form.Text = "黑匣子叠加工具 · 新电脑配置"
$form.Size = New-Object System.Drawing.Size(760, 560)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(238, 241, 245)
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "新电脑配置"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 16, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(18, 12)
$title.Size = New-Object System.Drawing.Size(300, 36)
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = "自动装 Python 和依赖（pillow / numpy / pandas），再把启动器改写成本机的 Python 路径"
$sub.ForeColor = [System.Drawing.Color]::FromArgb(100, 105, 115)
$sub.Location = New-Object System.Drawing.Point(20, 50)
$sub.Size = New-Object System.Drawing.Size(720, 20)
$form.Controls.Add($sub)

$txt = New-Object System.Windows.Forms.TextBox
$txt.Multiline = $true
$txt.ReadOnly = $true
$txt.ScrollBars = "Vertical"
$txt.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 42)
$txt.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
$txt.Font = New-Object System.Drawing.Font("Consolas", 9)
$txt.Location = New-Object System.Drawing.Point(20, 78)
$txt.Size = New-Object System.Drawing.Size(706, 390)
$txt.WordWrap = $false
$form.Controls.Add($txt)

$status = New-Object System.Windows.Forms.Label
$status.Text = "准备中…"
$status.Location = New-Object System.Drawing.Point(22, 476)
$status.Size = New-Object System.Drawing.Size(520, 22)
$status.ForeColor = [System.Drawing.Color]::FromArgb(55, 65, 81)
$form.Controls.Add($status)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = "关闭"
$btn.Enabled = $false
$btn.Size = New-Object System.Drawing.Size(110, 34)
$btn.Location = New-Object System.Drawing.Point(616, 470)
$btn.Add_Click({ $form.Close() })
$form.Controls.Add($btn)

function Pump { try { [System.Windows.Forms.Application]::DoEvents() } catch {} }

# ------------------------------------------------------------------ 异步任务（避免界面「未响应」）
function Wait-JobPump($job, $msg, $timeoutSec, $watchFile = "") {
    $t0 = Get-Date
    while ($job.State -eq "Running" -or $job.State -eq "NotStarted") {
        $el = [int]((Get-Date) - $t0).TotalSeconds
        $siz = ""
        if ($watchFile -and (Test-Path $watchFile)) {
            try { $siz = ("  已下载 " + [int]((Get-Item $watchFile).Length / 1MB) + " MB") } catch {}
        }
        try { $script:status.Text = "$msg（已等 $el 秒$siz，网络慢会久一点，请别关窗口）" } catch {}
        try { [System.Windows.Forms.Application]::DoEvents() } catch {}
        Start-Sleep -Milliseconds 150
        if ($el -gt $timeoutSec) {
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            return $null
        }
    }
    $ok = ($job.State -eq "Completed")
    $out = Receive-Job $job 2>&1
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ ok = $ok; out = $out }
}

function Invoke-Download($url, $out, $timeoutSec = 300) {
    Note ("下载 " + $url)
    $job = Start-Job -ScriptBlock {
        param($u, $o)
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $u -OutFile $o -UseBasicParsing -TimeoutSec 600
            if ((Test-Path $o) -and ((Get-Item $o).Length -gt 1MB)) { return "OK" }
                        return "TOO_SMALL"
        } catch { return ("ERR " + $_.Exception.Message) }
    } -ArgumentList $url, $out
    $r = Wait-JobPump $job ("下载 " + [System.IO.Path]::GetFileName($out)) $timeoutSec $out
    if (-not $r) { Note "  超时，放弃这个源"; return $false }
    $msg = ($r.out | Select-Object -Last 1)
    if ("$msg" -eq "OK") { Note "  下载完成"; return $true }
    Note ("  失败：" + $msg)
    return $false
}

function Write-Log($text) {
    $script:txt.AppendText("$text`r`n")
    $script:txt.SelectionStart = $script:txt.Text.Length
    $script:txt.ScrollToCaret()
    Pump
    try { Add-Content -Path $logFile -Value $text -Encoding UTF8 } catch {}
}

function Step($n, $text) {
    Write-Log ""
    Write-Log ("[{0}] {1}" -f $n, $text)
    $script:status.Text = "$text …"
}

function Note($text) { Write-Log ("      " + $text) }

function Find-Python {
    $cands = @()
    foreach ($cmd in @("python.exe", "python3.exe")) {
        $g = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($g) { $cands += $g.Source }
    }
    $pyL = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyL) {
        try {
            $p = & $pyL.Source -3 -c "import sys;print(sys.executable)" 2>$null
            if ($p) { $cands += ($p | Select-Object -First 1).Trim() }
        } catch {}
    }
    $cands += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($c in $cands) {
        if ($c -and (Test-Path $c)) {
            $v = & $c -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ("$v" -match '^3\.(9|1[0-9])') { return (Resolve-Path $c).Path }
        }
    }
    return $null
}

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($m, $u, $env:Path) -join ";"
}

# ------------------------------------------------------------------ 主流程
$form.Show()
Pump
Write-Log "黑匣子叠加工具 · 新电脑配置"
Write-Log "程序目录：$dir"
if ($NoInstall) { Write-Log "（本次是 -NoInstall 试跑模式，不会真的安装东西）" }

try {
    # ---- 1 Python
    Step 1 "检查 Python"
    $py = Find-Python
    $script:pyMethod = if ($py) { "already" } else { "" }
    if ($py) {
        $ver = & $py -c "import sys;print(sys.version.split()[0])"
        Note "已找到 Python $ver"
        Note $py
    } else {
        Note "没找到 Python，准备安装 3.12"
        if ($NoInstall) {
            Note "（-NoInstall：跳过安装）"
        } else {
            $installed = $false
            $wg = Get-Command winget.exe -ErrorAction SilentlyContinue
            if ($wg) {
                Note "用 winget 安装（可能弹权限确认，请点「是」）…"
                & winget install -e --id Python.Python.3.12 --silent `
                    --accept-package-agreements --accept-source-agreements 2>&1 |
                    ForEach-Object { Note $_ }
                Refresh-Path
                $py = Find-Python
                if ($py) { $installed = $true; $script:pyMethod = "winget"; Note "winget 安装完成" }
            }
            if (-not $installed) {
                Note "winget 不可用，改从官网下载安装包（约 25 MB）…"
                $tmp = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
                $urls = @(
                    "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe",
                    "https://mirrors.huaweicloud.com/python/3.12.8/python-3.12.8-amd64.exe"
                )
                foreach ($u in $urls) {
                    try {
                        Note "下载 $u"
                        Invoke-WebRequest -Uri $u -OutFile $tmp -UseBasicParsing -TimeoutSec 600
                        if ((Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 10MB)) { break }
                    } catch {
                        Note ("这个源不行：" + $_.Exception.Message)
                    }
                }
                if ((Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 10MB)) {
                    Note "静默安装（1~2 分钟）…"
                    Start-Process -FilePath $tmp -Wait -ArgumentList `
                        "/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1 Include_test=0"
                    Refresh-Path
                    $py = Find-Python
                    if ($py) { $script:pyMethod = "installer"; Note "安装完成" }
                } else {
                    Note "下载失败，没法自动装"
                }
            }
        }
    }

    if (-not $py) {
        Write-Log ""
        Write-Log "Python 没装成，后面的依赖也装不了。"
        Write-Log "可以手动装：https://www.python.org/downloads/ （装时勾 Add python.exe to PATH）"
        Write-Log "装完再双击一次本程序。"
        $script:failed = $true
    } else {
        $pw = Join-Path (Split-Path $py) "pythonw.exe"
        if (-not (Test-Path $pw)) { $pw = $py }

        # ---- 2 依赖
        Step 2 "安装依赖（pillow / numpy / pandas）"
        if ($NoInstall) {
            Note "（-NoInstall：跳过 pip 安装）"
        } else {
            $job = Start-Job -ScriptBlock {
                param($exe)
                $env:PYTHONIOENCODING = "utf-8"
                & $exe -m pip install --upgrade pip 2>&1
                & $exe -m pip install pillow numpy pandas 2>&1
                return $LASTEXITCODE
            } -ArgumentList $py
            $r = Wait-JobPump $job "安装依赖（pip）" 600
            if ($r) { $r.out | ForEach-Object { Note $_ } }
            $code = 1
            if ($r -and $r.ok) { $code = [int]($r.out | Select-Object -Last 1) }
            if ($code -ne 0) {
                Note "默认源不行，换清华镜像再装一次…"
                $job2 = Start-Job -ScriptBlock {
                    param($exe)
                    $env:PYTHONIOENCODING = "utf-8"
                    & $exe -m pip install pillow numpy pandas -i https://pypi.tuna.tsinghua.edu.cn/simple 2>&1
                    return $LASTEXITCODE
                } -ArgumentList $py
                $r2 = Wait-JobPump $job2 "安装依赖（清华镜像）" 600
                if ($r2) { $r2.out | ForEach-Object { Note $_ } }
                if ($r2 -and $r2.ok) { $code = [int]($r2.out | Select-Object -Last 1) }
            }
            if ($code -eq 0) { Note "依赖都装好了" } else { Note "依赖安装有报错（见上面 pip 输出）"; $script:failed = $true }
        }

        # ---- 3 工具（ffmpeg / blackbox_decode）
        Step 3 "检查 ffmpeg 与黑匣子解码器"
        $toolsDir = Join-Path $dir "tools"
        if (-not (Test-Path $toolsDir)) { New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null }
        $ffExe = Join-Path $toolsDir "ffmpeg.exe"
        $bdExe = Join-Path $toolsDir "blackbox_decode.exe"
        $tmpTools = Join-Path $env:TEMP ("bbov-tools-" + [guid]::NewGuid().ToString("N").Substring(0, 6))
        New-Item -ItemType Directory -Path $tmpTools -Force | Out-Null

        # 本机可能已经装了 PIDtoolbox（它自带 blackbox_decode.exe），顺手复制过来
        $script:foundBd = ""
        $lookDirs = @(
            "C:\Program Files\PIDtoolbox\application",
            "C:\Program Files (x86)\PIDtoolbox\application",
            (Join-Path $env:LOCALAPPDATA "Programs\PIDtoolbox\application"),
            (Join-Path $env:LOCALAPPDATA "PIDtoolbox\application")
        )
        foreach ($ld in $lookDirs) {
            $cand = Join-Path $ld "blackbox_decode.exe"
            if (Test-Path $cand) { $script:foundBd = $cand; break }
        }
        if (-not $script:foundBd) {
            $found = Get-Command "blackbox_decode.exe" -ErrorAction SilentlyContinue
            if ($found) { $script:foundBd = $found.Source }
        }
        if ($script:foundBd) { Note ("本机已有解码器：" + $script:foundBd) }

        function Save-Url($url, $out) {
            return (Invoke-Download $url $out 300)
        }

        if (Test-Path $ffExe) {
            Note "ffmpeg.exe 已有"
        } elseif ($NoInstall) {
            Note "（-NoInstall：不下载 ffmpeg）"
        } else {
            $ok = $false
            $ffUrls = @(
                "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://gh-proxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://ghproxy.net/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://hub.gitmirror.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            )
            foreach ($u in $ffUrls) {
                $zip = Join-Path $tmpTools "ffmpeg.zip"
                if (Save-Url $u $zip) {
                    try {
                        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmpTools "ff") -Force
                        $exe = Get-ChildItem -Path (Join-Path $tmpTools "ff") -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
                        if ($exe) { Copy-Item $exe.FullName $ffExe -Force; $ok = $true; break }
                    } catch { Note ("  解压失败：" + $_.Exception.Message) }
                }
            }
            if (-not $ok -and (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
                Note "直接下载失败，改用 winget 安装 ffmpeg ..."
                $job = Start-Job -ScriptBlock {
                    & winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements 2>&1
                }
                $rw = Wait-JobPump $job "用 winget 安装 ffmpeg" 600
                if ($rw) { $rw.out | ForEach-Object { Note $_ } }
                $wg = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Filter "ffmpeg.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($wg) { Copy-Item $wg.FullName $ffExe -Force; $ok = $true }
            }
            if ($ok) { Note "ffmpeg.exe 下载好了" } else { Note "ffmpeg 没下成功（见上面提示，可手动放到 toolsfmpeg.exe）" }
        }

        if (Test-Path $bdExe) {
            Note "blackbox_decode.exe 已有"
        } elseif ($NoInstall) {
            Note "（-NoInstall：不下载解码器）"
        } elseif ($script:foundBd) {
            Copy-Item $script:foundBd $bdExe -Force
            Note ("从本机找到并复制：" + $script:foundBd)
        } else {
            $ok = $false
            try {
                Note "查询 blackbox-tools 最新版本 ..."
                $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/betaflight/blackbox-tools/releases" `
                    -UseBasicParsing -TimeoutSec 60 -Headers @{ "User-Agent" = "bboverlay-setup" }
                foreach ($r in $rel) {
                    foreach ($a in $r.assets) {
                        if ($a.name -match "win" -and $a.name -match "\.zip$") {
                            $zip = Join-Path $tmpTools $a.name
                            if (Save-Url $a.browser_download_url $zip) {
                                Expand-Archive -Path $zip -DestinationPath (Join-Path $tmpTools "bb") -Force
                                $exe = Get-ChildItem -Path (Join-Path $tmpTools "bb") -Filter "blackbox_decode.exe" -Recurse | Select-Object -First 1
                                if ($exe) { Copy-Item $exe.FullName $bdExe -Force; $ok = $true; break }
                            }
                        }
                    }
                    if ($ok) { break }
                }
            } catch { Note ("  自动下载失败：" + $_.Exception.Message) }
            if ($ok) { Note "blackbox_decode.exe 下载好了" }
            else {
                Note "解码器没下成功（blackbox-tools 官方只发源码、没有现成 exe）。三个办法："
                Note "  1) 用本程序压缩包里自带的 tools\blackbox_decode.exe（推荐）"
                Note "  2) 如果你装过 PIDtoolbox，从它的 application 目录复制 blackbox_decode.exe"
                Note "  3) 自己编译：https://github.com/betaflight/blackbox-tools"
            }
        }
        Remove-Item -Recurse -Force $tmpTools -ErrorAction SilentlyContinue

        # ---- 4 自检
        Step 4 "自检"
        $st = Join-Path $dir "bboverlay.py"
        if (Test-Path $st) {
            & $py $st --selftest 2>&1 | ForEach-Object { Write-Log ("      " + $_) }
            if ($LASTEXITCODE -ne 0) { $script:failed = $true }
        } else {
            Write-Log "      找不到 bboverlay.py，程序文件是不是不全？"
            $script:failed = $true
        }

        # ---- 5 记下 Python 路径（启动器会读这个文件）
        Step 5 "记录 Python 路径"
        $ppFile = Join-Path $dir "python-path.txt"
        try {
            $enc = New-Object System.Text.UnicodeEncoding($false, $true)  # UTF-16LE + BOM
            [System.IO.File]::WriteAllText($ppFile, $pw, $enc)
            $rec = @{ python_path = $py; pythonw_path = $pw; python_method = $script:pyMethod;
                      installed_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
            $recFile = Join-Path $dir "安装记录.json"
            [System.IO.File]::WriteAllText($recFile, ($rec | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
            Note "已写入 python-path.txt"
            Note "Python：$pw"
        } catch {
            Write-Log ("      写 python-path.txt 失败：" + $_.Exception.Message)
            $script:failed = $true
        }
    }
} catch {
    Write-Log ""
    Write-Log ("出异常：" + $_.Exception.Message)
    $script:failed = $true
}

$span = [int]((Get-Date) - $startTime).TotalSeconds
Write-Log ""
if (-not $script:failed) {
    Write-Log "=============================================="
    Write-Log "  配置完成！用时 $span 秒"
    Write-Log "  以后双击「启动黑匣子叠加工具.vbs」就能用了"
    Write-Log "=============================================="
    $status.Text = "配置完成，可以关掉这个窗口了"
    $status.ForeColor = [System.Drawing.Color]::FromArgb(22, 128, 61)
} else {
    Write-Log "=============================================="
    Write-Log "  没完全成功，看上面的记录和「配置日志.txt」"
    Write-Log "=============================================="
    $status.Text = "有失败项，见上方记录"
    $status.ForeColor = [System.Drawing.Color]::FromArgb(200, 40, 40)
}
$btn.Enabled = $true

while ($form.Visible) {
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 80
}