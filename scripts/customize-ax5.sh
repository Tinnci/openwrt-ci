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
path.write_text(text.replace("192.168.1.1", "10.77.0.1"))
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
cp "$script_dir/benchmark-emmc.sh" files/usr/sbin/ax5-emmc-benchmark
chmod 755 files/usr/sbin/ax5-emmc-benchmark

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

# Home DNS scope is local; never forward home.arpa names upstream.
cat > files/etc/uci-defaults/97-ax5-home-network <<'EOF'
#!/bin/sh
set -e
uci set system.@system[0].hostname='ax5'
uci set dhcp.@dnsmasq[0].domain='home.arpa'
uci set dhcp.@dnsmasq[0].local='/home.arpa/'
uci set dhcp.@dnsmasq[0].expandhosts='1'
uci commit system
uci commit dhcp
exit 0
EOF
chmod 755 files/etc/uci-defaults/97-ax5-home-network

# Preserve upstream NSS/EDMA affinity policy. Do not add irqbalance on top.
# Bound dirty memory so bulk file writes cannot consume most of a 512 MB board.
mkdir -p files/etc/sysctl.d
cat > files/etc/sysctl.d/90-ax5-memory.conf <<'EOF'
vm.dirty_background_bytes=4194304
vm.dirty_bytes=16777216
EOF
