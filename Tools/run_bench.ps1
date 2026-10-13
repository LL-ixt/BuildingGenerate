# M5/M6: run the city fly-through benchmark (Builds/Bench/HanoiBench.exe, built by CityBenchmarkBuild.RunBatch)
# for several configurations; results (csv / txt / png) land in Unity_logs/bench/.
#
#   powershell -ExecutionPolicy Bypass -File Tools/run_bench.ps1                 # default set: grd0, grd1
#   powershell -ExecutionPolicy Bypass -File Tools/run_bench.ps1 -Configs "grd1_occ:-grd 1 -occlusion 1"
#
# The exe is pinned to the high-performance GPU (RTX on this laptop) via the per-app Windows graphics
# preference (Settings > System > Display > Graphics); remove it there if needed.
param(
    [string[]]$Configs = @("grd0:-grd 0", "grd1:-grd 1"),
    [int]$TimeoutMin = 10
)
$ErrorActionPreference = "Stop"
# with -File, "a","b" arrives as one string "a,b": split it again
$Configs = @($Configs | ForEach-Object { $_ -split ',' } | Where-Object { $_ -ne '' })
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "Builds\Bench\HanoiBench.exe"
$out = Join-Path $root "Unity_logs\bench"
if (-not (Test-Path $exe)) { throw "missing $exe (run CityBenchmarkBuild.RunBatch first)" }
New-Item -ItemType Directory -Force $out | Out-Null

$key = "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences"
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
Set-ItemProperty -Path $key -Name $exe -Value "GpuPreference=2;"

foreach ($c in $Configs) {
    $tag, $extra = $c.Split(":", 2)
    $log = Join-Path $out "player_$tag.log"
    $argList = "-hanoiBench -benchTag $tag -benchOut `"$out`" -screen-width 1920 -screen-height 1080 -screen-fullscreen 0 -logFile `"$log`" $extra"
    Write-Host "[bench] ${tag} : $argList"
    $txt = Join-Path $out "bench_$tag.txt"
    if (Test-Path $txt) { Remove-Item $txt }
    $p = Start-Process -FilePath $exe -ArgumentList $argList -PassThru
    if (-not $p.WaitForExit($TimeoutMin * 60 * 1000)) { $p.Kill(); Write-Host "[bench] ${tag} TIMEOUT" }
    if (Test-Path $txt) { Get-Content $txt -Encoding UTF8 } else { Write-Host "[bench] ${tag}: no result, see $log" }
}
