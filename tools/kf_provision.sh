#!/usr/bin/env bash
# kf-provision.sh <公司名> <域名> <slug> <端口>
set -euo pipefail
COMPANY="${1:?公司名}"; DOMAIN="${2:?域名}"; SLUG="${3:?slug}"; PORT="${4:?端口}"
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
docker compose up -d --quiet-pull >/dev/null 2>&1
for i in $(seq 1 40); do
  docker exec "${PROJ}-db-1" mariadb -uroot -p"$ROOTPASS" -e 'SELECT 1' >/dev/null 2>&1 && break
  sleep 2
done
cat > "$SITE/wp.env" <<ENV
WORDPRESS_DB_HOST=db:3306
WORDPRESS_DB_USER=wpuser
WORDPRESS_DB_PASSWORD=$DBPASS
WORDPRESS_DB_NAME=wordpress
ENV
chmod 600 "$SITE/wp.env"
W() { docker run --rm --env-file "$SITE/wp.env" --network "${PROJ}_default" -v "$SITE/html:/var/www/html" --user 33:33 "$REG/wordpress:cli-php8.3" wp "$@"; }
W core install --url="http://127.0.0.1:$PORT" --title="$COMPANY" --admin_user="admin" --admin_password="$ADMINPW" --admin_email="admin@$DOMAIN" --skip-email >/dev/null
W option update timezone_string "Asia/Singapore" >/dev/null
W option update blogdescription "Website, email and hosting package" >/dev/null
W rewrite structure '/%postname%/' --hard >/dev/null
if [ -n "$INDUSTRY" ]; then
  PY=$(command -v python3)
  "$PY" "$BASE/core/kf_template.py" --site "$SITE" --industry "$INDUSTRY" \
    --company "$COMPANY" --domain "$DOMAIN" >/dev/null 2>&1 || echo "warn: 模板应用失败" >&2
fi
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")
printf '{"plan":"%s","company":"%s","domain":"%s","slug":"%s","port":%s,"created":"%s","http":%s}\n' \
  "$PLAN" "$COMPANY" "$DOMAIN" "$SLUG" "$PORT" "$(date '+%Y-%m-%d %H:%M')" "$CODE" > "$SITE/meta.json"
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
printf '{"plan_id":"%s","plan":"%s","started":"%s","expires":"%s","status":"active"}\n' \
  "$PLAN_ID" "$PLAN" "$START" "$EXP" > "$SITE/billing.json"
echo "OK|$SLUG|http://127.0.0.1:$PORT|$CODE|$SITE/handover.md"
