# NGS Local Testing Script for Windows
# This script helps you run NGS locally for testing with your Outlook emails

Write-Host "=== NGS Local Testing Setup ===" -ForegroundColor Cyan

# Check if Docker is running
$dockerRunning = docker info 2>$null
if (-not $?) {
    Write-Host "ERROR: Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Create .env if it doesn't exist
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file from template..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

# Create watch folder for file-based testing
$watchPath = ".\watch"
if (-not (Test-Path $watchPath)) {
    Write-Host "Creating watch folder at $watchPath" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $watchPath | Out-Null
    New-Item -ItemType Directory -Path "$watchPath\processed" | Out-Null
    New-Item -ItemType Directory -Path "$watchPath\failed" | Out-Null
}

Write-Host ""
Write-Host "Choose your email provider:" -ForegroundColor Green
Write-Host "1. File-based (drag emails from Outlook to ./watch folder)"
Write-Host "2. Outlook COM (read directly from Outlook - requires pywin32)"
Write-Host "3. Graph API (Office 365 with Azure AD app)"
Write-Host ""
$choice = Read-Host "Enter choice (1/2/3)"

# Update .env based on choice
$envContent = Get-Content ".env" -Raw

switch ($choice) {
    "1" {
        Write-Host "Setting up file-based provider..." -ForegroundColor Yellow
        $envContent = $envContent -replace "EMAIL_PROVIDER=.*", "EMAIL_PROVIDER=file"
        $envContent = $envContent -replace "FILE_WATCH_PATH=.*", "FILE_WATCH_PATH=./watch"
        Set-Content ".env" $envContent

        Write-Host ""
        Write-Host "File-based testing configured!" -ForegroundColor Green
        Write-Host ""
        Write-Host "How to test:" -ForegroundColor Cyan
        Write-Host "1. Start NGS: docker-compose --profile dev up -d"
        Write-Host "2. Open Outlook, select emails you want to test with"
        Write-Host "3. Drag & drop them into the 'watch' folder"
        Write-Host "4. NGS will process them automatically"
        Write-Host "5. Open http://localhost:3000 to see incidents"
    }
    "2" {
        Write-Host "Setting up Outlook COM provider..." -ForegroundColor Yellow
        $envContent = $envContent -replace "EMAIL_PROVIDER=.*", "EMAIL_PROVIDER=outlook"
        Set-Content ".env" $envContent

        Write-Host ""
        Write-Host "Installing pywin32..." -ForegroundColor Yellow
        pip install pywin32

        Write-Host ""
        Write-Host "Outlook COM configured!" -ForegroundColor Green
        Write-Host ""
        Write-Host "How to test:" -ForegroundColor Cyan
        Write-Host "1. Make sure Outlook is running"
        Write-Host "2. Run the worker locally: cd worker && python -m worker.main"
        Write-Host "3. Or start via docker-compose (but COM won't work in Docker)"
        Write-Host "4. Open http://localhost:3000 to see incidents"
        Write-Host ""
        Write-Host "NOTE: Outlook COM only works when running worker locally (not in Docker)" -ForegroundColor Yellow
    }
    "3" {
        Write-Host ""
        Write-Host "Graph API requires Azure AD setup. Please edit .env with:" -ForegroundColor Yellow
        Write-Host "- GRAPH_TENANT_ID"
        Write-Host "- GRAPH_CLIENT_ID"
        Write-Host "- GRAPH_CLIENT_SECRET"
        Write-Host "- GRAPH_USER_EMAIL"
        Write-Host ""
        Write-Host "See README.md for setup instructions."
    }
}

Write-Host ""
Write-Host "=== Starting Services ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Run: docker-compose --profile dev up -d" -ForegroundColor Green
Write-Host ""
Write-Host "Services:" -ForegroundColor Cyan
Write-Host "- Frontend: http://localhost:3000"
Write-Host "- API: http://localhost:8000"
Write-Host "- API Docs: http://localhost:8000/docs"
Write-Host ""
Write-Host "Login: admin / admin123" -ForegroundColor Yellow
