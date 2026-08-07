[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$webRoot = Join-Path $projectRoot 'web'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project virtual-environment Python was not found at: $python"
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction Stop
}

function Invoke-VerificationStage {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Action
    )

    Write-Host "==> $Name"
    & $Action
    $stageExitCode = $LASTEXITCODE
    if ($stageExitCode -ne 0) {
        throw "$Name failed with exit code $stageExitCode."
    }
    Write-Host "<== $Name passed"
}

Push-Location $projectRoot
try {
    Invoke-VerificationStage 'Compile Python sources' {
        & $python -m compileall -q app tests scripts
    }
    Invoke-VerificationStage 'Run backend tests' {
        & $python -m pytest -q
    }
    Invoke-VerificationStage 'Check active frontend API contracts' {
        & $python scripts\check_api_contracts.py
    }
    Invoke-VerificationStage 'Run frontend tests' {
        & $npmCommand.Source --prefix $webRoot run test
    }
    Invoke-VerificationStage 'Lint frontend' {
        & $npmCommand.Source --prefix $webRoot run lint
    }
    Invoke-VerificationStage 'Build frontend production bundle' {
        & $npmCommand.Source --prefix $webRoot run build
    }
}
finally {
    Pop-Location
}

Write-Host 'Verification completed successfully.'
