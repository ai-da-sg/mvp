#!/usr/bin/env bash
set -euo pipefail
: "${DEPLOY_HOST:?Set DEPLOY_HOST}" "${DEPLOY_USER:?Set DEPLOY_USER}"
: "${DEPLOY_SSH_KEY:?Set DEPLOY_SSH_KEY}" "${DEPLOY_KNOWN_HOSTS:?Set verified host keys}"
: "${DEPLOY_BASE:?Set DEPLOY_BASE}" "${DEPLOY_PYTHON:?Set DEPLOY_PYTHON}"
: "${GITHUB_SHA:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" "${RUNNER_TEMP:?}"
DEPLOY_PORT=${DEPLOY_PORT:-22}
[[ $DEPLOY_HOST =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && $DEPLOY_USER =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]]
[[ $DEPLOY_BASE =~ ^/[a-zA-Z0-9_./-]+$ && $DEPLOY_PYTHON =~ ^/[a-zA-Z0-9_./-]+$ ]]
[[ $DEPLOY_PORT =~ ^[0-9]+$ && $GITHUB_SHA =~ ^[0-9a-f]{40}$ ]]
[[ $GITHUB_RUN_ID =~ ^[0-9]+$ && $GITHUB_RUN_ATTEMPT =~ ^[0-9]+$ ]]
(( DEPLOY_PORT > 0 && DEPLOY_PORT <= 65535 ))
keydir=$(mktemp -d "$RUNNER_TEMP/kf-ssh.XXXXXX")
remote_dir="/tmp/kf-release-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
target="$DEPLOY_USER@$DEPLOY_HOST"
opts=(-i "$keydir/key" -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$keydir/known_hosts" -o ConnectTimeout=15)
cleanup() { rm -rf "$keydir"; }
trap cleanup EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" > "$keydir/key"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$keydir/known_hosts"
chmod 600 "$keydir/key" "$keydir/known_hosts"
(cd dist && sha256sum -c release.tgz.sha256)
ssh "${opts[@]}" -p "$DEPLOY_PORT" "$target" "umask 077; mkdir '$remote_dir'"
scp "${opts[@]}" -P "$DEPLOY_PORT" dist/release.tgz dist/kf_release.py "$target:$remote_dir/"
# The SSH account must own the existing user services and installation.
ssh "${opts[@]}" -p "$DEPLOY_PORT" "$target" "'$DEPLOY_PYTHON' '$remote_dir/kf_release.py' deploy '$remote_dir/release.tgz' --base '$DEPLOY_BASE' --expected-revision '$GITHUB_SHA'"
ssh "${opts[@]}" -p "$DEPLOY_PORT" "$target" "rm -f '$remote_dir/release.tgz' '$remote_dir/kf_release.py'; rmdir '$remote_dir'"
