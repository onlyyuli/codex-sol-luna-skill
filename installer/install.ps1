param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "upgrade", "uninstall", "doctor")]
    [string]$Action = "install",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
    throw "Python 3 is required."
}

$localInstaller = Join-Path $PSScriptRoot "sol_luna_installer.py"
if (Test-Path -LiteralPath $localInstaller -PathType Leaf) {
    & $python.Source $localInstaller $Action @RemainingArgs
    if ($LASTEXITCODE -ne 0) {
        throw "sol-luna installer failed with exit code $LASTEXITCODE."
    }
    return
}

$repository = if ($env:SOL_LUNA_REPOSITORY) { $env:SOL_LUNA_REPOSITORY } else { "__GITHUB_REPOSITORY__" }
$releaseRef = if ($env:SOL_LUNA_REF) { $env:SOL_LUNA_REF } else { "__SOL_LUNA_REF__" }
$repositoryPlaceholder = "__GITHUB_" + "REPOSITORY__"
$refPlaceholder = "__SOL_LUNA_" + "REF__"
if ($repository -eq $repositoryPlaceholder) {
    throw "This source wrapper is not a release asset. Set SOL_LUNA_REPOSITORY=owner/repo."
}
if ($releaseRef -eq $refPlaceholder) {
    $releaseRef = "v0.1.0"
}

$tempFile = Join-Path ([System.IO.Path]::GetTempPath()) ("sol_luna_installer_" + [Guid]::NewGuid() + ".py")
$hadRepositoryEnv = Test-Path Env:SOL_LUNA_REPOSITORY
$hadRefEnv = Test-Path Env:SOL_LUNA_REF
$previousRepositoryEnv = $env:SOL_LUNA_REPOSITORY
$previousRefEnv = $env:SOL_LUNA_REF
try {
    $url = "https://raw.githubusercontent.com/$repository/$releaseRef/installer/sol_luna_installer.py"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tempFile
    $env:SOL_LUNA_REPOSITORY = $repository
    $env:SOL_LUNA_REF = $releaseRef
    & $python.Source $tempFile $Action @RemainingArgs
    if ($LASTEXITCODE -ne 0) {
        throw "sol-luna installer failed with exit code $LASTEXITCODE."
    }
}
finally {
    if ($hadRepositoryEnv) {
        $env:SOL_LUNA_REPOSITORY = $previousRepositoryEnv
    }
    else {
        Remove-Item Env:SOL_LUNA_REPOSITORY -ErrorAction SilentlyContinue
    }
    if ($hadRefEnv) {
        $env:SOL_LUNA_REF = $previousRefEnv
    }
    else {
        Remove-Item Env:SOL_LUNA_REF -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
}
