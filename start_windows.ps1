param(
    [int]$ObserveSeconds = 28800,
    [string]$DataDir = $(if ($env:GEN5W_DATA_DIR) { $env:GEN5W_DATA_DIR } else { $PSScriptRoot }),
    [string]$ToolsDir,
    [string]$Adb,
    [string]$ImageDir,
    [int]$EmulatorPort = 5588,
    [int]$AdbPort = 5042,
    [int]$ConsolePort = 5590
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot
$DataDir = (Resolve-Path $DataDir).Path
if (!$ToolsDir) { $ToolsDir = Join-Path $DataDir 'deps\classic-sdk\tools' }
if (!$Adb) { $Adb = Join-Path $DataDir 'deps\platform-tools\adb.exe' }
if (!$ImageDir) { $ImageDir = Join-Path $DataDir 'deps\api19\armeabi-v7a' }
$names = @('Gen5W-Emulator-Engine', 'Gen5W-Emulator-Launcher')
if (@(Get-NetFirewallRule -Name $names -ErrorAction SilentlyContinue).Count) {
    throw 'Existing task firewall rules must be inspected; they will not be overwritten.'
}
$remote = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
$created = @()
try {
    $programs = @((Join-Path $ToolsDir 'qemu\windows-x86_64\qemu-system-armel.exe'), (Join-Path $ToolsDir 'emulator.exe'))
    for ($i = 0; $i -lt $names.Count; $i++) {
        $program = (Resolve-Path $programs[$i]).Path
        New-NetFirewallRule -Name $names[$i] -DisplayName $names[$i] -Direction Outbound -Action Block -Profile Any -Program $program -RemoteAddress $remote | Out-Null
        $created += $names[$i]
    }
    $ramdisk = Join-Path $DataDir 'inputs\v039\v039-ranchu-root-console-logger-storage-no-micom-micom-sim-services.cpio.gz'
    py.exe -3 run_windows_baseline.py --data-dir $DataDir --tools-dir $ToolsDir --adb $Adb --image-dir $ImageDir --ranchu --v039 services --network isolated --seconds 600 --observe-seconds $ObserveSeconds --ramdisk $ramdisk --serial-port $ConsolePort --port $EmulatorPort --adb-port $AdbPort --buffer-count-two --display-size 800 480
    if ($LASTEXITCODE -ne 0) { throw "Emulator runner failed: $LASTEXITCODE" }
} finally {
    foreach ($name in $created) {
        Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
}
