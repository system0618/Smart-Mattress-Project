param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".git")) {
    throw "Please run this script from the repository root: Smart-Mattress-Project"
}

$RemoteUrl = $RemoteUrl.Trim()
if ($RemoteUrl -match '^\[[^\]]+\]\((?<url>https://[^)]+)\)$') {
    $RemoteUrl = $Matches["url"]
    Write-Host "Detected Markdown link input. Using plain URL: $RemoteUrl"
}

if ($RemoteUrl -notmatch '^https://github\.com/[^/\s]+/[^/\s]+\.git$') {
    throw "RemoteUrl must be a plain GitHub HTTPS URL, for example: https://github.com/system0618/Smart-Mattress-Project.git"
}

Write-Host "Repository: $(Get-Location)"
Write-Host "Remote URL: $RemoteUrl"

$existingRemotes = git remote
if ($existingRemotes -contains "origin") {
    $existingOrigin = git remote get-url origin
    Write-Host "origin already exists: $existingOrigin"
    git remote set-url origin $RemoteUrl
    Write-Host "Updated origin."
}
else {
    git remote add origin $RemoteUrl
    Write-Host "Added origin."
}

git branch -M main
git push -u origin main

Write-Host "Published to GitHub successfully."
