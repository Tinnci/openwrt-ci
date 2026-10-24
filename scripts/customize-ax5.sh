#!/usr/bin/env bash
# Run from the locked OpenWrt source directory, after feeds installation.
set -euo pipefail

config=package/base-files/files/bin/config_generate
test -f "$config"
python3 - "$config" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
if "192.168.1.1" not in text:
    raise SystemExit("Expected upstream default LAN address not found")
path.write_text(text.replace("192.168.1.1", "192.168.3.1"))
PY

# Do not import this router's users, passwords, UUIDs or share paths.
# New LAN services require explicit configuration before use.
mkdir -p files/etc/uci-defaults
cat > files/etc/uci-defaults/99-ax5-storage-safety <<'EOF'
#!/bin/sh
for service in minidlna nfsd rpcbind; do
    if [ -x "/etc/init.d/$service" ]; then
        "/etc/init.d/$service" disable
        "/etc/init.d/$service" stop
    fi
done
exit 0
EOF
chmod 755 files/etc/uci-defaults/99-ax5-storage-safety

# Keep DNS-SD on LAN; do not reflect discovery onto other networks.
mkdir -p files/etc/avahi
cat > files/etc/avahi/avahi-daemon.conf <<'EOF'
[server]
use-ipv4=yes
use-ipv6=yes
allow-interfaces=br-lan
[wide-area]
enable-wide-area=no
[publish]
publish-addresses=yes
publish-hinfo=no
publish-workstation=yes
[reflector]
enable-reflector=no
EOF
