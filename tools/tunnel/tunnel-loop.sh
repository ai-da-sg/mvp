#!/usr/bin/env bash
# 断线自动重连的隧道守护（手机 / Linux / macOS 通用）
A="${1:-18080}"; B="${2:-18089}"
# 后台走 HTTPS 反代（18444），不再转发明文 18090
ARGS=(-L "127.0.0.1:18444:127.0.0.1:18444")
for p in $(seq "$A" "$B"); do ARGS+=(-L "127.0.0.1:$p:127.0.0.1:$p"); done
while true; do
  ssh -N -i "${KF_KEY:-$HOME/.ssh/dsh_ed25519}" \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes \
    -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o BatchMode=yes \
    -p 13022 "${ARGS[@]}" xcms@101.204.233.11
  echo "$(date '+%F %T') 隧道断开，5 秒后重连" >&2
  sleep 5
done
