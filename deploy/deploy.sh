#!/usr/bin/env bash
# Usage: sudo bash deploy/deploy.sh /absolute/path/to/repo COMMIT_OR_TAG
# Deploys only committed code. Fetch/push are deliberately separate operations.
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# == 2 ]] || { echo 'Usage: deploy.sh REPOSITORY COMMIT_OR_TAG' >&2; exit 1; }
repo=$(realpath "$1")
base=/opt/bilibili-bot
state=/var/lib/bilibili-bot
for command in git python3 curl systemctl flock tar runuser; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
mkdir -p "$base/releases" "$base/backups" /etc/bilibili-bot
exec 9>"$base/deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
# A checkout owned by the invoking sudo user is normal. Trust only the supplied path.
gitrepo() { git -c safe.directory="$repo" -C "$repo" "$@"; }
[[ -z $(gitrepo status --porcelain) ]] || { echo 'Commit or stash checkout changes first.' >&2; exit 1; }
commit=$(gitrepo rev-parse --verify --end-of-options "$2^{commit}")
gitrepo cat-file -e "$commit:deploy/bilibili-web.service"
if gitrepo ls-tree -r --name-only "$commit" | grep -Eq '(^|/)(config\.json|data/|\.env$|cookies\.txt$)'; then
    echo 'Refusing release containing tracked private state.' >&2; exit 1
fi
id bilibili-bot >/dev/null 2>&1 || useradd --system --home-dir "$state" --shell /usr/sbin/nologin bilibili-bot
install -d -o bilibili-bot -g bilibili-bot -m 700 "$state" "$state/data"
release=$(mktemp -d "$base/releases/${commit:0:12}-XXXXXX")
chmod 755 "$base" "$base/releases" "$release"
gitrepo archive "$commit" | tar -x -C "$release"
# Extracted code is readable by the service, but not writable by it.
chmod -R a+rX "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/pip" install -r "$release/bilibili-ai-bot/requirements-server.txt"
"$release/.venv/bin/pip" freeze > "$release/installed-requirements.txt"
printf '%s\n' "$commit" > "$release/REVISION"
chmod -R a+rX "$release"

# Validate in a disposable directory, without importing real server credentials.
runuser -u bilibili-bot -- "$release/.venv/bin/python" -m unittest discover \
    -s "$release/bilibili-ai-bot/tests" -p 'test_deployment.py'

if [[ ! -e /etc/bilibili-bot/environment ]]; then
    secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    cat > /etc/bilibili-bot/environment <<EOF
BILI_STATE_DIR=$state
BILI_PRODUCTION=1
SECRET_KEY=$secret
TZ=Asia/Shanghai
PYTHONUNBUFFERED=1
COOKIE_SECURE=0
EOF
fi
chmod 600 /etc/bilibili-bot/environment
if [[ ! -e "$state/config.json" ]]; then
    # Create fresh config only. Existing config is never overwritten.
    runuser -u bilibili-bot -- env BILI_STATE_DIR="$state" \
        PYTHONPATH="$release/bilibili-ai-bot" "$release/.venv/bin/python" - <<'PY'
import secrets
import config
config.update_config({"CHAT_PASSWORD": secrets.token_urlsafe(24),
                      "ENABLE_PROACTIVE": False, "ENABLE_DYNAMIC": False,
                      "ENABLE_PRIVATE_MESSAGES": False})
PY
fi

old=$(readlink -f "$base/current" || true)
bot_active=0; web_active=0
systemctl is-active --quiet bilibili-bot && bot_active=1
systemctl is-active --quiet bilibili-web && web_active=1
switched=0
recover() {
    result=$?
    trap - ERR
    set +e
    echo 'Deployment failed. Restoring the previous code/services where available.' >&2
    if [[ $switched == 1 ]]; then
        systemctl stop bilibili-bot bilibili-web
        if [[ -n $old ]]; then
            ln -sfn "$old" "$base/current.recover"
            mv -Tf "$base/current.recover" "$base/current"
            install -m 644 "$old/deploy/"*.service /etc/systemd/system/
            systemctl daemon-reload
        fi
    fi
    [[ $web_active == 0 ]] || systemctl start bilibili-web
    [[ $bot_active == 0 ]] || systemctl start bilibili-bot
    echo 'State was not rolled back. Inspect logs and the backup before retrying.' >&2
    exit "$result"
}
trap recover ERR
# Stop both services (including scheduled child processes) for a consistent backup.
if [[ -n $old ]]; then
    systemctl stop bilibili-bot bilibili-web
fi
backup="$base/backups/$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}.tar.gz"
tar -czf "$backup" -C / var/lib/bilibili-bot etc/bilibili-bot
if [[ -n $old ]]; then
    printf '%s\n' "$old" > "$base/previous-release"
fi
switched=1
ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
install -m 644 "$release/deploy/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bilibili-web
systemctl start bilibili-web
healthy=0
for ((i=0; i<20; i++)); do
    if systemctl is-active --quiet bilibili-web && curl -fsS --max-time 3 http://127.0.0.1:5000/api/health | python3 -c 'import json,sys; assert json.load(sys.stdin)["ok"] is True'; then
        healthy=1; break
    fi
    sleep 1
done
[[ $healthy == 1 ]] || { echo 'Panel health check failed.' >&2; false; }
if [[ $bot_active == 1 ]]; then
    systemctl start bilibili-bot
    sleep 3
    systemctl is-active --quiet bilibili-bot
fi
trap - ERR
echo "Deployed commit: $commit"
echo "Backup: $backup"
echo 'Panel: SSH tunnel to 127.0.0.1:5000. Config: /var/lib/bilibili-bot/config.json'
echo 'First installation leaves the bot stopped. Configure and test the panel before enabling it.'
