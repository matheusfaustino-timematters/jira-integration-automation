# run-jira.ps1
Set-Location -Path $PSScriptRoot   # Ensures script runs from its own directory (optional but recommended)

# Run the Python script using uv
uv run .\jira_integration\main.py

# Optional: pause or check exit code
if ($LASTEXITCODE -ne 0) {
    Write-Error "Script failed with exit code $LASTEXITCODE"
    pause  # keeps the window open if you run by double-clicking
}
