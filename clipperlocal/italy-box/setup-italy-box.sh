#!/usr/bin/env bash
# ClipperLocal - Italy box setup for a Linux laptop (Ubuntu/Debian). Run once: sudo bash setup-italy-box.sh
set -e
[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }

echo "==> Tailscale"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-tailscale.conf
echo 'net.ipv6.conf.all.forwarding = 1' >> /etc/sysctl.d/99-tailscale.conf
sysctl -p /etc/sysctl.d/99-tailscale.conf >/dev/null
tailscale up --advertise-exit-node
IP=$(tailscale ip -4 | head -1)
[ -n "$IP" ] || { echo "Tailscale not connected yet. Log in and run again."; exit 1; }

echo "==> Proxy (only on the Tailscale address $IP)"
apt-get install -y -q python3-pip python3-venv >/dev/null
python3 -m venv /opt/italybox && /opt/italybox/bin/pip install -q pproxy
cat > /etc/systemd/system/italybox.service <<EOF
[Unit]
Description=ClipperLocal Italy box proxy
After=network-online.target tailscaled.service
Wants=network-online.target
[Service]
ExecStart=/opt/italybox/bin/pproxy -l socks5://$IP:1080
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now italybox

echo "==> Keep awake with the lid closed"
sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
systemctl restart systemd-logind || true
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null

echo
echo "Done! Italy box address for ClipperLocal (Settings -> Italy box proxy):  socks5://$IP:1080"
echo "Then: Tailscale admin page -> this machine -> Edit route settings -> allow 'Use as exit node', and invite your brother."
