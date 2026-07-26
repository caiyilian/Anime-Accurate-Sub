[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [string]$SeasonRoot = ".omo\season_v6_quality",

    [ValidateRange(1, 999)]
    [int]$SeasonEpisodes = 14,

    [string]$TaskName = "AnimeAccurateSubMonitor",

    [string]$FirewallRuleName = "Anime Accurate Sub Monitor (TCP 8765)",

    [switch]$SkipFirewall,

    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdministrator) {
    throw "Run this script from an elevated PowerShell session."
}

if ($Uninstall) {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask -and $PSCmdlet.ShouldProcess($TaskName, "Remove scheduled task")) {
        if ($existingTask.State -eq "Running") {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    if (-not $SkipFirewall) {
        $existingRule = Get-NetFirewallRule `
            -DisplayName $FirewallRuleName `
            -ErrorAction SilentlyContinue
        if ($existingRule -and $PSCmdlet.ShouldProcess($FirewallRuleName, "Remove firewall rule")) {
            $existingRule | Remove-NetFirewallRule
        }
    }
    Write-Output "Monitor task removed."
    return
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$seasonCandidate = if ([IO.Path]::IsPathRooted($SeasonRoot)) {
    $SeasonRoot
} else {
    Join-Path $projectRoot $SeasonRoot
}
$seasonPath = [IO.Path]::GetFullPath($seasonCandidate)
if (-not (Test-Path -LiteralPath $seasonPath -PathType Container)) {
    throw "Season output directory does not exist: $seasonPath"
}

$pythonCommand = Get-Command python -ErrorAction Stop
$pythonPath = $pythonCommand.Source
$currentUser = $identity.Name
$arguments = (
    "scripts\web_ui.py --host 0.0.0.0 --port $Port " +
    "--season-root `"$seasonPath`" --season-episodes $SeasonEpisodes"
)

if ($PSCmdlet.ShouldProcess($TaskName, "Install persistent monitor task")) {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask -and $existingTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Milliseconds 500
    }

    $action = New-ScheduledTaskAction `
        -Execute $pythonPath `
        -Argument $arguments `
        -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $taskPrincipal = New-ScheduledTaskPrincipal `
        -UserId $currentUser `
        -LogonType Interactive `
        -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $taskPrincipal `
        -Settings $settings `
        -Description "Anime Accurate Sub read-only LAN progress dashboard." `
        -Force | Out-Null
}

if (-not $SkipFirewall -and $PSCmdlet.ShouldProcess($FirewallRuleName, "Allow private TCP port $Port")) {
    $existingRule = Get-NetFirewallRule `
        -DisplayName $FirewallRuleName `
        -ErrorAction SilentlyContinue
    if ($existingRule) {
        $existingRule | Set-NetFirewallRule `
            -Enabled True `
            -Direction Inbound `
            -Action Allow `
            -Profile Private
        $existingRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter `
            -Protocol TCP `
            -LocalPort $Port
    } else {
        New-NetFirewallRule `
            -DisplayName $FirewallRuleName `
            -Description "Allow the read-only subtitle progress dashboard on trusted private LANs." `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $Port `
            -Profile Private | Out-Null
    }
}

if ($PSCmdlet.ShouldProcess($TaskName, "Start monitor task")) {
    Start-ScheduledTask -TaskName $TaskName
    $healthy = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/api/health" `
                -TimeoutSec 2
            if ($response.status -eq "ok") {
                $healthy = $true
                break
            }
        } catch {
            # The task can need a few seconds to import FastAPI and start listening.
        }
    }
    if (-not $healthy) {
        throw "Monitor task started but health check failed on port $Port."
    }
}

$task = Get-ScheduledTask -TaskName $TaskName
Write-Output "Task: $TaskName ($($task.State))"
Write-Output "Local URL: http://127.0.0.1:$Port/monitor"
Write-Output "The firewall rule is limited to the Windows Private network profile."
