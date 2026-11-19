# 编译 .exe 启动器（Windows 自带 .NET 的 csc，不需要装任何东西）
# 用法： powershell -ExecutionPolicy Bypass -File 启动器源码\编译.ps1
# 输出： 程序根目录\启动黑匣子叠加工具.exe
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cs = Join-Path $here "启动器.cs"
$out = Join-Path $root "启动黑匣子叠加工具.exe"

$csc = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $csc) {
    Write-Host "没找到 .NET 的 csc.exe（Windows 自带应该有），可以改用 vbs 启动器。" -ForegroundColor Red
    exit 1
}

Write-Host "编译中：$cs"
& $csc /nologo /target:winexe /codepage:65001 /optimize+ `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll `
    /out:"$out" "$cs"

if (Test-Path $out) {
    Write-Host ("完成：" + $out + "  " + [int]((Get-Item $out).Length / 1KB) + " KB") -ForegroundColor Green
} else {
    Write-Host "编译失败" -ForegroundColor Red
    exit 1
}