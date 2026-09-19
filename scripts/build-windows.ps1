param(
    [string]$Python = "py",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildVenv = Join-Path ([System.IO.Path]::GetTempPath()) ("PDO-Build-" + [guid]::NewGuid())

function Assert-NativeCommandSucceeded {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Push-Location $ProjectRoot
try {
    if ($Python -eq "py") {
        & $Python -3.12 -m venv $BuildVenv
    }
    else {
        & $Python -m venv $BuildVenv
    }
    Assert-NativeCommandSucceeded "Creating the build environment"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
    & $BuildPython -m pip install --upgrade pip
    Assert-NativeCommandSucceeded "Upgrading pip"
    & $BuildPython -m pip install -r (Join-Path $ProjectRoot "requirements-build.txt")
    Assert-NativeCommandSucceeded "Installing build dependencies"

    $env:QT_QPA_PLATFORM = "offscreen"
    & $BuildPython -m pytest tests/test_cli.py tests/test_desktop.py `
        tests/test_daemon.py::TestPidManagement tests/test_protocol.py `
        tests/test_integration.py tests/test_importer.py tests/test_exporter.py -q
    Assert-NativeCommandSucceeded "CLI, desktop, and pipeline tests"

    $SpecDir = Join-Path $ProjectRoot "build\spec"
    New-Item -ItemType Directory -Path $SpecDir -Force | Out-Null
    $BuildArgs = @(
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "PDO", "--specpath", $SpecDir,
        "--paths", (Join-Path $ProjectRoot "src"),
        "--collect-data", "pdo.desktop",
        "--hidden-import", "google.genai",
        "--hidden-import", "zhipuai",
        "--hidden-import", "openai",
        "--icon", (Join-Path $ProjectRoot "packaging\windows\pdo.ico"),
        (Join-Path $ProjectRoot "src\pdo\desktop\app.py")
    )
    & $BuildPython -m PyInstaller @BuildArgs
    Assert-NativeCommandSucceeded "PyInstaller build"

    Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") `
        -Destination (Join-Path $ProjectRoot "dist\PDO\LICENSE")
    & (Join-Path $ProjectRoot "dist\PDO\PDO.exe") --smoke-test
    Assert-NativeCommandSucceeded "Packaged GUI smoke test"

    $Version = & $BuildPython -c "import pdo; print(pdo.__version__)"
    Assert-NativeCommandSucceeded "Version lookup"
    if (-not $InnoCompiler) {
        $Candidates = @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path ${env:ProgramFiles} "Inno Setup 7\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe")
        )
        $InnoCompiler = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    }
    if (-not $InnoCompiler -or -not (Test-Path $InnoCompiler)) {
        throw "Inno Setup was not found. Pass -InnoCompiler with the path to ISCC.exe."
    }
    & $InnoCompiler "/DMyAppVersion=$Version" `
        (Join-Path $ProjectRoot "packaging\windows\pdo.iss")
    Assert-NativeCommandSucceeded "Windows installer"
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $BuildVenv) {
        Remove-Item -LiteralPath $BuildVenv -Recurse -Force
    }
}

Write-Host "Done: $ProjectRoot\dist\installer\PDO-Setup-$Version-x64.exe"
