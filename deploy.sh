#!/usr/bin/env bash
# KampongFlow 发布：提交 → 推送 → 部署 → 健康检查（失败自动回滚）
#
# 用法: ./deploy.sh -m "改动说明"
# 配置: 复制 deploy.env.example 为 deploy.env 并填写远程主机
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC"

# ---------- 配置 ----------
ENVF="$SRC/deploy.env"
[ -f "$ENVF" ] && . "$ENVF"

REMOTE="${KF_DEPLOY_TARGET:-}"          # user@host
SSH_PORT="${KF_DEPLOY_PORT:-22}"
SSH_PASS="${KF_DEPLOY_PASS:-}"          # 留空则用密钥
RBASE="${KF_DEPLOY_BASE:-/opt/kampongflow}"
SVC_CONSOLE="${KF_DEPLOY_SVC_CONSOLE:-kf-console}"
SVC_DNS="${KF_DEPLOY_SVC_DNS:-kf-dns}"
CPORT="${KF_DEPLOY_CONSOLE_PORT:-18090}"
DPORT="${KF_DEPLOY_DNS_PORT:-5354}"
PPORT="${KF_DEPLOY_PROXY_PORT:-18444}"
BRANCH="${KF_DEPLOY_BRANCH:-main}"

MSG=""
DO_PUSH=1
DO_DEPLOY=1
DRY=0

if [ -t 1 ]; then
  OK=$'\033[32m'; WARN=$'\033[33m'; ERR=$'\033[31m'; DIM=$'\033[90m'; B=$'\033[1m'; N=$'\033[0m'
else
  OK=""; WARN=""; ERR=""; DIM=""; B=""; N=""
fi
step() { printf '\n%s\n' "${B}$*${N}"; }
ok()   { printf '  %s✓%s %s\n' "$OK" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$WARN" "$N" "$*"; }
die()  { printf '  %s✗%s %s\n' "$ERR" "$N" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
KampongFlow 发布脚本

用法: ./deploy.sh -m "改动说明" [选项]

  -m, --message TEXT   提交说明（有改动时必填或交互输入）
      --no-push        只部署，不提交不推送
      --no-deploy      只提交推送，不部署
      --dry-run        只显示将执行的动作
  -h, --help           显示帮助

配置（deploy.env，参考 deploy.env.example）
  KF_DEPLOY_TARGET     user@host       必填，部署目标
  KF_DEPLOY_PORT       SSH 端口        默认 22
  KF_DEPLOY_PASS       SSH 密码        留空则使用密钥
  KF_DEPLOY_BASE       远程安装目录    默认 /opt/kampongflow
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -m|--message) MSG="${2:?}"; shift 2 ;;
    --no-push)    DO_PUSH=0; shift ;;
    --no-deploy)  DO_DEPLOY=0; shift ;;
    --dry-run)    DRY=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done

# ---------- SSH 封装 ----------
SSH_OPTS=(-o StrictHostKeyChecking=no -o ConnectTimeout=20 -p "$SSH_PORT")
if [ -n "$SSH_PASS" ]; then
  command -v sshpass >/dev/null 2>&1 || die "配置了 KF_DEPLOY_PASS 但没装 sshpass"
  SSH=(sshpass -p "$SSH_PASS" ssh "${SSH_OPTS[@]}")
  SCP=(sshpass -p "$SSH_PASS" ssh "${SSH_OPTS[@]}")
else
  SSH=(ssh "${SSH_OPTS[@]}")
  SCP=(ssh "${SSH_OPTS[@]}")
fi
BANNER='^(openjdk version|OpenJDK Runtime Environment|OpenJDK 64-Bit Server VM)'
rsh() {
  # 远端登录 shell 会打印 Java 版本横幅，这里过滤掉但保留真实退出码
  local out rc=0
  out=$("${SSH[@]}" "$REMOTE" "$@" 2>&1) || rc=$?
  if [ -n "$out" ]; then printf '%s\n' "$out" | grep -vE "$BANNER" || true; fi
  return $rc
}

printf '\n%s\n' "${B}KampongFlow 发布${N}"
printf '  %s%s → %s:%s%s\n' "$DIM" "$SRC" "${REMOTE:-未配置}" "$RBASE" "$N"

# ---------- 1. 本地检查 ----------
step "1/5 本地检查"
git rev-parse --git-dir >/dev/null 2>&1 || die "当前目录不是 git 仓库"
BR="$(git rev-parse --abbrev-ref HEAD)"
[ "$BR" = "$BRANCH" ] || warn "当前分支是 $BR，脚本按 $BRANCH 推送"
ok "分支 $BR · $(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain)" ]; then
  CHANGES=$(git status --porcelain | wc -l)
  ok "有 $CHANGES 个文件改动待提交"
else
  ok "工作区干净，无新提交"
  [ "$DO_PUSH" = "1" ] && info=1
fi

# ---------- 2. 提交 ----------
step "2/5 提交"
if [ -n "$(git status --porcelain)" ]; then
  if [ -z "$MSG" ]; then
    if [ -t 0 ]; then read -r -p "  提交说明: " MSG || true; fi
    [ -z "$MSG" ] && die "有改动但没有提交说明（用 -m 指定）"
  fi
  if [ "$DRY" = "1" ]; then
    warn "[dry-run] 将提交：$MSG"
  else
    git add -A
    git commit -q -m "$MSG"
    ok "已提交 $(git rev-parse --short HEAD) — $MSG"
  fi
else
  ok "无需提交"
fi

# ---------- 3. 推送 ----------
step "3/5 推送"
if [ "$DO_PUSH" = "1" ]; then
  if [ "$DRY" = "1" ]; then
    warn "[dry-run] 将推送 $BRANCH 到 origin"
  else
    GIT_TERMINAL_PROMPT=0 git push -q origin "$BRANCH" 2>&1 | sed 's/[0-9a-f]\{20,\}/***/g' | tail -3 || \
      die "推送失败（检查凭据：git config --global credential.helper store）"
    ok "已推送到 origin/$BRANCH"
  fi
else
  ok "已跳过（--no-push）"
fi

# ---------- 4. 部署 ----------
step "4/5 部署"
if [ "$DO_DEPLOY" = "0" ]; then
  ok "已跳过（--no-deploy）"
else
  [ -n "$REMOTE" ] || die "未配置 KF_DEPLOY_TARGET，见 deploy.env.example"

  if [ "$DRY" = "1" ]; then
    warn "[dry-run] 将同步 console/ core/ tools/ theme/ templates/ 到 $REMOTE:$RBASE"
    warn "[dry-run] 将重启 $SVC_CONSOLE 与 $SVC_DNS"
    exit 0
  fi

  TS=$(date +%Y%m%d-%H%M%S)
  FILES="console core tools theme templates"
  info=$(rsh "mkdir -p '$RBASE' && du -sh '$RBASE' 2>/dev/null | cut -f1" 2>/dev/null || echo "?")
  ok "远程目录 $RBASE（当前 $info）"

  # 备份远程代码（数据不动）
  rsh "set -e; B='$RBASE'; K=\$(mktemp -d); mkdir -p \$K/code; \
       for d in $FILES; do [ -d \$B/\$d ] && cp -a \$B/\$d \$K/code/ 2>/dev/null || true; done; \
       tar czf /tmp/kf-pre-$TS.tgz -C \$K code; rm -rf \$K; echo /tmp/kf-pre-$TS.tgz" >/tmp/kf_backup_path 2>/dev/null \
    && ok "远程已备份 → $(cat /tmp/kf_backup_path)" || warn "远程备份失败，继续（谨慎）"

  # 同步代码
  tar czf - $FILES | rsh "tar xzf - -C '$RBASE'" || die "代码同步失败"
  ok "代码已同步"

  # 远端自检
  if ! rsh "cd '$RBASE' && python3 -m py_compile console/kf_console.py core/kf_sections.py core/kf_dns.py core/kf_template.py tools/kf_update.py tools/kf_notify.py" 2>/tmp/kf_err; then
    warn "远端编译失败，开始回滚"
    rsh "tar xzf /tmp/kf-pre-$TS.tgz -C '$RBASE' --strip-components=1 2>/dev/null; systemctl --user restart $SVC_CONSOLE $SVC_DNS" || true
    head -5 /tmp/kf_err >&2
    die "已回滚到部署前版本"
  fi
  ok "远端语法检查通过"

  # 重启
  rsh "systemctl --user restart $SVC_CONSOLE $SVC_DNS" || die "重启服务失败"
  ok "服务已重启"
  sleep 4

  # ---------- 5. 健康检查 ----------
  step "5/5 健康检查"
  FAIL=0

  A=$(rsh "systemctl --user is-active $SVC_CONSOLE" 2>/dev/null | tr -d '\r' | grep -oE '^(active|inactive|failed|activating|deactivating)' | head -1)
  [ "$A" = "active" ] && ok "控制台进程 active" || { warn "控制台状态 $A"; FAIL=1; }

  D=$(rsh "systemctl --user is-active $SVC_DNS" 2>/dev/null | tr -d '\r' | grep -oE '^(active|inactive|failed|activating|deactivating)' | head -1)
  [ "$D" = "active" ] && ok "DNS 进程 active" || { warn "DNS 状态 $D"; FAIL=1; }

  C=$(rsh "curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:$CPORT/login" 2>/dev/null | tr -d '\r' | grep -oE '[0-9]{3}' | head -1)
  [ "$C" = "200" ] && ok "登录页 HTTP 200" || { warn "登录页返回 $C"; FAIL=1; }

  # HTTPS 反代：真实用户走的是这条路径
  P=$(rsh "curl -sk -o /dev/null -w '%{http_code}\\n' https://127.0.0.1:$PPORT/login" 2>/dev/null | tr -d '\r' | grep -oE '[0-9]{3}' | head -1)
  [ "$P" = "200" ] && ok "HTTPS 反代 :$PPORT 200" || { warn "HTTPS 反代返回 ${P:-无响应}"; FAIL=1; }

  # 后台必须只监听回环
  L=$(rsh "ss -tln 2>/dev/null | grep ':$CPORT ' | awk '{print \$4}' | head -1" 2>/dev/null | tr -d '\r')
  case "$L" in
    127.0.0.1:*) ok "后台只监听回环 ($L)" ;;
    "")           warn "查不到后台监听地址" ;;
    *)            warn "后台监听在 $L，应改为 127.0.0.1"; FAIL=1 ;;
  esac

  Z=$(rsh "ls '$RBASE'/dns/zones.json >/dev/null 2>&1 && echo yes" 2>/dev/null | tr -d '\r')
  if [ "$Z" = "yes" ]; then
    Q=$(rsh "python3 -c \"import json;print(list(json.load(open('$RBASE/dns/zones.json')).values())[0]['domain'])\"" 2>/dev/null | tr -d '\r' | grep -E '^[a-z0-9.-]+$' | head -1)
    if [ -n "$Q" ]; then
      R=$(rsh "dig +short @127.0.0.1 -p $DPORT $Q A | head -1" 2>/dev/null | tr -d '\r' | grep -E '^[0-9a-fA-F:.]+$' | head -1)
      [ -n "$R" ] && ok "DNS 解析 $Q → $R" || { warn "DNS 解析 $Q 无结果"; FAIL=1; }
    fi
  fi

  if [ "$FAIL" = "1" ]; then
    printf '\n  %s健康检查未通过，自动回滚%s\n' "$ERR" "$N"
    rsh "tar xzf /tmp/kf-pre-$TS.tgz -C '$RBASE' --strip-components=1 2>/dev/null; systemctl --user restart $SVC_CONSOLE $SVC_DNS" || true
    sleep 3
    C2=$(rsh "curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:$CPORT/login" 2>/dev/null | tr -d '\r' | grep -oE '[0-9]{3}' | head -1)
    [ "$C2" = "200" ] && ok "已回滚，服务恢复（HTTP 200）" || warn "回滚后仍是 $C2，需人工介入"
    die "发布失败"
  fi
fi

printf '\n%s\n' "${B}发布完成${N}"
printf '  %s提交 %s · 分支 %s%s\n' "$DIM" "$(git rev-parse --short HEAD)" "$BRANCH" "$N"
printf '  后台 http://127.0.0.1:%s\n\n' "$CPORT"
