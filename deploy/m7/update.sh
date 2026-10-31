#!/usr/bin/env bash
# Pull the latest code (e.g. after Jarvis's draft branch is merged) and restart.
#   sudo bash /opt/assistant/deploy/m7/update.sh [path-to-git-checkout]
set -euo pipefail
SRC=${1:-$HOME/personal-assistant}
APP=/opt/assistant
git -C "$SRC" pull --ff-only
rsync -a --delete --exclude .venv --exclude data --exclude .env --exclude config/settings.yaml "$SRC/" "$APP/"
chown -R assistant:assistant "$APP"
sudo -u assistant bash -c "cd $APP && .venv/bin/pip install -q -e '.[google]'"
systemctl restart assistant
echo "updated + restarted"
