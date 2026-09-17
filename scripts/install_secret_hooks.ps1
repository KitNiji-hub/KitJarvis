param([string]$GitleaksPath)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$existing = git config --get core.hooksPath
if ($existing -and $existing -ne '.githooks') {
    throw 'A different hooksPath is configured. Integrate those hooks explicitly before installing.'
}
if (-not $existing) {
    foreach ($hook in @('pre-commit', 'pre-push')) {
        $activeHook = git rev-parse --git-path "hooks/$hook"
        if (Test-Path -LiteralPath $activeHook) {
            throw 'An existing local hook needs explicit integration before changing hooksPath.'
        }
    }
}
if ($GitleaksPath) {
    $resolvedScanner = (Resolve-Path -LiteralPath $GitleaksPath).Path
} else {
    $resolvedScanner = (Get-Command gitleaks -ErrorAction Stop).Source
}
$version = & $resolvedScanner version
if ($LASTEXITCODE -ne 0 -or $version.Trim().TrimStart('v') -ne '8.30.1') {
    throw 'Gitleaks 8.30.1 is required. See SECURITY.md for verified installation.'
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ must be on PATH for Git hooks.' }
git config --local secretguard.gitleaksPath $resolvedScanner
if ($LASTEXITCODE -ne 0) { throw 'Unable to configure scanner path.' }
python scripts/secret_guard.py check
if ($LASTEXITCODE -ne 0) { throw 'Scanner verification failed.' }
git config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { throw 'Unable to configure hooksPath.' }
Write-Host 'Installed pre-commit and pre-push secret protection for this checkout.'
