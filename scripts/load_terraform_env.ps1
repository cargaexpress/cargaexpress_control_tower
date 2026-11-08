<#
.SYNOPSIS
  Loads environment variables from .env.terraform into the current PowerShell session for Terraform.
.DESCRIPTION
  Reads .env.terraform (or .env.terraform.example) and exports all AWS_* and TF_VAR_*
  variables into $env: so that Terraform commands pick them up automatically.
.EXAMPLE
  .\scripts\load_terraform_env.ps1
#>

$envFile = Join-Path $PSScriptRoot "..\.env.terraform"
if (-not (Test-Path $envFile)) {
    $exampleFile = Join-Path $PSScriptRoot "..\.env.terraform.example"
    Write-Warning "File .env.terraform not found. Checking $exampleFile..."
    if (Test-Path $exampleFile) {
        $envFile = $exampleFile
    } else {
        Write-Error "Neither .env.terraform nor .env.terraform.example could be found."
        exit 1
    }
}

Write-Host "Loading environment variables from: $envFile" -ForegroundColor Cyan
$count = 0

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Length -eq 2) {
            $key = $parts[0].Trim()
            $val = $parts[1].Trim().Trim('"').Trim("'")
            if ($val -ne "") {
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
                $count++
                if ($key.Contains("SECRET") -or $key.Contains("KEY") -or $key.Contains("PASSWORD")) {
                    Write-Host "  [OK] Exported $key = **********" -ForegroundColor Green
                } else {
                    Write-Host "  [OK] Exported $key = $val" -ForegroundColor Green
                }
            }
        }
    }
}

Write-Host "Successfully loaded $count environment variables into current session." -ForegroundColor Green
Write-Host "You can now run: terraform plan / terraform validate" -ForegroundColor Yellow
