#!/usr/bin/env bash
# 生成后台用的自签证书（含 IP 与常用域名 SAN）
#
# 用法: tools/kf_tls.sh [域名 ...]
# 说明：没有可解析的域名时无法签发可信证书，这里用自签证书加密链路，
#       客户端首次访问需手动信任一次。
set -euo pipefail

BASE="${KF_BASE:-/mnt/data1/kampongflow}"
TLS="$BASE/console/tls"
CERT="$TLS/cert.pem"
KEY="$TLS/key.pem"
DAYS="${KF_TLS_DAYS:-825}"
PRIMARY="${KF_TLS_CNAME:-kampongflow.local}"

mkdir -p "$TLS"
chmod 700 "$TLS"

# 收集 SAN：命令行域名 + 本机所有 IP
DOMAINS=("$PRIMARY")
while [ $# -gt 0 ]; do DOMAINS+=("$1"); shift; done

IPS=$(
  {
    ip -4 addr show 2>/dev/null | awk '/inet /{split($2,a,"/");print a[1]}'
    hostname -I 2>/dev/null | tr " " "\n"
  } | grep -E "^[0-9]+\." | sort -u
)

SAN=""
for d in "${DOMAINS[@]}"; do
  [ -n "$d" ] && SAN+="DNS:$d,"
done
for i in $IPS; do
  SAN+="IP:$i,"
done
SAN="${SAN%,}"

echo "签发证书，SAN: $SAN"
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$KEY" -out "$CERT" \
  -days "$DAYS" -sha256 \
  -subj "/C=SG/O=KampongFlow/CN=$PRIMARY" \
  -addext "subjectAltName=$SAN" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null

chmod 600 "$KEY"
chmod 644 "$CERT"

echo "证书已生成："
openssl x509 -in "$CERT" -noout -subject -dates | sed 's/^/  /'
echo "  SAN: $SAN"
echo
echo "把证书导入手机信任链："
echo "  证书 $CERT"
