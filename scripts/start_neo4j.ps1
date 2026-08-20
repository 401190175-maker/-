<#
.SYNOPSIS
    Start local Neo4j (idempotent): pass through when the Bolt port is ready,
    otherwise start Neo4j and wait until it is ready.

.DESCRIPTION
    Intended to be called before MCP server / CLI / daily queries. Configuration
    is loaded from .env into the current process only (no files are written).
    Readiness is probed against the Bolt address from NEO4J_URI
    (default bolt://127.0.0.1:7687).

.PARAMETER Neo4jHome
    Neo4j installation root (must contain bin\neo4j.bat). When omitted, the
    script checks $env:NEO4J_HOME, PATH, then common install roots.

.PARAMETER WaitTimeoutSeconds
    Timeout in seconds to wait for the Bolt port, default 120.

.PARAMETER PortCheckIntervalSeconds
    Readiness probe interval in seconds, default 2.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_neo4j.ps1
#>
[CmdletBinding()]
param(
    [string]$Neo4jHome,
    [int]$WaitTimeoutSeconds = 120,
    [int]$PortCheckIntervalSeconds = 2
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 1. Load .env into the current process so NEO4J_URI etc. match this project
$EnvPath = Join-Path $ProjectRoot '.env'
if (Test-Path -LiteralPath $EnvPath) {
    Get-Content -LiteralPath $EnvPath | Where-Object {
        $_ -match '^[A-Za-z_][A-Za-z0-9_]*='
    } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
    }
}

function Get-BoltEndpoint {
    param([string]$UriText)
    $match = [regex]::Match($UriText, '^bolt://(?:[^@/]+@)?([^:/?#]+)(?::(\d+))?')
    if (-not $match.Success) {
        throw "Cannot parse NEO4J_URI: $UriText"
    }
    $port = 7687
    if ($match.Groups[2].Success) {
        $port = [int]$match.Groups[2].Value
    }
    return [pscustomobject]@{ Host = $match.Groups[1].Value; Port = $port }
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            try {
                $task = $client.ConnectAsync($HostName, $Port)
                if ($task.Wait(1000) -and $client.Connected) {
                    return $true
                }
            }
            finally {
                $client.Dispose()
            }
        }
        catch {
            # Retry: transient refusal during Neo4j startup is expected.
        }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Find-Neo4jBat {
    param([string]$Neo4jHome)
    if ($Neo4jHome) {
        $candidate = Join-Path $Neo4jHome 'bin\neo4j.bat'
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    $cmd = Get-Command 'neo4j.bat' -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $roots = @(
        'E:\Neo4j',
        'C:\Program Files\Neo4j',
        'C:\Neo4j',
        (Join-Path $env:LOCALAPPDATA 'Neo4j'),
        (Join-Path $env:USERPROFILE 'scoop\apps')
    )
    foreach ($root in $roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) {
            continue
        }
        $dirs = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^neo4j' } |
            Sort-Object Name -Descending
        foreach ($dir in $dirs) {
            $candidate = Join-Path $dir.FullName 'bin\neo4j.bat'
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }
    throw 'Neo4j installation not found (pass -Neo4jHome or set NEO4J_HOME)'
}

# 2. Resolve the Bolt readiness endpoint
$uri = $env:NEO4J_URI
if (-not $uri) {
    $uri = 'bolt://127.0.0.1:7687'
}
$endpoint = Get-BoltEndpoint -UriText $uri

# 3. Already ready: pass through (idempotent, no restart)
if (Test-TcpPort -HostName $endpoint.Host -Port $endpoint.Port) {
    Write-Host "Neo4j already running: $($endpoint.Host):$($endpoint.Port)"
    return
}

# 4. Start Neo4j (detached console; no Windows service required)
$neo4jBat = Find-Neo4jBat -Neo4jHome $Neo4jHome
$neo4jHome = Split-Path -Parent (Split-Path -Parent $neo4jBat)
Write-Host "Starting Neo4j (detached console): $neo4jBat"
$proc = Start-Process -FilePath $neo4jBat -ArgumentList 'console' -WorkingDirectory $neo4jHome -WindowStyle Hidden -PassThru
if ($null -eq $proc -or $proc.HasExited) {
    throw "Failed to launch Neo4j console process: $neo4jBat (check $neo4jHome\logs\debug.log)"
}

# 5. Wait until the Bolt port is ready
$deadline = (Get-Date).AddSeconds($WaitTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-TcpPort -HostName $endpoint.Host -Port $endpoint.Port) {
        Write-Host "Neo4j ready: $($endpoint.Host):$($endpoint.Port)"
        return
    }
    Start-Sleep -Seconds $PortCheckIntervalSeconds
}
throw "Neo4j not ready within $WaitTimeoutSeconds seconds: $($endpoint.Host):$($endpoint.Port)"
