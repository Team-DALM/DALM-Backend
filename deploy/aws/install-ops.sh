#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$EUID" -ne 0 || "$(pwd -P)" != /opt/dalm/backend/deploy/aws ]]; then
  echo 'Run as root from /opt/dalm/backend/deploy/aws.' >&2
  exit 1
fi
install -m 644 systemd/dalm-deploy.service systemd/dalm-deploy.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dalm-deploy.timer
# Backup contains user data; it is separately opt-in, never enabled by this installer.
if [[ "${DALM_ENABLE_BACKUPS:-false}" == "true" ]]; then
  install -m 644 systemd/dalm-backup.service systemd/dalm-backup.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now dalm-backup.timer
fi
systemctl list-timers dalm-deploy.timer --no-pager
