#!/usr/bin/env bash
# 手机端隧道保活控制: tunnelctl.sh start|stop|restart|status
LOG=${KF_TUNNEL_LOG:-/root/workspace/tunnel.log}
PIDF=${KF_TUNNEL_PID:-/root/workspace/tunnel.pid}
RUNNER="$(dirname "$0")/tunnel-loop.sh"

alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; }

start() {
  if alive; then echo "已在运行 (pid $(cat "$PIDF"))"; return 0; fi
  setsid nohup "$RUNNER" 18080 18089 >>"$LOG" 2>&1 </dev/null &
  echo $! > "$PIDF"
  sleep 2
  if alive; then echo "已启动 (pid $(cat "$PIDF"))"; else echo "启动失败，见 $LOG"; return 1; fi
}

stop() {
  if [ -f "$PIDF" ]; then
    pid=$(cat "$PIDF")
    pkill -TERM -P "$pid" 2>/dev/null
    kill -TERM "$pid" 2>/dev/null
    sleep 1
    pkill -KILL -P "$pid" 2>/dev/null
    kill -KILL "$pid" 2>/dev/null
    rm -f "$PIDF"
  fi
  echo "已停止"
}

status() {
  if alive; then echo "守护进程: 运行中 (pid $(cat "$PIDF"))"; else echo "守护进程: 未运行"; fi
  node -e '
  const ports=[18080,18081,18082,18083];
  (async()=>{const out=[];for(const p of ports){let s="FAIL";try{const r=await fetch(`http://127.0.0.1:${p}/`,{signal:AbortSignal.timeout(4000)});s=r.status}catch(e){}out.push(p+":"+s)}
  console.log("站点 "+out.join("  "))})()'
  # 自签证书会让 node fetch 报 DEPTH_ZERO_SELF_SIGNED_CERT，
  # 临时放开校验只为探测可达性
  NODE_TLS_REJECT_UNAUTHORIZED=0 node $(dirname "$0")/probe-backend.js 2>&1 \
    | grep -v "Warning" | grep -v "trace-warnings"
}

case "${1:-status}" in
  start) start ;; stop) stop ;; restart) stop; start ;; status) status ;;
  *) echo "用法: $0 start|stop|restart|status"; exit 2 ;;
esac
