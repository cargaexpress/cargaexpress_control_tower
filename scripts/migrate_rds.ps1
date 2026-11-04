<#
.SYNOPSIS
    CargaExpress Supply Chain Control Tower - RDS Migration Tool (HU-38)

.DESCRIPTION
    Executes Alembic migrations and validates schema consistency against
    an Amazon RDS PostgreSQL database for CargaExpress.

.PARAMETER DatabaseUrl
    Full connection URI (e.g. postgresql+asyncpg://user:pass@host:5432/cargaexpress).

.PARAMETER Host
    RDS database host endpoint.

.PARAMETER Port
    PostgreSQL port (default: 5432).

.PARAMETER User
    PostgreSQL username (default: 'cargaexpress').

.PARAMETER Password
    PostgreSQL user password.

.PARAMETER Database
    Database name (default: 'cargaexpress').

.PARAMETER SslMode
    PostgreSQL SSL mode: 'require', 'prefer', 'disable' (default: 'require').

.PARAMETER Action
    Migration action: 'upgrade' (default), 'check', 'downgrade', 'current', 'heads', 'history'.

.PARAMETER Revision
    Target revision (default: 'head' for upgrade, '-1' for downgrade).

.PARAMETER NoVerify
    Skip schema drift verification ('alembic check') after applying upgrade.

.PARAMETER Sql
    Generate offline SQL script without executing against the database.

.PARAMETER Help
    Show detailed help information.

.EXAMPLE
    .\scripts\migrate_rds.ps1 -DatabaseUrl "postgresql+asyncpg://user:pass@rds-host:5432/cargaexpress"

.EXAMPLE
    .\scripts\migrate_rds.ps1 -Host "cargaexpress.c123.us-east-1.rds.amazonaws.com" -User "dbadmin" -Password "Secret123"

.EXAMPLE
    .\scripts\migrate_rds.ps1 -Host "rds-host" -Password "Secret" -Action check
#>

[CmdletBinding()]
param(
    [Alias("url", "DatabaseUri")]
    [string]$DatabaseUrl = $(if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "" }),

    [Alias("Host", "Endpoint")]
    [string]$HostName = $(if ($env:DB_HOST) { $env:DB_HOST } else { "" }),

    [int]$Port = 5432,

    [Alias("u", "Username")]
    [string]$User = "cargaexpress",

    [Alias("p", "Pass")]
    [string]$Password = $(if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { "" }),

    [Alias("d", "DbName")]
    [string]$Database = "cargaexpress",

    [string]$SslMode = "require",

    [Alias("a")]
    [ValidateSet("upgrade", "check", "downgrade", "current", "heads", "history")]
    [string]$Action = "upgrade",

    [Alias("r")]
    [string]$Revision = "head",

    [switch]$NoVerify,
    [switch]$Sql,

    [Alias("h")]
    [switch]$Help
)

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success([string]$Message) {
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$BackendDir = Resolve-Path (Join-Path $RepoRoot "backend")

# Construct Connection URL
$targetUrl = ""
if (-not [string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $targetUrl = $DatabaseUrl
}
elseif (-not [string]::IsNullOrWhiteSpace($HostName) -and -not [string]::IsNullOrWhiteSpace($Password)) {
    if ($SslMode -eq "disable") {
        $targetUrl = "postgresql+asyncpg://$($User):$($Password)@$($HostName):$Port/$Database"
    }
    else {
        $targetUrl = "postgresql+asyncpg://$($User):$($Password)@$($HostName):$Port/$Database`?ssl=$SslMode"
    }
}
else {
    Write-Err "Missing database connection credentials."
    Write-Err "Pass either -DatabaseUrl <url> or -Host <host> with -Password <password>."
    exit 1
}

# Normalize URL driver to postgresql+asyncpg://
if ($targetUrl -match "^postgres://") {
    $targetUrl = "postgresql+asyncpg://" + $targetUrl.Substring(11)
}
elseif ($targetUrl -match "^postgresql://") {
    $targetUrl = "postgresql+asyncpg://" + $targetUrl.Substring(13)
}

# Mask password for display
$maskedUrl = $targetUrl -replace '://([^:]+):([^@]+)@', '://$1:****@'

Write-Host "============================================================" -ForegroundColor White
Write-Host "CargaExpress RDS Database Migration Runner" -ForegroundColor White
Write-Host "  Action:       $Action (target: $Revision)"
Write-Host "  Target DB:    $maskedUrl"
Write-Host "  SQL Only:     $($Sql.IsPresent)"
Write-Host "  Verify Drift: $(-not $NoVerify.IsPresent)"
Write-Host "============================================================" -ForegroundColor White

# Set current location to backend directory
Set-Location -Path $BackendDir

# Set DATABASE_URL for python environment
$env:DATABASE_URL = $targetUrl

# Determine runner (uv, alembic, or python)
$runnerCmd = ""
$runnerArgs = @()

if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $runnerCmd = "uv"
    $runnerArgs = @("run", "python", "-m", "alembic")
}
elseif (Get-Command "alembic" -ErrorAction SilentlyContinue) {
    $runnerCmd = "alembic"
}
elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $runnerCmd = "python"
    $runnerArgs = @("-m", "alembic")
}
else {
    Write-Err "Neither 'uv', 'alembic', nor 'python' was found in PATH."
    exit 1
}

function Invoke-Alembic([string[]]$extraArgs) {
    $allArgs = @()
    if ($runnerArgs.Length -gt 0) {
        $allArgs += $runnerArgs
    }
    $allArgs += $extraArgs

    & $runnerCmd $allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic command failed with exit code $LASTEXITCODE."
    }
}

$startTime = Get-Date

try {
    switch ($Action) {
        "upgrade" {
            if ($Sql) {
                Write-Step "Generating offline SQL statements for upgrade to $Revision..."
                Invoke-Alembic @("upgrade", $Revision, "--sql")
                Write-Success "Offline SQL generation complete."
                break
            }

            Write-Step "Applying pending migrations up to revision [$Revision]..."
            Invoke-Alembic @("upgrade", $Revision)
            Write-Success "Migrations applied successfully."

            if (-not $NoVerify) {
                Write-Step "Verifying schema consistency and model synchronization (alembic check)..."
                try {
                    Invoke-Alembic @("check")
                    Write-Success "Schema verification passed. Database is completely synchronized with models."
                }
                catch {
                    Write-Warn "Schema drift detected between SQLAlchemy models and target database: $_"
                }
            }
        }

        "check" {
            Write-Step "Checking for schema drift or unapplied migrations..."
            Invoke-Alembic @("check")
            Write-Success "Schema check completed."
        }

        "downgrade" {
            $targetRev = $Revision
            if ($targetRev -eq "head") {
                $targetRev = "-1"
            }
            Write-Warn "Downgrading database schema to [$targetRev]..."
            Invoke-Alembic @("downgrade", $targetRev)
            Write-Success "Downgrade executed."
        }

        "current" {
            Write-Step "Querying current database revision..."
            Invoke-Alembic @("current")
        }

        "heads" {
            Write-Step "Displaying latest available migration heads..."
            Invoke-Alembic @("heads")
        }

        "history" {
            Write-Step "Displaying migration history..."
            Invoke-Alembic @("history", "--verbose")
        }
    }

    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    Write-Success ("Database operation '$Action' finished successfully in {0:N1}s." -f $elapsed)
    exit 0
}
catch {
    Write-Err "Migration operation failed: $_"
    exit 1
}
