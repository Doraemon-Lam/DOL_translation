param([switch]$Disable,[switch]$NoUi)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskBin = Join-Path $taskRoot 'bin'
if (-not (Test-Path -LiteralPath "$taskBin\manifest.json")) { $taskBin = Join-Path $taskRoot 'build\bin' }
try {
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $taskArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        if ($Disable) { $taskArguments += ' -Disable' }
        if ($NoUi) { $taskArguments += ' -NoUi' }
        $taskChild = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -WindowStyle Hidden -ArgumentList $taskArguments -PassThru -Wait
        exit $taskChild.ExitCode
    }
    $taskManifest = Get-Content -LiteralPath "$taskBin\manifest.json" -Raw | ConvertFrom-Json
    foreach ($taskName in @('dol-localizer-experimental.dll','localizer-loader.exe','translation-dictionary.bin')) {
        if ((Get-FileHash -LiteralPath "$taskBin\$taskName" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.files.$taskName) { throw "Package hash mismatch: $taskName" }
    }
    $taskGames = @(Get-Process -Name 'GVOnline.bin' -ErrorAction SilentlyContinue)
    if ($taskGames.Count -ne 1) { throw 'Start exactly one game instance before loading localization.' }
    $taskMode = '--authorized-game-experiment'
    if ($Disable) { $taskMode = '--disable-translations' }
    & "$taskBin\localizer-loader.exe" $taskMode $taskGames[0].Id "$taskBin\dol-localizer-experimental.dll" *> "$taskBin\loader.log"
    $taskCode = $LASTEXITCODE
    $taskAlreadyLoaded = (-not $Disable -and $taskCode -eq 6)
    if ($taskCode -ne 0 -and -not $taskAlreadyLoaded) { throw "Loader returned $taskCode. See bin/loader.log. A different/old module may require a game restart." }
    @{pid=$taskGames[0].Id;disabled=[bool]$Disable;alreadyLoaded=$taskAlreadyLoaded;exitCode=$taskCode} | ConvertTo-Json | Set-Content -LiteralPath "$taskRoot\runtime-status.json" -Encoding utf8
    if (-not $NoUi) {
        Add-Type -AssemblyName System.Windows.Forms
        $taskMessage = 'Localization loaded. Reopen the dialog/menu. Reload after each game restart.'
        if ($Disable) { $taskMessage = 'Translation disabled for this game session. Restart the game to remove the module completely.' }
        if ($taskAlreadyLoaded) { $taskMessage = 'This localization package is already loaded.' }
        [System.Windows.Forms.MessageBox]::Show($taskMessage,'DOL translation') | Out-Null
    }
} catch {
    if ($NoUi) { Write-Error $_ } else { Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'DOL translation - error') | Out-Null }
    exit 1
}
