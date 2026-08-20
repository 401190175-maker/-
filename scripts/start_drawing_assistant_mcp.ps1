$ErrorActionPreference = 'Stop'

# Host MCP launchers read child stderr as UTF-8. Force UTF-8 for our own
# PowerShell errors/warnings and for the python child, so a localized error
# message can never corrupt the MCP connection.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

# Start local Neo4j first (idempotent, best-effort). A failure to start the
# database is a business-level problem surfaced by the query result, not an
# MCP server startup problem: never abort the server process here, otherwise
# the host cannot register the tools at all.
try {
    # Keep MCP stdout pure JSON-RPC frames: silence all output from the helper.
    & (Join-Path $PSScriptRoot 'start_neo4j.ps1') -WaitTimeoutSeconds 90 *> $null
}
catch {
    Write-Warning ('[start_drawing_assistant_mcp] could not auto-start Neo4j (continuing): ' + $_.Exception.Message)
}

$EnvPath = Join-Path $ProjectRoot '.env'
if (Test-Path -LiteralPath $EnvPath) {
    Get-Content -LiteralPath $EnvPath | Where-Object {
        $_ -match '^[A-Za-z_][A-Za-z0-9_]*='
    } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
    }
}

python scripts\serve_drawing_assistant_mcp.py
