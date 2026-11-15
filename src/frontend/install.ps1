# Installs the Windows frontend toolchain and dependencies. Use -Start to run Vite.
[CmdletBinding()]
param([switch]$Start)

$ErrorActionPreference = 'Stop'
$nodeVersion = '24.22.3'
$pnpmVersion = '11.25.0'

# SHA-256 from https://nodejs.org/dist/v24.22.3/SHASUMS256.txt
$nodeChecksums = @{
    x64   = 'e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f'
    arm64 = 'b3cc74a295b39d4f273271e96f58c06dd2b35757ca12abec64c7d0598b434f14'
}
$nativeArchitecture = $env:PROCESSOR_ARCHITEW6432
if (-not $nativeArchitecture) { $nativeArchitecture = $env:PROCESSOR_ARCHITECTURE }
$architecture = switch ($nativeArchitecture) {
    'AMD64' { 'x64' }
    'ARM64' { 'arm64' }
    default { throw 'This installer requires Windows on x64 or ARM64.' }
}

$toolsDir = Join-Path $PSScriptRoot '.frontend-tools'
$nodeRelease = "node-v$nodeVersion-win-$architecture"
$nodeDir = Join-Path $toolsDir $nodeRelease
$nodeExe = Join-Path $nodeDir 'node.exe'
$npmCmd = Join-Path $nodeDir 'npm.cmd'
$verifiedRuntime = Join-Path $nodeDir '.verified'
$pnpmDir = Join-Path $toolsDir "pnpm-$pnpmVersion"
$pnpmCmd = Join-Path $pnpmDir 'node_modules/.bin/pnpm.cmd'
$npmCache = Join-Path $toolsDir 'npm-cache'
$pnpmStore = Join-Path $toolsDir 'pnpm-store'
$originalPath = $env:Path

New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
Push-Location -LiteralPath $PSScriptRoot
try {
    # Keep a second installer from writing the same runtime or dependency tree.
    $lockPath = Join-Path $toolsDir 'install.lock'
    $installLock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        if (-not ((Test-Path -LiteralPath $verifiedRuntime -PathType Leaf) -and
                  (Test-Path -LiteralPath $nodeExe -PathType Leaf) -and
                  (Test-Path -LiteralPath $npmCmd -PathType Leaf))) {
            Write-Host "Downloading Node.js $nodeVersion for Windows $architecture..."
            $archivePath = Join-Path $toolsDir "$nodeRelease.zip"
            try {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -OutFile $archivePath `
                    -Uri "https://nodejs.org/dist/v$nodeVersion/$nodeRelease.zip"
                if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $nodeChecksums[$architecture]) {
                    throw "Node.js archive checksum failed for $nodeRelease."
                }
                Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsDir -Force
                New-Item -ItemType File -Force -Path $verifiedRuntime | Out-Null
            } finally {
                if (Test-Path -LiteralPath $archivePath -PathType Leaf) { Remove-Item -LiteralPath $archivePath }
            }
        }

        $env:Path = "$nodeDir;$originalPath"
        if (-not (Test-Path -LiteralPath $pnpmCmd -PathType Leaf)) {
            Write-Host "Installing pnpm $pnpmVersion..."
            New-Item -ItemType Directory -Force -Path $pnpmDir | Out-Null
            & $npmCmd install --prefix "$pnpmDir" --cache "$npmCache" --no-save --no-package-lock `
                --ignore-scripts --no-audit --no-fund "pnpm@$pnpmVersion"
            if ($LASTEXITCODE -ne 0) { throw "pnpm installation failed (exit code $LASTEXITCODE)." }
        }

        Write-Host 'Installing locked frontend dependencies...'
        # Recheck the dependency layout when a previous install used another store.
        & $pnpmCmd --store-dir "$pnpmStore" --config.confirm-modules-purge=false `
            --config.optimistic-repeat-install=false `
            install --frozen-lockfile --prod=false --prefer-offline --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed (exit code $LASTEXITCODE)." }
    } finally {
        $installLock.Dispose()
    }

    if ($Start) {
        & $pnpmCmd --config.verify-deps-before-run=false run dev
        if ($LASTEXITCODE -ne 0) { throw "Frontend server exited with code $LASTEXITCODE." }
    } else {
        Write-Host 'Frontend dependencies are ready. Run this installer with -Start to launch LunarSight.'
    }
} finally {
    $env:Path = $originalPath
    Pop-Location
}
