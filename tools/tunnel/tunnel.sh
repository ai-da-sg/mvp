#!/usr/bin/env bash
# 建立到测试服务器的本地隧道（手机 / Linux / macOS 通用，密钥需已就位）
# 用法: ./tunnel.sh [起始端口] [结束端口]
A="${1:-18080}"; B="${2:-18089}"
# 后台走 HTTPS 反代（18444），不要再转发明文的 18090
ARGS=(-L "127.0.0.1:18444:127.0.0.1:18444")
for p in $(seq "$A" "$B"); do ARGS+=(-L "127.0.0.1:$p:127.0.0.1:$p"); done
exec ssh -N -i "${KF_KEY:-$HOME/.ssh/dsh_ed25519}" \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -p 13022 "${ARGS[@]}" xcms@101.204.233.11
