#!/usr/bin/env bash
# Deploy hook for GitHub Actions (forced-command target of the deploy key).
#
# The deploy key in authorized_keys is restricted to run ONLY this script:
#   restrict,command="/home/ubuntu/kgc/server/deploy_hook.sh",no-pty,\
#     no-agent-forwarding,no-port-forwarding ssh-ed25519 AAAA... github-actions-deploy
#
# So an attacker who steals the key can pull + restart, nothing else.
set -euo pipefail
cd /home/ubuntu/kgc

dirty="$(git status --porcelain --untracked-files=no)"
if [ -n "$dirty" ]; then
  echo "refusing to deploy: tracked files modified on server:"
  echo "$dirty"
  exit 1
fi

GIT_LFS_SKIP_SMUDGE=1 git pull --ff-only origin main
git lfs pull

sudo -n systemctl restart kgc.service
sudo -n systemctl restart kgc-dashboard.service

echo "deploy OK: $(git rev-parse --short HEAD)"
