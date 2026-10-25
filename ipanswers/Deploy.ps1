#requires -Version 7.0
[CmdletBinding()]
param([string]$SshAlias = 'lon1', [switch]$Diagnose)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$remotePath = '/tmp/ipanswers-' + [guid]::NewGuid().ToString('N')
$archive = Join-Path ([IO.Path]::GetTempPath()) ('ipanswers-' + [guid]::NewGuid().ToString('N') + '.tar.gz')
try {
    foreach ($tool in @('ssh', 'scp', 'tar')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Required tool missing: $tool" }
    }
    if ($SshAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { throw 'Use an SSH config alias such as lon1.' }
    Write-Host "Connecting using your existing '$SshAlias' SSH alias..."
    & tar -czf $archive -C $PSScriptRoot server.py checker.py update_data.py requirements.txt site deploy-server.py diagnose_server.py nginx_frontend.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not build upload archive.' }
    & ssh $SshAlias "umask 077; mkdir '$remotePath'"
    if ($LASTEXITCODE -ne 0) { throw 'SSH connection failed.' }
    & scp $archive "${SshAlias}:$remotePath/site.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
    $serverArguments = ''
    if ($Diagnose) {
        $serverArguments = ' --diagnose'
        Write-Host 'Read-only web-server diagnostic. Enter your lon1 sudo password when prompted.'
    } else {
        Write-Host 'Installing. Enter your lon1 sudo password when prompted.'
        Write-Host 'First installation downloads the local location/network databases; allow a few minutes.'
    }
    & ssh -t $SshAlias "tar -xzf '$remotePath/site.tar.gz' -C '$remotePath' && sudo python3 '$remotePath/deploy-server.py'$serverArguments"
    if ($LASTEXITCODE -ne 0) { throw "Server installation failed. Installer files remain at $remotePath for diagnosis." }
    & ssh $SshAlias "rm -rf -- '$remotePath'"
    if ($Diagnose) {
        Write-Host 'Diagnostic complete. Send the output so the active web-server setup can be matched.'
    } else {
        Write-Host 'Ready: https://ipanswers.space' -ForegroundColor Green
    }
} finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
