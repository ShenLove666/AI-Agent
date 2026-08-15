[CmdletBinding()]
param(
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$webRoot = Join-Path $projectRoot 'web'

function Invoke-VerificationStage {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Action,

        [Parameter(Mandatory)]
        [ref]$ExitCode
    )

    Write-Host "==> $Name"
    & $Action
    $ExitCode.Value = $LASTEXITCODE
    if ($ExitCode.Value -ne 0) {
        [Console]::Error.WriteLine(
            "$Name failed with exit code $($ExitCode.Value)."
        )
        return
    }
    Write-Host "<== $Name passed"
}

$verificationExitCode = 0
$locationPushed = $false
try {
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    }
    else {
        $python = (Resolve-Path -LiteralPath $PythonExecutable).Path
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Project virtual-environment Python was not found at: $python"
    }

    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npmCommand) {
        $npmCommand = Get-Command npm -ErrorAction Stop
    }

    $stages = @(
        @{
            Name = 'Compile Python sources'
            Action = { & $python -m compileall -q app tests scripts }
        },
        @{
            Name = 'Run backend tests'
            Action = { & $python -m pytest -q }
        },
        @{
            Name = 'Check active frontend API contracts'
            Action = { & $python scripts\check_api_contracts.py }
        },
        @{
            Name = 'Run frontend tests'
            Action = { & $npmCommand.Source --prefix $webRoot run test }
        },
        @{
            Name = 'Type-check frontend'
            Action = { & $npmCommand.Source --prefix $webRoot run typecheck }
        },
        @{
            Name = 'Lint frontend'
            Action = { & $npmCommand.Source --prefix $webRoot run lint }
        },
        @{
            Name = 'Build frontend production bundle'
            Action = { & $npmCommand.Source --prefix $webRoot run build }
        }
    )

    Push-Location $projectRoot
    $locationPushed = $true
    foreach ($stage in $stages) {
        Invoke-VerificationStage `
            -Name $stage.Name `
            -Action $stage.Action `
            -ExitCode ([ref]$verificationExitCode)
        if ($verificationExitCode -ne 0) {
            break
        }
    }
}
catch {
    $verificationExitCode = 1
    [Console]::Error.WriteLine("Verification failed: $($_.Exception.Message)")
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
}

if ($verificationExitCode -eq 0) {
    Write-Host 'Verification completed successfully.'
}

exit $verificationExitCode
