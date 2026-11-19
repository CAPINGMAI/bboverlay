# =====================================================================
#  bboverlay —— 环境体检
#  检查运行这个程序需要的东西是否齐全，生成「体检报告.txt」
#  用法：双击「环境体检.vbs」（窗口里列出结果，也能保存/复制）
# =====================================================================
$ErrorActionPreference = "Continue"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try { [System.Windows.Forms.Application]::EnableVisualStyles() } catch {}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rep = New-Object System.Collections.ArrayList

function L($t) { [void]$rep.Add($t) }
function OK($t)   { L ("[OK] " + $t) }
function BAD($t)  { L ("[!!] " + $t) }
function INFO($t) { L ("     " + $t) }

function Try-Run($exe, $arguments, $timeoutSec = 25) {
    try {
        $job = Start-Job -ScriptBlock {
            param($e, $a)
            try { (& $e $a 2>&1 | Out-String) } catch { "ERR " + $_.Exception.Message }
        } -ArgumentList $exe, $arguments
        $t0 = Get-Date
        while ($job.State -eq "Running" -or $job.State -eq "NotStarted") {
            Start-Sleep -Milliseconds 100
            if (((Get-Date) - $t0).TotalSeconds -gt $timeoutSec) {
                Stop-Job $job -ErrorAction SilentlyContinue
                Remove-Job $job -Force -ErrorAction SilentlyContinue
                return $null
            }
        }
        $out = Receive-Job $job 2>&1 | Out-String
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        return $out
    } catch { return $null }
}

L "================ bboverlay 环境体检 ================"
L ("时间：" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
L ("程序目录：" + $dir)
L ""

# ---------------------------------------------------------------- 1 系统
L "【1】系统"
$os = Get-CimInstance Win32_OperatingSystem
L ("     " + $os.Caption + "  版本 " + $os.Version)
if ([Environment]::Is64BitOperatingSystem) { OK "64 位 Windows" } else { BAD "不是 64 位 Windows（ffmpeg/解码器要 64 位）" }
$drv = $dir.Substring(0, 1)
$pd = Get-PSDrive -Name $drv -ErrorAction SilentlyContinue
if ($pd) {
    $freeGB = [math]::Round($pd.Free / 1GB, 1)
    INFO ("程序所在盘（" + $drv + ":）剩余空间：" + $freeGB + " GB")
    if ($freeGB -lt 5) { BAD "剩余空间不足 5 GB，生成视频可能失败" } else { OK "磁盘空间够用" }
}

# ---------------------------------------------------------------- 2 写入权限
L ""
L "【2】写入权限（程序要往自己目录写缓存/输出）"
$testFile = Join-Path $dir ".write_test"
$writable = $false
try {
    "x" | Out-File -FilePath $testFile -Encoding ascii -ErrorAction Stop
    Remove-Item $testFile -Force -ErrorAction SilentlyContinue
    $writable = $true
} catch { $writable = $false }
if ($writable) { OK "程序目录可写" }
else { BAD "程序目录不可写！放在 C:\Program Files 之类的位置会失败，请换到 D 盘等普通文件夹" }

# ---------------------------------------------------------------- 3 程序文件
L ""
L "【3】程序文件"
$need = @("bboverlay.py", "bboverlay_gui.py", "bbrender.py", "bbminimap.py", "bbatt.py",
          "bbsync.py", "bbphotomap.py", "bbcompose.py", "bboverlay_layout_editor.py",
          "assets\grad.png")
$miss = @()
foreach ($f in $need) { if (-not (Test-Path (Join-Path $dir $f))) { $miss += $f } }
if ($miss.Count -eq 0) { OK "程序文件齐全（9 个 py + assets\grad.png）" }
else { BAD ("缺这些文件：" + ($miss -join "、") + " —— 请重新解压整个程序包") }

# ---------------------------------------------------------------- 4 Python
L ""
L "【4】Python"
$py = ""
$pp = Join-Path $dir "python-path.txt"
if (Test-Path $pp) {
    $t = ""
    try { $t = (Get-Content $pp -Raw -Encoding Unicode).Trim() } catch {}
    if (-not ($t -and (Test-Path $t))) {
        try { $t = (Get-Content $pp -Raw -Encoding UTF8).Trim() } catch {}
    }
    if ($t -and (Test-Path $t)) { $py = $t; INFO ("python-path.txt 指向：" + $t) }
    else { BAD "python-path.txt 存在但路径无效（重新跑一次配置程序即可）" }
}
if (-not $py) { INFO "没有 python-path.txt（配置程序会生成）" }

$cands = @()
$cands += (Join-Path $env:LOCALAPPDATA "Programs/Python/Python313/pythonw.exe")
$cands += (Join-Path $env:LOCALAPPDATA "Programs/Python/Python312/pythonw.exe")
$cands += (Join-Path $env:LOCALAPPDATA "Programs/Python/Python311/pythonw.exe")
$cands += "C:/Python313/pythonw.exe"
$cands += "C:/Python312/pythonw.exe"
$cands += "C:/Python311/pythonw.exe"
$cands += "C:/python/pythonw.exe"
$cands += "D:/python/pythonw.exe"
$cands += "E:/python/pythonw.exe"
$g = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($g) { $cands += $g.Source }

if (-not $py) {
    foreach ($c in $cands) { if (Test-Path $c) { $py = $c; break } }
}

# 用一个探测脚本检查依赖（避免命令行引号问题）
$probePy = Join-Path $env:TEMP "bbchk_probe.py"
$probeCode = @'
import sys
print("VERSION " + sys.version.split()[0])
for m in ("numpy", "pandas", "PIL", "tkinter"):
    try:
        __import__(m)
        print("MOD " + m + " ok")
    except Exception:
        print("MOD " + m + " fail")
'@
try { $probeCode | Out-File -FilePath $probePy -Encoding utf8 } catch {}

if ($py) {
    OK ("找到 Python：" + $py)
    $pye = $py -replace 'pythonw\.exe$', 'python.exe'
    if (-not (Test-Path $pye)) { $pye = $py }

    $o = Try-Run $pye $probePy
    $ver = ""
    $modBad = @()
    if ($o) {
        foreach ($line in ($o -split "`n")) {
            $ln = $line.Trim()
            if ($ln -like "VERSION *") { $ver = $ln.Substring(8) }
            if ($ln -like "MOD * fail") {
                $modBad += ($ln -split " ")[1]
            }
        }
    }
    if ($ver) { INFO ("版本：" + $ver) }
    $mods = @("numpy", "pandas", "PIL", "tkinter")
    if ($modBad.Count -eq 0 -and $ver) {
        OK ("依赖都在：" + ($mods -join " / "))
    } elseif ($modBad.Count -eq 0) {
        INFO "没能跑通探测脚本（可能是杀软拦了 Python），先重新运行配置程序试试"
    } else {
        $altOk = ""
        foreach ($c in $cands) {
            if ($c -eq $py) { continue }
            if (-not (Test-Path $c)) { continue }
            $ce = $c -replace 'pythonw\.exe$', 'python.exe'
            if (-not (Test-Path $ce)) { $ce = $c }
            $oo = Try-Run $ce $probePy
            if ($oo -and ($oo -match "MOD numpy ok") -and ($oo -match "MOD pandas ok") -and
                ($oo -match "MOD PIL ok") -and ($oo -match "MOD tkinter ok")) {
                $altOk = $c
                break
            }
        }
        if ($altOk) {
            BAD ("当前这个 Python 缺依赖（" + ($modBad -join "、") + "）")
            INFO ("不过机器上另一个 Python 是齐全的：" + $altOk)
            INFO "解决：重新运行一次配置程序（会把 python-path.txt 改成齐全的那个）"
        } else {
            BAD ("缺依赖：" + ($modBad -join "、") + " —— 重新运行配置程序安装")
        }
    }
} else {
    BAD "没找到 Python —— 先双击「新电脑配置程序.vbs」"
}

L ""
L "【5】ffmpeg / blackbox_decode"
function Find-Exe($name, $envName) {
    $e = [Environment]::GetEnvironmentVariable($envName)
    if ($e -and (Test-Path $e)) { return $e }
    $p = Join-Path $dir ("tools\" + $name)
    if (Test-Path $p) { return $p }
    $g = Get-Command $name -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    return ""
}
$ff = Find-Exe "ffmpeg.exe" "FFMPEG"
$bd = Find-Exe "blackbox_decode.exe" "BLACKBOX_DECODE"
if ($ff) {
    OK ("ffmpeg：" + $ff)
    $v = Try-Run $ff "-version"
    if ($v -and $v -match "ffmpeg version") {
        INFO (($v -split "`n")[0].Trim())
    } else {
        BAD "ffmpeg 找到了但跑不起来（可能被杀软破坏或下载不完整，删掉重新下载）"
    }
} else {
    BAD "没有 ffmpeg —— 放进 tools\ffmpeg.exe，或重新运行配置程序自动下载"
}
if ($bd) { OK ("blackbox_decode：" + $bd) }
else { BAD "没有 blackbox_decode —— 放进 tools\，或从 PIDtoolbox 目录复制，或重新运行配置程序" }

# ---------------------------------------------------------------- 6 网络
L ""
L "【6】网络（只影响卫星小地图）"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $r = Invoke-WebRequest -Uri "https://webst01.is.autonavi.com/appmaptile?style=6&x=27&y=13&z=5" -UseBasicParsing -TimeoutSec 10
    if ($r.StatusCode -eq 200) { OK "能连上地图瓦片服务（小地图能下底图）" }
    else { BAD ("地图瓦片返回 " + $r.StatusCode + "（小地图会空白，其他不受影响）") }
} catch {
    BAD "连不上地图瓦片（离线时小地图自动跳过，不影响出片）"
}

# ---------------------------------------------------------------- 7 启动器
L ""
L "【7】启动器"
foreach ($f in @("启动黑匣子叠加工具.vbs", "启动黑匣子叠加工具.exe", "新电脑配置程序.vbs", "一键卸载程序.vbs")) {
    if (Test-Path (Join-Path $dir $f)) { OK ($f + " 在") } else { INFO ($f + " 不在（可选）") }
}
try {
    $ws = New-Object -ComObject WScript.Shell
    OK "Windows 脚本宿主（VBS）可用"
} catch {
    BAD "系统禁用了脚本宿主 —— 请改用 启动黑匣子叠加工具.exe 启动"
}

# ---------------------------------------------------------------- 8 杀软
L ""
L "【8】杀毒软件"
try {
    $mp = Get-MpComputerStatus -ErrorAction Stop
    if ($mp.RealTimeProtectionEnabled) { INFO "Windows Defender 实时保护：开" }
} catch {}
$avNames = @()
try {
    $av = Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -ErrorAction Stop
    foreach ($a in $av) { $avNames += $a.displayName }
} catch {}
if ($avNames.Count -gt 0) {
    INFO ("检测到：" + ($avNames -join "、"))
    INFO "双击没反应时，先把本文件夹加入杀软白名单/排除目录"
}

# ---------------------------------------------------------------- 汇总
L ""
L "================ 结论 ================"
$bad = @($rep | Where-Object { $_ -match '^\[!!\]' })
if ($bad.Count -eq 0) { L "没发现问题，可以直接用。" }
else {
    L ("有 " + $bad.Count + " 项要处理：")
    foreach ($b in $bad) { L ("  " + $b) }
}
L ""
L "（这份报告同时保存成同目录下的「体检报告.txt」）"

$report = Join-Path $dir "体检报告.txt"
try { $rep -join "`r`n" | Out-File -FilePath $report -Encoding utf8 } catch {}

# ---------------------------------------------------------------- 界面
$form = New-Object System.Windows.Forms.Form
$form.Text = "bboverlay · 环境体检"
$form.Size = New-Object System.Drawing.Size(860, 730)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(238, 241, 245)
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = "环境体检结果"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 15, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(18, 12)
$title.Size = New-Object System.Drawing.Size(320, 34)
$form.Controls.Add($title)

$txt = New-Object System.Windows.Forms.TextBox
$txt.Multiline = $true
$txt.ReadOnly = $true
$txt.ScrollBars = "Both"
$txt.WordWrap = $false
$txt.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 42)
$txt.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
$txt.Font = New-Object System.Drawing.Font("Consolas", 9)
$txt.Location = New-Object System.Drawing.Point(18, 56)
$txt.Size = New-Object System.Drawing.Size(806, 570)
$txt.Text = ($rep -join "`r`n")
$form.Controls.Add($txt)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "关闭"
$btnClose.Size = New-Object System.Drawing.Size(110, 34)
$btnClose.Location = New-Object System.Drawing.Point(714, 638)
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

$btnOpen = New-Object System.Windows.Forms.Button
$btnOpen.Text = "打开报告文件"
$btnOpen.Size = New-Object System.Drawing.Size(130, 34)
$btnOpen.Location = New-Object System.Drawing.Point(568, 638)
$btnOpen.Add_Click({ try { Start-Process $report } catch { [void][System.Windows.Forms.MessageBox]::Show("报告没保存成功") } })
$form.Controls.Add($btnOpen)

$btnCopy = New-Object System.Windows.Forms.Button
$btnCopy.Text = "复制结果"
$btnCopy.Size = New-Object System.Drawing.Size(110, 34)
$btnCopy.Location = New-Object System.Drawing.Point(446, 638)
$btnCopy.Add_Click({ try { [System.Windows.Forms.Clipboard]::SetText(($rep -join "`r`n")); $btnCopy.Text = "已复制" } catch {} })
$form.Controls.Add($btnCopy)

[void]$form.ShowDialog()