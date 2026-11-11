#!/bin/bash
# Turns a fresh Ubuntu WSL distro into Jarvis's agent sandbox. Run as root by scripts/setup_wsl_sandbox.py;
# safe to run again.
#
# What makes it a sandbox rather than "Linux on the same PC":
#   - the Windows drives are not mounted, so nothing here can see the owner's files. Jarvis mounts the one
#     folder a job works in (sandbox/prepare.py), as root, just before the job;
#   - Windows programs can't be started from here (interop off), or a Linux process could run cmd.exe as the
#     owner;
#   - the agent is an ordinary user with no sudo and no password, so it can't undo either of those.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -q
# bubblewrap + socat: what Claude Code's own sandbox is built on. The rest is the least an agent needs to
# research and build: it can't install system packages itself.
apt-get install -y -q --no-install-recommends \
    bubblewrap socat ripgrep git curl ca-certificates python3 python3-venv python3-pip unzip jq

id agent >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --uid 1000 agent
passwd -l root >/dev/null
passwd -l agent >/dev/null
gpasswd -d agent sudo >/dev/null 2>&1 || true

install -d -m 755 /opt/jarvis /work /owner /etc/claude-code

cat > /etc/wsl.conf <<'EOF'
# Written by Jarvis (sandbox/provision.sh). Don't loosen: see that file for why each line is here.
[boot]
systemd=false

[automount]
enabled=false
mountFsTab=false

[interop]
enabled=false
appendWindowsPath=false

[user]
default=agent
EOF

# The job folder is owned by Windows, which git would otherwise refuse to work in.
git config --system --replace-all safe.directory '*'
# Files on the Windows side have no Linux permission bits worth comparing.
git config --system core.fileMode false

echo "provisioned"
