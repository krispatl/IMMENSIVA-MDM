$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'runtime\python.exe'
$instance = (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($runtime)))).Hash.Substring(0, 12)
try {
    foreach ($rule in @(
        @{ Name = 'IMMENSIVA Venue Suite headset and touch TCP'; Protocol = 'TCP'; Ports = @('17080', '17083') },
        @{ Name = 'IMMENSIVA Venue Suite pilot discovery UDP'; Protocol = 'UDP'; Ports = @('17081') },
        @{ Name = 'IMMENSIVA Venue Suite NetSync TCP'; Protocol = 'TCP'; Ports = @('5555', '5556', '5557', '8800', '49999') },
        @{ Name = 'IMMENSIVA Venue Suite NetSync discovery UDP'; Protocol = 'UDP'; Ports = @('49999') }
    )) {
        $ruleName = "$($rule.Name) [$instance]"
        $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "Already configured: $($rule.Name)"
        } else {
            New-NetFirewallRule -Name $ruleName -DisplayName $rule.Name -Direction Inbound -Action Allow `
                -Program $runtime -Profile Private -RemoteAddress LocalSubnet `
                -Protocol $rule.Protocol -LocalPort $rule.Ports | Out-Null
            Write-Host "Allowed: $($rule.Name)"
        }
    }
} catch {
    Write-Error "Run Allow Venue Suite on Wi-Fi.cmd as administrator. $($_.Exception.Message)"
    exit 1
}
