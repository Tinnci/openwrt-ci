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

# Configure RAM-only swap; never create a swap file or partition on eMMC.
cat > files/etc/uci-defaults/98-ax5-zram <<'EOF'
#!/bin/sh
set -e
uci set system.@system[0].zram_size_mb='128'
uci set system.@system[0].zram_comp_algo='lzo'
uci set system.@system[0].zram_priority='100'
uci commit system
/etc/init.d/zram enable
exit 0
EOF
chmod 755 files/etc/uci-defaults/98-ax5-zram

# Install an on-demand, read-only report; never collect or upload automatically.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p files/usr/sbin
cp "$script_dir/collect-emmc-telemetry.sh" files/usr/sbin/ax5-emmc-report
chmod 755 files/usr/sbin/ax5-emmc-report

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
