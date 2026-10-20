<#
Starts n8n for this project, with settings that keep it private:
  - only this computer can reach it (127.0.0.1),
  - its file nodes can only read and write the project's docs folder, and
  - its usage reporting, update checks, templates and similar internet contact are switched off.

Run it from the project folder, in PowerShell:
    .\n8n\start-n8n.ps1              start n8n at http://127.0.0.1:5678 (press Ctrl+C to stop)
    .\n8n\start-n8n.ps1 -DryRun      only show the settings, do not start anything
    .\n8n\start-n8n.ps1 -Port 5700   use another port

The first run downloads n8n, which is large and can take several minutes. Later runs start in seconds.
n8n keeps its data (workflows, credentials, run history) in C:\Users\<you>\.n8n.
#>
param(
    [int]$Port = 5678,
    [switch]$DryRun
)

$docsFolder = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs'

$settings = [ordered]@{
    N8N_LISTEN_ADDRESS                = '127.0.0.1'   # n8n's default is every network interface
    N8N_RESTRICT_FILE_ACCESS_TO       = $docsFolder   # the only folder n8n's file nodes may read or write
    N8N_HOST                          = '127.0.0.1'
    N8N_PORT                          = "$Port"
    N8N_DIAGNOSTICS_ENABLED           = 'false'       # anonymous usage reports
    N8N_VERSION_NOTIFICATIONS_ENABLED = 'false'       # update and security notices fetched from n8n.io
    N8N_TEMPLATES_ENABLED             = 'false'       # workflow templates fetched from n8n.io
    N8N_PERSONALIZATION_ENABLED       = 'false'       # onboarding questions
    N8N_HIRING_BANNER_ENABLED         = 'false'
}

if ($DryRun) {
    Write-Host "n8n would start at http://127.0.0.1:$Port with these settings:"
    foreach ($name in $settings.Keys) { Write-Host ("  {0,-34} = {1}" -f $name, $settings[$name]) }
    return
}

try {
    foreach ($name in $settings.Keys) { Set-Item -Path "Env:$name" -Value $settings[$name] }
    Write-Host "Starting n8n at http://127.0.0.1:$Port (press Ctrl+C to stop)..."
    npx --yes n8n
}
finally {
    # leave no n8n settings behind in this PowerShell window
    foreach ($name in $settings.Keys) { Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue }
}
