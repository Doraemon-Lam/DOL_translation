param([string]$Python = 'python', [string]$BaseDictionary = '')
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskBin = Join-Path $taskRoot 'build\bin'
$taskObjects = Join-Path $taskRoot 'build\obj'
New-Item -ItemType Directory -Path $taskBin,$taskObjects -Force | Out-Null
if (-not $BaseDictionary) { $BaseDictionary = Join-Path $taskRoot 'dictionaries\base.json' }
& $Python -X utf8 "$taskRoot\tools\dictionary.py" --input $BaseDictionary --output "$taskBin\translation-dictionary.bin" --digest-header "$taskObjects\dictionary-digest.h"
if ($LASTEXITCODE -ne 0) { throw 'Base dictionary compilation failed' }
$taskSupplements = @(Get-ChildItem -LiteralPath "$taskRoot\dictionaries" -Filter 'supplement-*.json' | Sort-Object Name | ForEach-Object FullName)
& $Python -X utf8 "$taskRoot\tools\dictionary.py" --input @taskSupplements --output "$taskBin\live-overlay.bin" --variants --overlay
if ($LASTEXITCODE -ne 0) { throw 'Overlay compilation failed' }
& $Python -X utf8 -m unittest discover -s "$taskRoot\tests" -v
if ($LASTEXITCODE -ne 0) { throw 'Dictionary tests failed' }

$taskVsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $taskVsWhere)) { throw 'Install Visual Studio C++ Build Tools and the Windows SDK' }
$taskVs = & $taskVsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $taskVs) { throw 'No Visual Studio C++ toolchain found' }
$taskVcVersion = (Get-Content -LiteralPath "$taskVs\VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt" -Raw).Trim()
$taskVc = Join-Path $taskVs "VC\Tools\MSVC\$taskVcVersion"
$taskSdk = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots').KitsRoot10
$taskSdkVersion = Get-ChildItem -LiteralPath "$taskSdk\Lib" -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' -and (Test-Path -LiteralPath "$($_.FullName)\um\x86\kernel32.lib") } | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1 -ExpandProperty Name
if (-not $taskSdkVersion) { throw 'No x86 Windows SDK found' }
$env:INCLUDE = "$taskVc\include;$taskSdk\Include\$taskSdkVersion\ucrt;$taskSdk\Include\$taskSdkVersion\shared;$taskSdk\Include\$taskSdkVersion\um"
$env:LIB = "$taskVc\lib\x86;$taskSdk\Lib\$taskSdkVersion\ucrt\x86;$taskSdk\Lib\$taskSdkVersion\um\x86"
$taskCompiler = "$taskVc\bin\Hostx64\x86\cl.exe"
Push-Location -LiteralPath $taskObjects
try {
    & $taskCompiler /nologo /W3 /O2 /MT /c "$taskRoot\third_party\minhook\src\buffer.c" "$taskRoot\third_party\minhook\src\hook.c" "$taskRoot\third_party\minhook\src\trampoline.c" "$taskRoot\third_party\minhook\src\hde\hde32.c"
    if ($LASTEXITCODE -ne 0) { throw 'MinHook compilation failed' }
    $taskFlags = @('/nologo','/W4','/EHsc','/std:c++17','/utf-8','/MT','/DFULL_DICTIONARY','/DLIVE_OVERLAY',"/I$taskRoot\third_party\minhook\include","/I$taskObjects")
    $taskObjectFiles = @('buffer.obj','hook.obj','trampoline.obj','hde32.obj')
    & $taskCompiler @taskFlags /Od /DLOCALIZER_SELFTEST /DLOGGER_SELFTEST "$taskRoot\src\localizer.cpp" @taskObjectFiles "/Fe$taskBin\localizer-selftest.exe" /link /MACHINE:X86 bcrypt.lib
    if ($LASTEXITCODE -ne 0) { throw 'Native test compilation failed' }
    & "$taskBin\localizer-selftest.exe"
    if ($LASTEXITCODE -ne 0) { throw "Native ABI/log/overlay tests failed: $LASTEXITCODE" }
    & $taskCompiler @taskFlags /O2 /LD "$taskRoot\src\localizer.cpp" @taskObjectFiles "/Fe$taskBin\dol-localizer-experimental.dll" /link /MACHINE:X86 bcrypt.lib "/DEF:$taskRoot\src\localizer.def"
    if ($LASTEXITCODE -ne 0) { throw 'DLL compilation failed' }
    & $taskCompiler /nologo /W4 /EHsc /std:c++17 /utf-8 /O2 /MT "$taskRoot\src\loader.cpp" "/Fe$taskBin\localizer-loader.exe" /link /MACHINE:X86
    if ($LASTEXITCODE -ne 0) { throw 'Loader compilation failed' }
    & "$taskBin\localizer-loader.exe" --selftest-dll "$taskBin\dol-localizer-experimental.dll"
    if ($LASTEXITCODE -ne 0) { throw 'DLL host guard / export tests failed' }
} finally { Pop-Location }
$taskManifest = [ordered]@{formatVersion=1;architecture='x86';gameSha256='ef9aa7a832c5ecf874238f2e4b5d185cdb6c8d26b14cba7102d98dbfc82116ae';files=[ordered]@{}}
foreach ($taskName in @('dol-localizer-experimental.dll','localizer-loader.exe','translation-dictionary.bin')) {
    $taskManifest.files[$taskName] = (Get-FileHash -LiteralPath "$taskBin\$taskName" -Algorithm SHA256).Hash.ToLowerInvariant()
}
$taskManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$taskBin\manifest.json" -Encoding utf8
Write-Output "Build and tests passed: $taskBin"
