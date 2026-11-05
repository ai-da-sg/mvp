#!/usr/bin/env bash
# KampongFlow 一键安装
# 用法: ./install.sh [选项]      完整说明见 ./install.sh --help
set -euo pipefail

VERSION="1.0.0"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 默认值 ----------
KF_BASE="${KF_BASE:-/opt/kampongflow}"
KF_PORT="${KF_PORT:-18090}"
KF_SITE_PORT="${KF_SITE_PORT:-18080}"
KF_DOMAIN="${KF_DOMAIN:-kampongflow.sg}"
KF_PROXY_PORT="${KF_PROXY_PORT:-18444}"
KF_EMAIL="${KF_EMAIL:-}"
ADMIN_PASS=""
WITH_DOCKER=1
WITH_DEMO=0
NON_INTERACTIVE=0
FORCE=0
UPGRADE=0
PYTHON="${PYTHON:-python3}"
REGISTRY="docker.m.daocloud.io/library"

# ---------- 输出 ----------
if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[90m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_B=""; C_0=""
fi
info() { printf '%s\n' "  $*"; }
ok()   { printf '%s\n' "  ${C_OK}✓${C_0} $*"; }
warn() { printf '%s\n' "  ${C_WARN}!${C_0} $*"; }
die()  { printf '%s\n' "  ${C_ERR}✗${C_0} $*" >&2; exit 1; }
head_() { printf '\n%s\n' "${C_B}$*${C_0}"; }

usage() {
  cat <<EOF
KampongFlow 多租户建站平台 · 安装脚本 v${VERSION}

用法: ./install.sh [选项]

安装位置
  -d, --dir DIR         安装目录              (默认 $KF_BASE)
  -p, --port PORT       控制台端口            (默认 $KF_PORT)
  -s, --site-port PORT  首个站点端口          (默认 $KF_SITE_PORT)

必填内容
  --admin-pass PASS     管理员密码，≥10 位且含三类字符 (不填则自动生成)
  --email EMAIL         接收日报与告警的邮箱  (默认空，可稍后在后台填)

站点与域名
  --domain DOMAIN       主域名                (默认 $KF_DOMAIN)
  --proxy-port PORT     HTTPS 反代端口        (默认 $KF_PROXY_PORT)
  --demo                装完后创建一个演示站点
  --no-docker           只装控制台，不拉镜像、不建站点

其他
      --upgrade         升级已有安装：只换代码并重启，不动数据
  -y, --yes             非交互，全部用默认值/自动生成
  -f, --force           目标目录已存在时强制覆盖（会保留 sites/ 与 console/ 数据）
  -h, --help            显示本帮助

示例
  ./install.sh --dir /mnt/data1/kampongflow --port 18090 \\
               --admin-pass 'MyStr0ng-Pass-2026' --email ops@example.sg --demo

  ./install.sh -y --no-docker -d ./kf        # 最小安装，仅跑控制台
EOF
}

# ---------- 参数 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    -d|--dir)        KF_BASE="${2:?}"; shift 2 ;;
    -p|--port)       KF_PORT="${2:?}"; shift 2 ;;
    -s|--site-port)  KF_SITE_PORT="${2:?}"; shift 2 ;;
    --domain)        KF_DOMAIN="${2:?}"; shift 2 ;;
    --proxy-port)    KF_PROXY_PORT="${2:?}"; shift 2 ;;
    --admin-pass)    ADMIN_PASS="${2:?}"; shift 2 ;;
    --email)         KF_EMAIL="${2:?}"; shift 2 ;;
    --python)        PYTHON="${2:?}"; shift 2 ;;
    --upgrade)       UPGRADE=1; shift ;;
    --demo)          WITH_DEMO=1; shift ;;
    --no-docker)     WITH_DOCKER=0; shift ;;
    -y|--yes)        NON_INTERACTIVE=1; shift ;;
    -f|--force)      FORCE=1; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) die "未知参数：$1（用 --help 查看用法）" ;;
  esac
done

# ---------- 校验 ----------
case "$KF_BASE" in
  /*) ;;
  *) KF_BASE="$(cd "$(dirname "$KF_BASE")" 2>/dev/null && pwd)/$(basename "$KF_BASE")" \
       || die "安装目录必须是绝对路径" ;;
esac

port_ok() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_ok "$KF_PORT"      || die "控制台端口不合法：$KF_PORT"
port_ok "$KF_SITE_PORT" || die "站点端口不合法：$KF_SITE_PORT"

pw_problem() {
  local pw="$1" classes=0
  [ ${#pw} -ge 10 ] || { echo "至少 10 位"; return; }
  [[ "$pw" =~ [a-z] ]] && classes=$((classes+1))
  [[ "$pw" =~ [A-Z] ]] && classes=$((classes+1))
  [[ "$pw" =~ [0-9] ]] && classes=$((classes+1))
  [[ "$pw" =~ [^a-zA-Z0-9] ]] && classes=$((classes+1))
  [ "$classes" -ge 3 ] || echo "需含大写/小写/数字/符号中的至少三类"
}

gen_pass() { "$PYTHON" -c "import secrets;print(secrets.token_urlsafe(12))"; }

ask() {  # ask 变量名 提示 默认值
  local __var="$1" __prompt="$2" __default="${3:-}" __ans
  if [ "$NON_INTERACTIVE" = "1" ]; then printf -v "$__var" '%s' "$__default"; return; fi
  if [ -n "$__default" ]; then
    read -r -p "  $__prompt [$__default]: " __ans || true
    __ans="${__ans:-$__default}"
  else
    read -r -p "  $__prompt: " __ans || true
  fi
  printf -v "$__var" '%s' "$__ans"
}

printf '\n%s\n' "${C_B}KampongFlow 多租户建站平台 · 安装 v${VERSION}${C_0}"
printf '%s\n' "${C_DIM}  域名 · 建站 · DNS · 账单 · 客户代管${C_0}"

# ---------- 1. 依赖检查 ----------
head_ "1/7 检查依赖"

command -v "$PYTHON" >/dev/null 2>&1 || die "找不到 $PYTHON，请先安装 Python 3.8+"
PYV="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
"$PYTHON" -c 'import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)' \
  || die "Python 版本过低：$PYV（需要 3.8+）"
ok "Python $PYV ($(command -v "$PYTHON"))"

MISSING=()
for mod in reportlab PIL dns qrcode; do
  "$PYTHON" -c "import $mod" 2>/dev/null || MISSING+=("$mod")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  warn "缺少 Python 包：${MISSING[*]}"
  info "安装：$PYTHON -m pip install -r $SRC/requirements.txt"
  [ "$NON_INTERACTIVE" = "1" ] && die "非交互模式下依赖不全，已中止"
  read -r -p "  继续安装？（功能会受限）[y/N]: " a || true
  case "$a" in y|Y) ;; *) die "已中止" ;; esac
else
  ok "Python 依赖齐全（reportlab / Pillow / dnspython / qrcode）"
fi

if [ "$WITH_DOCKER" = "1" ]; then
  command -v docker >/dev/null 2>&1 || die "找不到 docker；如需跳过加 --no-docker"
  docker info >/dev/null 2>&1 || die "docker 未运行或当前用户无权限"
  docker compose version >/dev/null 2>&1 || die "缺少 docker compose 插件"
  ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) 可用"
  FREE_GB=$(df -BG --output=avail "$(dirname "$KF_BASE")" 2>/dev/null | tail -1 | tr -dc '0-9')
  [ -n "${FREE_GB:-}" ] && [ "$FREE_GB" -lt 5 ] && warn "磁盘剩余 ${FREE_GB}G，站点较多时可能不够"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  warn "没有 systemd，将只生成启动脚本，不注册服务"
  HAS_SYSTEMD=0
else
  HAS_SYSTEMD=1
fi

# ---------- 升级模式 ----------
if [ "$UPGRADE" = "1" ]; then
  head_ "升级模式"
  [ -f "$KF_BASE/console/kf_console.py" ] || die "$KF_BASE 下没有已安装的后台，不能升级（用普通安装）"
  [ "$SRC" != "$KF_BASE" ] || die "请从源码目录运行升级，不要指向安装目录自身"

  TS="$(date +%Y%m%d-%H%M%S)"
  BK="$KF_BASE/.upgrade-backup-$TS"
  mkdir -p "$BK"
  for d in console core tools theme templates; do
    [ -d "$KF_BASE/$d" ] && cp -a "$KF_BASE/$d" "$BK/" 2>/dev/null || true
  done
  ok "已备份代码 → $BK"

  # 只同步代码，不碰 sites/ 与 console 下的数据文件
  for f in console/kf_console.py console/ai.js console/prompts.js console/domains.js console/providers.js console/mcp.js console/automation.js console/appearance.js console/locale.js core/kf_ai.py core/kf_prompts.py core/kf_styles.py core/kf_sso.py core/kf_domain_vault.py core/kf_providers.py core/kf_cloud_api.py core/kf_cloud_dns.py core/kf_mcp.py core/kf_automation.py core/kf_tool_runtime.py core/kf_builtin_tools.py core/kf_health.py core/kf_mail.py core/kf_dns_provider.py core/kf_stepup.py core/kf_workflows.py core/kf_sections.py core/kf_dns.py core/kf_template.py \
           tools/kf_update.py tools/kf_sso_install.py tools/kf_notify.py tools/kf_provision.sh tools/kf_proxy.sh tools/kf_tls.sh; do
    install -D -m 755 "$SRC/$f" "$KF_BASE/$f"
  done
  mkdir -p "$KF_BASE/theme"
  cp -r "$SRC/theme/." "$KF_BASE/theme/"
  chmod -R a+rX "$KF_BASE/theme"
  ok "代码已更新"

  if ! "$PYTHON" -m py_compile "$KF_BASE"/console/kf_console.py "$KF_BASE"/core/*.py \
       "$KF_BASE"/tools/kf_*.py 2>/tmp/kf-upgrade-err; then
    warn "新代码编译失败，回滚"
    for d in console core tools theme templates; do
      [ -d "$BK/$d" ] && cp -a "$BK/$d/." "$KF_BASE/$d/" 2>/dev/null || true
    done
    head -3 /tmp/kf-upgrade-err >&2
    die "已回滚，服务未重启"
  fi
  ok "语法检查通过"

  if [ "$HAS_SYSTEMD" = "1" ]; then
    systemctl --user restart kf-console.service kf-dns.service 2>/dev/null || warn "重启失败，查 journalctl --user -u kf-console"
  elif [ -x "$KF_BASE/start.sh" ]; then
    bash "$KF_BASE/start.sh" >/dev/null 2>&1 || true
  fi
  sleep 4

  FAIL=0
  command -v systemctl >/dev/null 2>&1 && {
    [ "$(systemctl --user is-active kf-console 2>/dev/null)" = "active" ] || FAIL=1
    [ "$(systemctl --user is-active kf-dns 2>/dev/null)" = "active" ] || FAIL=1
  }
  CODE=$(curl -s -o /dev/null -w '%{http_code}\' "http://127.0.0.1:$KF_PORT/login" 2>/dev/null | grep -oE '[0-9]{3}' | head -1)
  [ "$CODE" = "200" ] || FAIL=1

  if [ "$FAIL" = "1" ]; then
    warn "健康检查未通过，回滚代码"
    for d in console core tools theme templates; do
      [ -d "$BK/$d" ] && cp -a "$BK/$d/." "$KF_BASE/$d/" 2>/dev/null || true
    done
    systemctl --user restart kf-console.service kf-dns.service 2>/dev/null || true
    sleep 3
    C2=$(curl -s -o /dev/null -w '%{http_code}\' "http://127.0.0.1:$KF_PORT/login" 2>/dev/null | grep -oE '[0-9]{3}' | head -1)
    [ "$C2" = "200" ] && ok "已回滚，服务恢复" || warn "回滚后仍异常（$C2），需人工介入"
    die "升级失败"
  fi

  ok "服务已重启并通过健康检查（HTTP 200）"
  printf '\n%s\n' "${C_B}升级完成${C_0}"
  info "安装目录  $KF_BASE"
  info "备份      $BK"
  info "版本      $(cat "$SRC/VERSION" 2>/dev/null || echo '?')"
  printf '\n'
  exit 0
fi

# ---------- 2. 交互收集 ----------
head_ "2/7 确认安装参数"

if [ "$NON_INTERACTIVE" = "0" ]; then
  ask KF_BASE       "安装目录"             "$KF_BASE"
  ask KF_PORT       "控制台端口"           "$KF_PORT"
  ask KF_SITE_PORT  "首个站点端口"         "$KF_SITE_PORT"
  ask KF_DOMAIN     "主域名"               "$KF_DOMAIN"
  ask KF_EMAIL      "接收日报的邮箱（可留空）" "$KF_EMAIL"
fi

if [ -z "$ADMIN_PASS" ]; then
  if [ "$NON_INTERACTIVE" = "0" ]; then
    while :; do
      read -r -s -p "  管理员密码（留空自动生成）: " p1 || true; echo
      [ -z "$p1" ] && break
      prob="$(pw_problem "$p1")"
      [ -z "$prob" ] && { ADMIN_PASS="$p1"; break; }
      warn "密码不合格：$prob"
    done
  fi
  [ -z "$ADMIN_PASS" ] && { ADMIN_PASS="$(gen_pass)"; GENERATED_PASS=1; }
fi
prob="$(pw_problem "$ADMIN_PASS")"
[ -n "$prob" ] && die "管理员密码不合格：$prob"

info "安装目录  $KF_BASE"
info "控制台端口 $KF_PORT    站点起始端口 $KF_SITE_PORT"
info "主域名    $KF_DOMAIN"
info "通知邮箱  ${KF_EMAIL:-（未设置）}"
info "容器模式  $([ "$WITH_DOCKER" = 1 ] && echo 启用 || echo 仅控制台)"

# ---------- 3. 目录与数据 ----------
head_ "3/7 准备目录"

if [ -e "$KF_BASE" ] && [ "$FORCE" != "1" ] && [ -n "$(ls -A "$KF_BASE" 2>/dev/null)" ]; then
  if [ "$NON_INTERACTIVE" = "1" ]; then
    warn "目录非空，非交互模式保留原数据继续"
  else
    read -r -p "  $KF_BASE 已存在且非空，继续？（保留 sites/ 与 console/ 数据）[y/N]: " a || true
    case "$a" in y|Y) ;; *) die "已中止" ;; esac
  fi
fi

mkdir -p "$KF_BASE"/{sites,console,dns,assets,logs}
chmod 700 "$KF_BASE/console"
# 敏感数据文件统一 600：账号哈希、会话、邮件 API Key 都在这些文件里
for f in users.json sessions.json settings.json roles.json loginfail.json ipfail.json; do
  [ -f "$KF_BASE/console/$f" ] && chmod 600 "$KF_BASE/console/$f"
done
[ -f "$KF_BASE/console/portal_secret" ] && chmod 600 "$KF_BASE/console/portal_secret"
ok "目录结构就绪（敏感文件权限 600）"

# 代码同步（源码目录与安装目录不同时）
if [ "$SRC" != "$KF_BASE" ]; then
  for f in console/kf_console.py console/ai.js console/prompts.js console/domains.js console/providers.js console/mcp.js console/automation.js console/appearance.js console/locale.js core/kf_ai.py core/kf_prompts.py core/kf_styles.py core/kf_sso.py core/kf_domain_vault.py core/kf_providers.py core/kf_cloud_api.py core/kf_cloud_dns.py core/kf_mcp.py core/kf_automation.py core/kf_tool_runtime.py core/kf_builtin_tools.py core/kf_health.py core/kf_mail.py core/kf_dns_provider.py core/kf_stepup.py core/kf_workflows.py core/kf_sections.py core/kf_dns.py core/kf_template.py \
           tools/kf_update.py tools/kf_sso_install.py tools/kf_notify.py tools/kf_provision.sh tools/kf_proxy.sh tools/kf_tls.sh; do
    install -D -m 755 "$SRC/$f" "$KF_BASE/$f"
  done
  mkdir -p "$KF_BASE/theme"
  cp -r "$SRC/theme/." "$KF_BASE/theme/"
  chmod -R a+rX "$KF_BASE/theme"
  ok "代码已复制到 $KF_BASE"
else
  ok "就地安装，代码无需复制"
fi

# 模板文件（已存在则不覆盖）
for tpl in plans.json settings.json; do
  if [ ! -f "$KF_BASE/console/$tpl" ]; then
    cp "$SRC/templates/$tpl" "$KF_BASE/console/$tpl"
    ok "初始化 console/$tpl"
  fi
done

# 管理员初始密码：交给程序首启时迁移为 users.json
if [ ! -f "$KF_BASE/console/users.json" ]; then
  printf '%s' "$ADMIN_PASS" > "$KF_BASE/console/admin.pass"
  chmod 600 "$KF_BASE/console/admin.pass"
  ok "写入初始管理员密码"
else
  warn "已存在 users.json，保留现有账号（本次密码不生效）"
fi

# 会话/门户密钥
if [ ! -f "$KF_BASE/console/portal_secret" ]; then
  "$PYTHON" -c "import secrets;print(secrets.token_hex(32))" > "$KF_BASE/console/portal_secret"
  chmod 600 "$KF_BASE/console/portal_secret"
  ok "生成会话密钥"
fi

# 通知邮箱写入设置
if [ -n "$KF_EMAIL" ]; then
  "$PYTHON" - "$KF_BASE/console/settings.json" "$KF_EMAIL" <<'PY'
import json, sys
p, mail = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p))
except Exception:
    d = {}
d.setdefault("smtp", {})["notify_to"] = mail
d["support_email"] = mail
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
PY
  ok "通知邮箱已写入设置"
fi

# ---------- 4. 语法自检 ----------
head_ "4/7 代码自检"
for f in console/kf_console.py core/kf_ai.py core/kf_prompts.py core/kf_styles.py core/kf_sso.py core/kf_domain_vault.py core/kf_providers.py core/kf_cloud_api.py core/kf_cloud_dns.py core/kf_mcp.py core/kf_automation.py core/kf_tool_runtime.py core/kf_builtin_tools.py core/kf_health.py core/kf_mail.py core/kf_dns_provider.py core/kf_stepup.py core/kf_workflows.py core/kf_sections.py core/kf_dns.py core/kf_template.py \
         tools/kf_update.py tools/kf_sso_install.py tools/kf_notify.py; do
  "$PYTHON" -m py_compile "$KF_BASE/$f" || die "语法错误：$f"
done
bash -n "$KF_BASE/tools/kf_provision.sh" || die "语法错误：tools/kf_provision.sh"
ok "全部文件语法通过"

# ---------- 5. 服务注册 ----------
head_ "5/7 注册后台服务"
UNIT_DIR="$HOME/.config/systemd/user"

if [ "$HAS_SYSTEMD" = "1" ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/kf-console.service" <<EOF
[Unit]
Description=KampongFlow 管理后台
After=network.target

[Service]
WorkingDirectory=$KF_BASE
ExecStart=$PYTHON $KF_BASE/console/kf_console.py
Restart=always
RestartSec=3
Environment=KF_PORT=$KF_PORT
Environment=KF_BASE=$KF_BASE
Environment=KF_DNS_PORT=5354
# 只监听回环，外部一律经反代进来
Environment=KF_BIND=127.0.0.1
# 反代是唯一入口，它转发的客户端 IP 可信
Environment=KF_TRUSTED_PROXIES=127.0.0.1
# 强制 HTTPS，Cookie 才带 Secure
Environment=KF_FORCE_HTTPS=1

[Install]
WantedBy=default.target
EOF

  cat > "$UNIT_DIR/kf-proxy.service" <<EOF
[Unit]
Description=KampongFlow HTTPS 反代
After=network.target kf-console.service

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=KF_BASE=$KF_BASE
Environment=KF_PORT=$KF_PORT
Environment=KF_PROXY_PORT=$KF_PROXY_PORT
ExecStart=$KF_BASE/tools/kf_proxy.sh start
ExecStop=$KF_BASE/tools/kf_proxy.sh stop

[Install]
WantedBy=default.target
EOF

  cat > "$UNIT_DIR/kf-dns.service" <<EOF
[Unit]
Description=KampongFlow DNS 解析
After=network.target

[Service]
ExecStart=$PYTHON $KF_BASE/core/kf_dns.py --port 5354
Restart=always
RestartSec=3
Environment=KF_BASE=$KF_BASE

[Install]
WantedBy=default.target
EOF

  cat > "$UNIT_DIR/kf-notify.service" <<EOF
[Unit]
Description=KampongFlow 每日摘要
After=network.target

[Service]
Environment=KF_BASE=$KF_BASE
Type=oneshot
ExecStart=$PYTHON $KF_BASE/tools/kf_notify.py
EOF

  cat > "$UNIT_DIR/kf-notify.timer" <<EOF
[Unit]
Description=每日发送 KampongFlow 摘要

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable --now kf-console.service >/dev/null 2>&1 || warn "控制台服务启动失败，稍后查 journalctl --user -u kf-console"
  # 反代需要证书，没有就先生成一份自签
  if [ ! -f "$KF_BASE/console/tls/cert.pem" ]; then
    KF_BASE="$KF_BASE" bash "$KF_BASE/tools/kf_tls.sh" >/dev/null 2>&1 || warn "证书生成失败"
  fi
  systemctl --user enable --now kf-proxy.service >/dev/null 2>&1 || warn "反代启动失败，查 tools/kf_proxy.sh status"
  systemctl --user enable --now kf-dns.service >/dev/null 2>&1 || warn "DNS 服务启动失败"
  systemctl --user enable --now kf-notify.timer >/dev/null 2>&1 || warn "定时任务注册失败"
  loginctl enable-linger "$USER" >/dev/null 2>&1 || warn "未能开启 linger，注销后服务可能停止"
  ok "systemd 服务已注册并启动"
else
  cat > "$KF_BASE/start.sh" <<EOF
#!/usr/bin/env bash
export KF_BASE=$KF_BASE KF_PORT=$KF_PORT KF_DNS_PORT=5354
# 后台只监听回环，外部经反代进来
export KF_BIND=127.0.0.1 KF_FORCE_HTTPS=1 KF_TRUSTED_PROXIES=127.0.0.1
nohup $PYTHON $KF_BASE/console/kf_console.py > $KF_BASE/logs/console.log 2>&1 &
nohup $PYTHON $KF_BASE/core/kf_dns.py --port 5354 > $KF_BASE/logs/dns.log 2>&1 &
sleep 1
# 有证书就起反代，没有就先签一份自签
[ -f "$KF_BASE/console/tls/cert.pem" ] || bash "$KF_BASE/tools/kf_tls.sh" >/dev/null 2>&1
KF_BASE=$KF_BASE KF_PORT=$KF_PORT KF_PROXY_PORT=$KF_PROXY_PORT bash "$KF_BASE/tools/kf_proxy.sh" start
echo "已启动控制台 :$KF_PORT（仅回环）、DNS :5354、HTTPS 反代 :$KF_PROXY_PORT"
EOF
  chmod +x "$KF_BASE/start.sh"
  ok "已生成 $KF_BASE/start.sh（手动启动）"
fi

# ---------- 6. 容器镜像 ----------
head_ "6/7 准备站点运行环境"
if [ "$WITH_DOCKER" = "1" ]; then
  for img in "wordpress:php8.3-apache" "mariadb:11.4"; do
    if docker image inspect "$REGISTRY/$img" >/dev/null 2>&1; then
      ok "镜像已存在 $img"
    else
      info "拉取 $img ..."
      docker pull -q "$REGISTRY/$img" >/dev/null 2>&1 && ok "拉取完成 $img" \
        || warn "拉取失败 $img（稍后可重试）"
    fi
  done
else
  info "已跳过（--no-docker）"
fi

# ---------- 7. 演示站点 ----------
head_ "7/7 收尾"
if [ "$WITH_DEMO" = "1" ] && [ "$WITH_DOCKER" = "1" ]; then
  if [ -d "$KF_BASE/sites/demo" ]; then
    warn "demo 已存在，跳过"
  else
    info "创建演示站点（约 1–2 分钟）..."
    KF_BASE="$KF_BASE" bash "$KF_BASE/tools/kf_provision.sh" \
      "演示公司" "demo.$KF_DOMAIN" demo "$KF_SITE_PORT" \
      "Starter" 1800 "tech" starter >/dev/null 2>&1 \
      && ok "演示站点已创建：http://127.0.0.1:$KF_SITE_PORT/" \
      || warn "演示站点创建失败，可在后台手工开通"
  fi
fi

sleep 2
PORT_OK=0
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$KF_PORT/login" 2>/dev/null || echo 000)
  [ "$code" = "200" ] && PORT_OK=1
fi

printf '\n%s\n' "${C_B}安装完成${C_0}"
printf '%s\n' "  ┌────────────────────────────────────────────"
info "后台      https://127.0.0.1:$KF_PROXY_PORT  (HTTPS，自签证书首次需信任)"
info "          http://127.0.0.1:$KF_PORT  (仅本机可达)"
info "账号      admin"
if [ "${GENERATED_PASS:-0}" = "1" ]; then
  printf '%s\n' "  │ 密码      ${C_WARN}$ADMIN_PASS${C_0}   ${C_DIM}（自动生成，请立即保存）${C_0}"
else
  printf '%s\n' "  │ 密码      你设置的那个"
fi
info "安装目录  $KF_BASE"
info "服务状态  $([ "$PORT_OK" = 1 ] && echo 正常 || echo "未响应，查 journalctl --user -u kf-console")"
printf '%s\n' "  └────────────────────────────────────────────"

cat <<EOF

  下一步
    1. 浏览器打开后台（HTTPS），首次访问需信任自签证书
    2. 登录后立刻把密码保存好
    3. 「团队」→「我的账号」开启两步验证，并保存 10 个恢复码
    4. 「维护」→ 邮件发送：填 Resend / SendGrid 的 API Key 并点「发送测试」
    5. 「站点」→ 开通第一个站点

  常用命令
    systemctl --user status kf-console     服务状态
    journalctl --user -u kf-console -f     看日志
    $KF_BASE/tools/kf_provision.sh "公司" "域名" slug 端口  新建站点

  文档
    $SRC/docs/部署.md     部署与端口
    $SRC/docs/运维.md     日常运维与排障
    $SRC/docs/安全.md     账号、权限与恢复

EOF
