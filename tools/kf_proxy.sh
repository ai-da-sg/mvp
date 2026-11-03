#!/usr/bin/env bash
# KampongFlow 反向代理：把后台 HTTPS 暴露到高端口，转发真实客户端 IP
#
# 用法: tools/kf_proxy.sh {start|stop|status|reload}
#
# 为什么不用系统 nginx：80/443 已被共享主机占用，且当前账号没有 sudo，
# 所以这里以用户态启动一个独立的 nginx 实例，只监听 18444。
set -euo pipefail

BASE="${KF_BASE:-/mnt/data1/kampongflow}"
RUN="${KF_PROXY_RUN:-$HOME/.local/state/kampongflow-proxy}"
CONF="$RUN/nginx.conf"
LOGS="$RUN/logs"
PIDFILE="$RUN/nginx.pid"
CONSOLE_PORT="${KF_PORT:-18090}"
LISTEN_PORT="${KF_PROXY_PORT:-18444}"
CERT="$BASE/console/tls/cert.pem"
SECRET_F="$BASE/console/proxy.secret"
KEY="$BASE/console/tls/key.pem"
NGINX="$(command -v nginx || echo /usr/sbin/nginx)"

case "${1:-status}" in
  start) ;;
  stop) ;;
  reload) ;;
  status) ;;
  *) echo "用法: $0 {start|stop|status|reload}" >&2; exit 1 ;;
esac

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "${1:-status}" in
  status)
    if is_running; then
      echo "反代运行中：https://0.0.0.0:$LISTEN_PORT → 127.0.0.1:$CONSOLE_PORT"
      echo "  主进程 PID $(cat "$PIDFILE")"
      exit 0
    fi
    echo "反代未运行"
    exit 1
    ;;
  stop)
    if is_running; then
      "$NGINX" -p "$RUN" -c "$CONF" -s quit 2>/dev/null || kill "$(cat "$PIDFILE")" 2>/dev/null || true
      sleep 1
      echo "已停止"
    else
      echo "未在运行"
    fi
    exit 0
    ;;
esac

# ---------- start / reload ----------
if [ ! -x "$NGINX" ]; then
  echo "找不到 nginx，请先安装" >&2
  exit 1
fi
if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "缺少证书，请先运行 tools/kf_tls.sh 生成" >&2
  exit 1
fi

mkdir -p "$RUN/logs" "$RUN/tmp" "$RUN/client_body"
chmod 700 "$RUN"

# 反代与后台共享的密钥（后台用 KF_PROXY_SECRET 或该文件读取）
if [ -z "${KF_PROXY_SECRET:-}" ]; then
  if [ ! -f "$SECRET_F" ]; then
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$SECRET_F"
    chmod 600 "$SECRET_F"
  fi
  PROXY_SECRET="$(cat "$SECRET_F")"
else
  PROXY_SECRET="$KF_PROXY_SECRET"
fi

# 客户端真实 IP：反代是唯一入口，所以转发头可信
cat > "$CONF" <<EOF
worker_processes 1;
pid $PIDFILE;
error_log $LOGS/error.log warn;

events {
    worker_connections 512;
}

http {
    access_log $LOGS/access.log;
    client_body_temp_path $RUN/client_body;
    proxy_temp_path $RUN/tmp/proxy;
    fastcgi_temp_path $RUN/tmp/fastcgi;
    uwsgi_temp_path $RUN/tmp/uwsgi;
    scgi_temp_path $RUN/tmp/scgi;

    # 后台返回的上传上限 8MB，留一点余量
    client_max_body_size 12m;

    # 站点页面可能较大，缓冲写盘
    proxy_buffering on;
    proxy_max_temp_file_size 64m;

    server {
        listen $LISTEN_PORT ssl;
        server_name _;

        ssl_certificate     $CERT;
        ssl_certificate_key $KEY;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_cache shared:SSL:4m;
        ssl_session_timeout 1h;

        # 后台自身的 X-Frame-Options 是 SAMEORIGIN，这里保持一致
        add_header X-Frame-Options SAMEORIGIN always;
        add_header X-Content-Type-Options nosniff always;

        location / {
            proxy_pass http://127.0.0.1:$CONSOLE_PORT;
            proxy_http_version 1.1;

            # 透传真实客户端 IP 与协议，后台的限流与 Secure Cookie 依赖它们
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$remote_addr;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_set_header X-Forwarded-Host \$host;
            # 共享密钥：后台据此判断请求确实来自本反代，
            # 否则本机进程可以伪造 X-Forwarded-For 绕过限流
            proxy_set_header X-KF-Proxy-Secret "$PROXY_SECRET";

            proxy_connect_timeout 10s;
            proxy_send_timeout 120s;
            proxy_read_timeout 120s;
        }
    }
}
EOF

if [ "${1:-start}" = "reload" ]; then
  "$NGINX" -p "$RUN" -c "$CONF" -s reload && echo "已重载"
  exit 0
fi

if is_running; then
  # 已运行：重载配置即可，重复执行不应报错
  "$NGINX" -p "$RUN" -c "$CONF" -s reload >/dev/null 2>&1 \
    && echo "反代已在运行，已重载配置：https://0.0.0.0:$LISTEN_PORT → 127.0.0.1:$CONSOLE_PORT" \
    || echo "反代已在运行（配置未变）"
  exit 0
fi

"$NGINX" -p "$RUN" -c "$CONF" -t >/dev/null 2>&1 || {
  echo "配置检查失败：" >&2
  "$NGINX" -p "$RUN" -c "$CONF" -t 2>&1 | tail -5 >&2
  exit 1
}
"$NGINX" -p "$RUN" -c "$CONF"
sleep 1

if is_running; then
  echo "反代已启动：https://0.0.0.0:$LISTEN_PORT → 127.0.0.1:$CONSOLE_PORT"
  echo "  证书 $CERT"
  echo "  日志 $LOGS/"
else
  echo "启动失败，查 $LOGS/error.log" >&2
  tail -5 "$LOGS/error.log" >&2 2>/dev/null || true
  exit 1
fi
