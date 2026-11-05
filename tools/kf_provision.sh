#!/usr/bin/env bash
# kf-provision.sh <公司名> <域名> <slug> <端口>
set -euo pipefail
COMPANY="${1:?公司名}"; DOMAIN="${2:?域名}"; SLUG="${3:?slug}"; PORT="${4:?端口}"
# slug 与 port 都要白名单：它们会进文件路径、容器名与端口映射
case "$SLUG" in
  [a-z][a-z0-9-]*) ;;
  *) echo "ERR: slug 只能用小写字母开头，含小写字母/数字/短横线，2-20 位" >&2; exit 1 ;;
esac
if [ "${#SLUG}" -lt 2 ] || [ "${#SLUG}" -gt 20 ]; then
  echo "ERR: slug 长度需在 2-20 位" >&2; exit 1
fi
case "$PORT" in
  ''|*[!0-9]*) echo "ERR: 端口必须是数字" >&2; exit 1 ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "ERR: 端口超出范围" >&2; exit 1
fi
PLAN="${5:-}"; PRICE="${6:-}"; INDUSTRY="${7:-}"; PLAN_ID="${8:-}"
BASE="${KF_BASE:-/mnt/data1/kampongflow}"
SITE="$BASE/sites/$SLUG"
PROJ="kf-$SLUG"
REG="docker.m.daocloud.io/library"
[ -d "$SITE" ] && { echo "ERR: $SITE 已存在"; exit 1; }
mkdir -p "$SITE/html" "$SITE/db"
DBPASS=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
ROOTPASS=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
ADMINPW=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 16)
cat > "$SITE/docker-compose.yml" <<EOF
name: $PROJ
services:
  db:
    image: $REG/mariadb:11.4
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: wordpress
      MARIADB_USER: wpuser
      MARIADB_PASSWORD: "$DBPASS"
      MARIADB_ROOT_PASSWORD: "$ROOTPASS"
    volumes: ["./db:/var/lib/mysql:Z"]
    mem_limit: 768m
    cpus: 2
  web:
    image: $REG/wordpress:php8.3-apache
    restart: unless-stopped
    depends_on: [db]
    environment:
      WORDPRESS_DB_HOST: db:3306
      WORDPRESS_DB_USER: wpuser
      WORDPRESS_DB_PASSWORD: "$DBPASS"
      WORDPRESS_DB_NAME: wordpress
    volumes: ["./html:/var/www/html:Z"]
    ports: ["127.0.0.1:$PORT:80"]
    mem_limit: 768m
    cpus: 2
EOF
# compose 里含数据库明文密码，必须只有属主可读
chmod 600 "$SITE/docker-compose.yml"
cd "$SITE"
docker compose up -d --quiet-pull >/dev/null
READY=0
for i in $(seq 1 40); do
  # 密码走环境变量，不进 argv（同主机其他用户 ps 可见）
  docker exec -e MYSQL_PWD="$ROOTPASS" "${PROJ}-db-1" mariadb -uroot -e 'SELECT 1' >/dev/null 2>&1 && { READY=1; break; }
  sleep 2
done
[ "$READY" = 1 ] || { echo "数据库未就绪" >&2; exit 1; }
cat > "$SITE/wp.env" <<ENV
WORDPRESS_DB_HOST=db:3306
WORDPRESS_DB_USER=wpuser
WORDPRESS_DB_PASSWORD=$DBPASS
WORDPRESS_DB_NAME=wordpress
ENV
chmod 600 "$SITE/wp.env"
W() { docker run --rm -i --env-file "$SITE/wp.env" --network "${PROJ}_default" -v "$SITE/html:/var/www/html" --user 33:33 "$REG/wordpress:cli-php8.3" wp "$@"; }
# WP 管理员密码改从 stdin 传入，不出现在 argv 里
# （argv 对同主机所有用户可见，ps 就能看到）
printf '%s\n' "$ADMINPW" | W core install --url="http://127.0.0.1:$PORT" --title="$COMPANY" \
  --admin_user="admin" --admin_email="admin@$DOMAIN" --skip-email \
  --prompt=admin_password >/dev/null 2>&1 || {
  # 老版本 wp-cli 不支持 --prompt，退回传参方式
  W core install --url="http://127.0.0.1:$PORT" --title="$COMPANY" --admin_user="admin" \
    --admin_password="$ADMINPW" --admin_email="admin@$DOMAIN" --skip-email >/dev/null
}
W option update timezone_string "Asia/Singapore" >/dev/null
W option update blogdescription "Website, email and hosting package" >/dev/null
W rewrite structure '/%postname%/' --hard >/dev/null
if [ -n "$INDUSTRY" ]; then
  PY=$(command -v python3)
  "$PY" "$BASE/core/kf_template.py" --site "$SITE" --industry "$INDUSTRY" \
    --company "$COMPANY" --domain "$DOMAIN" >/dev/null || { echo "模板应用失败" >&2; exit 1; }
fi
# The console writes media on the host; WordPress only needs to read these files.
docker run --rm --user 0:0 -e KF_MEDIA_OWNER="$(id -u):$(id -g)" \
  -v "$SITE/html:/var/www/html" "$REG/wordpress:cli-php8.3" sh -c \
  'mkdir -p /var/www/html/wp-content/uploads/kampong && chown "$KF_MEDIA_OWNER" /var/www/html/wp-content/uploads/kampong && chmod 755 /var/www/html/wp-content/uploads/kampong'
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")
python3 - "$SITE/meta.json" "$PLAN" "$COMPANY" "$DOMAIN" "$SLUG" "$PORT" "$CODE" <<'PYJSON'
import json, sys
from datetime import datetime
path, plan, company, domain, slug, port, code = sys.argv[1:]
with open(path, 'w') as f:
    json.dump(dict(plan=plan, company=company, domain=domain, slug=slug, port=int(port),
                   created=datetime.now().strftime('%Y-%m-%d %H:%M'), http=int(code)), f, ensure_ascii=False)
PYJSON
cat > "$SITE/handover.md" <<EOF
# 服务交接单

**客户**：$COMPANY
**域名**：$DOMAIN
**开通时间**：$(date '+%Y-%m-%d %H:%M')
**套餐**：$PLAN  $PRICE

## 网站
- 网址：http://127.0.0.1:$PORT/（正式域名待解析）
- 后台：http://127.0.0.1:$PORT/wp-admin
- 账号：admin
- 密码：$ADMINPW

## 数据库
- 库名：wordpress　用户：wpuser
- 密码：由服务方保管，不随本单分发
- 访问：仅容器内网 db:3306

## 端口
- 主机映射：127.0.0.1:$PORT（尚未绑定公网）
- 站点目录：$SITE

## 待办
- [ ] DNS A 记录指向服务器
- [ ] 申请 SSL 证书
- [ ] 创建企业邮箱
- [ ] 备份策略
EOF
chmod 600 "$SITE/handover.md"
START=$(date '+%Y-%m-%d')
EXP=$(date -d "+1 year" '+%Y-%m-%d')
python3 - "$SITE/billing.json" "$PLAN_ID" "$PLAN" "$START" "$EXP" <<'PYJSON'
import json, sys
path, plan_id, plan, started, expires = sys.argv[1:]
with open(path, 'w') as f:
    json.dump(dict(plan_id=plan_id, plan=plan, started=started, expires=expires, status='active'), f, ensure_ascii=False)
PYJSON
echo "OK|$SLUG|http://127.0.0.1:$PORT|$CODE|$SITE/handover.md"
