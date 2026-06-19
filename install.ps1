#Requires -Version 5.1
<#
.SYNOPSIS
    Delux Agent - Windows Installer
.DESCRIPTION
    Installs Delux Agent on Windows using PowerShell.
    Requires Python 3.11+.
.NOTES
    Run in PowerShell: .\install.ps1
    Or one-liner: powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.ps1 | iex"
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [switch]$NoShell,
    [switch]$NoSetup,
    [switch]$Help
)

# ── Colors ────────────────────────────────────────────────────────────
$Script:Cyan    = "`e[36m"
$Script:Green   = "`e[32m"
$Script:Yellow  = "`e[33m"
$Script:Red     = "`e[31m"
$Script:Bold    = "`e[1m"
$Script:Reset   = "`e[0m"
$Script:Dim     = "`e[2m"

function Write-Info    { param($m) Write-Host "  $($Script:Cyan)ℹ$($Script:Reset)  $m" }
function Write-OK      { param($m) Write-Host "  $($Script:Green)✓$($Script:Reset)  $m" }
function Write-Warn    { param($m) Write-Host "  $($Script:Yellow)⚠$($Script:Reset)  $m" }
function Write-Err     { param($m) Write-Host "  $($Script:Red)✗$($Script:Reset)  $m" -ForegroundColor Red }

function Show-Help {
    Write-Host @"

${Script:Bold}${Script:Cyan}◆${Script:Reset} ${Script:Bold}Delux Agent Windows Installer${Script:Reset}

Usage: .\install.ps1 [options]

Options:
  -InstallDir DIR   Install directory (default: $env:LOCALAPPDATA\delux)
  -NoShell          Skip PATH modification
  -NoSetup          Skip interactive setup wizard
  -Help             Show this help

Examples:
  .\install.ps1
  .\install.ps1 -InstallDir C:\delux
  .\install.ps1 -NoSetup

"@
    exit 0
}

if ($Help) { Show-Help }

# ── Check Python ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ${Script:Bold}${Script:Cyan}◆${Script:Reset} ${Script:Bold}Delux Agent Installer${Script:Reset}"
Write-Host "  ${Script:Dim}Shell-first AI assistant with skills, memory, MCP, and IDE${Script:Reset}"
Write-Host ""

$pythonCmd = $null
$pythonVersion = $null

# Check for Python in PATH, py launcher, and common locations
$candidates = @("python", "python3", "py -3")
$commonPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
    "$env:ProgramFiles\Python3*\python.exe",
    "${env:ProgramFiles(x86)}\Python3*\python.exe"
)

foreach ($cmd in $candidates) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "3\.(1[1-9]|[2-9][0-9])") {
            $pythonCmd = $cmd
            $pythonVersion = $version
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    foreach ($pattern in $commonPaths) {
        $paths = Get-ChildItem -Path (Resolve-Path -ErrorAction SilentlyContinue $pattern) -ErrorAction SilentlyContinue
        foreach ($p in $paths) {
            try {
                $version = & $p.FullName --version 2>&1
                if ($version -match "3\.(1[1-9]|[2-9][0-9])") {
                    $pythonCmd = $p.FullName
                    $pythonVersion = $version
                    break
                }
            } catch {}
        }
        if ($pythonCmd) { break }
    }
}

if (-not $pythonCmd) {
    Write-Err "Python 3.11+ not found."
    Write-Host ""
    Write-Host "  Install Python from: https://www.python.org/downloads/"
    Write-Host "  Or use winget: winget install Python.Python.3.12"
    Write-Host "  Then add Python to PATH during installation."
    exit 1
}

Write-OK "Python $pythonVersion found"

# ── Install Directory ──────────────────────────────────────────────────
if ($InstallDir -eq "") {
    if (Test-Path ".\pyproject.toml") {
        $InstallDir = (Get-Location).Path
        Write-Info "Installing from source: $InstallDir"
    } else {
        $InstallDir = "$env:LOCALAPPDATA\delux"
        Write-Info "Default install: $InstallDir"
    }
}

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$venvDir = Join-Path $InstallDir ".venv"

# ── Create Virtual Environment ────────────────────────────────────────
Write-Host ""
Write-Info "Creating virtual environment..."

& $pythonCmd -m venv $venvDir 2>$null

if (-not (Test-Path "$venvDir\Scripts\python.exe")) {
    Write-Err "Failed to create virtual environment"
    exit 1
}

$venvPython = "$venvDir\Scripts\python.exe"
$venvPip = "$venvDir\Scripts\pip.exe"

# ── Install ───────────────────────────────────────────────────────────
Write-Info "Installing Delux Agent..."

if (Test-Path ".\pyproject.toml") {
    & $venvPython -m pip install -e . --quiet 2>$null
} else {
    & $venvPip install delux-agent --quiet 2>$null
}

if ($LASTEXITCODE -ne 0) {
    Write-Err "Installation failed"
    exit 1
}

Write-OK "Installed to $venvDir"

# ── Add to PATH (optional) ────────────────────────────────────────────
if (-not $NoShell) {
    $scriptsDir = "$venvDir\Scripts"
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")

    if ($currentPath -notlike "*$scriptsDir*") {
        Write-Host ""
        Write-Info "Adding Delux to user PATH..."

        try {
            [Environment]::SetEnvironmentVariable(
                "Path",
                "$currentPath;$scriptsDir",
                "User"
            )
            Write-OK "Added $scriptsDir to PATH"
            Write-Host "  ${Script:Dim}Open a new terminal to use 'delux' command${Script:Reset}"
        } catch {
            Write-Warn "Could not modify PATH. Add $scriptsDir manually."
        }
    }
}

# ── Done ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ${Script:Bold}${Script:Green}Installation complete!${Script:Reset}"
Write-Host ""
Write-Host "  ${Script:Cyan}Next steps:${Script:Reset}"
Write-Host ""
Write-Host "    1. ${Script:Bold}Open a new terminal${Script:Reset}"
Write-Host "    2. ${Script:Bold}delux setup${Script:Reset}        ${Script:Dim}Configure your AI provider${Script:Reset}"
Write-Host "    3. ${Script:Bold}delux${Script:Reset}               ${Script:Dim}Open the interactive IDE${Script:Reset}"
Write-Host "    4. ${Script:Bold}delux ide${Script:Reset}           ${Script:Dim}Same as above${Script:Reset}"
Write-Host "    5. ${Script:Bold}delux 'hola'${Script:Reset}       ${Script:Dim}Run a one-shot prompt${Script:Reset}"
Write-Host ""
Write-Host "  ${Script:Dim}Direct path: $scriptsDir\delux.exe${Script:Reset}"
Write-Host ""
