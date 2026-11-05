#!/usr/bin/env python3
"""kf_dns.py — 租户 DNS 托管：区数据 + 权威解析。

存储：/mnt/data1/kampongflow/dns/zones.json
服务：UDP/TCP 5353（演示端口；生产换 53，或替换为 PowerDNS/Knot 后端）

注意：这是为了让功能端到端可验证的**演示实现**。生产环境应把解析交给
PowerDNS / Knot / BIND，本文件只需替换成「写库 + reload」。
"""
import argparse
import copy
import fcntl
from kf_ai import atomic_json,read_json
import json
import os
import socket
import threading
import time
from pathlib import Path

import dns.flags
import dns.message
import dns.name
import dns.rcode
import dns.rdatatype
import dns.rrset

BASE = Path(os.environ.get("KF_BASE", "/mnt/data1/kampongflow"))
ZONES_F = BASE / "dns" / "zones.json"
NS1 = "ns1.kampongflow.sg"
NS2 = "ns2.kampongflow.sg"
SERIAL = 2026110201

_cache = {"mtime": 0, "data": {}}
_lock = threading.Lock()
_write_lock=threading.RLock()


def load_zones():
    try:
        m = ZONES_F.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if m != _cache["mtime"]:
            try:
                _cache["data"] = json.loads(ZONES_F.read_text())
            except Exception:
                _cache["data"] = {}
            _cache["mtime"] = m
        return copy.deepcopy(_cache["data"])


def save_zones(data):
    atomic_json(ZONES_F,data)
    with _lock:_cache['mtime']=0


def update_zones(change):
    ZONES_F.parent.mkdir(parents=True,exist_ok=True)
    with _write_lock,(ZONES_F.parent/'.write.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            data=read_json(ZONES_F,{})
            result=change(data)
            save_zones(data)
            return result
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def new_zone(domain, ip):
    return {
        "domain": domain,
        "records": [
            {"name": "@", "type": "SOA", "ttl": 3600,
             "value": "%s hostmaster.%s %d 7200 3600 1209600 3600" % (NS1, domain, SERIAL)},
            {"name": "@", "type": "NS", "ttl": 3600, "value": NS1},
            {"name": "@", "type": "NS", "ttl": 3600, "value": NS2},
            {"name": "@", "type": "A", "ttl": 300, "value": ip},
            {"name": "www", "type": "CNAME", "ttl": 300, "value": "@"},
        ],
    }


def absolute(name, domain):
    if name in ("@", ""):
        return domain + "."
    if name.endswith("."):
        return name
    return "%s.%s." % (name, domain)


NAME_TYPES = ("CNAME", "NS", "PTR", "SRV")


def normalize_value(rtype, value, domain):
    """把目标补成绝对名：@ → 本域，单标签 → 本域内，带点 → 视为外部域名。"""
    v = str(value).strip()
    if rtype == "SOA":
        parts = v.split()
        if len(parts) == 7:
            parts[0] = normalize_value("NS", parts[0], domain)
            parts[1] = normalize_value("NS", parts[1], domain)
            return " ".join(parts)
        return v
    if rtype == "MX":
        parts = v.split(None, 1)
        if len(parts) == 2:
            return "%s %s" % (parts[0], normalize_value("NS", parts[1], domain))
        return v
    if rtype in NAME_TYPES:
        if v in ("@", ""):
            return domain + "."
        if v.endswith("."):
            return v
        if "." in v:
            return v + "."
        return absolute(v, domain)
    return v


def find_zone(qname):
    """最长后缀匹配。"""
    zones = load_zones()
    best = None
    for slug, z in zones.items():
        dom = z["domain"].lower().rstrip(".")
        if qname == dom + "." or qname.endswith("." + dom + "."):
            if best is None or len(dom) > len(best[1]["domain"]):
                best = (slug, z)
    return best


def answer(query):
    resp = dns.message.make_response(query)
    resp.flags |= dns.flags.AA
    if not query.question:
        resp.set_rcode(dns.rcode.FORMERR)
        return resp

    q = query.question[0]
    qname = q.name.to_text().lower()
    qtype = dns.rdatatype.to_text(q.rdtype)

    hit = find_zone(qname)
    if not hit:
        resp.set_rcode(dns.rcode.REFUSED)
        return resp

    slug, zone = hit
    domain = zone["domain"]
    labels = []
    if qname != domain + ".":
        labels = qname[: -len(domain) - 1].rstrip(".").split(".")

    matched = []
    for r in zone["records"]:
        if absolute(r["name"], domain).lower() != qname:
            continue
        # 不响应 ANY 查询：否则一次请求可拉走全部记录，成为 UDP 反射放大器
        if r["type"] == qtype:
            matched.append(r)

    # CNAME 跟随（只跟一层，够用）
    if not matched and qtype not in ("CNAME", "SOA", "NS"):
        for r in zone["records"]:
            if r["type"] == "CNAME" and absolute(r["name"], domain).lower() == qname:
                matched.append(r)

    if not matched:
        if qname == domain + "." and qtype == "SOA":
            matched = [r for r in zone["records"] if r["type"] == "SOA"]
        else:
            exists = any(absolute(r["name"], domain).lower() == qname for r in zone["records"])
            resp.set_rcode(dns.rcode.NOERROR if exists else dns.rcode.NXDOMAIN)
            return resp

    # CNAME 命中时，把目标地址一并带回，解析器少跑一轮
    extra = []
    for r in list(matched):
        if r["type"] == "CNAME":
            target = normalize_value("CNAME", r["value"], domain).lower()
            for r2 in zone["records"]:
                if r2["type"] in ("A", "AAAA") and absolute(r2["name"], domain).lower() == target:
                    extra.append(r2)
    matched = matched + extra

    for r in matched:
        rdtype = dns.rdatatype.from_text(r["type"])
        try:
            value=normalize_value(r["type"],r["value"],domain)
            if r['type']=='TXT' and not (value.startswith('"') and value.endswith('"')):
                raw=value.encode('utf-8');chunks=[raw[i:i+255] for i in range(0,len(raw),255)] or [b'']
                wire=b''.join(bytes([len(chunk)])+chunk for chunk in chunks)
                data=dns.rdata.from_wire(1,16,wire,0,len(wire))
                rr=dns.rrset.from_rdata(absolute(r['name'],domain),r['ttl'],data)
            else:
                rr = dns.rrset.from_text(absolute(r["name"], domain), r["ttl"], "IN", r["type"],value)
        except Exception as e:
            import traceback
            traceback.print_exc()
            continue
        resp.answer.append(rr)
    return resp


def serve_udp(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    print("DNS UDP on %d" % port, flush=True)
    while True:
        try:
            data, addr = s.recvfrom(4096)
            q = dns.message.from_wire(data)
            s.sendto(answer(q).to_wire(), addr)
        except Exception as e:
            import traceback
            traceback.print_exc()
            continue


MAX_DNS_MSG = 65535        # DNS over TCP 消息长度上限


def serve_tcp(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(16)
    print("DNS TCP on %d" % port, flush=True)
    while True:
        conn, _ = s.accept()
        try:
            # 超时：防止慢速连接占住服务（单线程串行处理，一个慢连接会拖住全部）
            conn.settimeout(10)
            ln = conn.recv(2)
            if len(ln) < 2:
                conn.close()
                continue
            need = int.from_bytes(ln, "big")
            if need > MAX_DNS_MSG:
                conn.close()      # 声明长度超限，直接拒绝
                continue
            buf = b""
            while len(buf) < need:
                chunk = conn.recv(need - len(buf))
                if not chunk:
                    break
                buf += chunk
            if len(buf) < need:
                conn.close()      # 没发完就断开
                continue
            q = dns.message.from_wire(buf)
            out = answer(q).to_wire()
            conn.sendall(len(out).to_bytes(2, "big") + out)
        except Exception as e:
            import traceback
            traceback.print_exc()
        finally:
            conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5353)
    a = ap.parse_args()
    threading.Thread(target=serve_tcp, args=(a.port,), daemon=True).start()
    serve_udp(a.port)
