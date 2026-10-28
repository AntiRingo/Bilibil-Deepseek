#!/usr/bin/env bash
# Restores the previous code and its Python environment; never restores data automatically.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
base=/opt/bilibili-bot
exec 9>"$base/deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
previous=$(cat "$base/previous-release")
previous=$(realpath "$previous")
[[ $previous == "$base/releases/"* && -f "$previous/REVISION" ]] || exit 1
current=$(readlink -f "$base/current")
bot_active=0
web_active=0
systemctl is-active --quiet bilibili-bot && bot_active=1
systemctl is-active --quiet bilibili-web && web_active=1
recover() {
    result=$?
    trap - ERR
    set +e
    systemctl stop bilibili-bot bilibili-web
    ln -sfn "$current" "$base/current.recover"
    mv -Tf "$base/current.recover" "$base/current"
    install -m 644 "$current/deploy/"*.service /etc/systemd/system/
    systemctl daemon-reload
    [[ $web_active == 0 ]] || systemctl start bilibili-web
    [[ $bot_active == 0 ]] || systemctl start bilibili-bot
    echo 'Rollback failed; attempted to restore the previously running release. Inspect journalctl.' >&2
    exit "$result"
}
trap recover ERR
systemctl stop bilibili-bot bilibili-web
umask 077
tar -czf "$base/backups/$(date -u +%Y%m%dT%H%M%SZ)-before-rollback.tar.gz" \
    -C / var/lib/bilibili-bot etc/bilibili-bot
ln -sfn "$previous" "$base/current.rollback"
mv -Tf "$base/current.rollback" "$base/current"
install -m 644 "$previous/deploy/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl start bilibili-web
healthy=0
for ((i=0; i<20; i++)); do
    if systemctl is-active --quiet bilibili-web && curl -fsS --max-time 3 http://127.0.0.1:5000/api/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["ok"] is True'; then healthy=1; break; fi
    sleep 1
done
[[ $healthy == 1 ]] || { echo 'Rollback panel failed.' >&2; false; }
[[ $bot_active == 0 ]] || systemctl start bilibili-bot
printf '%s\n' "$current" > "$base/previous-release"
trap - ERR
echo "Restored code: $(cat "$previous/REVISION"). Config and data retained."
