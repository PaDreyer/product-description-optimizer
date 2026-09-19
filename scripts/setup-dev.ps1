param(
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DevVenv = Join-Path $ProjectRoot "venv"

Push-Location $ProjectRoot
try {
    if ($Python -eq "py") {
        & $Python -3.12 -m venv $DevVenv
    }
    else {
        & $Python -m venv $DevVenv
    }
    if ($LASTEXITCODE -ne 0) { throw "Creating the development environment failed." }
    $DevPython = Join-Path $DevVenv "Scripts\python.exe"
    & $DevPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Upgrading pip failed." }
    & $DevPython -m pip install -e ".[dev,desktop,gemini,zhipuai,openai]"
    if ($LASTEXITCODE -ne 0) { throw "Installing project dependencies failed." }
}
finally {
    Pop-Location
}

Write-Host "Development environment is ready."
Write-Host "Activate it with: .\venv\Scripts\Activate.ps1"
