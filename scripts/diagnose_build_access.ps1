# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_build_access.ps1
# Optional: -RepairReadOnly (removes the read-only attribute, NOT ACL/Defender restrictions)
[CmdletBinding()]
param([switch]$RepairReadOnly)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$path = Join-Path $root 'src\web_manager.cpp'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "File not found: $path"
}
$file = Get-Item -LiteralPath $path
Write-Host "Project: $root"
Write-Host "File: $path"
Write-Host "Read-only: $($file.IsReadOnly)"
Write-Host "Windows identity: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
$acl = Get-Acl -LiteralPath $path
Write-Host "Owner: $($acl.Owner)"
Write-Host "ACL entries:"
$acl.Access | Select-Object IdentityReference, FileSystemRights, AccessControlType, IsInherited | Format-Table -AutoSize
if ($RepairReadOnly -and $file.IsReadOnly) {
    $file.IsReadOnly = $false
    Write-Host 'Read-only attribute cleared.' -ForegroundColor Green
}
# File.Open(ReadWrite) checks whether the caller can open the existing file for writing.
# It does not truncate or modify the contents. Shared-read avoids many benign editor conflicts.
try {
    $stream = [System.IO.File]::Open($path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::Read)
    $stream.Dispose()
    Write-Host 'Read/write open test: OK (file NOT modified)' -ForegroundColor Green
} catch {
    Write-Warning "Read/write open test failed: $($_.Exception.Message)"
    Write-Warning 'Inspect Windows Security > Ransomware protection > Protection history, antivirus and other build processes.'
}
try {
    $prefs = Get-MpPreference -ErrorAction Stop
    Write-Host "Defender Controlled Folder Access (raw status): $($prefs.EnableControlledFolderAccess)"
} catch {
    Write-Host 'Defender configuration not accessible in this session.'
}
