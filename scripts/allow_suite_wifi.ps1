$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'runtime\python.exe'
try {
    foreach ($rule in @(
        @{ Name = 'IMMENSIVA Venue Suite headset and touch TCP'; Protocol = 'TCP'; Ports = @('17080', '17083') },
        @{ Name = 'IMMENSIVA Venue Suite pilot discovery UDP'; Protocol = 'UDP'; Ports = @('17081') }
    )) {
        $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "Already configured: $($rule.Name)"
        } else {
            New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow `
                -Program $runtime -Profile Private -RemoteAddress LocalSubnet `
                -Protocol $rule.Protocol -LocalPort $rule.Ports | Out-Null
            Write-Host "Allowed: $($rule.Name)"
        }
    }
} catch {
    Write-Error "Run Allow Venue Suite on Wi-Fi.cmd as administrator. $($_.Exception.Message)"
    exit 1
}
