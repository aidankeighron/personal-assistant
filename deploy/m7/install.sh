#!/usr/bin/env bash
# M7 server setup (Ubuntu Server 24.04 LTS / Debian 12+). Run as a sudo-capable user:
#   git clone https://github.com/aidankeighron/personal-assistant.git ~/personal-assistant
#   sudo bash ~/personal-assistant/deploy/m7/install.sh
# Safe to re-run.
set -euo pipefail

REPO_SRC="$(cd "$(dirname "$0")/../.." && pwd)"
APP=/opt/assistant
VAULT=${VAULT:-/mnt/vault}
SVC_USER=assistant

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

say "Packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git rsync curl ufw sqlite3 ca-certificates >/dev/null

say "Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

say "Tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
tailscale status >/dev/null 2>&1 || echo ">>> run 'sudo tailscale up --ssh' after this script and log in"

say "Vault drive"
if mountpoint -q "$VAULT"; then
  echo "$VAULT is mounted"
else
  cat <<EOF
!!! $VAULT is not mounted. Mount the 5TB drive first (see docs/SETUP.md, step M7-3):
    lsblk -f                                  # find the drive's UUID
    sudo mkdir -p $VAULT
    echo 'UUID=<uuid> $VAULT ext4 defaults,nofail,noatime,x-systemd.device-timeout=30 0 2' | sudo tee -a /etc/fstab
    sudo mount -a
Continuing; data will go to $VAULT once it's mounted (the service waits for the mount).
EOF
  mkdir -p "$VAULT"
fi

say "Service user"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$SVC_USER"
usermod -aG docker "$SVC_USER"   # NOTE: docker group = root-equivalent. See docs/SETUP.md "hardening".
mkdir -p "$VAULT/assistant" "$VAULT/projects" "$VAULT/sandbox-work" "$VAULT/assistant/claude-home"
# containers run as the assistant's uid, so it owns everything they touch
chown -R "$SVC_USER:$SVC_USER" "$VAULT/assistant" "$VAULT/projects" "$VAULT/sandbox-work"
export PA_UID=$(id -u "$SVC_USER") PA_GID=$(id -g "$SVC_USER")

say "App code -> $APP"
if [[ "$REPO_SRC" != "$APP" ]]; then
  mkdir -p "$APP"
  rsync -a --delete --exclude .venv --exclude data --exclude .env --exclude config/settings.yaml \
    "$REPO_SRC/" "$APP/"
fi
chown -R "$SVC_USER:$SVC_USER" "$APP"
sudo -u "$SVC_USER" bash -c "cd $APP && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e '.[google]'"
if [[ ! -f "$APP/config/settings.yaml" ]]; then
  sudo -u "$SVC_USER" bash -c "cd $APP && .venv/bin/python -m assistant init"
fi

say "Sandbox image + container"
docker build -q -t pa-sandbox:latest "$APP/sandbox"
(cd "$APP/deploy/m7" && VAULT="$VAULT" PA_UID="$PA_UID" PA_GID="$PA_GID" docker compose up -d sandbox)

say "Register the assistant's own repo as a Jarvis project (so it can work on itself)"
if [[ ! -d "$VAULT/projects/personal-assistant" ]]; then
  git clone -q "$(git -C "$REPO_SRC" remote get-url origin 2>/dev/null || echo "$REPO_SRC")" "$VAULT/projects/personal-assistant" || true
  chown -R "$SVC_USER:$SVC_USER" "$VAULT/projects/personal-assistant" || true
fi
sudo -u "$SVC_USER" bash -c "cd $APP && .venv/bin/python -m assistant project personal-assistant --path $VAULT/projects/personal-assistant --description 'The assistant itself'" || true

say "Firewall"
ufw allow OpenSSH >/dev/null
ufw allow in on tailscale0 to any port 8000 proto tcp >/dev/null
ufw --force enable >/dev/null
ufw status | head -20

say "systemd"
install -m 644 "$APP/deploy/m7/assistant.service" /etc/systemd/system/assistant.service
systemctl daemon-reload
systemctl enable --now assistant
sleep 2
systemctl --no-pager --lines=5 status assistant || true

cat <<EOF

Done. Next steps:
  1. sudo tailscale up --ssh                         (if not already)
  2. sudo -u $SVC_USER nano $APP/.env                (PC_HOST, PC_HOST_TOKEN, PC_MAC, NTFY_TOPIC)
     sudo -u $SVC_USER nano $APP/config/settings.yaml
  3. Log Claude Code in for Jarvis (once):
       docker exec -it pa-sandbox claude             (then /login, then exit)
  4. sudo systemctl restart assistant
  5. sudo -u $SVC_USER $APP/.venv/bin/python -m assistant doctor
  6. Phone: install Tailscale + ntfy apps, subscribe to your topic, open http://m7:8000/app
EOF
