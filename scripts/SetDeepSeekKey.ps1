$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskKey = Read-Host 'Enter DeepSeek API key (input hidden)' -AsSecureString
$taskPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskKey)
try {
    if ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPtr).Length -eq 0) { throw 'Key cannot be empty.' }
} finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPtr) }
ConvertFrom-SecureString $taskKey | Set-Content -LiteralPath (Join-Path $taskRoot 'deepseek.key.protected') -Encoding Ascii
Write-Host 'Key saved for this Windows account.'
