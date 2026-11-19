# ClipperLocal Italy box setup. Run by ItalyBox-Setup.exe (as admin); you don't need to open this file.
#  1. Installs Tailscale (private network between your devices; nothing is opened to the internet)
#  2. Logs in and makes this laptop an "exit node" (the Android phone sends its traffic through it)
#  3. Installs italybox-proxy.exe: a tiny SOCKS5 proxy that only listens on the Tailscale address and only
#     accepts your own Tailscale devices (the account tabs use it). It starts at every boot.
#  4. Keeps the laptop awake when plugged in, even with the lid closed
param([string]$Here = $PSScriptRoot, [switch]$Remove)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$dir = Join-Path $env:ProgramData "ClipperLocal Italy box"
$task = "ClipperLocal Italy box proxy"
function Say($m) { Write-Output $m }

if ($Remove) {
  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
  Get-Process italybox-proxy -ErrorAction SilentlyContinue | Stop-Process -Force
  Remove-NetFirewallRule -DisplayName $task -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
  Say "Italy box proxy removed. (Tailscale stays installed; uninstall it from Windows Settings if you want.)"
  exit 0
}

New-Item -ItemType Directory -Force $dir | Out-Null
Get-Process italybox-proxy -ErrorAction SilentlyContinue | Stop-Process -Force
Copy-Item (Join-Path $Here "italybox-proxy.exe") (Join-Path $dir "italybox-proxy.exe") -Force

# --- 1. Tailscale
$ts = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (-not (Test-Path $ts)) {
  Say "[1/4] Downloading Tailscale"
  $msi = Join-Path $env:TEMP "tailscale-setup.msi"
  & curl.exe -L --retry 5 --retry-delay 5 -s -o $msi "https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi"
  Say "      Installing Tailscale"
  Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /quiet /norestart" -Wait
  Start-Sleep 5
}
if (-not (Test-Path $ts)) { Say "PROBLEM: Tailscale didn't install. Check the internet and run ItalyBox-Setup.exe again."; exit 1 }
Say "[1/4] Tailscale installed"

# --- 2. Log in + exit node
$ip = (& $ts ip -4 2>$null | Select-Object -First 1)
if (-not $ip) {
  Say "[2/4] Log in to Tailscale: a browser opens. Use YOUR account (the same one your brother joins)."
  $out = Join-Path $env:TEMP "tailscale-up.txt"
  Remove-Item $out, "$out.err" -ErrorAction SilentlyContinue
  Start-Process $ts -ArgumentList "up --advertise-exit-node --unattended" -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError "$out.err" | Out-Null
  $opened = $false
  for ($i = 0; $i -lt 900; $i++) {
    Start-Sleep 1
    $text = ((Get-Content $out, "$out.err" -Raw -ErrorAction SilentlyContinue) -join "")
    if (-not $opened -and $text -match "(https://login\.tailscale\.com/\S+)") {
      Start-Process $Matches[1]; $opened = $true
      Say "      If no browser opened, go to: $($Matches[1])"
    }
    $ip = (& $ts ip -4 2>$null | Select-Object -First 1)
    if ($ip) { break }
  }
  if (-not $ip) { Say "PROBLEM: Tailscale login didn't finish within 15 minutes. Run ItalyBox-Setup.exe again."; exit 1 }
} else {
  & $ts set --advertise-exit-node=true 2>$null | Out-Null
}
$ip = "$ip".Trim()
Say "[2/4] Tailscale connected: $ip (offered as exit node)"

# --- 3. Proxy at every boot (as SYSTEM, restarts if it stops)
$exe = Join-Path $dir "italybox-proxy.exe"
$action = New-ScheduledTaskAction -Execute $exe
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName $task
Remove-NetFirewallRule -DisplayName $task -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $task -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1080 `
  -RemoteAddress "100.64.0.0/10" -Program $exe | Out-Null
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep 1
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect($ip, 1080); $c.Close(); $ok = $true; break } catch {}
}
if ($ok) { Say "[3/4] Proxy running on socks5://${ip}:1080 (only your Tailscale devices can use it)" }
else { Say "PROBLEM: the proxy didn't start. Restart the laptop; it starts by itself at boot." }

# --- 4. Stay awake when plugged in (lid closed is fine)
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
Say "[4/4] Laptop stays awake when plugged in"

"socks5://${ip}:1080" | Set-Content -Encoding ASCII (Join-Path $dir "address.txt")
Say ""
Say "DONE. Italy box address for ClipperLocal (Settings -> Italy box proxy):  socks5://${ip}:1080"
Say "Last step in the Tailscale admin page (login.tailscale.com/admin/machines): this laptop -> ... -> Edit route settings -> allow 'Use as exit node'."
exit 0
