#!/usr/bin/env python3
"""kf-notify.py — 每日运营摘要邮件。

内容：域名/服务到期、余额偏低、最近 24 小时新线索。
用法：kf-notify.py [--dry-run]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(os.environ.get("KF_BASE", "/mnt/data1/kampongflow"))
SITES = BASE / "sites"
CONSOLE = BASE / "console"
SETTINGS = CONSOLE / "settings.json"
LOG = CONSOLE / "notify.log"
WPCLI = "docker.m.daocloud.io/library/wordpress:cli-php8.3"
TZ = timezone(timedelta(hours=8))

LEADS_PHP = (
    '<?php $o=[]; $since=date("Y-m-d H:i:s", time()-86400);'
    'foreach(get_posts(["post_type"=>"kf_lead","numberposts"=>50,'
    '"post_status"=>"any","date_query"=>[["after"=>$since]]]) as $p){'
    ' $o[]=["title"=>$p->post_title,"date"=>$p->post_date,"msg"=>$p->post_content]; }'
    ' echo json_encode($o, JSON_UNESCAPED_UNICODE);'
)


def read_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def days_until(s):
    try:
        return (datetime.strptime(s, "%Y-%m-%d").date() - date.today()).days
    except Exception:
        return None


def site_rows():
    rows = []
    if not SITES.exists():
        return rows
    for d in sorted(SITES.iterdir()):
        if not (d / "meta.json").exists():
            continue
        meta = read_json(d / "meta.json", {})
        bill = read_json(d / "billing.json", {})
        dom = bill.get("domain") or {}
        rows.append({
            "slug": d.name,
            "company": meta.get("company", d.name),
            "domain": meta.get("domain", ""),
            "domain_days": days_until(dom.get("expires", "")),
            "domain_auto": dom.get("auto_renew", True),
            "service_days": days_until(bill.get("expires", "")),
            "status": bill.get("status", ""),
        })
    return rows


def ledger_balance(slug):
    bal = 0.0
    for x in read_json(CONSOLE / "ledger.json", []):
        if x.get("slug") != slug:
            continue
        amt = float(x.get("amount") or 0)
        bal += amt if x.get("type") == "topup" else -amt
    return round(bal, 2)


def recent_leads(slug, d):
    tmp = d / "_notify_leads.php"
    try:
        tmp.write_text(LEADS_PHP)
        r = subprocess.run(
            ["docker", "run", "--rm", "--env-file", str(d / "wp.env"),
             "--network", "kf-%s_default" % slug,
             "-v", "%s/html:/var/www/html" % d,
             "-v", "%s:/tmp/leads.php:ro" % tmp,
             "--user", "33:33", WPCLI, "wp", "eval-file", "/tmp/leads.php"],
            capture_output=True, text=True, timeout=120)
        out = (r.stdout or "").strip()
        return json.loads(out) if out.startswith("[") else []
    except Exception:
        return []
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def build_digest(with_leads=True):
    rows = site_rows()
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    lines = ["KampongFlow 每日摘要 %s" % today, ""]

    exp_dom = [r for r in rows if r["domain_days"] is not None and r["domain_days"] <= 60]
    exp_svc = [r for r in rows if r["service_days"] is not None and r["service_days"] <= 60]
    low = [r for r in rows if ledger_balance(r["slug"]) < 500]

    lines.append("== 域名 60 天内到期（%d）==" % len(exp_dom))
    if exp_dom:
        for r in sorted(exp_dom, key=lambda x: x["domain_days"]):
            flag = "" if r["domain_auto"] else "  [未开自动续费]"
            lines.append("  %-22s %-26s %s 天%s" % (r["company"][:20], r["domain"],
                                                   r["domain_days"], flag))
    else:
        lines.append("  无")

    lines.append("")
    lines.append("== 服务 60 天内到期（%d）==" % len(exp_svc))
    if exp_svc:
        for r in sorted(exp_svc, key=lambda x: x["service_days"]):
            lines.append("  %-22s %s 天" % (r["company"][:20], r["service_days"]))
    else:
        lines.append("  无")

    lines.append("")
    lines.append("== 预付款余额低于 500（%d）==" % len(low))
    if low:
        for r in low:
            lines.append("  %-22s S$ %s" % (r["company"][:20], ledger_balance(r["slug"])))
    else:
        lines.append("  无")

    if with_leads:
        lines.append("")
        leads_total = 0
        body = []
        for d in sorted(SITES.iterdir()) if SITES.exists() else []:
            if not (d / "meta.json").exists():
                continue
            ls = recent_leads(d.name, d)
            if not ls:
                continue
            leads_total += len(ls)
            meta = read_json(d / "meta.json", {})
            for x in ls:
                body.append("  [%s] %s — %s" % (meta.get("company", d.name)[:18],
                                                x.get("title", "")[:40],
                                                (x.get("msg") or "")[:60].replace("\n", " ")))
        lines.append("== 最近 24 小时新线索（%d）==" % leads_total)
        lines.extend(body or ["  无"])

    lines.append("")
    lines.append("后台：http://127.0.0.1:18090")
    return "\n".join(lines)


def send(to, subject, body, smtp):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
    from kf_mail import send as send_once
    return send_once(to, subject, body, smtp)


def log(msg):
    try:
        with LOG.open("a") as f:
            f.write("%s %s\n" % (datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    settings = read_json(SETTINGS, {})
    smtp = dict(settings.get("smtp") or {})
    smtp.update(read_json(CONSOLE / "secrets.json", {}))
    for key in ("api_key", "pass", "user"):
        value = os.environ.get("KF_SMTP_" + key.upper())
        if value:
            smtp[key] = value
    to = (smtp.get("notify_to") or settings.get("support_email")
          or smtp.get("from") or "")
    body = build_digest(with_leads=True)

    if a.dry_run:
        print(body)
        return

    configured = bool((smtp.get("host") or "").strip() or (smtp.get("api_key") or "").strip())
    if not to or not configured:
        log("skip: SMTP 未配置或无收件地址")
        print("SMTP 未配置或无收件地址，跳过（摘要已生成但未发送）")
        return
    try:
        send(to, "KampongFlow 每日摘要 %s" % datetime.now(TZ).strftime("%Y-%m-%d"), body, smtp)
        log("sent -> %s" % to)
        print("已发送到 %s" % to)
    except Exception as e:
        log("failed: %s" % e)
        print("发送失败：%s" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
