#!/usr/bin/env python3
"""kf-update.py — 镜像更新检查与重建。

用法:
  kf-update.py --check    拉取镜像，比对 digest，写报告
  kf-update.py --apply    对使用旧镜像的站点重建容器，并验证
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SAFE_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,19}$")

BASE = Path(os.environ.get("KF_BASE", "/mnt/data1/kampongflow"))
SITES = BASE / "sites"
REPORT = BASE / "console" / "updates.json"

IMAGES = [
    "docker.m.daocloud.io/library/wordpress:php8.3-apache",
    "docker.m.daocloud.io/library/mariadb:11.4",
    "docker.m.daocloud.io/library/wordpress:cli-php8.3",
]


def sh(args, timeout=600, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def image_id(ref):
    rc, out, _ = sh(["docker", "image", "inspect", "--format", "{{.Id}}", ref])
    return out if rc == 0 else ""


def container_image_id(name):
    rc, out, _ = sh(["docker", "inspect", "--format", "{{.Image}}", name])
    return out if rc == 0 else ""


def sites_on_images():
    """返回 [{slug, dir, containers:[{name, image}]}]"""
    out = []
    if not SITES.exists():
        return out
    for d in sorted(SITES.iterdir()):
        if not (d / "docker-compose.yml").exists():
            continue
        rc, txt, _ = sh(["docker", "ps", "-a", "--filter", f"name=kf-{d.name}-",
                         "--format", "{{.Names}}"])
        if rc != 0 or not txt:
            continue
        out.append({"slug": d.name, "dir": str(d), "containers": txt.splitlines()})
    return out


def check():
    report = {"checked_at": time.strftime("%Y-%m-%d %H:%M"), "images": [],
              "sites": [], "outdated": 0}
    for ref in IMAGES:
        before = image_id(ref)
        rc, out, err = sh(["docker", "pull", "-q", ref], timeout=900)
        after = image_id(ref)
        changed = bool(before and after and before != after)
        report["images"].append({
            "ref": ref, "before": before[:19], "after": after[:19],
            "changed": changed, "ok": rc == 0,
            "message": (out or err)[-160:],
        })

    for s in sites_on_images():
        rows = []
        stale = False
        for cname in s["containers"]:
            cur = container_image_id(cname)
            rc, out, _ = sh(["docker", "inspect", "--format",
                             "{{.Config.Image}}", cname])
            ref = out.strip()
            latest = image_id(ref) if ref else ""
            out_of_date = bool(cur and latest and cur != latest)
            stale = stale or out_of_date
            rows.append({"name": cname, "image": ref, "current": cur[:19],
                         "latest": latest[:19], "outdated": out_of_date})
        if stale:
            report["outdated"] += 1
        report["sites"].append({"slug": s["slug"], "containers": rows, "stale": stale})

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "outdated": report["outdated"],
                      "checked_at": report["checked_at"]}, ensure_ascii=False))


def apply():
    rep = json.loads(REPORT.read_text()) if REPORT.exists() else {"sites": []}
    targets = [s["slug"] for s in rep.get("sites", []) if s.get("stale")]
    if not targets:
        print(json.dumps({"ok": True, "rebuilt": [], "message": "没有需要更新的站点"}))
        return

    results = []
    for slug in targets:
        # slug 来自 updates.json，白名单化以防 cwd 逃出 SITES
        if not SAFE_SLUG.match(str(slug or "")):
            print(f"{slug}: 非法 slug，跳过", file=sys.stderr)
            continue
        d = SITES / slug
        rc, out, err = sh(["docker", "compose", "up", "-d", "--force-recreate",
                           "--quiet-pull"], timeout=900, cwd=str(d))
        ok = rc == 0
        meta = {}
        try:
            meta = json.loads((d / "meta.json").read_text())
        except Exception:
            pass
        try:
            port = int(meta.get("port") or 0)
        except Exception:
            port = 0
        # 只允许回环上的站点端口段，防止被改写成任意本地端口做探测
        if not (18000 <= port <= 18999):
            port = 0
        code = 0
        if ok and port:
            for _ in range(20):
                time.sleep(2)
                r2, out2, _ = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                  f"http://127.0.0.1:{port}/"], timeout=20)
                code = int(out2 or 0)
                if code == 200:
                    break
        results.append({"slug": slug, "ok": ok, "http": code,
                        "message": (err or out)[-200:]})
        print(f"{slug}: rebuild {'ok' if ok else 'fail'} http={code}", file=sys.stderr)

    rep["applied_at"] = time.strftime("%Y-%m-%d %H:%M")
    rep["apply_results"] = results
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": all(r["ok"] and r["http"] == 200 for r in results),
                      "rebuilt": [r["slug"] for r in results], "results": results},
                     ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        apply()
    else:
        check()
