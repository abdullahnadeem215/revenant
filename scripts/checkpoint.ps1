# Full Revenant checkpoint: pytest, mypy --strict, ruff check, ruff format --check,
# and the Hypothesis tests N times. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\checkpoint.ps1 [-HypothesisRuns 20]
# Exits 0 only if every step passes.

param([int]$HypothesisRuns = 20)

$ErrorActionPreference = "Continue"
$core = Join-Path $PSScriptRoot "..\revenant-core"
$py = Join-Path $core ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv not found at $py. Create it in revenant-core first."
    exit 2
}

Push-Location $core
$failedSteps = @()

function Invoke-Step([string]$Title, [string[]]$CmdArgs) {
    Write-Host "=== $Title"
    $out = & $py @CmdArgs 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Host $out.TrimEnd()
    Write-Host "exit=$code"
    if ($code -ne 0) { $script:failedSteps += $Title }
}

Invoke-Step "pytest" @("-m", "pytest", "-p", "no:cacheprovider")
Invoke-Step "mypy --strict" @("-m", "mypy", "--strict", "src", "tests")
Invoke-Step "ruff check" @("-m", "ruff", "check", "src", "tests")
Invoke-Step "ruff format --check" @("-m", "ruff", "format", "--check", "src", "tests")

Write-Host "=== hypothesis x $HypothesisRuns"
$hypoFailures = 0
for ($i = 1; $i -le $HypothesisRuns; $i++) {
    $out = & $py -m pytest -q -m hypothesis -p no:cacheprovider 2>&1 | Out-String
    $code = $LASTEXITCODE
    $last = ($out.Trim() -split "`n")[-1].Trim()
    if ($code -ne 0) {
        $hypoFailures++
        Write-Host "run $i exit=$code FAILED"
        Write-Host $out.TrimEnd()
    } else {
        Write-Host "run $i exit=0 $last"
    }
}
Write-Host "hypothesis failing runs: $hypoFailures / $HypothesisRuns"
if ($hypoFailures -gt 0) { $failedSteps += "hypothesis" }

Pop-Location

Write-Host "=== summary"
if ($failedSteps.Count -eq 0) {
    Write-Host "CHECKPOINT PASSED"
    exit 0
}
Write-Host "CHECKPOINT FAILED: $($failedSteps -join ', ')"
exit 1
