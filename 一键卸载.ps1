# =====================================================================
#  bboverlay —— 一键卸载
#  只删除本程序自己目录里的东西（会逐个校验路径，绝不碰目录外的文件）
#  可选：卸载 pip 依赖、卸载本程序安装的 Python
#
#  直接双击「一键卸载程序.vbs」是图形界面；
#  命令行： -DryRun 只列出要删什么（不动手）
#           -Yes 不弹确认  -DeleteRuntime -DeleteOutput
#           -UninstallPackages -UninstallPython -DeleteFolder
# =====================================================================
param(
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$DeleteRuntime,
    [switch]$DeleteOutput,
    [switch]$UninstallPackages,
    [switch]$UninstallPython,
    [switch]$DeleteFolder
)

$ErrorActionPreference = "Continue"
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $env:PYTHONIOENCODING = "utf-8"
} catch {}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dirFull = [System.IO.Path]::GetFullPath($dir).TrimEnd('\')
$script:lines = New-Object System.Collections.ArrayList
$script:did = New-Object System.Collections.ArrayList

function Out-Line($t) {
    [void]$script:lines.Add($t)
    Write-Host $t
}

# 安全护栏：任何要删的路径都必须在本程序目录里面
function Test-InScope($p) {
    try {
        $full = [System.IO.Path]::GetFullPath($p).TrimEnd('\')
    } catch { return $false }
    if ($full -eq $dirFull) { return $false }          # 目录本身不在这里删
    return $full.StartsWith($dirFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Get-Size($p) {
    try {
        if (-not (Test-Path $p)) { return 0 }
        $i = Get-Item $p -Force
        if ($i.PSIsContainer) {
            $s = (Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
            if ($s) { return [int64]$s }
            return 0
        }
        return [int64]$i.Length
    } catch { return 0 }
}

function Fmt-Size($b) {
    if ($b -ge 1GB) { return "{0:N2} GB" -f ($b / 1GB) }
    if ($b -ge 1MB) { return "{0:N1} MB" -f ($b / 1MB) }
    if ($b -ge 1KB) { return "{0:N0} KB" -f ($b / 1KB) }
    return "$b B"
}

function Remove-ItemSafe($p, $label) {
    if (-not (Test-InScope $p)) {
        Out-Line ("  [跳过] 不在程序目录内，拒绝删除：" + $p)
        return
    }
    if (-not (Test-Path $p)) { return }
    if ($DryRun) {
        Out-Line ("  [试跑] 将删除：" + $p)
        return
    }
    try {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
        Out-Line ("  [已删] " + $label + "：" + $p)
        [void]$script:did.Add($p)
    } catch {
        Out-Line ("  [失败] " + $p + " —— " + $_.Exception.Message)
    }
}

# ------------------------------------------------------------------ 要找的东西
$runtimeDirs = @("work", "cache", "__pycache__")
$runtimeFiles = @("gui_config.json", "python-path.txt", "配置日志.txt", "配置记录.json", "安装记录.json")
$outputDirs = @("输出", "output")

$plan = @()
foreach ($d in $runtimeDirs) {
    $p = Join-Path $dir $d
    if ((Test-Path $p) -and (Get-Size $p) -gt 0) { $plan += [pscustomobject]@{Kind = "runtime"; Path = $p; Text = "$d/（解码缓存、瓦片、图层缓存）" } }
}
foreach ($f in $runtimeFiles) {
    $p = Join-Path $dir $f
    if (Test-Path $p) { $plan += [pscustomobject]@{Kind = "runtime"; Path = $p; Text = $f } }
}
foreach ($d in $outputDirs) {
    $p = Join-Path $dir $d
    if ((Test-Path $p) -and (Get-Size $p) -gt 0) { $plan += [pscustomobject]@{Kind = "output"; Path = $p; Text = "$d/（你生成的成片）" } }
}

# pip 依赖是否还在
$py = ""
$ppFile = Join-Path $dir "python-path.txt"
if (Test-Path $ppFile) {
    try {
        $pyw = (Get-Content -LiteralPath $ppFile -Encoding Unicode -Raw).Trim()
        if ($pyw -and (Test-Path $pyw)) { $py = $pyw -replace 'pythonw\.exe$', 'python.exe'; if (-not (Test-Path $py)) { $py = "" } }
    } catch {}
}
if (-not $py) {
    foreach ($c in @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
                     (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
                     (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
                     "C:\Python313\python.exe", "C:\Python312\python.exe", "C:\Python311\python.exe")) {
        if (Test-Path $c) { $py = $c; break }
    }
}
$hasPkgs = $false
if ($py) {
    try {
        $out = & $py -m pip show pillow numpy pandas 2>$null
        $hasPkgs = ($out -match "^Name:")
    } catch {}
}

# 安装记录（配置程序写的），用来判断 Python 是不是本程序装的
$rec = $null
$recPath = Join-Path $dir "安装记录.json"
if (Test-Path $recPath) {
    try { $rec = Get-Content -LiteralPath $recPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $rec = $null }
}
$pyInstalledByUs = $false
$pyMethod = ""
if ($rec -and $rec.python_method -and $rec.python_method -ne "already") {
    $pyInstalledByUs = $true
    $pyMethod = $rec.python_method
}

# ------------------------------------------------------------------ 界面
function Run-Uninstall([bool]$doRuntime, [bool]$doOutput, [bool]$doPkgs, [bool]$doPython, [bool]$doFolder) {
    Out-Line ""
    Out-Line "开始卸载……"
    if ($doRuntime) {
        Out-Line "[1] 运行时文件"
        foreach ($it in $plan | Where-Object { $_.Kind -eq "runtime" }) { Remove-ItemSafe $it.Path $it.Text }
    }
    if ($doOutput) {
        Out-Line "[2] 输出文件夹（生成的视频）"
        foreach ($it in $plan | Where-Object { $_.Kind -eq "output" }) { Remove-ItemSafe $it.Path $it.Text }
    }
    if ($doPkgs) {
        Out-Line "[3] pip 依赖（pillow / numpy / pandas）"
        if ($DryRun) { Out-Line "  [试跑] 将执行 pip uninstall pillow numpy pandas" }
        elseif ($py) {
            & $py -m pip uninstall -y pillow numpy pandas 2>&1 | ForEach-Object { Out-Line ("  " + $_) }
        } else { Out-Line "  [跳过] 没找到 Python" }
    }
    if ($doPython) {
        Out-Line "[4] 卸载本程序安装的 Python"
        if ($DryRun) { Out-Line "  [试跑] 将卸载 Python（方法：$pyMethod）" }
        elseif (-not $pyInstalledByUs) { Out-Line "  [跳过] 记录里没有“由本程序安装 Python”" }
        else {
            $did = $false
            if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
                $ids = @("Python.Python.3.13", "Python.Python.3.12", "Python.Python.3.11")
                foreach ($id in $ids) {
                    & winget uninstall -e --id $id --silent 2>&1 | ForEach-Object { Out-Line ("  " + $_) }
                    if ($LASTEXITCODE -eq 0) { $did = $true; break }
                }
            }
            if (-not $did) {
                Out-Line "  自动卸载没成功。请手动到「设置 → 应用 → 已安装的应用」里卸载 Python。"
                try { Start-Process "ms-settings:appsfeatures" } catch {}
            }
        }
    }
    if ($doFolder) {
        Out-Line "[5] 删除整个程序文件夹"
        if ($DryRun) {
            Out-Line ("  [试跑] 将删除：" + $dir)
        } else {
            # 自己删不了自己：交给一个独立进程等 2 秒再删
            $cmd = 'ping -n 3 127.0.0.1 >nul & rmdir /s /q "' + $dir + '"'
            try {
                Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden
                Out-Line ("  已在后台安排删除：" + $dir)
            } catch {
                Out-Line ("  安排删除失败：" + $_.Exception.Message)
            }
        }
    }
    Out-Line ""
    if ($DryRun) { Out-Line "（试跑结束，没有真的删除任何东西）" }
    else { Out-Line ("卸载完成。" + $(if ($doFolder) { " 程序文件夹会在几秒后消失。" } else { "" })) }
}

if ($Yes) {
    # 命令行模式：默认删运行时文件，其它按开关
    $doRuntime = $true
    if ($PSBoundParameters.ContainsKey("DeleteRuntime") -and (-not $DeleteRuntime)) { $doRuntime = $false }
    Run-Uninstall $doRuntime ([bool]$DeleteOutput) ([bool]$UninstallPackages) ([bool]$UninstallPython) ([bool]$DeleteFolder)
    exit 0
}

# ---------- 图形界面
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try { [System.Windows.Forms.Application]::EnableVisualStyles() } catch {}

$form = New-Object System.Windows.Forms.Form
$form.Text = "bboverlay · 一键卸载"
$form.Size = New-Object System.Drawing.Size(740, 640)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(238, 241, 245)
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "要卸载什么？"
$lbl.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 15, [System.Drawing.FontStyle]::Bold)
$lbl.Location = New-Object System.Drawing.Point(18, 12)
$lbl.Size = New-Object System.Drawing.Size(300, 34)
$form.Controls.Add($lbl)

$lbl2 = New-Object System.Windows.Forms.Label
$lbl2.Text = "程序目录：$dir"
$lbl2.ForeColor = [System.Drawing.Color]::FromArgb(100, 105, 115)
$lbl2.Location = New-Object System.Drawing.Point(20, 48)
$lbl2.Size = New-Object System.Drawing.Size(690, 20)
$form.Controls.Add($lbl2)

$cbRuntime = New-Object System.Windows.Forms.CheckBox
$rtSize = 0
foreach ($it in $plan | Where-Object { $_.Kind -eq "runtime" }) { $rtSize += (Get-Size $it.Path) }
$cbRuntime.Text = "删除运行时文件（解码缓存 / 瓦片缓存 / 配置 / 日志，约 $(Fmt-Size $rtSize)）"
$cbRuntime.Checked = $true
$cbRuntime.Location = New-Object System.Drawing.Point(22, 80)
$cbRuntime.Size = New-Object System.Drawing.Size(660, 24)
$form.Controls.Add($cbRuntime)

$cbOutput = New-Object System.Windows.Forms.CheckBox
$outSize = 0
foreach ($it in $plan | Where-Object { $_.Kind -eq "output" }) { $outSize += (Get-Size $it.Path) }
$cbOutput.Text = "删除「输出」文件夹里生成的视频（约 $(Fmt-Size $outSize)）—— 删了成片就没了"
$cbOutput.Checked = $false
$cbOutput.Location = New-Object System.Drawing.Point(22, 110)
$cbOutput.Size = New-Object System.Drawing.Size(660, 24)
$form.Controls.Add($cbOutput)

$cbPkgs = New-Object System.Windows.Forms.CheckBox
$cbPkgs.Text = "卸载 pip 依赖 pillow / numpy / pandas（注意：其他 Python 程序可能也在用）"
$cbPkgs.Checked = $false
$cbPkgs.Enabled = $hasPkgs
$cbPkgs.Location = New-Object System.Drawing.Point(22, 140)
$cbPkgs.Size = New-Object System.Drawing.Size(660, 24)
$form.Controls.Add($cbPkgs)

$cbPython = New-Object System.Windows.Forms.CheckBox
$cbPython.Text = if ($pyInstalledByUs) { "卸载本程序安装的 Python（$pyMethod）" } else { "卸载 Python（本次没记录到是本程序装的，默认不动）" }
$cbPython.Checked = $false
$cbPython.Enabled = $pyInstalledByUs
$cbPython.Location = New-Object System.Drawing.Point(22, 170)
$cbPython.Size = New-Object System.Drawing.Size(660, 24)
$form.Controls.Add($cbPython)

$cbFolder = New-Object System.Windows.Forms.CheckBox
$cbFolder.Text = "删除整个程序文件夹（含本卸载程序自己）"
$cbFolder.Checked = $true
$cbFolder.Location = New-Object System.Drawing.Point(22, 200)
$cbFolder.Size = New-Object System.Drawing.Size(660, 24)
$form.Controls.Add($cbFolder)

$txt = New-Object System.Windows.Forms.TextBox
$txt.Multiline = $true
$txt.ReadOnly = $true
$txt.ScrollBars = "Vertical"
$txt.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 42)
$txt.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
$txt.Font = New-Object System.Drawing.Font("Consolas", 9)
$txt.Location = New-Object System.Drawing.Point(22, 234)
$txt.Size = New-Object System.Drawing.Size(684, 300)
$txt.WordWrap = $false
$form.Controls.Add($txt)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = "开始卸载"
$btn.Size = New-Object System.Drawing.Size(130, 36)
$btn.Location = New-Object System.Drawing.Point(576, 548)
$btn.BackColor = [System.Drawing.Color]::FromArgb(190, 40, 40)
$btn.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($btn)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "取消"
$btnClose.Size = New-Object System.Drawing.Size(110, 36)
$btnClose.Location = New-Object System.Drawing.Point(452, 548)
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

function Flush-Log {
    foreach ($l in $script:lines) { $txt.AppendText("$l`r`n") }
    $script:lines.Clear()
    $txt.SelectionStart = $txt.Text.Length
    $txt.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

Out-Line "本程序只会删除它自己目录里的内容："
Out-Line ("  " + $dir)
Out-Line ""
if ($plan.Count -eq 0) { Out-Line "（没有需要清理的运行时文件）" }
foreach ($it in $plan) {
    Out-Line ("  · " + $it.Text + "   " + (Fmt-Size (Get-Size $it.Path)))
}
Out-Line ""
if (-not $hasPkgs) { Out-Line "（当前 Python 里没找到 pillow/numpy/pandas，或没找到 Python）" }
if ($py) { Out-Line ("Python：" + $py) }
Out-Line ""
Out-Line "勾选上面的项目后点「开始卸载」。默认只删运行时文件 + 程序文件夹，不动你的成片和 Python。"
Flush-Log

$btn.Add_Click({
    $msg = "确认卸载？`r`n`r`n"
    if ($cbRuntime.Checked) { $msg += "· 运行时文件`r`n" }
    if ($cbOutput.Checked) { $msg += "· 输出文件夹（生成的视频）`r`n" }
    if ($cbPkgs.Checked) { $msg += "· pip 依赖 pillow/numpy/pandas`r`n" }
    if ($cbPython.Checked) { $msg += "· 本程序安装的 Python`r`n" }
    if ($cbFolder.Checked) { $msg += "· 整个程序文件夹`r`n" }
    $msg += "`r`n删除后不可恢复，确定继续？"
    if ([System.Windows.Forms.MessageBox]::Show($msg, "再确认一下", "YesNo", "Warning") -ne "Yes") { return }
    $btn.Enabled = $false
    Run-Uninstall $cbRuntime.Checked $cbOutput.Checked $cbPkgs.Checked $cbPython.Checked $cbFolder.Checked
    Flush-Log
    [void][System.Windows.Forms.MessageBox]::Show("卸载完成，可以关掉这个窗口了。", "完成", "OK", "Information")
    $form.Close()
})

[void]$form.ShowDialog()