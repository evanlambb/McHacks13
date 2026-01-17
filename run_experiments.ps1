# Data Collection Batch Runner
# Runs multiple experiments consecutively

param(
    [string]$Name = "Three-Bayesians",
    [string]$Password = "Limit_Up_Limit_D0wn!",
    [string]$Server = "localhost:8080",
    [switch]$Secure,
    [string]$Scenario = "normal_market"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Batch Experiment Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Scenario: $Scenario" -ForegroundColor Yellow
Write-Host "Team: $Name" -ForegroundColor Yellow
Write-Host "Server: $Server" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Cyan

# Define experiments to run
$experiments = @(
    # Quantity tests
    "qty_100",
    "qty_200", 
    "qty_300",
    "qty_400",
    "qty_500",
    
    # Aggressive trading
    "aggressive_buy_100",
    "aggressive_sell_100",
    "spread_cross_100",
    
    # Inventory management
    "inventory_mgmt"
)

$total = $experiments.Count
$current = 0
$successful = 0
$failed = 0

foreach ($exp in $experiments) {
    $current++
    Write-Host "`n[$current/$total] Running: $exp" -ForegroundColor Green
    Write-Host "----------------------------------------" -ForegroundColor Gray
    
    $pythonArgs = @(
        "-m", "collectors.runner",
        "--scenario", $Scenario,
        "--experiment", $exp,
        "--name", $Name,
        "--password", $Password,
        "--host", $Server
    )
    
    if ($Secure) {
        $pythonArgs += "--secure"
    }
    
    try {
        python $pythonArgs
        if ($LASTEXITCODE -eq 0) {
            $successful++
            Write-Host "[OK] Success: $exp" -ForegroundColor Green
        } else {
            $failed++
            Write-Host "[FAIL] Failed: $exp (exit code: $LASTEXITCODE)" -ForegroundColor Red
        }
    } catch {
        $failed++
        Write-Host "[ERROR] Error running $exp : $_" -ForegroundColor Red
    }
    
    # Small delay between runs
    if ($current -lt $total) {
        Write-Host "`nWaiting 3 seconds before next experiment...`n" -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Batch Run Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Successful: $successful/$total" -ForegroundColor Green
Write-Host "Failed: $failed/$total" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "========================================`n" -ForegroundColor Cyan

# Generate summary report
Write-Host "Generating summary report..." -ForegroundColor Yellow
python -m analysis.summary --summary
Write-Host "`nDone! Check data/processed/summary_report.csv" -ForegroundColor Green

