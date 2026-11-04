<#
.SYNOPSIS
    CargaExpress Supply Chain Control Tower - ECR Build & Push Tool (HU-36 / HU-37)

.DESCRIPTION
    Builds, dual-tags (latest + image_tag), and pushes multi-stage container
    images (backend, worker, airflow) to Amazon Elastic Container Registry (ECR).

.PARAMETER Region
    AWS Region (default: $env:AWS_REGION or 'us-east-1').

.PARAMETER AccountId
    AWS Account ID (default: $env:AWS_ACCOUNT_ID or detected via AWS STS).

.PARAMETER Registry
    ECR Registry URL (default: <AccountId>.dkr.ecr.<Region>.amazonaws.com).

.PARAMETER ImageTag
    Image tag (default: git short commit SHA or 'latest').

.PARAMETER Services
    Target services to process: 'all', 'backend', 'worker', 'airflow' (default: 'all').

.PARAMETER SkipPush
    If specified, images will be compiled and tagged locally without pushing to ECR.

.PARAMETER SkipLogin
    If specified, skips the ECR authentication step.

.PARAMETER CreateRepos
    If specified, creates the ECR repositories if they do not already exist.

.EXAMPLE
    .\scripts\build_and_push_ecr.ps1
    Builds and pushes all images using default us-east-1 and auto-detected AWS account.

.EXAMPLE
    .\scripts\build_and_push_ecr.ps1 -Region us-east-2 -AccountId 123456789012 -ImageTag "v1.2.0"

.EXAMPLE
    .\scripts\build_and_push_ecr.ps1 -Services backend -SkipPush
    Builds only the backend image locally.
#>

[CmdletBinding()]
param(
    [Alias("r")]
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }),

    [Alias("a")]
    [string]$AccountId = $(if ($env:AWS_ACCOUNT_ID) { $env:AWS_ACCOUNT_ID } else { "" }),

    [string]$Registry = $(if ($env:ECR_REGISTRY) { $env:ECR_REGISTRY } else { "" }),

    [Alias("t")]
    [string]$ImageTag = $(if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { "" }),

    [Alias("s")]
    [string]$Services = "all",

    [switch]$SkipPush,
    [switch]$SkipLogin,
    [switch]$CreateRepos,
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
Set-Location -Path $RepoRoot

# Verify Docker availability
Write-Step "Checking Docker CLI availability..."
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Err "Docker CLI was not found in PATH. Please install or launch Docker Desktop."
    exit 1
}

try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Docker daemon is not responding. Please verify Docker Desktop is running."
        exit 1
    }
}
catch {
    Write-Err "Docker daemon communication failure: $_"
    exit 1
}

# Auto-detect AWS Account ID if missing
if ([string]::IsNullOrWhiteSpace($AccountId)) {
    if (Get-Command "aws" -ErrorAction SilentlyContinue) {
        Write-Step "Attempting to auto-detect AWS Account ID via AWS STS..."
        try {
            $detected = (aws sts get-caller-identity --query Account --output text 2>$null).Trim()
            if ($detected -match '^\d{12}$') {
                $AccountId = $detected
                Write-Step "Auto-detected Account ID: $AccountId"
            }
        }
        catch {
            Write-Warn "Could not auto-detect Account ID via STS."
        }
    }
}

if ([string]::IsNullOrWhiteSpace($AccountId) -and -not $SkipPush) {
    Write-Err "AWS Account ID could not be determined. Pass -AccountId <12-digits> or set `$env:AWS_ACCOUNT_ID."
    exit 1
}

# Compute Registry URL
if ([string]::IsNullOrWhiteSpace($Registry)) {
    $Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
}

# Compute Image Tag
if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    try {
        $gitSha = (git rev-parse --short HEAD 2>$null)
        if (-not [string]::IsNullOrWhiteSpace($gitSha)) {
            $ImageTag = $gitSha.Trim()
        }
        else {
            $ImageTag = "latest"
        }
    }
    catch {
        $ImageTag = "latest"
    }
}

Write-Host "============================================================" -ForegroundColor White
Write-Host "CargaExpress AWS ECR Build & Push Configuration" -ForegroundColor White
Write-Host "  Repository Root: $RepoRoot"
Write-Host "  AWS Region:      $Region"
Write-Host "  AWS Account ID:  $(if ($AccountId) { $AccountId } else { 'N/A' })"
Write-Host "  ECR Registry:    $Registry"
Write-Host "  Image Tag:       $ImageTag (+ latest)"
Write-Host "  Target Services: $Services"
Write-Host "  Push to ECR:     $(if ($SkipPush) { 'No (SkipPush)' } else { 'Yes' })"
Write-Host "============================================================" -ForegroundColor White

# Ensure repository exists helper
function Ensure-EcrRepo([string]$RepoName) {
    if ($CreateRepos) {
        try {
            aws ecr describe-repositories --repository-names $RepoName --region $Region 2>$null | Out-Null
        }
        catch {
            Write-Step "Creating missing ECR repository '$RepoName' in $Region..."
            aws ecr create-repository `
                --repository-name $RepoName `
                --region $Region `
                --image-scanning-configuration scanOnPush=true `
                --encryption-configuration encryptionType=AES256 | Out-Null
            Write-Success "Repository '$RepoName' created successfully."
        }
    }
}

# ECR Authentication
if (-not $SkipPush -and -not $SkipLogin) {
    Write-Step "Authenticating Docker with Amazon ECR ($Registry)..."
    if (-not (Get-Command "aws" -ErrorAction SilentlyContinue)) {
        Write-Err "AWS CLI is required for ECR login. Install aws-cli or pass -SkipLogin."
        exit 1
    }

    try {
        $password = aws ecr get-login-password --region $Region
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($password)) {
            Write-Err "Failed to retrieve ECR login password from AWS CLI."
            exit 1
        }

        $password | docker login --username AWS --password-stdin $Registry
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Docker login to $Registry failed."
            exit 1
        }
        Write-Success "ECR authentication succeeded."
    }
    catch {
        Write-Err "Authentication failed: $_"
        exit 1
    }
}

# Build and Push Function
function Build-And-Tag([string]$ImageName, [string]$DockerfilePath, [string]$TargetStage) {
    $fullTag = "$Registry/$ImageName`:$ImageTag"
    $latestTag = "$Registry/$ImageName`:latest"

    Write-Step "--> Building container image [$ImageName] from $DockerfilePath..."
    $buildArgs = @("build", "-f", $DockerfilePath, "-t", $fullTag, "-t", $latestTag)
    if (-not [string]::IsNullOrWhiteSpace($TargetStage)) {
        $buildArgs += @("--target", $TargetStage)
    }
    $buildArgs += "."

    & docker $buildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed building image [$ImageName]."
        exit 1
    }
    Write-Success "Image [$ImageName] built successfully."

    if (-not $SkipPush) {
        Ensure-EcrRepo $ImageName

        Write-Step "--> Pushing [$ImageName`:$ImageTag] to ECR..."
        & docker push $fullTag
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to push $fullTag."
            exit 1
        }

        Write-Step "--> Pushing [$ImageName`:latest] to ECR..."
        & docker push $latestTag
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to push $latestTag."
            exit 1
        }

        Write-Success "Image [$ImageName] pushed to $Registry with tags [$ImageTag, latest]."
    }
}

$startTime = Get-Date

$svcs = $Services.ToLower()

# Service 1: cargaexpress-backend
if ($svcs -eq "all" -or $svcs.Contains("backend")) {
    Build-And-Tag "cargaexpress-backend" "backend/Dockerfile" "final"
}

# Service 2: cargaexpress-worker
if ($svcs -eq "all" -or $svcs.Contains("worker")) {
    Build-And-Tag "cargaexpress-worker" "backend/Dockerfile" "final"
}

# Service 3: cargaexpress-airflow
if ($svcs -eq "all" -or $svcs.Contains("airflow")) {
    Build-And-Tag "cargaexpress-airflow" "Dockerfile.airflow" ""
}

$elapsed = ((Get-Date) - $startTime).TotalSeconds
Write-Host ""
Write-Success "============================================================"
Write-Success ("All requested images processed successfully in {0:N1}s." -f $elapsed)
if (-not $SkipPush) {
    Write-Success "Images deployed to ECR:"
    if ($svcs -eq "all" -or $svcs.Contains("backend")) { Write-Host "  - $Registry/cargaexpress-backend`:$ImageTag" -ForegroundColor White }
    if ($svcs -eq "all" -or $svcs.Contains("worker"))  { Write-Host "  - $Registry/cargaexpress-worker`:$ImageTag" -ForegroundColor White }
    if ($svcs -eq "all" -or $svcs.Contains("airflow")) { Write-Host "  - $Registry/cargaexpress-airflow`:$ImageTag" -ForegroundColor White }
}
Write-Success "============================================================"
exit 0
