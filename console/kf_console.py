#!/usr/bin/env python3
"""KampongFlow 管理后台 v2 — 站点 / 套餐 / 账单 / PDF 导出。

单文件，依赖：reportlab（用于中文 PDF）。
"""
import base64
import sys
import time
import importlib.util
import html as _htmlesc
import csv
import io
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

BASE    = Path(os.environ.get("KF_BASE", "/mnt/data1/kampongflow"))
SITES   = BASE / "sites"
PROV    = BASE / "kf-provision.sh"
CONSOLE = BASE / "console"
PORT    = int(os.environ.get("KF_PORT", "18090"))
HTTPS_PORT = int(os.environ.get("KF_HTTPS_PORT", "18443"))
USER    = os.environ.get("KF_USER", "admin")
PASS    = (CONSOLE / "admin.pass").read_text().strip()

PLANS_F    = CONSOLE / "plans.json"
INVOICES_F = CONSOLE / "invoices.json"
SETTINGS_F = CONSOLE / "settings.json"
PRESETS_F  = BASE / "design-presets.json"
SHARES_F   = CONSOLE / "shares.json"
PORTAL_F   = CONSOLE / "portal.json"
USERS_F    = CONSOLE / "users.json"
AUDIT_F    = CONSOLE / "audit.log"
CLIENTS_F  = CONSOLE / "clients.json"
LEDGER_F   = CONSOLE / "ledger.json"


def load_users():
    return _read(USERS_F, {})


def ensure_admin():
    """首次运行：把原 admin.pass 迁移成 users.json 里的 admin 账号。"""
    if USERS_F.exists():
        return
    import secrets as _s
    try:
        pw = (CONSOLE / "admin.pass").read_text().strip()
    except OSError:
        pw = "changeme"
    salt = _s.token_hex(8)
    _write(USERS_F, {"admin": {"name": "管理员", "role": "admin", "salt": salt,
                               "hash": pin_hash(pw, salt), "active": True,
                               "created": datetime.now(SGT).strftime("%Y-%m-%d")}})


def _totp(secret, counter, digits=6):
    import hmac, hashlib, struct, base64
    pad = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret.upper() + pad)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    code = (struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return "%0*d" % (digits, code)


def totp_verify(secret, code, window=1):
    import time
    if not secret or not code:
        return False
    code = str(code).strip().replace(" ", "")
    now = int(time.time() // 30)
    for i in range(-window, window + 1):
        if _totp(secret, now + i) == code:
            return True
    return False


def gen_recovery(n=10):
    import secrets as _s
    return ["%s-%s" % (_s.token_hex(2), _s.token_hex(2)) for _ in range(n)]


def hash_recovery(codes, salt):
    return [pin_hash(c.replace("-", "").lower(), salt + ":rec") for c in codes]


def match_recovery(user_entry, code):
    import hmac as _h
    salt = user_entry.get("salt", "") + ":rec"
    want = pin_hash(str(code).replace("-", "").lower(), salt)
    for i, h in enumerate(user_entry.get("recovery") or []):
        if _h.compare_digest(h, want):
            return i
    return -1


def totp_new_secret():
    import base64, secrets as _s
    return base64.b32encode(_s.token_bytes(20)).decode().rstrip("=")


ROLES_F = CONSOLE / "roles.json"

DEFAULT_ROLES = {
    "admin": {"label": "管理员", "write": None},
    "ops": {"label": "运营", "write": [
        "/api/spec", "/api/design", "/api/media/", "/api/dns/", "/api/domain/manage",
        "/api/clients/save", "/api/shares", "/api/publish", "/api/create", "/api/suspend",
        "/api/mfa", "/api/invoice/issue", "/api/ledger",
    ]},
    "finance": {"label": "财务", "write": [
        "/api/ledger", "/api/invoice", "/api/renew", "/api/clients/save",
        "/api/domain/manage", "/api/mfa",
    ]},
}


def roles():
    saved = _read(ROLES_F, {})
    out = json.loads(json.dumps(DEFAULT_ROLES))
    for k, v in (saved or {}).items():
        if k in out and isinstance(v, dict):
            if "write" in v:
                out[k]["write"] = v["write"]
            if "label" in v:
                out[k]["label"] = str(v["label"])[:20]
    return out


SELF_SERVICE = ("/api/password", "/api/mfa")   # 任何登录者都能操作自己

# 统一安全响应头：防点击劫持、MIME 嗅探、Referrer 外泄
SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy":
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'self'",
}


def can_write(role, path):
    if any(path.startswith(p) for p in SELF_SERVICE):
        return True
    r = roles().get(role)
    if not r:
        return False
    allowed = r.get("write")
    if allowed is None:
        return True
    return any(path == a or path.startswith(a) for a in allowed)


FAILS = {}
FAILS_F = CONSOLE / "loginfail.json"
FAIL_LIMIT = 5
FAIL_WINDOW = 15 * 60      # 15 分钟内
LOCK_SECONDS = 15 * 60     # 锁 15 分钟


def load_fails():
    try:
        data = json.loads(FAILS_F.read_text())
    except Exception:
        return
    now = time.time()
    for k, v in (data or {}).items():
        if isinstance(v, dict) and v.get("last", 0) > now - FAIL_WINDOW:
            FAILS[k] = v


def save_fails():
    try:
        tmp = FAILS_F.with_suffix(".tmp")
        tmp.write_text(json.dumps(FAILS))
        tmp.replace(FAILS_F)
    except Exception:
        pass


IP_FAILS = {}
IP_LIMIT = 20          # 同一 IP 15 分钟内失败 20 次就拦
IP_F = CONSOLE / "ipfail.json"


def ip_key(ip):
    return str(ip or "")


def load_ipfails():
    try:
        data = json.loads(IP_F.read_text())
    except Exception:
        return
    now = time.time()
    for k, v in (data or {}).items():
        if isinstance(v, dict) and v.get("last", 0) > now - FAIL_WINDOW:
            IP_FAILS[k] = v


def save_ipfails():
    try:
        tmp = IP_F.with_suffix(".tmp")
        tmp.write_text(json.dumps(IP_FAILS))
        tmp.replace(IP_F)
    except Exception:
        pass


LOOPBACK = ("127.0.0.1", "::1", "localhost", "")


def ip_blocked(ip):
    if str(ip) in LOOPBACK:
        return 0
    f = IP_FAILS.get(ip_key(ip))
    if not f:
        return 0
    return max(0, int(f.get("until", 0) - time.time()))


def note_ip_fail(ip):
    if str(ip) in LOOPBACK:
        return
    k = ip_key(ip)
    now = time.time()
    f = IP_FAILS.get(k) or {"count": 0, "last": 0, "until": 0}
    if now - f.get("last", 0) > FAIL_WINDOW:
        f["count"] = 0
    f["count"] = f.get("count", 0) + 1
    f["last"] = now
    if f["count"] >= IP_LIMIT:
        f["until"] = now + LOCK_SECONDS
    IP_FAILS[k] = f
    save_ipfails()


WEAK = {"password", "12345678", "123456789", "1234567890", "qwertyuiop",
        "admin123", "kampongflow", "letmein123", "welcome123", "abc123456"}


def password_problem(user, pw):
    """返回不通过的原因，None 表示合格。"""
    pw = pw or ""
    if len(pw) < 10:
        return "密码至少 10 位"
    if len(pw) > 128:
        return "密码太长"
    base = "".join(ch for ch in pw.lower() if ch.isalnum())
    if pw.lower() in WEAK or base in WEAK or any(
            base.startswith(w) and len(base) <= len(w) + 4 for w in list(WEAK)[:6]):
        return "这是常见弱密码"
    if user and len(pw) < 16 and user.lower() in pw.lower():
        return "密码不能包含用户名（或改用 16 位以上）"
    classes = sum([
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ])
    if classes < 3:
        return "密码需包含大写、小写、数字、符号中的至少三类"
    return None


def locked_for(user):
    """返回还需等待的秒数，0 表示未锁。"""
    f = FAILS.get((user or "").lower())
    if not f:
        return 0
    until = f.get("until", 0)
    return max(0, int(until - time.time()))


def note_fail(user):
    k = (user or "").lower()
    now = time.time()
    f = FAILS.get(k) or {"count": 0, "last": 0, "until": 0}
    if now - f.get("last", 0) > FAIL_WINDOW:
        f["count"] = 0
    f["count"] = f.get("count", 0) + 1
    f["last"] = now
    if f["count"] >= FAIL_LIMIT:
        f["until"] = now + LOCK_SECONDS
        f["count"] = 0
    FAILS[k] = f
    save_fails()
    return LOCK_SECONDS if f.get("until", 0) > now else 0


def clear_fails(user):
    if FAILS.pop((user or "").lower(), None) is not None:
        save_fails()


SESSIONS = {}
SESSIONS_F = CONSOLE / "sessions.json"
PENDING_MFA = {}


def load_sessions():
    """从磁盘恢复会话，重启服务不再踢掉所有人。"""
    try:
        data = json.loads(SESSIONS_F.read_text())
    except Exception:
        return
    now = time.time()
    for sid, s in (data or {}).items():
        if isinstance(s, dict) and s.get("exp", 0) > now:
            SESSIONS[sid] = s


def save_sessions():
    try:
        data = {k: v for k, v in SESSIONS.items() if v.get("exp", 0) > time.time()}
        tmp = SESSIONS_F.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(SESSIONS_F)
    except Exception:
        pass
SESSION_TTL = 12 * 3600


def new_session(user):
    import secrets as _s, hmac as _h, hashlib
    sid = _s.token_urlsafe(24)
    SESSIONS[sid] = {"user": user, "exp": time.time() + SESSION_TTL}
    save_sessions()
    sig = _h.new(portal_secret(), sid.encode(), hashlib.sha256).hexdigest()[:32]
    return "%s.%s" % (sid, sig)


def session_user(cookie_header):
    v = cookie_value(cookie_header, "kf_sid")
    if not v or "." not in v:
        return None
    sid, sig = v.rsplit(".", 1)
    import hmac as _h, hashlib
    want = _h.new(portal_secret(), sid.encode(), hashlib.sha256).hexdigest()[:32]
    if not _h.compare_digest(sig, want):
        return None
    s = SESSIONS.get(sid)
    if not s or s["exp"] < time.time():
        SESSIONS.pop(sid, None)
        return None
    s["exp"] = time.time() + SESSION_TTL      # 滑动续期
    return s["user"]


def check_login(user, pw):
    u = load_users().get(user)
    if not u or not u.get("active"):
        return False
    import hmac as _h
    return _h.compare_digest(pin_hash(pw, u.get("salt", "")), u.get("hash", ""))


def diff_summary(before, after, keys=None):
    """把前后差异压成一行，供审计使用。"""
    try:
        b = before or {}
        a = after or {}
        out = []
        for k in (keys or set(list(b.keys()) + list(a.keys()))):
            if isinstance(k, str) and k.startswith("_"):
                continue
            vb, va = b.get(k), a.get(k)
            if vb == va:
                continue
            out.append("%s: %s → %s" % (k, str(vb)[:40], str(va)[:40]))
            if len(out) >= 6:
                out.append("…")
                break
        return "；".join(out)
    except Exception:
        return ""


def audit(user, action, target="", detail=""):
    rec = {"ts": datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S"),
           "user": user or "-", "action": action, "target": target or "",
           "detail": str(detail)[:200]}
    try:
        if AUDIT_F.exists() and AUDIT_F.stat().st_size > 4 * 1024 * 1024:
            AUDIT_F.replace(AUDIT_F.with_suffix(".log.1"))
        with AUDIT_F.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_audit(limit=200, user=None, action=None, since=None, until=None):
    if not AUDIT_F.exists():
        return []
    rows = []
    for line in AUDIT_F.read_text(errors="replace").splitlines()[-5000:]:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if user and r.get("user") != user:
            continue
        if action and action.lower() not in (r.get("action", "") + " " +
                                             r.get("target", "") + " " +
                                             r.get("detail", "")).lower():
            continue
        ts = r.get("ts", "")
        if since and ts < since:
            continue
        if until and ts > until + " 23:59:59":
            continue
        rows.append(r)
    return rows[-limit:][::-1]
WPCLI_IMG  = "docker.m.daocloud.io/library/wordpress:cli-php8.3"

SGT = timezone(timedelta(hours=8))
_live = {}
_lock = threading.Lock()
_file_lock = threading.Lock()

SLUG_RE   = re.compile(r"^[a-z][a-z0-9-]{1,19}$")
MAX_DNS_RECORDS = 200      # 单个域名的记录数上限，防止被灌爆做反射放大
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# 优先嵌入系统 CJK 字体（自包含，任何阅读器都能显示）；没有则退回 CID 字体
FONT = "STSong-Light"
for _cand in ("/usr/share/fonts/google-droid/DroidSansFallback.ttf",):
    try:
        pdfmetrics.registerFont(TTFont("CJK", _cand))
        FONT = "CJK"
        break
    except Exception:
        continue

DEFAULT_PLANS = [
    {"id": "starter", "name": "Starter", "price": 1800, "period": "首年",
     "specs": "1 个站点 · 5 个邮箱 · 20GB · 2C/4G", "dns": True},
    {"id": "growth", "name": "Growth", "price": 2800, "period": "首年",
     "specs": "1 个站点 · 10 个邮箱 · 40GB · 4C/8G", "dns": True},
    {"id": "business", "name": "Business", "price": 4200, "period": "首年",
     "specs": "1 个站点 · 25 个邮箱 · 80GB · 8C/16G", "dns": True},
]
INDUSTRIES = {
    "littlegems": "My Little Gems（定制）",
    "preschool": "教育 / 幼儿园",
    "restaurant": "餐饮",
    "law": "律所",
    "trading": "贸易",
    "tech": "科技",
}

def _retry(fn, tries=3, delay=2.0, label=""):
    """网络抖动（DNS/连接）重试，最后一次失败才抛出。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(delay * (i + 1))
    raise RuntimeError("%s%s" % (label, last))


def send_mail(to, subject, body, smtp=None):
    """发信：优先走 HTTPS API（云主机普遍封 587/465），否则走 SMTP。"""
    import smtplib
    from email.message import EmailMessage
    s = smtp if smtp is not None else (settings().get("smtp") or {})
    provider = (s.get("provider") or "smtp").lower()

    if provider in ("resend", "sendgrid"):
        import urllib.request as _ur
        key = (s.get("api_key") or "").strip()
        frm = (s.get("from") or "").strip()
        if not key or not frm:
            raise RuntimeError("邮件 API 未配置")
        if provider == "resend":
            payload = {"from": frm, "to": [to], "subject": subject, "text": body}
            url, hdr = "https://api.resend.com/emails", {"Authorization": "Bearer " + key}
        else:
            payload = {"personalizations": [{"to": [{"email": to}]}],
                       "from": {"email": frm},
                       "subject": subject,
                       "content": [{"type": "text/plain", "value": body}]}
            url, hdr = "https://api.sendgrid.com/v3/mail/send", {"Authorization": "Bearer " + key}
        def _post():
            req = _ur.Request(url, data=json.dumps(payload).encode(),
                              headers={**hdr, "Content-Type": "application/json"}, method="POST")
            with _ur.urlopen(req, timeout=25) as r:
                if r.status >= 300:
                    raise RuntimeError("HTTP %d" % r.status)
            return True
        _retry(_post, label="邮件 API 失败：")
        return

    host = (s.get("host") or "").strip()
    frm = (s.get("from") or s.get("user") or "").strip()
    if not host or not frm:
        raise RuntimeError("SMTP 未配置")
    port = int(s.get("port") or 587)
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    def _smtp():
        if port == 465:
            srv = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            srv = smtplib.SMTP(host, port, timeout=20)
            if s.get("tls", True):
                srv.starttls()
        try:
            if s.get("user"):
                srv.login(s["user"], s.get("pass", ""))
            srv.send_message(msg)
        finally:
            try:
                srv.quit()
            except Exception:
                pass
        return True
    _retry(_smtp, label="SMTP 发送失败：")


DEFAULT_SETTINGS = {
    "company": "KampongFlow Pte Ltd",
    "currency": "SGD",
    "gst_enabled": False,
    "gst_rate": 0.09,
    "support_email": "support@kampongflow.sg",
    "smtp": {},
}


# ---------------------------------------------------------------- 数据读写
def _read(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


SENSITIVE_FILES = ("users.json", "sessions.json", "settings.json", "roles.json",
                   "loginfail.json", "ipfail.json")


def _write(path, data):
    """原子写入。敏感文件一律 600，只有属主可读写。"""
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    if p.name in SENSITIVE_FILES:
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
    tmp.replace(p)


def plans():
    if not PLANS_F.exists():
        _write(PLANS_F, DEFAULT_PLANS)
    return _read(PLANS_F, DEFAULT_PLANS)


def settings():
    if not SETTINGS_F.exists():
        _write(SETTINGS_F, DEFAULT_SETTINGS)
    s = dict(DEFAULT_SETTINGS)
    s.update(_read(SETTINGS_F, {}))
    return s


def invoices():
    return _read(INVOICES_F, [])


def next_invoice_no():
    year = datetime.now(SGT).year
    seq = 0
    for inv in invoices():
        m = re.match(rf"^KF-{year}-(\d+)$", inv.get("no", ""))
        if m:
            seq = max(seq, int(m.group(1)))
    return f"KF-{year}-{seq + 1:04d}"


_KS = None


def ks():
    global _KS
    if _KS is None:
        spec = importlib.util.spec_from_file_location("kf_sections_live", BASE / "core" / "kf_sections.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _KS = m
    return _KS


def design_vars(slug):
    d = _read(SITES / slug / "design.json", {})
    pal = d.get("palette") or {}
    shape = d.get("shape") or {}
    typ = d.get("type") or {}
    fonts = {
        "sans": '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,"PingFang SC",sans-serif',
        "serif": 'Georgia,"Times New Roman",Cambria,serif',
        "rounded": 'ui-rounded,"SF Pro Rounded",Quicksand,Arial,sans-serif',
        "mono": 'ui-monospace,Menlo,monospace',
    }
    def col(k, fb):
        v = pal.get(k)
        return v if isinstance(v, str) and re.match(r"^#[0-9a-fA-F]{3,8}$", v) else fb
    def ln(v, fb):
        return v if isinstance(v, str) and re.match(r"^\d{1,3}px$", v) else fb
    v = {
        "--kf-primary": col("primary", "#0f5132"),
        "--kf-primary-dark": col("primaryDark", "#0a3a24"),
        "--kf-accent": col("accent", "#d4a04a"),
        "--kf-bg": col("bg", "#f7f9f7"),
        "--kf-surface": col("surface", "#ffffff"),
        "--kf-ink": col("ink", "#16211c"),
        "--kf-muted": col("muted", "#5d6b64"),
        "--kf-deep": col("deep", "#10231a"),
        "--kf-radius": ln(shape.get("radius"), "16px"),
        "--kf-btn-radius": ln(shape.get("button"), "999px"),
        "--kf-pad": ln((d.get("layout") or {}).get("pad"), "76px"),
        "--kf-font-head": fonts.get(typ.get("heading"), fonts["sans"]),
        "--kf-font-body": fonts["sans"],
    }
    return ":root{" + "".join(f"{k}:{val};" for k, val in v.items()) + "}"


def preview_html(slug, page_slug, base=None, asset=None, public=False):
    draft = read_draft(slug)
    pages = draft.get("pages", [])
    if not pages:
        return "<p>没有页面</p>"
    page = next((p for p in pages if p["slug"] == page_slug), pages[0])
    meta = load_meta(slug)
    base = base or ("/preview/%s" % slug)
    asset = asset or ("/pa/%s" % slug)
    body = ks().render_sections(page.get("sections", []), site=str(SITES / slug))

    lis = []
    for p in pages:
        href = "%s/%s" % (base, p["slug"])
        cls = ' class="current-menu-item"' if p["slug"] == page["slug"] else ""
        lis.append('<li%s><a href="%s">%s</a></li>'
                   % (cls, href, esc(p.get("title", p["slug"]))))
    nav = "".join(lis)

    label = "客户预览" if public else "预览"
    note = "仅供审阅，尚未上线" if public else "未发布的草稿"
    extra = "" if public else '<a href="http://127.0.0.1:18085/" target="_blank">查看线上</a>'
    company = esc(meta.get("company", ""))
    title = "%s · %s · %s" % (label, esc(page.get("title", "")), company)

    return "".join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="robots" content="noindex">',
        "<title>%s</title>" % title,
        '<link rel="stylesheet" href="%s/style.css">' % asset,
        "<style>", design_vars(slug),
        ".kf-pvbar{position:sticky;top:0;z-index:99;background:#161b22;color:#e6edf3;",
        "font:13px/1.5 -apple-system,Segoe UI,sans-serif;padding:7px 14px;",
        "display:flex;gap:14px;align-items:center;flex-wrap:wrap}",
        ".kf-pvbar b{color:#d29922}.kf-pvbar a{color:#58a6ff;text-decoration:none}",
        "</style></head><body class=\"wp-theme-kampong\">",
        '<div class="kf-pvbar"><b>%s</b> %s · %s' % (label, note, company),
        '<a href="%s/" target="_self">首页</a>%s</div>' % (base, extra),
        '<header class="kf-header"><div class="kf-container kf-header-inner">',
        '<a class="kf-logo" href="%s/">%s</a>' % (base, company),
        '<nav class="kf-nav-wrap"><ul class="kf-nav">%s</ul></nav>' % nav,
        '</div></header>',
        '<main class="kf-main"><div class="kf-content">%s</div></main>' % body,
        '<footer class="kf-footer"><div class="kf-container"><div class="kf-bottom">',
        "<span>%s</span></div></div></footer></body></html>" % company,
    ])


_DNS = None


def dnsmod():
    global _DNS
    if _DNS is None:
        sp = importlib.util.spec_from_file_location("kf_dns_mod", BASE / "core" / "kf_dns.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _DNS = m
    return _DNS


DNS_PORT = int(os.environ.get("KF_DNS_PORT", "5354"))


def dns_query(name, rdtype):
    """直接问我们自己的解析器，返回 (rcode, 答案列表)。"""
    import dns.message
    import dns.query
    try:
        q = dns.message.make_query(name, rdtype, want_dnssec=False)
        r = dns.query.udp(q, "127.0.0.1", port=DNS_PORT, timeout=3)
        ans = []
        for rrset in r.answer:
            for rr in rrset:
                ans.append(rr.to_text())
        return int(r.rcode()), ans
    except Exception:
        return -1, []


def public_query(name, rdtype, server="8.8.8.8"):
    """问公网递归解析器，走 TCP（本机 UDP 53 被封）。"""
    import dns.message
    import dns.query
    try:
        q = dns.message.make_query(name, rdtype)
        r = dns.query.tcp(q, server, timeout=6)
        ans = [rr.to_text() for rrset in r.answer for rr in rrset]
        return int(r.rcode()), ans
    except Exception:
        return -1, []


def dns_delegation(slug):
    """检查公网是否已经委托给我们。"""
    m = dnsmod()
    z = m.load_zones().get(slug)
    if not z:
        return {"ok": False, "error": "未启用 DNS 托管", "checks": []}
    dom = z["domain"]
    want_ns = {m.NS1.lower(), m.NS2.lower()}
    checks = []

    rc, ns = public_query(dom, "NS")
    got = {x.rstrip(".").lower() for x in ns}
    if rc == 0 and got:
        hit = want_ns & got
        if hit == want_ns:
            status, detail = "ok", "已委托给我们：%s" % "、".join(sorted(hit))
        else:
            status = "warn"
            detail = "公网仍指向 %s" % "、".join(sorted(got)[:3])
            if len(got) > 3:
                detail += " 等 %d 条" % len(got)
    else:
        status, detail = "fail", "查不到公网 NS（域名可能未注册或解析超时）"
    checks.append({"name": "公网委托 NS", "status": status, "detail": detail})

    for host in (m.NS1, m.NS2):
        rc2, a2 = public_query(host, "A")
        checks.append({
            "name": "NS 主机名 %s" % host,
            "status": "ok" if a2 else "fail",
            "detail": "、".join(a2) if a2 else "公网解析不到，委托会失效（需要 glue 记录）",
        })

    rc3, a3 = public_query(dom, "A")
    our_ips = {r["value"] for r in z["records"] if r["type"] == "A" and r["name"] == "@"}
    if rc3 == 0 and a3:
        public_ips = set(a3)
        status = "ok" if (public_ips & our_ips) else "warn"
        checks.append({"name": "公网根域 A", "status": status,
                       "detail": "、".join(sorted(public_ips))})
    else:
        checks.append({"name": "公网根域 A", "status": "fail", "detail": "公网查不到 A 记录"})

    ok = all(c["status"] != "fail" for c in checks)
    return {"ok": ok, "domain": dom, "checks": checks}


def dns_check(slug):
    """对托管区做一轮基础健康检查。"""
    m = dnsmod()
    z = m.load_zones().get(slug)
    if not z:
        return {"ok": False, "error": "未启用 DNS 托管", "checks": []}
    dom = z["domain"]
    checks = []

    rc, ns = dns_query(dom, "NS")
    checks.append({
        "name": "NS 记录", "status": "ok" if len(ns) >= 2 else "fail",
        "detail": "%d 条：%s" % (len(ns), "、".join(n.rstrip(".") for n in ns)) if ns else "无",
    })

    rc, soa = dns_query(dom, "SOA")
    checks.append({"name": "SOA", "status": "ok" if (rc == 0 and soa) else "fail",
                   "detail": soa[0] if soa else "缺失或无法解析"})

    rc, a = dns_query(dom, "A")
    has_ip = any(x.split()[-1].count(".") == 3 for x in a)
    checks.append({"name": "根域 A 记录", "status": "ok" if has_ip else "fail",
                   "detail": "、".join(x.split()[-1] for x in a) if a else "缺失"})

    rc, www = dns_query("www." + dom, "A")
    checks.append({"name": "www 解析", "status": "ok" if www else "warn",
                   "detail": "、".join(www) if www else "未配置 www（可选）"})

    has_mx = any(r["type"] == "MX" for r in z["records"])
    rc, mx = dns_query(dom, "MX")
    checks.append({"name": "邮件 MX", "status": "ok" if mx else ("warn" if not has_mx else "fail"),
                   "detail": "、".join(mx) if mx else "未配置（没有企业邮箱可忽略）"})

    has_txt = any(r["type"] == "TXT" for r in z["records"])
    checks.append({"name": "SPF / TXT", "status": "ok" if has_txt else "warn",
                   "detail": "已配置" if has_txt else "建议加一条 SPF 记录"})

    ok = all(c["status"] != "fail" for c in checks)
    return {"ok": ok, "domain": dom, "checks": checks}


def dns_info(slug):
    m = dnsmod()
    zones = m.load_zones()
    z = zones.get(slug)
    return {"enabled": bool(z), "zone": z or {},
            "ns": [m.NS1, m.NS2], "port": 53,
            "demo_port": int(os.environ.get("KF_DNS_PORT", "5354"))}


def block_types():
    try:
        spec = importlib.util.spec_from_file_location("kf_sections_mod", BASE / "core" / "kf_sections.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return list(m.BLOCK_TYPES)
    except Exception:
        return ["hero", "cards", "split", "stats", "cta", "band", "gallery", "quotes", "table", "list", "rich"]


def schemas():
    try:
        spec = importlib.util.spec_from_file_location("kf_sections_mod2", BASE / "core" / "kf_sections.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.SCHEMAS
    except Exception:
        return {}


MEDIA_DIR = "wp-content/uploads/kampong"
MAX_UPLOAD = 8 * 1024 * 1024


def media_list(slug):
    d = SITES / slug / "html" / MEDIA_DIR
    if not d.exists():
        return []
    pages = read_spec(slug).get("pages", [])
    blobs = [(p.get("title", p.get("slug")), json.dumps(p, ensure_ascii=False)) for p in pages]
    out = []
    for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            continue
        if re.search(r"-\d{3,4}\.[a-z]+$", f.name):
            continue  # 多尺寸变体，不单独展示
        url = f"/{MEDIA_DIR}/{f.name}"
        used = [name for name, blob in blobs if url in blob]
        st = f.stat()
        out.append({"name": f.name, "url": url, "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                    "used_by": used})
    return out


def sniff_image(data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def to_webp_variants(data, max_w=1600, quality=82, widths=(1600, 800, 400)):
    """转 WebP 并生成多尺寸。返回 (main_bytes, main_w, main_h, {w: bytes})。"""
    import io
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    try:
        im.seek(0)
    except Exception:
        pass
    im = ImageOps.exif_transpose(im)
    if im.mode in ("P", "LA", "PA"):
        im = im.convert("RGBA")
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")

    main_w = min(max_w, im.width)
    if im.width > main_w:
        im = im.resize((main_w, max(1, round(im.height * main_w / im.width))), Image.LANCZOS)

    def encode(src):
        buf = io.BytesIO()
        src.save(buf, "WEBP", quality=quality, method=6)
        return buf.getvalue()

    main = encode(im)
    variants = {}
    for w in widths:
        if w >= main_w:
            continue
        h = max(1, round(im.height * w / im.width))
        variants[w] = encode(im.resize((w, h), Image.LANCZOS))
    return main, im.width, im.height, variants


def parse_multipart(body, boundary):
    for part in body.split(b"--" + boundary):
        if b"Content-Disposition" not in part:
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        if not data:
            continue
        if b'name="file"' not in head:
            continue
        m = re.search(rb'filename="([^"]*)"', head)
        return (m.group(1).decode("utf-8", "ignore") if m else "upload"), data.rstrip(b"\r\n")
    return None, None


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def page_diff(live_sections, draft_sections):
    changes, added, removed = [], 0, 0
    n = max(len(live_sections), len(draft_sections))
    for i in range(n):
        if i >= len(draft_sections):
            removed += 1
            continue
        if i >= len(live_sections):
            added += 1
            continue
        a, b = live_sections[i], draft_sections[i]
        if a.get("type") != b.get("type"):
            changes.append({"index": i, "type": b.get("type", ""),
                            "fields": [{"path": "type", "before": a.get("type"),
                                        "after": b.get("type")}]})
            continue
        fa, fb = flatten(a), flatten(b)
        fields = []
        for k in sorted(set(fa) | set(fb)):
            if fa.get(k) != fb.get(k):
                fields.append({"path": k, "before": fa.get(k), "after": fb.get(k)})
        if fields:
            changes.append({"index": i, "type": b.get("type", ""), "fields": fields})
    return {"changes": changes, "added": added, "removed": removed}


def spec_path(slug):
    return SITES / slug / "site-spec.json"


def _extend_on_payment(inv):
    """续费账单付款后，自动把站点到期日往后推。"""
    if inv.get("kind") != "renewal":
        return
    slug = inv.get("slug")
    years = int(inv.get("years") or 1)
    b = read_billing(slug)
    if not b:
        return
    base = b.get("expires") or datetime.now(SGT).strftime("%Y-%m-%d")
    dl = days_left(slug)
    if dl is not None and dl < 0:
        base = datetime.now(SGT).strftime("%Y-%m-%d")
    b["expires"] = add_years(base, years)
    b["status"] = "active"
    (SITES / slug / "billing.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))


def clients():
    return _read(CLIENTS_F, {})


def ledger():
    return _read(LEDGER_F, [])


def client_of(slug):
    meta = load_meta(slug)
    base = {
        "company": meta.get("company", slug),
        "contact": "", "phone": "", "email": "", "uen": "", "address": "",
        "agreement_no": "", "agreement_date": "",
        "service_start": "", "service_end": "",
        "scope": [], "annual_fee": 0, "notes": "", "owner": "",
    }
    base.update(clients().get(slug) or {})
    return base


def ledger_of(slug):
    rows = [x for x in ledger() if x.get("slug") == slug]
    rows.sort(key=lambda x: x.get("ts", ""), reverse=True)
    bal = 0.0
    for x in ledger():
        if x.get("slug") != slug:
            continue
        amt = float(x.get("amount") or 0)
        bal += amt if x.get("type") == "topup" else -amt
    return rows, round(bal, 2)


def add_ledger(slug, etype, amount, category, note, user=""):
    with _file_lock:
        rows = ledger()
        seq = len(rows) + 1
        rows.append({
            "id": "L-%04d" % seq, "slug": slug, "type": etype,
            "amount": round(float(amount), 2), "category": category,
            "note": str(note)[:120],
            "ts": datetime.now(SGT).strftime("%Y-%m-%d %H:%M"),
            "by": user or "-",
        })
        _write(LEDGER_F, rows)
    return rows[-1]


def read_domain(slug):
    b = read_billing(slug)
    d = b.get("domain") or {}
    return {
        "registrar": d.get("registrar", ""),
        "expires": d.get("expires", ""),
        "auto_renew": bool(d.get("auto_renew", True)),
        "owner": d.get("owner", "us"),       # us=在我们账户下代管
        "note": d.get("note", ""),
    }


def write_domain(slug, data):
    b = read_billing(slug)
    b["domain"] = data
    (SITES / slug / "billing.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))


def domain_days_left(slug):
    exp = read_domain(slug).get("expires") or ""
    if not exp:
        return None
    try:
        return (datetime.strptime(exp, "%Y-%m-%d").date()
                - datetime.now(SGT).date()).days
    except Exception:
        return None


def read_billing(slug):
    return _read(SITES / slug / "billing.json", {})


def days_left(slug):
    b = read_billing(slug)
    exp = (b.get("expires") or "").strip()
    if not exp:
        return None
    try:
        d = datetime.strptime(exp, "%Y-%m-%d").date()
    except Exception:
        return None
    return (d - datetime.now(SGT).date()).days


def add_years(date_str, years):
    try:
        y, m, d = [int(x) for x in date_str.split("-")]
        return "%04d-%02d-%02d" % (y + years, m, min(d, 28) if m == 2 else d)
    except Exception:
        return datetime.now(SGT).strftime("%Y-%m-%d")


def draft_path(slug):
    return SITES / slug / "site-draft.json"


def read_draft(slug):
    p = draft_path(slug)
    if p.exists():
        return _read(p, {"pages": []})
    return read_spec(slug)          # 首次进入：草稿 = 线上


def is_dirty(slug):
    return json.dumps(read_draft(slug), sort_keys=True) != json.dumps(read_spec(slug), sort_keys=True)


def read_spec(slug):
    return _read(spec_path(slug), {"pages": []})


def render_page(slug, page):
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "core" / "kf_sections.py"),
             "--site", str(SITES / slug), "--only", page],
            capture_output=True, text=True, timeout=180)
        return r.returncode == 0, (r.stdout or r.stderr).strip()[-300:]
    except Exception as e:
        return False, str(e)


UPDATES_F = CONSOLE / "updates.json"
_update_state = {"running": False, "mode": ""}


def read_updates():
    return _read(UPDATES_F, {})


def run_update(mode):
    _update_state["running"] = True
    _update_state["mode"] = mode
    try:
        subprocess.run([sys.executable, str(BASE / "tools" / "kf_update.py"),
                        "--" + mode], capture_output=True, text=True, timeout=3600)
    except Exception:
        pass
    finally:
        _update_state["running"] = False
        _update_state["mode"] = ""


LEADS_PHP = (
    '<?php $o=[]; foreach(get_posts(["post_type"=>"kf_lead","numberposts"=>100,'
    '"post_status"=>"any"]) as $p){ $o[]=["id"=>$p->ID,"title"=>$p->post_title,'
    '"date"=>$p->post_date,"msg"=>$p->post_content,'
    '"email"=>get_post_meta($p->ID,"_kf_email",true),'
    '"phone"=>get_post_meta($p->ID,"_kf_phone",true),'
    '"sent"=>get_post_meta($p->ID,"_kf_mail_sent",true)]; }'
    ' echo json_encode($o, JSON_UNESCAPED_UNICODE);'
)


def list_leads(slug):
    site = SITES / slug
    tmp = site / "_leads_tmp.php"
    try:
        tmp.write_text(LEADS_PHP)
        r = subprocess.run(
            ["docker", "run", "--rm", "--env-file", str(site / "wp.env"),
             "--network", "kf-%s_default" % slug,
             "-v", "%s/html:/var/www/html" % site,
             "-v", "%s:/tmp/leads.php:ro" % tmp,
             "--user", "33:33", WPCLI_IMG, "wp", "eval-file", "/tmp/leads.php"],
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


def host_map():
    """域名 → {slug, port}，用于模拟虚拟主机。"""
    m = {}
    if not SITES.exists():
        return m
    for d in SITES.iterdir():
        if not d.is_dir():
            continue
        meta = load_meta(d.name)
        dom = (meta.get("domain") or "").strip().lower()
        port = int(meta.get("port") or 0)
        if not dom or not port:
            continue
        m[dom] = {"slug": d.name, "port": port}
        if not dom.startswith("www."):
            m["www." + dom] = {"slug": d.name, "port": port}
    return m


def proxy_site(port, path, method="GET", body=None, headers=None):
    url = "http://127.0.0.1:%d%s" % (port, path)
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or []):
        if k.lower() in ("host", "connection", "accept-encoding", "content-length"):
            continue
        req.add_header(k, v)
    try:
        r = urllib.request.urlopen(req, timeout=40)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception:
        return 502, {}, b"<h1>502 Bad Gateway</h1>"


def esc(v):
    """服务端 HTML 转义（前端那份在 JS 里，两者不能混用）。"""
    return _htmlesc.escape("" if v is None else str(v), quote=True)


ACCESS_F = CONSOLE / "portal-access.log"
MAX_LOG = 2 * 1024 * 1024


def log_access(slug, event, token="", note="", handler=None):
    ip, ua = "", ""
    if handler is not None:
        try:
            ip = handler.client_address[0]
        except Exception:
            ip = ""
        ua = (handler.headers.get("User-Agent") or "")[:120]
    rec = {"ts": datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S"),
           "slug": slug, "event": event, "token": (token or "")[:8],
           "ip": ip, "ua": ua, "note": note[:120]}
    try:
        if ACCESS_F.exists() and ACCESS_F.stat().st_size > MAX_LOG:
            ACCESS_F.replace(ACCESS_F.with_suffix(".log.1"))
        with ACCESS_F.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_access(slug, limit=100):
    if not ACCESS_F.exists():
        return []
    out = []
    try:
        for line in ACCESS_F.read_text(errors="replace").splitlines()[-2000:]:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("slug") == slug:
                out.append(r)
    except Exception:
        return []
    return out[-limit:][::-1]


SECRET_F = CONSOLE / "portal_secret"
_attempts = {}
_attempt_lock = threading.Lock()


def portal_secret():
    if not SECRET_F.exists():
        import secrets as _s
        SECRET_F.write_text(_s.token_urlsafe(32))
        try:
            SECRET_F.chmod(0o600)
        except OSError:
            pass
    return SECRET_F.read_text().strip().encode()


def pin_hash(pin, salt):
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120000).hex()


def hmac_compare(pin, entry):
    salt = entry.get("pin_salt") or ""
    want = entry.get("pin_hash") or ""
    if not salt or not want:
        return False
    import hmac as _h
    return _h.compare_digest(pin_hash(pin, salt), want)


def portal_cookie(token):
    import hmac, hashlib
    exp = int(time.time()) + 12 * 3600
    sig = hmac.new(portal_secret(), ("%s|%d" % (token, exp)).encode(),
                   hashlib.sha256).hexdigest()
    return "kf_p_%s=%d.%s" % (token[:8], exp, sig), exp


def cookie_value(header, name):
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def portal_check_cookie(token, header):
    import hmac, hashlib
    p = portals().get(token) or {}
    if not p.get("pin_hash"):
        return True
    v = cookie_value(header, "kf_p_%s" % token[:8])
    if not v or "." not in v:
        return False
    exp_s, sig = v.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    want = hmac.new(portal_secret(), ("%s|%d" % (token, exp)).encode(),
                    hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


def attempts_blocked(token):
    now = time.time()
    with _attempt_lock:
        st = _attempts.get(token)
        if not st:
            return False
        if st.get("until", 0) > now:
            return True
        if st.get("count", 0) >= 5 and st.get("until", 0) <= now:
            _attempts.pop(token, None)
    return False


def record_attempt(token, ok):
    now = time.time()
    with _attempt_lock:
        st = _attempts.setdefault(token, {"count": 0, "until": 0})
        if ok:
            _attempts.pop(token, None)
            return
        st["count"] += 1
        if st["count"] >= 5:
            st["until"] = now + 900


def portals():
    return _read(PORTAL_F, {})


def portal_slug(token):
    p = portals().get(token)
    if not p or not p.get("active"):
        return None
    if not (SITES / p["slug"]).exists():
        return None
    return p["slug"]


def login_page(err="", next_url="/"):
    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 · KampongFlow</title>
<style>
html,body{height:100%%}
body{margin:0;min-height:100vh;min-height:100dvh;display:flex;align-items:center;
 justify-content:center;background:#0d1117;color:#e6edf3;
 font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif;
 padding:20px;box-sizing:border-box}
.box{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:28px;width:100%%;max-width:360px}
h1{font-size:18px;margin:0 0 4px}p.sub{color:#8b949e;font-size:13px;margin:0 0 18px}
label{display:block;font-size:12px;color:#8b949e;margin-bottom:5px}
input{width:100%%;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#e6edf3;
 padding:11px 12px;font-size:15px;margin-bottom:12px}
button{width:100%%;padding:12px;border:0;border-radius:8px;background:#238636;color:#fff;
 font-size:15px;font-weight:650;cursor:pointer}
.err{background:#3d1d1d;color:#f85149;border-radius:8px;padding:9px 12px;font-size:13px;margin-bottom:14px}
</style></head><body><div class="box">
<h1>KampongFlow</h1><p class="sub">员工登录</p>
%s
<form method="post" action="/login">
<input type="hidden" name="next" value="%s">
<label>用户名</label><input name="user" autocomplete="username" autofocus required>
<label>密码</label><input name="pw" type="password" autocomplete="current-password" required>
<label>两步验证码（如已开启）</label><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6">
<button type="submit">登录</button>
</form></div></body></html>""" % (('<div class="err">%s</div>' % err) if err else "", next_url)


def pin_form(token, err=""):
    note = ('<div class="err">%s</div>' % err) if err else ""
    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>请输入访问码</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:#f6f7f9;color:#1d2330;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
 Roboto,"PingFang SC",sans-serif;padding:20px}
.box{background:#fff;border:1px solid #e6e8ee;border-radius:16px;padding:28px;
 width:100%%;max-width:360px;text-align:center}
h1{font-size:17px;margin:0 0 6px}p{color:#7b8494;font-size:13.5px;margin:0 0 18px}
input{width:100%%;text-align:center;letter-spacing:.4em;font-size:20px;padding:12px;
 border:1px solid #dfe3ea;border-radius:10px;margin-bottom:12px}
input:focus{outline:2px solid #0f5132;outline-offset:1px}
button{width:100%%;padding:12px;border:0;border-radius:999px;background:#0f5132;color:#fff;
 font-size:15px;font-weight:650;cursor:pointer}
.err{background:#fdecea;color:#b3261e;border-radius:8px;padding:9px 12px;font-size:13px;
 margin-bottom:14px}
</style></head><body><div class="box">
<h1>客户中心</h1><p>请输入我们提供的 6 位访问码</p>
%s
<form method="post" action="/portal/%s/unlock">
<input name="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="8"
       pattern="[0-9]*" autofocus required>
<button type="submit">进入</button>
</form></div></body></html>""" % (note, token)


def portal_html(token, slug, msg=""):
    meta = load_meta(slug)
    b = read_billing(slug)
    d = _read(SITES / slug / "design.json", {})
    primary = (d.get("palette") or {}).get("primary", "#0f5132")
    accent = (d.get("palette") or {}).get("accent", "#d4a04a")
    dl = days_left(slug)
    invs = [i for i in invoices() if i.get("slug") == slug]
    invs.sort(key=lambda x: x.get("issued_at", ""), reverse=True)

    rows = []
    for i in invs:
        paid = i.get("status") == "paid"
        rows.append(
            '<tr><td class="mono">%s</td><td>%s</td><td>%s %s</td>'
            '<td><span class="pill %s">%s</span></td>'
            '<td><a href="/portal/%s/invoice/%s.pdf">PDF</a></td></tr>'
            % (i.get("no", ""), i.get("issued_at", ""), "SGD",
               "{:,.0f}".format(i.get("total", 0)), "ok" if paid else "wait",
               "已付款" if paid else "待支付", token, i.get("no", "")))

    dm = read_domain(slug)
    managed = dm.get("owner") == "us"
    renew_html = (
        '<div class="note" style="background:#f3f6fa;color:#46505f">'
        '本服务由我们全程代管：域名、解析、续费、证书都由我们处理，到期前会主动联系你。</div>'
        if managed else
        '<form method="post" action="/portal/%s/renew">'
        '<button class="btn" type="submit">申请续费一年</button></form>' % token
    )

    site_url = "http://127.0.0.1:%d/" % int(meta.get("port") or 0)
    exp = b.get("expires", "—")
    if dl is None:
        exp_txt = esc(exp)
    elif dl < 0:
        exp_txt = "%s（已过期 %d 天）" % (esc(exp), -dl)
    else:
        exp_txt = "%s（还剩 %d 天）" % (esc(exp), dl)

    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>%(company)s · 客户中心</title>
<style>
:root{--p:%(primary)s;--a:%(accent)s}
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1d2330;
 font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif}
.top{background:var(--p);color:#fff;padding:26px 20px}
.top .in{max-width:860px;margin:0 auto}
.top h1{margin:0;font-size:20px;font-weight:750}
.top .sub{opacity:.85;font-size:13px;margin-top:4px}
.wrap{max-width:860px;margin:0 auto;padding:22px 20px 60px}
.card{background:#fff;border:0;border-radius:14px;padding:20px;margin-bottom:16px;
 box-shadow:0 1px 2px rgba(29,35,48,.05),0 8px 22px rgba(29,35,48,.05)}
.card h2{font-size:15px;margin:0 0 14px;color:#5b6474;font-weight:600;
 letter-spacing:.02em;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.k{font-size:12px;color:#7b8494}.v{font-size:16px;font-weight:650;margin-top:2px;word-break:break-all}
table{width:100%%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;
 color:#7b8494;padding:8px 0;font-weight:600}
td{padding:11px 0;border-bottom:1px solid #eef1f5}
tr:last-child td{border-bottom:none}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:13px}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px}
.pill.ok{background:#e7f6ec;color:#1a7f37}.pill.wait{background:#fff4e5;color:#a15c00}
a{color:var(--p)}
.btn{display:inline-block;margin-top:14px;background:var(--p);color:#fff;border:0;
 padding:11px 22px;border-radius:999px;font-size:14px;font-weight:650;cursor:pointer}
.note{margin-top:12px;font-size:13px;padding:10px 14px;border-radius:8px;background:#eef6ff;color:#0b4a8f}
.foot{color:#8b93a1;font-size:12px;text-align:center;margin-top:26px}
</style></head><body>
<div class="top"><div class="in"><h1>%(company)s</h1>
<div class="sub">客户中心 · 账单与续费</div></div></div>
<div class="wrap">
%(msg)s
<div class="card"><h2>套餐与状态</h2>
<div class="grid">
<div><div class="k">当前套餐</div><div class="v">%(plan)s</div></div>
<div><div class="k">到期时间</div><div class="v">%(exp)s</div></div>
<div><div class="k">网站地址</div><div class="v"><a href="%(url)s" target="_blank">%(domain)s</a></div></div>
<div><div class="k">状态</div><div class="v">%(status)s</div></div>
</div>
%(renew)s
</div>
<div class="card"><h2>账单记录</h2>
<table><thead><tr><th>编号</th><th>开具时间</th><th>金额</th><th>状态</th><th>下载</th></tr></thead>
<tbody>%(rows)s</tbody></table>
</div>
<div class="foot">如需帮助，请通过 WhatsApp 或电话联系。</div>
</div></body></html>""" % {
        "company": esc(meta.get("company", slug)), "primary": primary, "accent": accent,
        "plan": esc(b.get("plan") or "—"), "exp": exp_txt,
        "url": esc(site_url), "domain": esc(meta.get("domain", "")),
        "status": "正常运行" if b.get("status") != "suspended" else "已暂停",
        "rows": "".join(rows) or '<tr><td colspan="5">暂无账单</td></tr>',
        "token": token, "msg": msg, "renew": renew_html,
    }


def shares():
    return _read(SHARES_F, {})


def share_for(token):
    s = shares().get(token)
    if not s or not s.get("active"):
        return None
    exp = (s.get("expires") or "").strip()
    if exp:
        try:
            if datetime.strptime(exp, "%Y-%m-%d") < datetime.now(SGT).replace(tzinfo=None):
                return None
        except Exception:
            pass
    return s


def presets():
    return _read(PRESETS_F, {})


def site_design(slug):
    d = _read(SITES / slug / "design.json", {})
    return d if isinstance(d, dict) else {}


COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEN_RE = re.compile(r"^\d{1,3}px$")
HEADS = {"sans", "serif", "rounded", "mono"}


def sanitize_design(body):
    pal = body.get("palette") or {}
    shape = body.get("shape") or {}
    typ = body.get("type") or {}
    layout = body.get("layout") or {}
    photos = body.get("photos") or {}

    def col(v, fb):
        return v.lower() if isinstance(v, str) and COLOR_RE.match(v) else fb

    def ln(v, fb):
        return v if isinstance(v, str) and LEN_RE.match(v) else fb

    head = typ.get("heading") if typ.get("heading") in HEADS else "sans"
    ov = str(photos.get("overlay", "0.46"))
    if not re.match(r"^(0?\.\d+|1)$", ov):
        ov = "0.46"
    return {
        "preset": str(body.get("preset", "custom"))[:20],
        "palette": {
            "primary": col(pal.get("primary"), "#0f5132"),
            "primaryDark": col(pal.get("primaryDark"), "#0a3a24"),
            "accent": col(pal.get("accent"), "#d4a04a"),
            "bg": col(pal.get("bg"), "#f7f9f7"),
            "surface": col(pal.get("surface"), "#ffffff"),
            "ink": col(pal.get("ink"), "#16211c"),
            "muted": col(pal.get("muted"), "#5d6b64"),
            "deep": col(pal.get("deep"), "#10231a"),
        },
        "shape": {"radius": ln(shape.get("radius"), "16px"),
                  "button": ln(shape.get("button"), "999px")},
        "type": {"heading": head},
        "layout": {"pad": ln(layout.get("pad"), "76px")},
        "photos": {"overlay": ov},
    }


def apply_design(slug, tokens):
    site = SITES / slug
    (site / "design.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=1))
    try:
        subprocess.run(
            ["docker", "run", "--rm", "--env-file", str(site / "wp.env"),
             "--network", f"kf-{slug}_default",
             "-v", f"{site}/html:/var/www/html", "--user", "33:33", WPCLI_IMG,
             "wp", "option", "update", "kf_design", json.dumps(tokens, ensure_ascii=False)],
            capture_output=True, text=True, timeout=150)
        return True
    except Exception:
        return False


def load_meta(slug):
    try:
        return json.loads((SITES / slug / "meta.json").read_text())
    except Exception:
        return {"company": slug, "domain": "", "port": 0, "created": ""}


def http_status(port):
    if not port:
        return 0
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def docker_state(slug):
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=kf-{slug}",
             "--format", "{{.Names}}|{{.Status}}"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        if "|" in line:
            n, s = line.split("|", 1)
            rows.append({"name": n, "status": s})
    return rows


def site_list():
    items = []
    if not SITES.exists():
        return items
    inv_by_slug = {}
    for inv in invoices():
        inv_by_slug.setdefault(inv.get("slug"), inv)
    for d in sorted(SITES.iterdir()):
        if not d.is_dir():
            continue
        m = load_meta(d.name)
        port = int(m.get("port") or 0)
        with _lock:
            live = dict(_live[d.name]) if d.name in _live else None
        cs = docker_state(d.name)
        running = sum(1 for c in cs if c["status"].startswith("Up"))
        inv = inv_by_slug.get(d.name)
        items.append({
            "slug": d.name,
            "company": m.get("company", d.name),
            "domain": m.get("domain", ""),
            "port": port,
            "created": m.get("created", ""),
            "plan": m.get("plan", ""),
            "http": http_status(port),
            "containers": cs,
            "running": running,
            "state": live["state"] if live else ("active" if running >= 2 else "stopped"),
            "message": live.get("msg", "") if live else "",
            "invoice": inv.get("no") if inv else "",
            "invoice_status": inv.get("status") if inv else "",
            "expires": read_billing(d.name).get("expires", ""),
            "days_left": days_left(d.name),
            "billing_status": read_billing(d.name).get("status", ""),
            "domain_expires": read_domain(d.name).get("expires", ""),
            "domain_days": domain_days_left(d.name),
            "domain_owner": read_domain(d.name).get("owner", "us"),
            "owner": client_of(d.name).get("owner", ""),
        })
    return items


def free_port():
    used = {int(x.get("port") or 0) for x in site_list()}
    for p in range(18080, 18200):
        if p not in used:
            return p
    return 0


def provision(company, domain, slug, port, plan_name="", plan_price="", industry="", plan_id=""):
    with _lock:
        _live[slug] = {"state": "provisioning", "msg": "正在开通，约 60 秒"}
    try:
        r = subprocess.run([str(PROV), company, domain, slug, str(port), plan_name, str(plan_price), industry, plan_id],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            with _lock:
                _live[slug] = {"state": "failed",
                               "msg": (r.stderr or r.stdout or "未知错误").strip()[-400:]}
        else:
            with _lock:
                _live.pop(slug, None)
    except Exception as e:
        with _lock:
            _live[slug] = {"state": "failed", "msg": str(e)}


# ---------------------------------------------------------------- PDF
def _styles():
    cn = ParagraphStyle("cn", fontName=FONT, fontSize=10, leading=15,
                        textColor=colors.HexColor("#222222"))
    h1 = ParagraphStyle("h1", parent=cn, fontSize=19, leading=26, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=cn, fontSize=12.5, leading=18,
                        spaceBefore=9, spaceAfter=4,
                        textColor=colors.HexColor("#0f5132"))
    small = ParagraphStyle("small", parent=cn, fontSize=8.8, leading=13,
                           textColor=colors.HexColor("#666666"))
    cell = ParagraphStyle("cell", parent=cn, fontSize=9.5, leading=13.5)
    return cn, h1, h2, small, cell


def _kv_table(rows, cell):
    data = [[Paragraph(f"<b>{k}</b>", cell), Paragraph(v, cell)] for k, v in rows]
    t = Table(data, colWidths=[38 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e5e5")),
    ]))
    return t


def handover_pdf(slug):
    meta = load_meta(slug)
    f = SITES / slug / "handover.md"
    if not f.exists():
        raise FileNotFoundError("没有交接单")
    cn, h1, h2, small, cell = _styles()
    s = settings()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"服务交接单 {meta.get('company', slug)}")
    story = [
        Paragraph("服务交接单", h1),
        Paragraph(f"{s['company']}　·　{datetime.now(SGT):%Y-%m-%d}", small),
        Spacer(1, 8 * mm),
        _kv_table([
            ("客户", meta.get("company", slug)),
            ("域名", meta.get("domain", "-")),
            ("套餐", meta.get("plan", "-")),
            ("开通时间", str(meta.get("created", "-")).replace("T", " ")[:16]),
            ("站点标识", slug),
        ], cell),
        Spacer(1, 4 * mm),
    ]
    for raw in f.read_text().splitlines():
        line = raw.rstrip()
        if not line:
            story.append(Spacer(1, 2.5 * mm))
            continue
        if line.startswith("# "):
            continue
        if line.startswith("**客户**") or line.startswith("**域名**") \
                or line.startswith("**开通时间**") or line.startswith("**套餐**"):
            continue  # 已在顶部表格里
        if line.startswith("## "):
            story.append(Paragraph(line[3:], h2))
            continue
        if line.startswith("- [ ] "):
            story.append(Paragraph(f"[ ]&nbsp;&nbsp;{line[6:]}", cn))
            continue
        if line.startswith("- "):
            txt = line[2:].replace("**", "")
            story.append(Paragraph(f"· {txt}", cn))
            continue
        story.append(Paragraph(line.replace("**", ""), cn))
    story += [Spacer(1, 8 * mm),
              Paragraph("如信息有误请联系 support，本单由系统自动生成。", small)]
    doc.build(story)
    return buf.getvalue()


def invoice_pdf(inv):
    cn, h1, h2, small, cell = _styles()
    s = settings()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"账单 {inv['no']}")
    story = [
        Paragraph(s["company"], h1),
        Paragraph("INVOICE / 账单", h2),
        Spacer(1, 3 * mm),
        _kv_table([
            ("账单编号", inv["no"]),
            ("客户", inv["company"]),
            ("域名", inv.get("domain", "-")),
            ("套餐", inv.get("plan_name", "-")),
            ("签发日期", inv.get("issued_at", "-")),
            ("状态", "已付款" if inv.get("status") == "paid" else "待付款"),
        ], cell),
        Spacer(1, 6 * mm),
    ]
    rows = [["项目", "说明", "金额"],
            [inv.get("plan_name", "服务"), inv.get("plan_specs", ""),
             f"{s['currency']} {inv['subtotal']:,.2f}"]]
    if inv.get("gst", 0):
        rows.append(["GST", f"{int(s['gst_rate'] * 100)}%", f"{inv['gst']:,.2f}"])
    rows.append(["合计", "", f"{s['currency']} {inv['total']:,.2f}"])
    t = Table(rows, colWidths=[40 * mm, 80 * mm, 38 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f3f1")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#dddddd")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#0f5132")),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [t, Spacer(1, 8 * mm),
              Paragraph(f"付款方式：银行转账 / Stripe。如有疑问请联系 {s['support_email']}", small)]
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- 页面
PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KampongFlow 控制台</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:22px 16px 64px}
.topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.who{font-size:12.5px;color:var(--dim);white-space:nowrap}
.who a{color:var(--acc);text-decoration:none}
h1{font-size:19px;margin:0 0 2px}
.sub{color:var(--dim);font-size:13px;margin-bottom:18px}
.tabs{display:flex;gap:6px;margin-bottom:18px;border-bottom:1px solid var(--line);
  overflow-x:auto;flex-wrap:nowrap;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.tabs::-webkit-scrollbar{display:none}
.tab{padding:9px 16px;cursor:pointer;color:var(--dim);font-size:14px;
  border-bottom:2px solid transparent;white-space:nowrap;flex:0 0 auto}
.tab.on{color:var(--fg);border-bottom-color:var(--acc)}
.stats{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:104px}
.stat b{display:block;font-size:20px}
.stat span{color:var(--dim);font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13.5px;vertical-align:top}
th{color:var(--dim);font-weight:500;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.ok{background:var(--ok)}.bad{background:var(--bad)}.warn{background:var(--warn)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
form{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-top:20px}
.formrow{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px}
input,select{background:#0d1117;border:1px solid var(--line);border-radius:6px;color:var(--fg);
padding:8px 10px;font-size:14px;width:100%}
.field{flex:1;min-width:130px}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:14px;
cursor:pointer;font-weight:500}
button.ghost{background:#21262d;border:1px solid var(--line);color:var(--fg);padding:5px 10px;font-size:12.5px}
button:disabled{opacity:.5;cursor:default}
.msg{margin-top:12px;font-size:13px}
.msg.bad{color:var(--bad)}.msg.ok{color:var(--ok)}
.hidden{display:none}
footer{margin-top:26px;color:var(--dim);font-size:12px}
.sec-list{margin-top:14px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.sec-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line);
  background:var(--card);font-size:13px;cursor:pointer}
.sec-row:last-child{border-bottom:none}
.sec-row.on{background:#1c2530;box-shadow:inset 3px 0 0 var(--acc)}
.sec-row .t{font-family:ui-monospace,Menlo,monospace;color:var(--acc);min-width:74px}
.sec-row .s{flex:1;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sec-row button{background:#21262d;border:1px solid var(--line);color:var(--fg);border-radius:5px;
  padding:2px 7px;font-size:12px;cursor:pointer}
.lead-card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;margin-bottom:9px}
.lead-top{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px}
.lead-top b{color:var(--fg)}
.lead-top .t{color:var(--dim);font-size:11.5px;margin-left:auto}
.lead-msg{margin-top:7px;font-size:13px;color:var(--fg);white-space:pre-wrap;line-height:1.6}
.lead-meta{margin-top:6px;font-size:12px;color:var(--dim);font-family:ui-monospace,Menlo,monospace}
.badge-warn{background:#d2992222;color:#d29922;border-radius:4px;padding:1px 6px;font-size:11px}
.callout{background:#1c2530;border:1px solid var(--line);border-left:3px solid var(--acc);
  border-radius:8px;padding:10px 14px;font-size:12.5px;color:var(--dim);line-height:1.7}
.dom-row{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.dom-row .h{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dom-row .name{font-family:ui-monospace,Menlo,monospace;color:var(--acc);font-size:13px}
.dom-row .hint{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--dim);
  margin-top:6px;word-break:break-all}
.dom-row button{background:#21262d;border:1px solid var(--line);color:var(--fg);
  border-radius:5px;padding:3px 9px;font-size:12px;cursor:pointer}
.share-row{display:flex;gap:10px;align-items:center;padding:10px 12px;background:var(--card);
  border:1px solid var(--line);border-radius:8px;margin-bottom:8px;font-size:12.5px;flex-wrap:wrap}
.share-row .u{font-family:ui-monospace,Menlo,monospace;color:var(--acc);flex:1;word-break:break-all}
.share-row .dead{color:var(--dim);text-decoration:line-through}
.share-row button{background:#21262d;border:1px solid var(--line);color:var(--fg);
  border-radius:5px;padding:3px 9px;font-size:12px;cursor:pointer}
@media(max-width:760px){
  .sm-hide{display:none}
  .topbar{flex-direction:column;gap:4px}
  .who{font-size:12px;align-self:flex-start}
  .sub{font-size:12px}
  h1{font-size:17px}
  table,thead,tbody,tr,td{display:block;width:100%}
  thead{display:none}
  tbody tr{border:1px solid var(--line);border-radius:10px;padding:12px;
    margin-bottom:10px;background:var(--card)}
  tbody td{border:0;padding:3px 0;text-align:left}
  tbody td:first-child{font-weight:650;color:var(--fg);font-size:13px}
  tbody tr td:last-child a,tbody tr td:last-child button{margin-top:6px}
  .wrap{padding:16px 12px 60px}
  th,td{padding:8px 6px;font-size:12.5px}
  .stat{min-width:88px;padding:8px 10px}
  .stat b{font-size:17px}
}
.diff-box{margin-top:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.diff-box.hidden{display:none}
.diff-sec{margin-bottom:10px}
.diff-head{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--acc);margin-bottom:4px}
.diff-row{display:flex;gap:8px;font-size:12px;padding:3px 0;align-items:baseline;flex-wrap:wrap}
.diff-row .k{font-family:ui-monospace,Menlo,monospace;color:var(--dim);min-width:110px}
.diff-row .old{color:#f85149;text-decoration:line-through;opacity:.75;word-break:break-all}
.diff-row .new{color:#3fb950;word-break:break-all}
.diff-row .arrow{color:var(--dim)}
.media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tile img{width:100%;height:120px;object-fit:cover;display:block;background:#0d1117}
.tile .meta{padding:8px 10px;font-size:11.5px;color:var(--dim);line-height:1.5}
.tile .meta b{display:block;color:var(--fg);font-size:12px;font-weight:500;word-break:break-all}
.tile .ops{display:flex;gap:6px;padding:0 10px 10px}
.tile .ops button{flex:1;background:#21262d;border:1px solid var(--line);color:var(--fg);
  border-radius:5px;padding:4px 0;font-size:11.5px;cursor:pointer}
.tile .ops button.del{color:#f85149;border-color:#5c2b2b}
.used{display:inline-block;background:#1f6feb22;color:#58a6ff;border-radius:4px;padding:1px 5px;font-size:10.5px}
.form-area{margin-top:12px}
.fld{margin-bottom:10px}
.fld label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px}
.fld input[type=text],.fld textarea,.fld select{width:100%;background:#0d1117;border:1px solid var(--line);
  border-radius:6px;color:var(--fg);padding:8px 10px;font-size:13.5px}
.fld textarea{min-height:64px;resize:vertical}
.fld .row2{display:flex;gap:8px}
.fld .row2 input{flex:1}
.fld .sub{display:flex;gap:6px;margin-bottom:6px;align-items:flex-start}
.fld .sub .grow{flex:1;display:flex;flex-direction:column;gap:6px}
.fld .sub button{background:#21262d;border:1px solid var(--line);color:var(--fg);border-radius:5px;
  padding:3px 8px;font-size:12px;cursor:pointer;height:30px}
.fld .add{background:#1f6feb22;border:1px dashed #388bfd;color:var(--acc);border-radius:6px;
  padding:6px 10px;font-size:12.5px;cursor:pointer;width:100%;margin-top:2px}
.fld .imgnote{font-size:11.5px;color:var(--dim);margin-top:5px}
.fld .thumb{width:100%;max-height:110px;object-fit:cover;border-radius:8px;margin-top:6px;border:1px solid var(--line)}
.fld .chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fg)}
.adv{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
.adv summary{cursor:pointer;font-size:12.5px;color:var(--dim)}
.json-edit{width:100%;min-height:160px;background:#0d1117;border:1px solid var(--line);border-radius:8px;
  color:var(--fg);font-family:ui-monospace,Menlo,monospace;font-size:12.5px;padding:10px;margin-top:6px}
.design-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
@media(max-width:820px){.design-grid{grid-template-columns:1fr}}
.preview{background:#fff;color:#222;border-radius:14px;padding:16px;border:1px solid var(--line)}
.pv-hero{border-radius:12px;padding:20px;color:#fff}
.pv-kicker{font-size:10px;letter-spacing:.12em;opacity:.85;margin-bottom:8px}
.pv-h1{font-size:26px;font-weight:800;line-height:1.1;margin-bottom:6px}
.pv-p{font-size:13px;opacity:.9;margin-bottom:12px}
.pv-btn{display:inline-block;padding:8px 16px;background:#fff;font-weight:650;font-size:12.5px}
.pv-card{background:#fff;border:1px solid rgba(0,0,0,.1);padding:14px;margin-top:12px;font-size:13px}
.pv-small{font-size:12px;color:#777;margin-top:3px}
input[type=color]{height:38px;padding:2px;cursor:pointer}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;border:1px solid var(--line)}
</style></head><body><div class="wrap">
<div class="topbar">
  <div>
    <h1>KampongFlow 控制台</h1>
    <div class="sub">一次性交付：域名 · 建站 · 邮箱 · 托管</div>
  </div>
  <div class="who"><span id="whoami">—</span> · <a href="/logout">退出</a></div>
</div>
<div class="tabs">
<div class="tab on" data-t="sites">站点</div>
<div class="tab" data-t="billing">账单</div>
<div class="tab" data-t="plans">套餐</div>
<div class="tab" data-t="layout">结构</div>
<div class="tab" data-t="media">媒体</div>
<div class="tab" data-t="share">分享</div>
<div class="tab" data-t="domain">域名</div>
<div class="tab" data-t="leads">线索</div>
<div class="tab" data-t="maint">维护</div>
<div class="tab" data-t="client">客户</div>
<div class="tab" data-t="team">团队</div>
<div class="tab" data-t="dns">DNS</div>
<div class="tab" data-t="design">设计</div>
</div>

<div id="p-sites">
<div class="stats" id="stats"></div>
<label style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--dim);margin-bottom:10px">
  <input type="checkbox" id="onlyMine" onchange="renderSites()"> 只看我负责的
</label>
<table><thead><tr><th>站点</th><th>客户 / 域名</th><th class="sm-hide">负责人</th><th class="sm-hide">套餐</th><th>状态</th><th class="sm-hide">账单</th><th>到期</th><th>操作</th></tr></thead>
<tbody id="rows"><tr><td colspan="8" style="color:var(--dim)">加载中…</td></tr></tbody></table>
<form id="f"><div class="formrow">
<div class="field"><label>客户名称</label><input name="company" placeholder="Tanjong Pte Ltd" required></div>
<div class="field"><label>域名</label><input name="domain" placeholder="example.sg" required></div>
<div class="field"><label>标识 slug</label><input name="slug" placeholder="tanjong" required></div>
<div class="field"><label>套餐</label><select name="plan_id" id="planSel"></select></div>
<div class="field"><label>行业模板</label><select name="industry" id="indSel"></select></div>
<button id="btn">下单并开通</button>
</div><div class="msg" id="msg"></div></form>
</div>

<div id="p-billing" class="hidden">
<div class="stats" id="billStats"></div>
<table><thead><tr><th>账单号</th><th>客户</th><th>套餐</th><th>金额</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
<tbody id="billRows"></tbody></table>
</div>

<div id="p-plans" class="hidden">
<table><thead><tr><th>套餐</th><th>价格</th><th>规格</th><th>操作</th></tr></thead><tbody id="planRows"></tbody></table>
<form id="pf"><div class="formrow">
<div class="field"><label>套餐 ID</label><input name="id" placeholder="starter" required></div>
<div class="field"><label>名称</label><input name="name" placeholder="Starter" required></div>
<div class="field"><label>价格 (SGD)</label><input name="price" type="number" placeholder="1800" required></div>
<div class="field"><label>周期</label><input name="period" placeholder="首年" value="首年"></div>
<div class="field" style="flex:2"><label>规格说明</label><input name="specs" placeholder="1 个站点 · 5 个邮箱 · 20GB"></div>
<button>保存套餐</button>
</div><div class="msg" id="pmsg"></div></form>
</div>



<div id="p-layout" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="lSlug"></select></div>
<div class="field"><label>页面</label><select id="lPage"></select></div>
<div class="field"><label>新增区块</label><select id="lType"></select></div>
<button class="ghost" id="lAdd">添加</button>
</div>
<div class="sec-list" id="lList"></div>
<div id="lForm" class="form-area"></div>
<details class="adv"><summary>高级：直接编辑 JSON</summary>
<textarea id="lJson" class="json-edit" spellcheck="false"></textarea>
<button class="ghost" id="lApplyJson" style="margin-top:8px">从 JSON 覆盖表单</button>
</details>
<div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<button id="lSave">保存草稿</button>
<button class="ghost" id="lPreview">预览草稿</button>
<button class="ghost" id="lDiff">查看改动</button>
<button id="lPublish">发布本页</button>
<button class="ghost" id="lPublishAll">全部发布</button>
<span id="lDirty" class="pill"></span>
<span id="lMsg" class="msg"></span>
</div>
<div id="lDiffBox" class="diff-box hidden"></div>
</div>

<div id="p-media" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="mSlug"></select></div>
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button id="mUpload">上传图片</button></div>
<input type="file" id="mFile" accept="image/*" style="display:none">
</div>
<div class="media-grid" id="mGrid"></div>
<div class="msg" id="mMsg"></div>
</div>

<div id="p-share" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="sSlug"></select></div>
<div class="field"><label>有效天数</label><input id="sDays" type="number" value="14" min="1" max="365"></div>
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button id="sCreate">生成预览链接</button></div>
</div>
<div id="sList" style="margin-top:16px"></div>
<div class="msg" id="sMsg"></div>
</div>

<div id="p-domain" class="hidden">
<div class="callout">本地模拟：浏览器用 hosts 把域名指向本机，请求经隧道进入后台，再按 Host 头转发到对应站点。证书是自签的，浏览器会提示不安全，点继续即可。</div>
<div id="dList" style="margin-top:14px"></div>
<div class="msg" id="dMsg"></div>
</div>

<div id="p-leads" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="ldSlug"></select></div>
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button class="ghost" id="ldRefresh">刷新</button></div>
</div>
<div id="ldList" style="margin-top:16px"></div>
<div class="msg" id="ldMsg"></div>
</div>

<div id="p-maint" class="hidden">
<div class="callout">镜像更新检查：拉取 wordpress / mariadb / wp-cli 三个镜像，比对运行中容器的 image ID。定时任务每周一 09:00 自动执行。</div>
<div class="formrow" style="margin-top:14px">
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button id="mtCheck">立即检查</button></div>
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button class="ghost" id="mtApply">重建过期站点</button></div>
<div class="field"><label>&nbsp;</label><span id="mtStatus" class="msg"></span></div>
</div>
<div id="mtBody" style="margin-top:14px"></div>
<div class="callout" style="margin-top:18px"><b style="color:var(--fg)">邮件发送</b>
  <div style="font-size:12px;color:var(--dim);margin-top:4px">云主机通常封了 587/465，建议用 HTTPS 邮件 API（Resend / SendGrid）</div>
  <div class="formrow" style="margin-top:10px">
    <div class="field" style="flex:0 0 180px"><label>发送方式</label>
      <select id="smProvider"><option value="resend">Resend API</option>
      <option value="sendgrid">SendGrid API</option><option value="smtp">SMTP</option></select></div>
    <div class="field" style="flex:1"><label>API Key（选 API 时填）</label>
      <input id="smKey" type="password" placeholder="re_... / SG...."></div>
  </div>
  <div class="formrow" style="margin-top:10px">
    <div class="field" style="flex:0 0 190px"><label>SMTP 主机</label><input id="smHost" placeholder="smtp.zoho.com"></div>
    <div class="field" style="flex:0 0 90px"><label>端口</label><input id="smPort" value="587"></div>
    <div class="field" style="flex:0 0 180px"><label>用户名</label><input id="smUser" placeholder="ops@yourdomain.sg"></div>
    <div class="field" style="flex:0 0 160px"><label>密码</label><input id="smPass" type="password" placeholder="留空则不修改"></div>
    <div class="field" style="flex:0 0 180px"><label>发件人</label><input id="smFrom" placeholder="KampongFlow <ops@...>"></div>
  </div>
  <div class="formrow" style="margin-top:10px">
    <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
      <label class="chk" style="margin-top:6px"><input type="checkbox" id="smTls" checked> 使用 STARTTLS</label></div>
    <div class="field" style="flex:0 0 200px"><label>测试收件地址</label><input id="smTo" placeholder="you@example.com"></div>
    <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
      <button class="ghost" onclick="saveSmtp()">保存</button>
      <button class="ghost" onclick="testSmtp()">发送测试</button>
      <button class="ghost" onclick="runDigest()">立即发送日报</button></div>
    <div class="msg" id="smMsg"></div>
  </div>
</div>
</div>

<div id="p-client" class="hidden">
<div class="formrow">
<div class="field"><label>客户</label><select id="clSlug"></select></div>
<div class="field" style="flex:0 0 auto"><label>预付款余额</label>
  <div id="clBal" style="font-size:16px;font-weight:650;padding-top:6px">—</div></div>
</div>
<div id="clBoard" style="margin-top:16px"></div>
<div id="clForm" style="margin-top:16px"></div>
<div id="clLedger" style="margin-top:18px"></div>
<div class="msg" id="clMsg"></div>
</div>

<div id="p-team" class="hidden">
<div class="callout">每个员工一个账号，所有写操作都会记进审计日志。只有管理员能管理账号。</div>
<div id="tmSec" style="margin-top:14px"></div>
<div id="tmMe" style="margin-top:14px"></div>
<div class="callout" style="margin-top:12px"><b style="color:var(--fg)">修改密码</b>
  <div class="formrow" style="margin-top:10px">
    <div class="field" style="flex:0 0 190px"><label>旧密码</label><input id="pwOld" type="password" autocomplete="current-password"></div>
    <div class="field" style="flex:0 0 190px"><label>新密码（至少 10 位）</label><input id="pwNew" type="password" autocomplete="new-password"></div>
    <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
      <button class="ghost" onclick="changePw()">保存</button></div>
    <div class="msg" id="pwMsg"></div>
  </div></div>
<div id="tmRecovery"></div>
<div id="tmList" style="margin-top:14px"></div>
<div class="formrow" style="margin-top:14px">
  <div class="field" style="flex:0 0 140px"><label>用户名</label><input id="tmUser" placeholder="alice"></div>
  <div class="field" style="flex:0 0 140px"><label>显示名</label><input id="tmName" placeholder="Alice"></div>
  <div class="field" style="flex:0 0 120px"><label>角色</label>
    <select id="tmRole"><option value="ops">运营</option><option value="finance">财务</option><option value="admin">管理员</option></select></div>
  <button class="ghost" onclick="addUser()">新建账号</button>
</div>
<div class="msg" id="tmMsg"></div>
<div style="font-size:12px;color:var(--dim);margin:18px 0 6px">写入权限（每行一条路径前缀，留空=全禁，管理员固定全开）</div>
<div id="tmRoles"></div>
<div style="font-size:12px;color:var(--dim);margin:18px 0 6px">操作日志</div>
<div class="formrow" style="margin-bottom:8px">
  <div class="field" style="flex:0 0 140px"><label>操作人</label><select id="auUser"><option value="">全部</option></select></div>
  <div class="field" style="flex:0 0 160px"><label>关键词</label><input id="auKey" placeholder="client_save"></div>
  <div class="field" style="flex:0 0 150px"><label>起</label><input id="auFrom" type="date"></div>
  <div class="field" style="flex:0 0 150px"><label>止</label><input id="auTo" type="date"></div>
  <div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button class="ghost" onclick="loadAudit()">查询</button></div>
</div>
<div id="tmAudit"></div>
</div>

<div id="p-dns" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="dnSlug"></select></div>
<div class="field" style="flex:0 0 auto"><label>&nbsp;</label><button class="ghost" id="dnRefresh">刷新</button></div>
</div>
<div id="dnBody" style="margin-top:16px"></div>
<div class="msg" id="dnMsg"></div>
</div>

<div id="p-design" class="hidden">
<div class="formrow">
<div class="field"><label>站点</label><select id="dSlug"></select></div>
<div class="field"><label>预设</label><select id="dPreset"></select></div>
</div>
<div class="formrow" style="margin-top:10px">
<div class="field"><label>主色</label><input type="color" id="cPrimary"></div>
<div class="field"><label>强调色</label><input type="color" id="cAccent"></div>
<div class="field"><label>背景色</label><input type="color" id="cBg"></div>
<div class="field"><label>卡片圆角 <span id="rVal"></span></label><input type="range" id="rRadius" min="0" max="28" step="1"></div>
<div class="field"><label>按钮</label><select id="sButton"><option value="999px">胶囊</option><option value="10px">圆角</option><option value="4px">方正</option></select></div>
<div class="field"><label>标题字体</label><select id="sHead"><option value="sans">无衬线</option><option value="serif">衬线</option><option value="rounded">圆润</option></select></div>
</div>
<div style="margin-top:14px"><button id="dSave">应用设计</button> <span id="dmsg" class="msg"></span></div>
<div class="design-grid">
  <div class="preview" id="pv">
    <div class="pv-hero" id="pvHero"><div class="pv-kicker">PRESCHOOL · SINGAPORE</div>
      <div class="pv-h1">Little Gems</div>
      <div class="pv-p">A play-based bilingual preschool.</div>
      <div class="pv-btn" id="pvBtn">Book a Visit</div></div>
    <div class="pv-card" id="pvCard"><b>Character</b><div class="pv-small">Grounded in solid character.</div></div>
  </div>
  <div class="preview" style="font-size:12.5px;color:#8b949e">
    <b style="color:#e6edf3">令牌说明</b>
    <div style="margin-top:8px;line-height:1.7">
    主色决定首屏、页脚、按钮与卡片色条；<br>
    背景色影响整页底色；<br>
    圆角同时作用于卡片与图片；<br>
    字体只换标题，正文保持不变。
    </div>
    <div style="margin-top:10px;color:#58a6ff" id="pvMeta"></div>
  </div>
</div>
</div>

<footer id="foot"></footer>
</div>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money=n=>'S$ '+Number(n||0).toLocaleString('en-SG',{minimumFractionDigits:0});
let STATE={sites:[],invoices:[],plans:[]};
let ROLE='ops';
function applyRole(){
  const hidden = ROLE==='finance'
    ? ['layout','design','media','share','dns','maint','team']
    : (ROLE==='admin' ? [] : ['team']);
  document.querySelectorAll('.tab').forEach(el=>{
    el.style.display = hidden.includes(el.dataset.t) ? 'none' : '';
  });
  const f=$('#f'); if(f) f.style.display = (ROLE==='finance') ? 'none' : '';
}
function badge(s){const m={active:['ok','运行中'],provisioning:['warn','开通中'],failed:['bad','失败'],stopped:['bad','已停止']};
 const [c,t]=m[s]||['warn',s];return `<span class="dot ${c}"></span>${t}`}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));t.classList.add('on');
 ['sites','billing','plans','layout','media','share','domain','leads','maint','client','team','dns','design'].forEach(k=>$('#p-'+k).classList.toggle('hidden',k!==t.dataset.t));
 if(t.dataset.t==='design') initDesign();
 if(t.dataset.t==='layout') initLayout();
 if(t.dataset.t==='media') initMedia();
 if(t.dataset.t==='share') initShare();
 if(t.dataset.t==='domain') initDomain();
 if(t.dataset.t==='leads') initLeads();
 if(t.dataset.t==='maint') initMaint();
 if(t.dataset.t==='client') initClient();
 if(t.dataset.t==='team') initTeam();
 if(t.dataset.t==='dns') initDns();});
function renderSites(){
  let s=(STATE.sites||[]);
  if($('#onlyMine') && $('#onlyMine').checked && STATE.me){
    s=s.filter(x=>x.owner===STATE.me);
  }
  $('#rows').innerHTML=s.length? s.map(x=>`<tr>
  <td class="mono">${esc(x.slug)}</td>
  <td><b>${esc(x.company)}</b><div class="mono" style="color:var(--dim)">${esc(x.domain)}</div></td>
  <td class="sm-hide" style="font-size:12.5px;color:var(--dim)">${esc(x.owner)||'—'}</td>
  <td class="sm-hide">${esc(x.plan)||'-'}</td>
  <td>${badge(x.state)}<div class="mono" style="color:var(--dim);font-size:11.5px">HTTP ${x.http||'-'} · ${x.running}/2</div>
   ${x.message?`<div style="color:var(--bad);font-size:11.5px">${esc(x.message)}</div>`:''}</td>
  <td class="sm-hide">${x.invoice?`<a href="/api/invoice/${encodeURIComponent(x.invoice)}/pdf">${esc(x.invoice)}</a>
   <div style="color:var(--dim);font-size:11.5px">${x.invoice_status==='paid'?'已付':'待付'}</div>`
   :`<button class="ghost" onclick="issue('${esc(x.slug)}')">开票</button>`}</td>
  <td>${expiryCell(x)}</td>
  <td>${x.http===200?`<a href="http://${location.hostname}:${x.port}/" target="_blank">打开</a>　`:''}
   <a href="/api/site/${encodeURIComponent(x.slug)}/handover.pdf">交接单</a>
   <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
     ${ROLE==='finance'?'':`<button class="ghost" onclick="renewSite('${esc(x.slug)}')">续费</button>
     <button class="ghost" onclick="toggleSuspend('${esc(x.slug)}','${x.billing_status||'active'}')">${x.billing_status==='suspended'?'恢复':'暂停'}</button>`}
   </div></td></tr>`).join('')
  :'<tr><td colspan="8" style="text-align:center;padding:28px 12px">'
    +'<div style="color:var(--dim);font-size:13px;margin-bottom:10px">还没有站点，先开通一个</div>'
    +'<button onclick="document.querySelector(\'#f input[name=company]\').focus()">开通站点</button></td></tr>';
}

async function load(){
 const r=await fetch('/api/state');STATE=await r.json();
 ROLE=STATE.role||'ops'; applyRole();
 if($('#whoami')) $('#whoami').textContent=(STATE.me||'')+'（'+({admin:'管理员',ops:'运营',finance:'财务'}[ROLE]||ROLE)+'）';
 const s=STATE.sites||[];
 $('#stats').innerHTML=`<div class="stat"><b>${s.length}</b><span>站点</span></div>
  <div class="stat"><b>${s.filter(x=>x.state==='active').length}</b><span>运行中</span></div>
  <div class="stat"><b>${s.filter(x=>x.http===200).length}</b><span>HTTP 正常</span></div>`;
 renderSites();
 $('#planSel').innerHTML=(STATE.plans||[]).map(p=>`<option value="${p.id}">${esc(p.name)} — ${money(p.price)}</option>`).join('');
 $('#indSel').innerHTML=(STATE.industries||[]).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');
 const iv=STATE.invoices||[];
 const paid=iv.filter(i=>i.status==='paid'),unpaid=iv.filter(i=>i.status!=='paid');
 $('#billStats').innerHTML=`<div class="stat"><b>${money(paid.reduce((a,b)=>a+b.total,0))}</b><span>已收款</span></div>
  <div class="stat"><b>${money(unpaid.reduce((a,b)=>a+b.total,0))}</b><span>待收款</span></div>
  <div class="stat"><b>${iv.length}</b><span>账单数</span></div>`;
 $('#billRows').innerHTML=iv.length?iv.map(i=>`<tr>
  <td class="mono">${esc(i.no)}</td><td>${esc(i.company)}</td><td>${esc(i.plan_name)}</td>
  <td class="mono">${money(i.total)}</td>
  <td><span class="pill" style="color:${i.status==='paid'?'var(--ok)':'var(--warn)'}">${i.status==='paid'?'已付款':'待付款'}</span></td>
  <td class="mono" style="color:var(--dim)">${esc(i.issued_at)}</td>
  <td><a href="/api/invoice/${encodeURIComponent(i.no)}/pdf">PDF</a>
   ${i.status!=='paid'?`　<button class="ghost" onclick="pay('${esc(i.no)}')">标记已付</button>`:''}</td></tr>`).join('')
  :'<tr><td colspan="7" style="color:var(--dim)">暂无账单</td></tr>';
 $('#planRows').innerHTML=(STATE.plans||[]).map(p=>`<tr><td><b>${esc(p.name)}</b>
  <div class="mono" style="color:var(--dim);font-size:11.5px">${esc(p.id)}</div></td>
  <td class="mono">${money(p.price)} <span style="color:var(--dim)">/ ${esc(p.period)}</span></td>
  <td>${esc(p.specs)}</td><td><a href="#" onclick="editPlan('${esc(p.id)}');return false">编辑</a></td></tr>`).join('');
 $('#foot').textContent='最后刷新 '+new Date().toLocaleTimeString();
}

function expiryCell(x){
  const d=x.days_left;
  if(d===null||d===undefined) return '<span style="color:var(--dim)">—</span>';
  const color = d<0 ? 'var(--bad)' : (d<30 ? 'var(--warn)' : 'var(--dim)');
  const label = d<0 ? ('已过期 '+(-d)+' 天') : (d+' 天后');
  return `<span style="color:${color}">${esc(x.expires||'')}</span>
    <div style="font-size:11.5px;color:${color}">${d<0?'已过期':''}${d>=0?label:''}</div>`;
}
async function renewSite(slug){
  const y=prompt('续费几年？（1-5）','1'); if(!y) return;
  const r=await fetch('/api/renew',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:slug,years:Number(y)})});
  const d=await r.json();
  if(r.ok){ alert('已续费至 '+d.expires+'\n账单 '+d.invoice); load(); }
  else alert('失败：'+(d.error||''));
}
async function toggleSuspend(slug,status){
  const act = status==='suspended' ? 'start' : 'stop';
  if(!confirm(act==='stop'?'暂停该站点？客户将无法访问。':'恢复该站点？')) return;
  const r=await fetch('/api/suspend',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:slug,action:act})});
  const d=await r.json();
  if(!r.ok) alert('失败：'+(d.error||''));
  load();
}

async function issue(slug){
 const r=await fetch('/api/invoice/issue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug})});
 const d=await r.json(); if(!r.ok)alert(d.error||'失败'); load();}
async function pay(no){
 const r=await fetch('/api/invoice/pay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({no})});
 const d=await r.json(); if(!r.ok)alert(d.error||'失败'); load();}
function editPlan(id){const p=STATE.plans.find(x=>x.id===id);const f=$('#pf');
 f.id.value=p.id;f.name.value=p.name;f.price.value=p.price;f.period.value=p.period;f.specs.value=p.specs;
 $('#pmsg').textContent='编辑中：'+p.name;}
$('#f').addEventListener('submit',async e=>{e.preventDefault();
 const fd=new FormData(e.target);$('#btn').disabled=true;$('#msg').className='msg';$('#msg').textContent='提交中…';
 try{const r=await fetch('/api/create',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(Object.fromEntries(fd))});const d=await r.json();
  if(!r.ok){$('#msg').className='msg bad';$('#msg').textContent=d.error||'失败'}
  else{$('#msg').className='msg ok';$('#msg').textContent=`已下单 ${d.invoice}，正在开通 ${d.slug}（约 60 秒）`;e.target.reset()}}
 catch(err){$('#msg').className='msg bad';$('#msg').textContent=String(err)}
 $('#btn').disabled=false;load();});
$('#pf').addEventListener('submit',async e=>{e.preventDefault();
 const fd=Object.fromEntries(new FormData(e.target));fd.price=Number(fd.price);
 const r=await fetch('/api/plan/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(fd)});
 const d=await r.json();$('#pmsg').className='msg '+(r.ok?'ok':'bad');
 $('#pmsg').textContent=r.ok?'已保存':(d.error||'失败');load();});









// ---------------- DNS ----------------
let DNSINFO=null;
function dnsRow(r,i){
  const locked=(r.type==='SOA'||r.type==='NS')&&r.name==='@';
  return `<div class="dom-row" style="padding:8px 12px"><div class="h">
    <span class="name" style="min-width:110px">${esc(r.name)}</span>
    <span style="min-width:52px;color:var(--fg)">${esc(r.type)}</span>
    <span class="hint" style="margin:0;flex:1">${esc(r.value)}</span>
    <span style="color:var(--dim);font-size:11.5px">TTL ${r.ttl}</span>
    ${locked?'<span style="color:var(--dim);font-size:11.5px">系统</span>'
            :`<button onclick="delDns(${i})">删除</button>`}
  </div></div>`;
}
async function loadDns(slug){
  const r=await fetch('/api/dns/'+encodeURIComponent(slug));
  const d=await r.json(); DNSINFO=d;
  const box=$('#dnBody');
  if(!d.enabled){
    const noPlan = d.plan_dns === false;
    box.innerHTML=`<div class="callout">这个站点还没有托管 DNS。启用后会自动创建区，并把 @ 与 www 指到服务器。</div>`
      + (noPlan
          ? `<div style="margin-top:14px;color:var(--warn);font-size:13px">当前套餐「${esc(d.plan_name||'')}」不含 DNS 托管，请先升级套餐。</div>`
          : `<div style="margin-top:14px"><button onclick="enableDns()">启用 DNS 托管</button></div>`);
    return;
  }
  const dm=d.domain_manage||{};
  const dd=d.domain_days;
  const recs=(d.zone.records||[]).map(dnsRow).join('');
  const dmCard=`<div class="callout" style="margin-bottom:14px">
      <b style="color:var(--fg)">域名代管</b>
      ${dd===null||dd===undefined?'':`（${dd<0?'已过期 '+(-dd)+' 天':'还剩 '+dd+' 天'}）`}
      <div class="formrow" style="margin-top:10px">
        <div class="field" style="flex:0 0 150px"><label>注册商</label>
          <input id="dmReg" value="${esc(dm.registrar||'')}" placeholder="Vodien / Namecheap"></div>
        <div class="field" style="flex:0 0 150px"><label>到期日</label>
          <input id="dmExp" value="${esc(dm.expires||'')}" placeholder="2027-11-02"></div>
        <div class="field" style="flex:0 0 170px"><label>归属</label>
          <select id="dmOwner">
            <option value="us" ${dm.owner!=='client'?'selected':''}>在我们账户（代管）</option>
            <option value="client" ${dm.owner==='client'?'selected':''}>在客户账户</option>
          </select></div>
        <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
          <label class="chk" style="margin-top:6px"><input type="checkbox" id="dmAuto" ${dm.auto_renew?'checked':''}> 自动续费</label></div>
        <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
          <button class="ghost" onclick="saveDomain()">保存</button></div>
      </div></div>`;
  box.innerHTML=dmCard+`
    <div class="callout">把域名的 NS 改成下面两条，解析就由我们接管。<br>
      <b style="color:var(--acc)">${esc(d.ns[0])}</b>　<b style="color:var(--acc)">${esc(d.ns[1])}</b><br>
      当前演示端口 ${d.demo_port}（生产为 ${d.port}）</div>
    <div class="formrow" style="margin-top:12px">
      <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
        <button class="ghost" onclick="checkDns('/api/dns/check')">本机解析检查</button>
        <button class="ghost" onclick="checkDns('/api/dns/delegation')">公网委托检测</button></div>
      <div class="field"><label>&nbsp;</label><span style="font-size:12px;color:var(--dim)">DNSSEC：未启用（演示解析器不支持签名，生产接 PowerDNS 后可开）</span></div>
    </div>
    <div id="dnCheck"></div>
    <div style="font-size:12px;color:var(--dim);margin:14px 0 6px">记录（${(d.zone.records||[]).length}）</div>
    ${recs}
    <div class="formrow" style="margin-top:14px">
      <div class="field" style="flex:0 0 130px"><label>名称</label><input id="dnName" placeholder="@ 或 www"></div>
      <div class="field" style="flex:0 0 110px"><label>类型</label>
        <select id="dnType"><option>A</option><option>AAAA</option><option>CNAME</option>
        <option>MX</option><option>TXT</option><option>NS</option><option>SRV</option></select></div>
      <div class="field"><label>值</label><input id="dnValue" placeholder="101.204.233.11"></div>
      <div class="field" style="flex:0 0 90px"><label>TTL</label><input id="dnTtl" value="300"></div>
      <button class="ghost" onclick="addDns()">添加记录</button>
    </div>`;
}
async function enableDns(){
  const r=await fetch('/api/dns/enable',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:$('#dnSlug').value})});
  const d=await r.json();
  $('#dnMsg').className='msg '+(r.ok?'ok':'bad');
  $('#dnMsg').textContent=r.ok?('已托管 '+d.domain):('失败：'+(d.error||''));
  loadDns($('#dnSlug').value);
}
async function addDns(){
  const body={slug:$('#dnSlug').value,name:$('#dnName').value||'@',type:$('#dnType').value,
    value:$('#dnValue').value,ttl:Number($('#dnTtl').value)||300};
  const r=await fetch('/api/dns/record',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  const d=await r.json();
  $('#dnMsg').className='msg '+(r.ok?'ok':'bad');
  $('#dnMsg').textContent=r.ok?'记录已添加':('失败：'+(d.error||''));
  if(r.ok) loadDns($('#dnSlug').value);
}
async function delDns(i){
  if(!confirm('删除这条记录？')) return;
  const r=await fetch('/api/dns/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:$('#dnSlug').value,index:i})});
  const d=await r.json();
  $('#dnMsg').className='msg '+(r.ok?'ok':'bad');
  $('#dnMsg').textContent=r.ok?'已删除':('失败：'+(d.error||''));
  if(r.ok) loadDns($('#dnSlug').value);
}
async function saveDomain(){
  const r=await fetch('/api/domain/manage',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:$('#dnSlug').value, registrar:$('#dmReg').value,
      expires:$('#dmExp').value, owner:$('#dmOwner').value,
      auto_renew:$('#dmAuto').checked})});
  const d=await r.json();
  $('#dnMsg').className='msg '+(r.ok?'ok':'bad');
  $('#dnMsg').textContent=r.ok?'域名信息已保存':('失败：'+(d.error||''));
  if(r.ok) loadDns($('#dnSlug').value);
}
async function checkDns(ep){
  const box=$('#dnCheck');
  box.innerHTML='<div style="color:var(--dim);font-size:13px;margin-top:10px">检查中…（公网检测需要几秒）</div>';
  const r=await fetch(ep||'/api/dns/check',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:$('#dnSlug').value})});
  const d=await r.json();
  if(!r.ok){ box.innerHTML='<div class="msg bad">'+(d.error||'检查失败')+'</div>'; return; }
  const ico={ok:'\u2713',warn:'!',fail:'\u2717'};
  const col={ok:'var(--ok)',warn:'var(--warn)',fail:'var(--bad)'};
  box.innerHTML='<div style="margin-top:12px">'+d.checks.map(c=>`
    <div class="dom-row" style="padding:8px 12px"><div class="h">
      <span style="color:${col[c.status]};min-width:16px">${ico[c.status]}</span>
      <span class="name" style="min-width:110px">${esc(c.name)}</span>
      <span class="hint" style="margin:0;flex:1">${esc(c.detail)}</span>
    </div></div>`).join('')+'</div>';
}
function initDns(){
  const sel=$('#dnSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadDns(sel.value);
    $('#dnRefresh').onclick=()=>loadDns(sel.value);
  }
  loadDns(sel.value);
}

// ---------------- 客户 ----------------
const SCOPE_OPTS=["建站","托管","域名代管","企业邮箱","解析托管","内容维护","技术支持"];
function clField(id,label,val,ph){
  return `<div class="field"><label>${label}</label><input id="${id}" value="${esc(val||'')}" placeholder="${esc(ph||'')}"></div>`;
}
function renderClient(c, bal){
  $('#clBal').textContent='S$ '+(bal||0).toLocaleString('en-SG');
  const scope=SCOPE_OPTS.map(s=>`<label class="chk" style="display:inline-flex;margin-right:14px">
      <input type="checkbox" class="clScope" value="${s}" ${(c.scope||[]).includes(s)?'checked':''}> ${s}</label>`).join('');
  $('#clForm').innerHTML=`
    <div class="formrow">
      ${clField('cContact','联系人',c.contact,'Ms Tan')}
      ${clField('cPhone','电话 / WhatsApp',c.phone,'+65 9000 0000')}
      ${clField('cEmail','邮箱',c.email,'a@b.sg')}
      ${clField('cUen','UEN / 注册号',c.uen,'201912345K')}
    </div>
    <div class="formrow" style="margin-top:10px">
      ${clField('cAgr','协议编号',c.agreement_no,'KF-A-2026-0001')}
      ${clField('cAgrDate','签署日',c.agreement_date,'2026-11-02')}
      ${clField('cStart','服务开始',c.service_start,'2026-11-02')}
      ${clField('cEnd','服务到期',c.service_end,'2027-11-02')}
      ${clField('cFee','年费 (SGD)',c.annual_fee,'4200')}
      <div class="field"><label>负责人</label><select id="cOwner"></select></div>
    </div>
    <div class="fld" style="margin-top:12px"><label>服务范围</label><div>${scope}</div></div>
    <div class="fld"><label>备注</label><textarea id="cNotes" style="min-height:60px">${esc(c.notes||'')}</textarea></div>
    <button onclick="saveClient()">保存客户档案</button>`;
  const sel=$('#cOwner');
  const me=STATE.me||'';
  sel.innerHTML='<option value="">未指定</option>'+((STATE.staff)||[]).map(u=>
    `<option value="${esc(u)}" ${u===c.owner?'selected':''}>${esc(u)}${u===me?'（我）':''}</option>`).join('');
}
function daysBadge(d, auto){
  if(d===null||d===undefined) return '<span style="color:var(--dim)">未记录</span>';
  const col = d<0 ? 'var(--bad)' : d<=30 ? 'var(--warn)' : d<=60 ? 'var(--warn)' : 'var(--dim)';
  const txt = d<0 ? ('已过期 '+(-d)+' 天') : (d+' 天');
  return `<span style="color:${col}">${txt}</span>` + (auto?'':' <span style="color:var(--bad);font-size:11px">未开自动续费</span>');
}
async function loadBoard(){
  const r=await fetch('/api/renewals'); const d=await r.json();
  const items=d.items||[];
  const urgent=items.filter(x=>x.domain_days!==null && x.domain_days<=60);
  const head=`<div style="font-size:12px;color:var(--dim);margin-bottom:6px">
      续费待办 · 共 ${items.length} 个域名，${urgent.length} 个 60 天内到期</div>`;
  const rows=items.map(x=>{
    const flag=(x.domain_days!==null&&x.domain_days<=30)?'box-shadow:inset 3px 0 0 var(--warn);':'';
    return `<div class="dom-row" style="padding:8px 12px;${flag}"><div class="h">
      <span class="name" style="min-width:120px">${esc(x.company)}</span>
      <span class="hint" style="margin:0;flex:1">${esc(x.domain||'—')} · ${esc(x.registrar||'未登记')}</span>
      <span style="min-width:120px;font-size:12px">域名 ${daysBadge(x.domain_days,x.auto_renew)}</span>
      <span style="min-width:120px;font-size:12px;color:var(--dim)">服务 ${daysBadge(x.service_days,true)}</span>
      <button onclick="$('#clSlug').value='${esc(x.slug)}';loadClient('${esc(x.slug)}');window.scrollTo(0,0)">查看</button>
    </div></div>`;
  }).join('');
  $('#clBoard').innerHTML=head+(rows||'<div style="color:var(--dim);font-size:13px">还没有域名记录</div>');
}
async function loadClient(slug){
  const [cs, lg]=await Promise.all([
    fetch('/api/clients').then(r=>r.json()),
    fetch('/api/ledger/'+encodeURIComponent(slug)).then(r=>r.json())]);
  const row=(cs.items||[]).find(x=>x.slug===slug);
  renderClient(row?row.client:{}, lg.balance||0);
  const rows=lg.items||[];
  $('#clLedger').innerHTML=`<div style="font-size:12px;color:var(--dim);margin-bottom:6px">收支流水（${rows.length}）</div>`
    + (rows.length? rows.map(x=>`<div class="dom-row" style="padding:8px 12px"><div class="h">
        <span class="name" style="min-width:76px">${esc(x.id)}</span>
        <span style="min-width:52px;color:${x.type==='topup'?'var(--ok)':'var(--warn)'}">${x.type==='topup'?'收入':'支出'}</span>
        <span class="hint" style="margin:0;flex:1">${esc(x.category)} · ${esc(x.note||'')}</span>
        <span style="min-width:88px;text-align:right">S$ ${Number(x.amount).toLocaleString('en-SG')}</span>
        <span style="color:var(--dim);font-size:11.5px;min-width:70px;text-align:right">${esc(x.by||'-')}</span>
        <span style="color:var(--dim);font-size:11.5px;min-width:112px;text-align:right">${esc(x.ts)}</span>
      </div></div>`).join('')
      : '<div style="color:var(--dim);font-size:13px">还没有流水</div>')
    + `<div class="formrow" style="margin-top:12px">
        <div class="field" style="flex:0 0 110px"><label>类型</label>
          <select id="lgType"><option value="topup">收入</option><option value="cost">支出</option></select></div>
        <div class="field" style="flex:0 0 110px"><label>金额</label><input id="lgAmt" placeholder="1200"></div>
        <div class="field" style="flex:0 0 130px"><label>类别</label>
          <select id="lgCat"><option>服务费</option><option>域名</option><option>服务器</option><option>证书</option><option>工时</option><option>其他</option></select></div>
        <div class="field"><label>备注</label><input id="lgNote" placeholder="首年服务费"></div>
        <button class="ghost" onclick="addLedger()">记一笔</button>
      </div>`;
}
async function saveClient(){
  const scope=[...document.querySelectorAll('.clScope:checked')].map(x=>x.value);
  const body={slug:$('#clSlug').value, contact:$('#cContact').value, phone:$('#cPhone').value,
    email:$('#cEmail').value, uen:$('#cUen').value, agreement_no:$('#cAgr').value,
    agreement_date:$('#cAgrDate').value, service_start:$('#cStart').value,
    service_end:$('#cEnd').value, annual_fee:Number($('#cFee').value)||0,
    notes:$('#cNotes').value, scope:scope, owner:$('#cOwner').value};
  const r=await fetch('/api/clients/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  $('#clMsg').className='msg '+(r.ok?'ok':'bad');
  $('#clMsg').textContent=r.ok?'客户档案已保存':('失败：'+(d.error||''));
}
async function addLedger(){
  const body={slug:$('#clSlug').value,type:$('#lgType').value,amount:Number($('#lgAmt').value)||0,
    category:$('#lgCat').value,note:$('#lgNote').value};
  const r=await fetch('/api/ledger',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  $('#clMsg').className='msg '+(r.ok?'ok':'bad');
  $('#clMsg').textContent=r.ok?'已记账':('失败：'+(d.error||''));
  if(r.ok) loadClient($('#clSlug').value);
}
function initClient(){
  loadBoard();
  const sel=$('#clSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadClient(sel.value);
  }
  loadClient(sel.value);
}

// ---------------- 团队 ----------------
async function loadTeam(){
  const [u,a]=await Promise.all([
    fetch('/api/users').then(r=>r.json()),
    fetch('/api/audit').then(r=>r.json())]);
  $('#tmList').innerHTML=(u.items||[]).map(x=>`
    <div class="dom-row" style="padding:9px 12px"><div class="h">
      <span class="name" style="min-width:96px">${esc(x.user)}</span>
      <span style="min-width:110px;color:var(--fg)">${esc(x.name)}</span>
      <span style="min-width:66px;color:${x.role==='admin'?'var(--acc)':'var(--dim)'}">${x.role==='admin'?'管理员':x.role==='finance'?'财务':'运营'}</span>
      <span class="hint" style="margin:0;flex:1">${x.active?'启用':'已停用'}${x.mfa?` · <span style="color:var(--ok)">MFA</span> 恢复码 ${x.recovery_left}`:''}${x.locked?` · <span style="color:var(--bad)">已锁定</span>`:''}</span>
      <button onclick="userAct('${esc(x.user)}','${x.active?'disable':'enable'}')">${x.active?'停用':'启用'}</button>
      <button onclick="userAct('${esc(x.user)}','reset')">重置密码</button>
      ${x.mfa?`<button onclick="userAct('${esc(x.user)}','reset_mfa')">重置 MFA</button>`:''}
      ${x.locked?`<button onclick="userAct('${esc(x.user)}','unlock')">解锁</button>`:''}
    </div></div>`).join('') || '<div style="color:var(--dim);font-size:13px">还没有账号</div>';
  const us=$('#auUser');
  if(us && us.options.length<=1){
    us.innerHTML='<option value="">全部</option>'+(u.items||[]).map(x=>`<option value="${esc(x.user)}">${esc(x.user)}</option>`).join('');
  }
}
async function changePw(){
  const r=await fetch('/api/password',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({old:$('#pwOld').value,new:$('#pwNew').value})});
  const d=await r.json();
  $('#pwMsg').className='msg '+(r.ok?'ok':'bad');
  $('#pwMsg').textContent=r.ok?('密码已修改'+(d.killed?('，已踢掉 '+d.killed+' 个其他会话'):'')):('失败：'+(d.error||''));
  if(r.ok){ $('#pwOld').value=''; $('#pwNew').value=''; }
}
async function loadSecurity(){
  const r=await fetch('/api/security'); const d=await r.json();
  const items=d.items||[];
  const bad=[];
  if(items.some(x=>!x.mfa)) bad.push(items.filter(x=>!x.mfa).length+' 个账号未开两步验证');
  if(items.some(x=>x.locked)) bad.push(items.filter(x=>x.locked).length+' 个账号被锁定');
  if(items.some(x=>x.pwd_age!==null && x.pwd_age!==undefined && x.pwd_age>180)) bad.push('有账号密码超过 180 天未更换');
  if((d.blocked_ips||[]).length) bad.push((d.blocked_ips||[]).length+' 个 IP 被临时拦截');
  const roleName={admin:'管理员',ops:'运营',finance:'财务'};
  const rows=items.map(x=>{
    const mfa = x.mfa
      ? `<span style="color:var(--ok)">已开</span> <span style="color:var(--dim);font-size:11.5px">码 ${x.recovery_left}</span>`
      : `<span style="color:var(--warn)">未开</span>`;
    const age = (x.pwd_age===null||x.pwd_age===undefined) ? '—'
      : `<span style="color:${x.pwd_age>180?'var(--warn)':'var(--fg)'}">${x.pwd_age} 天前</span>`;
    return `<div class="dom-row" style="padding:8px 12px"><div class="h">
      <span class="name" style="min-width:80px">${esc(x.user)}</span>
      <span style="min-width:52px;color:var(--dim);font-size:12px">${roleName[x.role]||x.role}</span>
      <span style="min-width:84px;font-size:12px">${mfa}</span>
      <span style="min-width:84px;font-size:12px">${x.locked?'<span style="color:var(--bad)">已锁定</span>':'正常'}</span>
      <span class="hint" style="margin:0;flex:1;font-size:11.5px">密码 ${age} · 登录 ${esc(x.last_login||'从未')}</span>
    </div></div>`;
  }).join('');
  $('#tmSec').innerHTML=`<div class="callout" style="${bad.length?'border-left-color:var(--warn)':''}">
      <b style="color:var(--fg)">账号安全总览</b>
      <div style="font-size:12.5px;color:${bad.length?'var(--warn)':'var(--ok)'};margin-top:6px">
        ${bad.length?bad.join('；'):'全部账号状态正常'}</div>
      <div style="font-size:11.5px;color:var(--dim);margin-top:6px">
        同一 IP 15 分钟内失败 ${d.ip_limit} 次会被临时拦截</div>
    </div>` + (rows||'');
}
async function loadMfa(){
  const r=await fetch('/api/mfa'); const d=await r.json();
  const box=$('#tmMe');
  if(d.enabled){
    box.innerHTML=`<div class="callout"><b style="color:var(--ok)">两步验证已开启</b>（${esc(d.user)}）
      <div class="formrow" style="margin-top:10px">
        <div class="field" style="flex:0 0 160px"><label>验证码</label><input id="mfaCode" placeholder="6 位数字"></div>
        <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
          <button class="ghost" onclick="mfaAct('regen')">重新生成恢复码</button>
          <button class="ghost" onclick="mfaAct('disable')">关闭两步验证</button></div>
      </div></div>`;
  }else{
    const uri=d.otpauth||'';
    box.innerHTML=`<div class="callout"><b>两步验证未开启</b>（${esc(d.user)}）
      <div style="margin-top:8px;font-size:12.5px;color:var(--dim)">
        1. 在验证器 App（Google Authenticator / 1Password）里手动添加账号<br>
        2. 密钥：<b style="color:var(--acc);font-family:monospace">${esc(d.secret||'')}</b>（或粘贴下面的链接）<br>
        3. 输入 App 显示的 6 位验证码完成绑定</div>
      <div class="hint" style="margin-top:8px">${esc(uri)}</div>
      <div class="formrow" style="margin-top:10px">
        <div class="field" style="flex:0 0 160px"><label>验证码</label><input id="mfaCode" placeholder="6 位数字"></div>
        <div class="field" style="flex:0 0 auto"><label>&nbsp;</label>
          <button onclick="mfaAct('enable')">开启两步验证</button></div>
      </div></div>`;
  }
}
async function mfaAct(act){
  const r=await fetch('/api/mfa',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:act,code:$('#mfaCode').value})});
  const d=await r.json();
  if(!r.ok){ $('#tmMsg').className='msg bad'; $('#tmMsg').textContent='失败：'+(d.error||''); return; }
  $('#tmMsg').className='msg ok';
  if((act==='enable'||act==='regen') && d.recovery){
    $('#tmMsg').textContent='已开启两步验证';
    $('#tmRecovery').innerHTML=`<div class="callout" style="border-left-color:var(--warn)">
      <b style="color:var(--warn)">恢复码（只显示这一次）</b>
      <div style="margin:8px 0;font-family:ui-monospace,Menlo,monospace;font-size:14px;line-height:1.9">
        ${d.recovery.map(c=>esc(c)).join('　')}</div>
      <div style="font-size:12px;color:var(--dim)">手机丢失或换机时，用任一码代替验证码登录，每码只能用一次。请打印或存进密码管理器。</div>
      <button class="ghost" style="margin-top:8px" onclick="copyShare('${d.recovery.join(' ')}')">复制全部恢复码</button>
    </div>`;
  } else {
    $('#tmMsg').textContent = act==='enable'?'已开启两步验证':(act==='regen'?'已生成新恢复码':'已关闭');
  }
  loadMfa();
}
async function addUser(){
  const r=await fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'add',user:$('#tmUser').value,name:$('#tmName').value,role:$('#tmRole').value})});
  const d=await r.json();
  $('#tmMsg').className='msg '+(r.ok?'ok':'bad');
  $('#tmMsg').textContent=r.ok?('已创建 '+d.user+'，初始密码：'+d.password):('失败：'+(d.error||''));
  if(r.ok){ $('#tmUser').value=''; $('#tmName').value=''; loadTeam(); }
}
async function userAct(user,act){
  if(act==='disable' && !confirm('停用 '+user+' ？')) return;
  const r=await fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:act,user:user})});
  const d=await r.json();
  $('#tmMsg').className='msg '+(r.ok?'ok':'bad');
  $('#tmMsg').textContent=r.ok?(act==='reset'?('新密码：'+d.password):'已更新'):('失败：'+(d.error||''));
  loadTeam();
}
function initTeam(){ loadTeam(); loadSecurity(); loadMfa(); loadRoles(); loadAudit(); }


// ---------------- 维护 ----------------
let MT_POLL=null;
function renderUpdates(d){
  const r=d.report||{};
  const body=$('#mtBody');
  if(!r.checked_at){ body.innerHTML='<div style="color:var(--dim);font-size:13px">还没有检查记录，点上面的「立即检查」。</div>'; return; }
  const imgs=(r.images||[]).map(i=>`<div class="dom-row"><div class="h">
      <span class="name">${esc(i.ref.split('/').pop())}</span>
      <span style="color:${i.changed?'var(--warn)':'var(--ok)'}">${i.changed?'有更新':'最新'}</span>
      ${i.changed?`<span class="hint" style="margin:0">${esc(i.before)} → ${esc(i.after)}</span>`:''}
    </div></div>`).join('');
  const sites=(r.sites||[]).map(s=>`<div class="dom-row"><div class="h">
      <span class="name">${esc(s.slug)}</span>
      <span style="color:${s.stale?'var(--warn)':'var(--ok)'}">${s.stale?'需重建':'正常'}</span>
    </div></div>`).join('');
  body.innerHTML=`<div class="hint" style="margin-bottom:10px">上次检查：${esc(r.checked_at)}${r.applied_at?' · 上次重建：'+esc(r.applied_at):''}</div>
    <div style="font-size:12px;color:var(--dim);margin-bottom:6px">镜像</div>${imgs}
    <div style="font-size:12px;color:var(--dim);margin:12px 0 6px">站点</div>${sites||'<div style="color:var(--dim);font-size:13px">无</div>'}`;
}
async function pollUpdates(){
  const r=await fetch('/api/updates'); const d=await r.json();
  renderUpdates(d);
  if(d.running){ $('#mtStatus').className='msg'; $('#mtStatus').textContent = d.mode==='apply'?'重建中…':'检查中…'; }
  else { clearInterval(MT_POLL); MT_POLL=null; $('#mtStatus').className='msg ok'; $('#mtStatus').textContent='完成'; }
}
async function triggerUpdate(act){
  $('#mtStatus').className='msg'; $('#mtStatus').textContent = act==='apply'?'重建中…':'检查中（要拉镜像，可能要几分钟）…';
  const r=await fetch('/api/updates',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:act})});
  const d=await r.json();
  if(!r.ok){ $('#mtStatus').className='msg bad'; $('#mtStatus').textContent=d.error||'失败'; return; }
  if(!MT_POLL) MT_POLL=setInterval(pollUpdates, 3000);
}

// ---------------- SMTP ----------------
async function loadSmtp(){
  const r=await fetch('/api/smtp'); const d=await r.json(); const s=d.smtp||{};
  $('#smProvider').value=s.provider||'resend';
  $('#smKey').value='';
  $('#smHost').value=s.host||''; $('#smPort').value=s.port||587;
  $('#smUser').value=s.user||''; $('#smPass').value='';
  $('#smFrom').value=s.from||''; $('#smTls').checked=s.tls!==false;
}
async function saveSmtp(){
  const body={provider:$('#smProvider').value,api_key:$('#smKey').value,
    host:$('#smHost').value,port:Number($('#smPort').value)||587,
    user:$('#smUser').value,pass:$('#smPass').value,from:$('#smFrom').value,
    tls:$('#smTls').checked};
  const r=await fetch('/api/smtp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  $('#smMsg').className='msg '+(r.ok?'ok':'bad');
  $('#smMsg').textContent=r.ok?'已保存':('失败：'+(d.error||''));
  if(r.ok) loadSmtp();
}
async function runDigest(){
  $('#smMsg').className='msg';
  $('#smMsg').textContent='正在生成并发送…';
  const r=await fetch('/api/notify/run',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  $('#smMsg').className='msg '+(r.ok?'ok':'bad');
  $('#smMsg').textContent=r.ok?('已发送：'+(d.to||'')):('失败：'+(d.error||''));
}
async function testSmtp(){
  const to=$('#smTo').value;
  const r=await fetch('/api/smtp/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:to})});
  const d=await r.json();
  $('#smMsg').className='msg '+(r.ok?'ok':'bad');
  $('#smMsg').textContent=r.ok?('已发送到 '+to):('失败：'+(d.error||''));
}

// ---------------- 权限 ----------------
async function loadRoles(){
  const r=await fetch('/api/roles'); const d=await r.json();
  const items=d.items||{};
  $('#tmRoles').innerHTML=Object.keys(items).map(k=>{
    const v=items[k];
    const val = v.write===null ? '(全部允许)' : (v.write||[]).join('\n');
    return `<div class="fld"><label>${esc(v.label||k)}（${esc(k)}）</label>
      <textarea class="json-edit" style="min-height:70px" data-role="${esc(k)}"
        ${v.write===null?'disabled':''}>${esc(val)}</textarea>
      ${v.write===null?'':`<button class="ghost" style="margin-top:6px" onclick="saveRole('${esc(k)}')">保存</button>`}</div>`;
  }).join('');
}
async function saveRole(role){
  const el=[...document.querySelectorAll('[data-role]')].find(x=>x.dataset.role===role);
  const write=el.value.split('\n').map(x=>x.trim()).filter(Boolean);
  const r=await fetch('/api/roles',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:role,write:write})});
  const d=await r.json();
  $('#tmMsg').className='msg '+(r.ok?'ok':'bad');
  $('#tmMsg').textContent=r.ok?('已更新 '+role):('失败：'+(d.error||''));
}
async function loadAudit(){
  const q=new URLSearchParams();
  if($('#auUser').value) q.set('user',$('#auUser').value);
  if($('#auKey').value) q.set('action',$('#auKey').value);
  if($('#auFrom').value) q.set('since',$('#auFrom').value);
  if($('#auTo').value) q.set('until',$('#auTo').value);
  const r=await fetch('/api/audit?'+q.toString());
  const d=await r.json();
  $('#tmAudit').innerHTML=(d.items||[]).slice(0,80).map(e=>`
    <div class="dom-row" style="padding:6px 12px"><div class="h">
      <span class="name" style="min-width:76px">${esc(e.user)}</span>
      <span class="hint" style="margin:0;flex:1">${esc(e.action)}${e.detail?` · ${esc(e.detail)}`:''}${e.target?` · ${esc(e.target)}`:''}</span>
      <span style="color:var(--dim);font-size:11.5px">${esc(e.ts)}</span>
    </div></div>`).join('') || '<div style="color:var(--dim);font-size:13px">没有匹配记录</div>';
}

function initMaint(){
  loadSmtp();
  if(!$('#mtCheck').onclick){
    $('#mtCheck').onclick=()=>triggerUpdate('check');
    $('#mtApply').onclick=()=>{
      if(!confirm('对使用旧镜像的站点重建容器？期间站点会短暂不可用（约 10-30 秒）。')) return;
      triggerUpdate('apply');
    };
  }
  pollUpdates();
}

// ---------------- 线索 ----------------
async function loadLeads(slug){
  $('#ldMsg').textContent='读取中…';
  const r=await fetch('/api/leads/'+encodeURIComponent(slug));
  const d=await r.json();
  const items=d.items||[];
  $('#ldMsg').textContent = items.length ? ('共 '+items.length+' 条') : '';
  const box=$('#ldList');
  if(!items.length){
    box.innerHTML='<div style="text-align:center;padding:26px 12px">'
      +'<div style="color:var(--dim);font-size:13px;margin-bottom:6px">还没有收到提交</div>'
      +'<div style="color:var(--dim);font-size:12px">客户提交联系表单后，线索会出现在这里</div></div>';
    return; }
  box.innerHTML=items.map(x=>`
    <div class="lead-card">
      <div class="lead-top"><b>${esc(x.title.split(' — ')[0])}</b>
        <span style="color:var(--acc)">${esc(x.email||'')}</span>
        ${x.phone?`<span style="color:var(--dim)">${esc(x.phone)}</span>`:''}
        ${x.sent==='0'?'<span class="badge-warn">邮件未发送</span>':''}
        <span class="t">${esc(x.date||'')}</span></div>
      <div class="lead-msg">${esc(x.msg||'')}</div>
    </div>`).join('');
}
function initLeads(){
  const sel=$('#ldSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadLeads(sel.value);
    $('#ldRefresh').onclick=()=>loadLeads(sel.value);
  }
  loadLeads(sel.value);
}

// ---------------- 域名 ----------------
async function initDomain(){
  const r=await fetch('/api/domains');
  const d=await r.json();
  const items=d.items||[];
  const box=$('#dList');
  if(!items.length){ box.innerHTML='<div style="color:var(--dim);font-size:13px">没有配置域名的站点</div>'; return; }
  box.innerHTML=items.map(x=>`
    <div class="dom-row">
      <div class="h"><span class="name">https://${esc(x.www)}:${x.https_port}/</span>
        <button onclick="copyShare('https://${esc(x.www)}:${x.https_port}/')">复制网址</button>
        <button onclick="copyShare('127.0.0.1 ${esc(x.www)}')">复制 hosts 行</button>
        <a href="https://${esc(x.www)}:${x.https_port}/" target="_blank" style="font-size:12px">打开</a>
      </div>
      <div class="hint">在电脑上执行（一次性）：sudo sh -c 'echo "127.0.0.1 ${esc(x.domain)} ${esc(x.www)}" >> /etc/hosts'</div>
      <div class="hint">Windows：C:\\Windows\\System32\\drivers\\etc\\hosts 里加一行  127.0.0.1 ${esc(x.domain)} ${esc(x.www)}</div>
    </div>`).join('');
}

// ---------------- 分享 ----------------
async function loadShares(slug){
  const r=await fetch('/api/shares/'+encodeURIComponent(slug));
  const d=await r.json();
  const box=$('#sList');
  const items=d.items||[];
  if(!items.length){
    box.innerHTML='<div style="text-align:center;padding:26px 12px">'
      +'<div style="color:var(--dim);font-size:13px;margin-bottom:10px">还没有分享链接，生成一条发给客户审阅</div>'
      +'<button onclick="document.querySelector(\'#sCreate\').click()">生成预览链接</button></div>';
    return; }
  box.innerHTML=items.map(s=>{
    const full=location.origin+s.url;
    return `<div class="share-row">
      <span class="${s.alive?'u':'u dead'}">${esc(full)}</span>
      <span style="color:var(--dim)">${s.alive?('有效至 '+esc(s.expires)):'已失效'}</span>
      ${s.alive?`<button onclick="copyShare('${full}')">复制</button>`:''}
      <button onclick="revokeShare('${s.token}')">作废</button>
    </div>`;
  }).join('');
}
function copyShare(u){
  navigator.clipboard.writeText(u).then(()=>{
    $('#sMsg').className='msg ok'; $('#sMsg').textContent='链接已复制';
  }).catch(()=>{ $('#sMsg').className='msg bad'; $('#sMsg').textContent='复制失败，请长按选择'; });
}
async function revokeShare(token){
  if(!confirm('作废这个链接？客户将无法再打开。')) return;
  const r=await fetch('/api/shares/revoke',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:token})});
  const d=await r.json();
  $('#sMsg').className='msg '+(r.ok?'ok':'bad');
  $('#sMsg').textContent=r.ok?'已作废':('失败：'+(d.error||''));
  loadShares($('#sSlug').value);
}
function initShare(){
  const sel=$('#sSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadShares(sel.value);
    $('#sCreate').onclick=async()=>{
      const r=await fetch('/api/shares',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({slug:sel.value,days:Number($('#sDays').value)||14})});
      const d=await r.json();
      $('#sMsg').className='msg '+(r.ok?'ok':'bad');
      $('#sMsg').textContent=r.ok?('已生成，有效期至 '+d.expires):('失败：'+(d.error||''));
      loadShares(sel.value);
    };
  }
  loadShares(sel.value);
}

// ---------------- 媒体 ----------------
let MSLUG='';
function humanSize(n){ return n>1048576 ? (n/1048576).toFixed(1)+' MB' : Math.round(n/1024)+' KB'; }
async function loadGrid(slug){
  MSLUG=slug;
  const r=await fetch('/api/media/'+encodeURIComponent(slug));
  const d=await r.json();
  const items=d.items||[];
  const g=$('#mGrid');
  if(!items.length){
    g.innerHTML='<div style="grid-column:1/-1;text-align:center;padding:30px 12px">'
      +'<div style="color:var(--dim);font-size:13px;margin-bottom:10px">还没有图片</div>'
      +'<button onclick="document.querySelector(\'#mFile\').click()">上传第一张图片</button></div>';
    return; }
  g.innerHTML=items.map(m=>`
    <div class="tile">
      <img src="${m.url}" alt="${esc(m.name)}" loading="lazy">
      <div class="meta"><b>${esc(m.name)}</b>
        ${humanSize(m.size)} · ${esc(m.mtime)}
        ${m.used_by&&m.used_by.length?`<div><span class="used">用于 ${esc(m.used_by.join('、'))}</span></div>`:''}
      </div>
      <div class="ops">
        <button onclick="copyUrl('${m.url}')">复制地址</button>
        <button class="del" onclick="delMedia('${esc(m.name)}')">删除</button>
      </div>
    </div>`).join('');
  $('#mMsg').textContent='';
}
function copyUrl(u){
  navigator.clipboard.writeText(location.origin+u).then(()=>{
    $('#mMsg').className='msg ok'; $('#mMsg').textContent='已复制：'+u;
  }).catch(()=>{ $('#mMsg').className='msg bad'; $('#mMsg').textContent='复制失败，请手动选择'; });
}
async function delMedia(name, force){
  if(!force && !confirm('删除 '+name+' ？此操作不可撤销')) return;
  const r=await fetch('/api/media/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:MSLUG,name:name,force:!!force})});
  const d=await r.json();
  if(r.status===409){
    if(confirm(d.error+'\n\n仍然删除？删掉后页面会出现裂图。')) return delMedia(name,true);
    return;
  }
  $('#mMsg').className='msg '+(r.ok?'ok':'bad');
  $('#mMsg').textContent=r.ok?('已删除 '+name):('失败：'+(d.error||''));
  loadGrid(MSLUG);
}
function initMedia(){
  const sel=$('#mSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadGrid(sel.value);
    $('#mUpload').onclick=()=>$('#mFile').click();
    $('#mFile').onchange=async()=>{
      const f=$('#mFile').files[0]; if(!f) return;
      if(f.size>8*1024*1024){ alert('图片超过 8MB，请先压缩'); return; }
      $('#mMsg').className='msg'; $('#mMsg').textContent='上传中…';
      const fd=new FormData(); fd.append('file',f);
      const r=await fetch('/api/upload?slug='+encodeURIComponent(sel.value),{method:'POST',body:fd});
      const d=await r.json();
      $('#mMsg').className='msg '+(r.ok?'ok':'bad');
      if(r.ok){
        const pct=d.original?Math.round(100-(d.size/d.original)*100):0;
        $('#mMsg').textContent=`已上传 ${d.name}　${d.original?humanSize(d.original)+' → '+humanSize(d.size)+'（省 '+pct+'%）':''}`;
      } else $('#mMsg').textContent='失败：'+(d.error||'');
      $('#mFile').value='';
      loadGrid(sel.value);
    };
  }
  loadGrid(sel.value);
}

// ---------------- 结构 ----------------
let LSPEC={pages:[]}, LSLUG='', LIDX=-1, LW=null, LSCHEMAS={}, LMEDIA=[];

function curPage(){ return (LSPEC.pages||[]).find(p=>p.slug===$('#lPage').value); }
function defFor(f){
  if(f.type==='bool') return false;
  if(f.type==='cta') return {label:'',href:''};
  if(f.type==='strings'||f.type==='items') return [];
  if(f.type==='table') return {headers:[],rows:[]};
  return '';
}
function secSummary(s){
  return s.title || s.caption || s.kicker || s.html && 'HTML' || '';
}
function syncJson(){ if(LW) $('#lJson').value=JSON.stringify(LW,null,1); }

function el(tag, cls, txt){ const e=document.createElement(tag); if(cls)e.className=cls; if(txt!=null)e.textContent=txt; return e; }
function inp(val, ph){
  const i=document.createElement('input'); i.type='text'; i.value=val??''; if(ph)i.placeholder=ph; return i;
}
function buildCta(v,set){
  const box=el('div','row2');
  const a=inp(v&&v.label,'按钮文字'), b=inp(v&&v.href,'/contact/');
  a.oninput=()=>set({label:a.value,href:b.value});
  b.oninput=()=>set({label:a.value,href:b.value});
  box.append(a,b); return box;
}
function buildStrings(v,set){
  const box=el('div');
  const paint=()=>{
    box.innerHTML='';
    (v||[]).forEach((item,i)=>{
      const row=el('div','sub');
      const i1=inp(item); i1.style.flex='1';
      i1.oninput=()=>{ v[i]=i1.value; set(v); };
      const del=el('button',null,'×');
      del.onclick=()=>{ v.splice(i,1); paint(); set(v); };
      row.append(i1,del); box.append(row);
    });
    const add=el('button','add','+ 添加一条');
    add.onclick=()=>{ v.push(''); paint(); set(v); };
    box.append(add);
  };
  paint(); return box;
}
function buildItems(f,v,set){
  const box=el('div');
  const paint=()=>{
    box.innerHTML='';
    (v||[]).forEach((item,i)=>{
      const row=el('div','sub');
      const g=el('div','grow');
      f.itemFields.forEach(sf=>{
        let c;
        if(sf.type==='textarea'){ c=document.createElement('textarea'); c.value=item[sf.k]??''; }
        else { c=inp(item[sf.k], sf.label); }
        c.oninput=()=>{ item[sf.k]=c.value; set(v); };
        g.append(c);
      });
      const del=el('button',null,'×');
      del.onclick=()=>{ v.splice(i,1); paint(); set(v); };
      row.append(g,del); box.append(row);
    });
    const add=el('button','add','+ 添加一条');
    add.onclick=()=>{ v.push({}); paint(); set(v); };
    box.append(add);
  };
  paint(); return box;
}
function buildTable(v,set){
  const box=el('div');
  const ta=document.createElement('textarea');
  ta.className='json-edit'; ta.style.minHeight='120px';
  ta.style.fontFamily='ui-monospace,Menlo,monospace';
  ta.value=[(v.headers||[]).join(' | '), ...(v.rows||[]).map(r=>r.join(' | '))].join('\n');
  ta.placeholder='第一行是表头，之后每行一条记录，单元格用 | 分隔';
  ta.oninput=()=>{
    const lines=ta.value.split('\n').filter(x=>x.trim()!=='');
    set({headers:(lines[0]||'').split('|').map(s=>s.trim()),
         rows:lines.slice(1).map(l=>l.split('|').map(s=>s.trim()))});
  };
  box.append(ta); return box;
}

async function loadMedia(slug){
  try{ const r=await fetch('/api/media/'+encodeURIComponent(slug)); const d=await r.json(); LMEDIA=d.items||[]; }
  catch(e){ LMEDIA=[]; }
}
function buildImage(val,set){
  const box=el('div');
  const row=el('div','row2');
  const i=inp(val,'/wp-content/uploads/...'); i.style.flex='1';
  i.oninput=()=>{ set(i.value); paint(); };
  const up=el('button',null,'上传'); up.className='ghost'; up.type='button'; up.style.height='36px';
  const file=document.createElement('input'); file.type='file'; file.accept='image/*'; file.style.display='none';
  up.onclick=()=>file.click();
  const pick=document.createElement('select'); pick.style.maxWidth='140px';
  const paintPicker=()=>{
    pick.innerHTML='<option value="">已有图片…</option>'+
      LMEDIA.map(m=>`<option value="${m.url}">${esc(m.name)}</option>`).join('');
    pick.value='';
  };
  pick.onchange=()=>{ if(pick.value){ i.value=pick.value; set(pick.value); paint(); } };
  file.onchange=async()=>{
    if(!file.files[0]) return;
    if(file.files[0].size > 8*1024*1024){ alert('图片超过 8MB，请先压缩'); file.value=''; return; }
    up.textContent='上传中…'; up.disabled=true;
    const fd=new FormData(); fd.append('file', file.files[0]);
    try{
      const r=await fetch('/api/upload?slug='+encodeURIComponent(LSLUG),{method:'POST',body:fd});
      const d=await r.json();
      if(!r.ok) throw new Error(d.error||'上传失败');
      i.value=d.url; set(d.url); paint();
      if(d.original){
        const pct=Math.round(100-(d.size/d.original)*100);
        note.textContent=`${humanSize(d.original)} → ${humanSize(d.size)}（省 ${pct}%）${d.width?' · '+d.width+'×'+d.height:''}`;
      }
      await loadMedia(LSLUG); paintPicker();
    }catch(e){ alert(e.message); }
    up.textContent='上传'; up.disabled=false;
  };
  row.append(i,up,pick,file);
  const note=el('div','imgnote');
  const img=document.createElement('img'); img.className='thumb'; img.style.display='none';
  const paint=()=>{
    if(i.value){ img.src=i.value; img.style.display='block'; } else { img.style.display='none'; }
  };
  box.append(row,img,note); paintPicker(); paint();
  return box;
}

function buildField(f){
  const wrap=el('div','fld');
  wrap.append(el('label',null,f.label));
  const val = LW[f.k]!==undefined ? LW[f.k] : defFor(f);
  const set = v => { LW[f.k]=v; syncJson(); };
  if(f.type==='text'){ const i=inp(val); i.oninput=()=>set(i.value); wrap.append(i); }
  else if(f.type==='textarea'||f.type==='html'){
    const ta=document.createElement('textarea'); ta.value=val??'';
    if(f.type==='html'){ ta.style.fontFamily='ui-monospace,Menlo,monospace'; ta.style.minHeight='140px'; }
    ta.oninput=()=>set(ta.value); wrap.append(ta);
  }
  else if(f.type==='bool'){
    const l=el('label','chk'); const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=!!val;
    cb.onchange=()=>set(cb.checked); l.append(cb, document.createTextNode(' 开启')); wrap.append(l);
  }
  else if(f.type==='select'){
    const s=document.createElement('select');
    (f.options||[]).forEach(([v,lab])=>{ const o=document.createElement('option'); o.value=v; o.textContent=lab; s.append(o); });
    s.value=val??''; s.onchange=()=>set(s.value); wrap.append(s);
  }
  else if(f.type==='cta'){ wrap.append(buildCta(val,set)); }
  else if(f.type==='strings'){ wrap.append(buildStrings(val,set)); }
  else if(f.type==='items'){ wrap.append(buildItems(f,val,set)); }
  else if(f.type==='table'){ wrap.append(buildTable(val,set)); }
  else if(f.type==='image'){ wrap.append(buildImage(val,set)); }
  return wrap;
}
function renderForm(){
  const box=$('#lForm'); box.innerHTML='';
  const page=curPage();
  if(!page || LIDX<0 || !page.sections[LIDX]){
    box.innerHTML='<div style="color:var(--dim);font-size:13px">点上面的区块开始编辑</div>'; LW=null; return;
  }
  LW=JSON.parse(JSON.stringify(page.sections[LIDX]));
  const sch=LSCHEMAS[LW.type];
  if(!sch){ box.innerHTML='<div style="color:#f85149;font-size:13px">该类型暂无可视化表单，请用下面的 JSON</div>'; syncJson(); return; }
  sch.fields.forEach(f=>box.append(buildField(f)));
  syncJson();
}
function renderSecList(){
  const page=curPage(); const box=$('#lList');
  if(!page){ box.innerHTML=''; return; }
  box.innerHTML=page.sections.map((s,i)=>
    `<div class="sec-row ${i===LIDX?'on':''}" data-i="${i}">
      <span class="t">${esc(s.type)}</span>
      <span class="s">${esc(secSummary(s))}</span>
      <button data-act="up">↑</button><button data-act="down">↓</button><button data-act="del">×</button>
    </div>`).join('') || '<div class="sec-row"><span class="s">这一页还没有区块</span></div>';
  box.querySelectorAll('.sec-row[data-i]').forEach(row=>{
    const i=Number(row.dataset.i);
    row.onclick=e=>{
      const act=e.target.dataset.act;
      if(act){ e.stopPropagation(); moveSec(i,act); return; }
      LIDX=i; renderSecList(); renderForm();
    };
  });
}
function moveSec(i,act){
  const page=curPage(); if(!page) return;
  const s=page.sections;
  if(act==='del'){ s.splice(i,1); LIDX=Math.min(i,s.length-1); }
  if(act==='up'&&i>0){ [s[i-1],s[i]]=[s[i],s[i-1]]; LIDX=i-1; }
  if(act==='down'&&i<s.length-1){ [s[i+1],s[i]]=[s[i],s[i+1]]; LIDX=i+1; }
  renderSecList(); renderForm();
}
function paintDirty(){
  const el=$('#lDirty');
  if(!el) return;
  el.textContent = LSPEC.dirty ? '有未发布改动' : '已与线上一致';
  el.style.color = LSPEC.dirty ? 'var(--warn)' : 'var(--ok)';
  el.style.borderColor = LSPEC.dirty ? 'var(--warn)' : 'var(--line)';
}
async function loadSpec(slug){
  const r=await fetch('/api/spec/'+encodeURIComponent(slug));
  if(!r.ok){ $('#lMsg').textContent='读取失败'; return; }
  const d=await r.json();
  LSPEC=d.spec; LSLUG=slug; LIDX=-1; LSCHEMAS=d.schemas||{};
  await loadMedia(slug);
  $('#lPage').innerHTML=(LSPEC.pages||[]).map(p=>`<option value="${p.slug}">${esc(p.title)}</option>`).join('');
  $('#lType').innerHTML=d.types.map(t=>`<option value="${t}">${esc((LSCHEMAS[t]||{}).label||t)}</option>`).join('');
  renderSecList(); renderForm(); paintDirty();
}
function slugVal(){ return $('#lSlug').value; }
function fmtVal(v){
  if(v===undefined||v===null) return '(无)';
  let s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length > 90 ? s.slice(0,90)+'…' : s;
}
async function showDiff(){
  const page=curPage(); if(!page) return;
  const box=$('#lDiffBox');
  const r=await fetch('/api/diff/'+encodeURIComponent(slugVal())+'/'+encodeURIComponent(page.slug));
  const d=await r.json();
  box.classList.remove('hidden');
  if(!r.ok){ box.innerHTML='<div class="msg bad">'+esc(d.error||'读取失败')+'</div>'; return; }
  const n=(d.changes||[]).length + (d.added||0) + (d.removed||0);
  let html='';
  if(d.is_new) html+='<div class="diff-sec" style="color:var(--warn)">这是一个尚未发布的页面</div>';
  if(!n && !d.is_new){ box.innerHTML='<div style="color:var(--dim);font-size:13px">这一页没有未发布的改动</div>'; return; }
  html += (d.changes||[]).map(c=>`
    <div class="diff-sec"><div class="diff-head">#${c.index+1} · ${esc(c.type)}</div>
    ${c.fields.map(f=>`<div class="diff-row"><span class="k">${esc(f.path)}</span>
      <span class="old">${esc(fmtVal(f.before))}</span><span class="arrow">→</span>
      <span class="new">${esc(fmtVal(f.after))}</span></div>`).join('')}</div>`).join('');
  if(d.added) html+=`<div class="diff-sec" style="color:var(--ok)">新增 ${d.added} 个区块</div>`;
  if(d.removed) html+=`<div class="diff-sec" style="color:var(--bad)">删除 ${d.removed} 个区块</div>`;
  box.innerHTML=html;
}
async function publish(slug, page){
  const what = page ? '这一页' : '全部页面';
  if(!confirm('发布'+what+'到线上？客户会立即看到。')) return;
  $('#lMsg').className='msg'; $('#lMsg').textContent='发布中…';
  const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(page?{slug:slug,page:page}:{slug:slug})});
  const d=await r.json();
  $('#lMsg').className='msg '+(r.ok?'ok':'bad');
  $('#lMsg').textContent = r.ok ? ('已发布 '+d.pages+' 个页面') : ('发布失败：'+(d.error||''));
  LSPEC.dirty = !r.ok && LSPEC.dirty;
  paintDirty();
  if(r.ok) $('#lDiffBox').classList.add('hidden');
}
async function initLayout(){
  const sel=$('#lSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadSpec(sel.value);
    $('#lPage').onchange=()=>{ LIDX=-1; renderSecList(); renderForm(); };
    $('#lAdd').onclick=()=>{
      const page=curPage(); if(!page) return;
      page.sections.push({type:$('#lType').value});
      LIDX=page.sections.length-1; renderSecList(); renderForm();
    };
    $('#lApplyJson').onclick=()=>{
      try{ LW=JSON.parse($('#lJson').value); renderForm(); }
      catch(e){ $('#lMsg').className='msg bad'; $('#lMsg').textContent='JSON 格式错误'; }
    };
    $('#lPreview').onclick=()=>{
      const page=curPage(); if(!page) return;
      window.open('/preview/'+encodeURIComponent(sel.value)+'/'+encodeURIComponent(page.slug),'_blank');
    };
    $('#lDiff').onclick=showDiff;
    $('#lPublishAll').onclick=()=>publish(slugVal(), null);
    $('#lPublish').onclick=()=>publish(slugVal(), (curPage()||{}).slug);
    $('#lPublish_old').onclick=async()=>{
      if(!confirm('把草稿发布到线上？客户会立即看到这些改动。')) return;
      $('#lMsg').className='msg'; $('#lMsg').textContent='发布中…';
      const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({slug:sel.value})});
      const d=await r.json();
      $('#lMsg').className='msg '+(r.ok?'ok':'bad');
      $('#lMsg').textContent = r.ok ? ('已发布 '+d.pages+' 个页面') : ('发布失败：'+(d.error||''));
      LSPEC.dirty = !r.ok && LSPEC.dirty;
      paintDirty();
    };
    $('#lSave').onclick=async()=>{
      const page=curPage(); if(!page) return;
      if(LIDX>=0 && LW){ page.sections[LIDX]=LW; }
      $('#lMsg').className='msg'; $('#lMsg').textContent='保存中…';
      const r=await fetch('/api/spec',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({slug:sel.value,page:page.slug,sections:page.sections})});
      const d=await r.json();
      $('#lMsg').className='msg '+(r.ok?'ok':'bad');
      $('#lMsg').textContent = r.ok ? ('已保存到草稿（'+(d.length||0)+' 字符），线上未变')
        : ('保存被拒绝：'+(d.error||''));
      LSPEC.dirty = r.ok ? true : LSPEC.dirty;
      paintDirty();
      renderSecList();
    };
  }
  await loadSpec(sel.value);
}

// ---------------- 设计 ----------------
let DPRESETS={}, DTOK={};
function previewDesign(){
  const p=DTOK.palette||{}, s=DTOK.shape||{}, ty=DTOK.type||{};
  const head={sans:'-apple-system,Segoe UI,Roboto,sans-serif',serif:'Georgia,serif',rounded:'ui-rounded,Quicksand,sans-serif'}[ty.heading||'sans'];
  $('#pvHero').style.background=`linear-gradient(135deg,${p.primary},${p.primaryDark||p.primary})`;
  $('#pvHero').style.borderRadius=s.radius||'16px';
  $('#pvH1');
  $('#pv').querySelector('.pv-h1').style.fontFamily=head;
  const btn=$('#pvBtn'); btn.style.borderRadius=s.button||'999px'; btn.style.color=p.primary;
  const card=$('#pvCard'); card.style.borderRadius=s.radius||'16px'; card.style.borderTop='4px solid '+p.primary;
  $('#pv').style.background=p.bg||'#f7f9f7';
  $('#rVal').textContent=(parseInt(s.radius||'16',10))+'px';
  $('#pvMeta').textContent=`${p.primary} · 圆角 ${s.radius} · ${ty.heading}`;
}
function fillDesign(t){
  DTOK=JSON.parse(JSON.stringify(t||{}));
  const p=DTOK.palette||{}, s=DTOK.shape||{}, ty=DTOK.type||{};
  $('#cPrimary').value=p.primary||'#0f5132';
  $('#cAccent').value=p.accent||'#d4a04a';
  $('#cBg').value=p.bg||'#f7f9f7';
  $('#rRadius').value=parseInt(s.radius||'16',10);
  $('#sButton').value=s.button||'999px';
  $('#sHead').value=ty.heading||'sans';
  previewDesign();
}
function syncTokens(){
  DTOK.palette=DTOK.palette||{}; DTOK.shape=DTOK.shape||{}; DTOK.type=DTOK.type||{};
  DTOK.palette.primary=$('#cPrimary').value;
  DTOK.palette.accent=$('#cAccent').value;
  DTOK.palette.bg=$('#cBg').value;
  DTOK.shape.radius=$('#rRadius').value+'px';
  DTOK.shape.button=$('#sButton').value;
  DTOK.type.heading=$('#sHead').value;
  previewDesign();
}
async function fetchDesign(slug){
  if(!slug) return;
  const r=await fetch('/api/design/'+encodeURIComponent(slug));
  if(!r.ok){$('#dmsg').textContent='读取失败';return;}
  const d=await r.json();
  DPRESETS=d.presets||{};
  const ps=$('#dPreset');
  ps.innerHTML='<option value="">自定义</option>'+Object.keys(DPRESETS).map(k=>`<option value="${k}">${k}</option>`).join('');
  fillDesign(d.tokens||{});
}
async function initDesign(){
  const sel=$('#dSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>fetchDesign(sel.value);
    $('#dPreset').onchange=e=>{const k=e.target.value; if(k&&DPRESETS[k]) fillDesign(DPRESETS[k]);};
    ['cPrimary','cAccent','cBg','sButton','sHead'].forEach(id=>$('#'+id).oninput=syncTokens);
    $('#rRadius').oninput=syncTokens;
    $('#dSave').onclick=async()=>{
      syncTokens();
      if($('#dPreset').value) DTOK.preset=$('#dPreset').value;
      const r=await fetch('/api/design',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(Object.assign({slug:sel.value},DTOK))});
      const d=await r.json();
      $('#dmsg').className='msg '+(r.ok?'ok':'bad');
      $('#dmsg').textContent=r.ok?'已应用到站点，刷新页面即可看到':'失败：'+(d.error||'');
    };
  }
  await fetchDesign(sel.value);
}

load();setInterval(load,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "KFConsole/0.2"

    def log_message(self, fmt, *a):
        pass

    def _auth_ok(self):
        u = session_user(self.headers.get("Cookie"))
        if u:
            self.user = u
            self.user_role = (load_users().get(u) or {}).get("role", "ops")
            return True
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            uu, _, p = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        if not check_login(uu, p):
            return False
        if (load_users().get(uu) or {}).get("mfa_secret"):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("WWW-Authenticate", 'Basic realm="KampongFlow"')
            self.end_headers()
            self.wfile.write(json.dumps(
                {"error": "该账号已开启两步验证，请使用登录页"}, ensure_ascii=False).encode())
            return False
        self.user = uu
        self.user_role = (load_users().get(uu) or {}).get("role", "ops")
        return True

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        if self._auth_ok():
            return True
        if self.path.startswith("/api/"):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="KampongFlow"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(303)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ------------------------------------------------------------ GET
    def _maybe_site(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        entry = host_map().get(host)
        if not entry:
            return False
        body = None
        if self.command == "POST":
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(n) if n else b""
            except Exception:
                body = b""
        status, hdrs, data = proxy_site(entry["port"], self.path, self.command, body,
                                        list(self.headers.items()))
        ctype = hdrs.get("Content-Type", "text/html; charset=utf-8")
        loc = hdrs.get("Location")
        if loc:
            loc = re.sub(r"https?://(127\.0\.0\.1|localhost):%d" % entry["port"],
                         "https://" + host, loc)
        if "text/html" in ctype:
            try:
                txt = data.decode("utf-8", "replace")
                txt = re.sub(r"https?://(127\.0\.0\.1|localhost):%d" % entry["port"],
                             "https://" + host, txt)
                data = txt.encode("utf-8")
            except Exception:
                pass
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if loc:
            self.send_header("Location", loc)
        if hdrs.get("Set-Cookie"):
            self.send_header("Set-Cookie", hdrs["Set-Cookie"])
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        return True

    def do_GET(self):
        if self._maybe_site():
            return
        raw = self.path.split("?")[0]
        if raw == "/login":
            return self._send(200, login_page(), "text/html; charset=utf-8")
        if raw == "/logout":
            sid = (cookie_value(self.headers.get("Cookie"), "kf_sid") or "").split(".")[0]
            SESSIONS.pop(sid, None)
            save_sessions()
            self.send_response(303)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "kf_sid=; Path=/; Max-Age=0; HttpOnly")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if raw.startswith("/portal/"):
            return self._send(410, "<h1>客户门户已停用</h1><p>客户无需登录，一切由我们代管。</p>",
                              "text/html; charset=utf-8")
        if raw.startswith("/s/") or raw.startswith("/sa/"):
            return self._public(raw)
        if not self._guard():
            return
        path = raw.rstrip("/") or "/"
        if path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/api/state":
            # settings 里含 smtp.api_key 等敏感值，绝不能原样下发
            pub = dict(settings())
            sm = dict(pub.get("smtp") or {})
            for k in ("api_key", "pass"):
                if sm.get(k):
                    sm[k] = "********"
            pub["smtp"] = sm
            return self._send(200, {"role": getattr(self, "user_role", "ops"),
                                    "me": getattr(self, "user", ""),
                                    "staff": sorted(load_users().keys()),
                                    "sites": site_list(), "invoices": invoices(),
                                    "plans": plans(), "settings": pub,
                                    "industries": sorted(INDUSTRIES.items()),
                                    "free_port": free_port()})
        if path == "/export/invoices.csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["账单号", "客户", "域名", "套餐", "金额", "GST", "合计",
                        "状态", "签发", "付款"])
            for i in invoices():
                w.writerow([i["no"], i["company"], i.get("domain", ""),
                            i.get("plan_name", ""), i["subtotal"], i.get("gst", 0),
                            i["total"], i["status"], i.get("issued_at", ""),
                            i.get("paid_at", "")])
            return self._send(200, "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="invoices.csv"'})
        m = re.match(r"^/api/diff/([a-z0-9-]+)/([a-z0-9-]+)$", path)
        if m:
            slug, page = m.group(1), m.group(2)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            live = next((p for p in read_spec(slug).get("pages", []) if p["slug"] == page), None)
            drf = next((p for p in read_draft(slug).get("pages", []) if p["slug"] == page), None)
            if not drf:
                return self._send(404, {"error": "草稿里没有这一页"})
            d = page_diff((live or {}).get("sections", []), drf.get("sections", []))
            d["page"], d["title"] = page, drf.get("title", page)
            d["is_new"] = live is None
            return self._send(200, d)

        m = re.match(r"^/preview/([a-z0-9-]+)(?:/([a-z0-9-]*))?$", path)
        if m:
            slug, page = m.group(1), (m.group(2) or "home")
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, preview_html(slug, page), "text/html; charset=utf-8")

        m = re.match(r"^/pa/([a-z0-9-]+)/(.+)$", path)
        if m:
            slug, rel = m.group(1), m.group(2)
            root = (SITES / slug / "html").resolve()
            if rel == "style.css":
                f = root / "wp-content" / "themes" / "kampong" / "style.css"
            elif rel.startswith("uploads/"):
                f = root / "wp-content" / rel
            else:
                return self._send(404, {"error": "not found"})
            try:
                f = f.resolve()
                if not str(f).startswith(str(root)) or not f.is_file():
                    return self._send(404, {"error": "not found"})
            except Exception:
                return self._send(404, {"error": "not found"})
            ctype = {".css": "text/css; charset=utf-8", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                     ".gif": "image/gif", ".svg": "image/svg+xml"}.get(f.suffix.lower(),
                                                                      "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype)

        if path == "/api/domains":
            hm = host_map()
            seen = {}
            for host, e in hm.items():
                if host.startswith("www."):
                    continue
                seen[e["slug"]] = {"domain": host, "www": "www." + host,
                                   "port": e["port"], "slug": e["slug"],
                                   "https_port": HTTPS_PORT, "http_port": PORT}
            return self._send(200, {"items": list(seen.values())})

        m = re.match(r"^/api/dns/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            info = dns_info(slug)
            plan = next((p for p in plans()
                         if p["id"] == read_billing(slug).get("plan_id")), None)
            info["plan_dns"] = bool(plan.get("dns", True)) if plan else True
            info["plan_name"] = plan["name"] if plan else ""
            info["domain_manage"] = read_domain(slug)
            info["domain_days"] = domain_days_left(slug)
            return self._send(200, info)

        if path == "/api/mfa":
            u = getattr(self, "user", "")
            info = load_users().get(u) or {}
            enabled = bool(info.get("mfa_secret"))
            out = {"enabled": enabled, "user": u}
            if not enabled:
                sec = PENDING_MFA.get(u) or totp_new_secret()
                PENDING_MFA[u] = sec
                out["secret"] = sec
                out["otpauth"] = ("otpauth://totp/KampongFlow:%s?secret=%s&issuer=KampongFlow"
                                  % (u, sec))
            return self._send(200, out)

        if path == "/api/renewals":
            items = []
            for d in sorted(SITES.iterdir()):
                if not d.is_dir():
                    continue
                dm = read_domain(d.name)
                meta = load_meta(d.name)
                items.append({
                    "slug": d.name,
                    "company": meta.get("company", d.name),
                    "domain": meta.get("domain", ""),
                    "registrar": dm.get("registrar", ""),
                    "domain_expires": dm.get("expires", ""),
                    "domain_days": domain_days_left(d.name),
                    "auto_renew": bool(dm.get("auto_renew", True)),
                    "service_expires": read_billing(d.name).get("expires", ""),
                    "service_days": days_left(d.name),
                    "status": read_billing(d.name).get("status", ""),
                })
            items.sort(key=lambda x: (x["domain_days"] is None, x["domain_days"] or 0))
            return self._send(200, {"items": items})

        if path == "/api/clients":
            items = []
            for d in sorted(SITES.iterdir()):
                if not d.is_dir():
                    continue
                c0 = client_of(d.name)
                _, bal = ledger_of(d.name)
                items.append({"slug": d.name, "client": c0, "balance": bal})
            return self._send(200, {"items": items})

        m = re.match(r"^/api/ledger/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            rows, bal = ledger_of(slug)
            return self._send(200, {"items": rows[:100], "balance": bal})

        if path == "/api/security":
            today = datetime.now(SGT).date()
            out = []
            for k, v in sorted(load_users().items()):
                ch = v.get("pwd_changed") or v.get("created") or ""
                try:
                    age = (today - datetime.strptime(ch, "%Y-%m-%d").date()).days
                except Exception:
                    age = None
                out.append({
                    "user": k, "name": v.get("name", k), "role": v.get("role", "ops"),
                    "active": bool(v.get("active")),
                    "mfa": bool(v.get("mfa_secret")),
                    "recovery_left": len(v.get("recovery") or []),
                    "locked": locked_for(k) > 0,
                    "lock_wait": locked_for(k),
                    "pwd_changed": ch, "pwd_age": age,
                    "last_login": v.get("last_login", ""),
                })
            return self._send(200, {"items": out,
                                    "blocked_ips": list(IP_FAILS.keys()),
                                    "ip_limit": IP_LIMIT})

        if path == "/api/smtp":
            s = dict(settings().get("smtp") or {})
            if s.get("pass"):
                s["pass"] = "********"
            if s.get("api_key"):
                s["api_key"] = "********"
            return self._send(200, {"smtp": s})

        if path == "/api/roles":
            return self._send(200, {"items": roles()})

        if path == "/api/users":
            users = load_users()
            items = [{"user": k, "name": v.get("name", k), "role": v.get("role", "ops"),
                      "active": bool(v.get("active")), "created": v.get("created", ""),
                      "mfa": bool(v.get("mfa_secret")),
                      "locked": locked_for(k) > 0,
                      "recovery_left": len(v.get("recovery") or [])}
                     for k, v in sorted(users.items())]
            return self._send(200, {"items": items, "me": getattr(self, "user", "")})

        if path.startswith("/api/audit"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            items = read_audit(
                limit=int((q.get("limit") or ["200"])[0]),
                user=(q.get("user") or [""])[0] or None,
                action=(q.get("action") or [""])[0] or None,
                since=(q.get("since") or [""])[0] or None,
                until=(q.get("until") or [""])[0] or None)
            return self._send(200, {"items": items, "count": len(items)})

        if path == "/api/updates":
            return self._send(200, {"report": read_updates(),
                                    "running": _update_state["running"],
                                    "mode": _update_state["mode"]})

        m = re.match(r"^/api/access/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, {"items": read_access(slug)})

        if path == "/api/portals":
            data = portals()
            by_slug = {}
            for tok, p in data.items():
                by_slug.setdefault(p["slug"], []).append(
                    {"token": tok, "active": bool(p.get("active")),
                     "created": p.get("created", "")})
            items = []
            for d in sorted(SITES.iterdir()):
                if not d.is_dir():
                    continue
                items.append({"slug": d.name,
                              "company": load_meta(d.name).get("company", d.name),
                              "links": by_slug.get(d.name, [])})
            return self._send(200, {"items": items})

        m = re.match(r"^/api/leads/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            items = list_leads(slug)
            return self._send(200, {"items": items, "count": len(items)})

        m = re.match(r"^/api/shares/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, {"items": self._shares_list(slug)})

        m = re.match(r"^/api/media/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, {"items": media_list(slug)})
        m = re.match(r"^/api/spec/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, {"spec": read_draft(slug), "live": read_spec(slug),
                                    "dirty": is_dirty(slug),
                                    "types": block_types(), "schemas": schemas()})
        m = re.match(r"^/api/design/([a-z0-9-]+)$", path)
        if m:
            slug = m.group(1)
            if not (SITES / slug).exists():
                return self._send(404, {"error": "站点不存在"})
            return self._send(200, {"tokens": site_design(slug), "presets": presets()})
        m = re.match(r"^/api/site/([a-z0-9-]+)/handover\.pdf$", path)
        if m:
            slug = m.group(1)
            # 交接单含 WordPress 管理员密码，只给管理员和运营看
            if getattr(self, "user_role", "ops") not in ("admin", "ops"):
                return self._send(403, {"error": "当前角色无权导出交接单"})
            try:
                pdf = handover_pdf(slug)
            except FileNotFoundError as e:
                return self._send(404, {"error": str(e)})
            return self._send(200, pdf, "application/pdf",
                              {"Content-Disposition": f'attachment; filename="{slug}-handover.pdf"'})
        m = re.match(r"^/api/invoice/([A-Za-z0-9-]+)/pdf$", path)
        if m:
            no = m.group(1)
            inv = next((i for i in invoices() if i["no"] == no), None)
            if not inv:
                return self._send(404, {"error": "没有这张账单"})
            return self._send(200, invoice_pdf(inv), "application/pdf",
                              {"Content-Disposition": f'attachment; filename="{no}.pdf"'})
        return self._send(404, {"error": "not found"})

    # ------------------------------------------------------------ POST
    def do_POST(self):
        if self.path.split("?")[0] == "/login":
            return self._login()
        if self.path.split("?")[0].startswith("/portal/"):
            return self._send(410, "<h1>客户门户已停用</h1>", "text/html; charset=utf-8")
        _audit_path = self.path.split("?")[0]
        if self._maybe_site():
            return
        if not self._guard():
            return
        path = self.path.split("?")[0]
        if not can_write(getattr(self, "user_role", "ops"), path):
            audit(getattr(self, "user", "-"), "denied", path)
            return self._send(403, {"error": "当前角色无权执行此操作"})
        audit(getattr(self, "user", "-"), "POST " + path, "")

        if path == "/api/upload":
            return self._upload()

        body = self._body()

        if path == "/api/create":
            return self._create(body)
        if path == "/api/invoice/issue":
            return self._issue(body.get("slug", ""))
        if path == "/api/invoice/pay":
            return self._pay(body.get("no", ""))
        if path == "/api/notify/run":
            try:
                r = subprocess.run([sys.executable, str(BASE / "tools" / "kf_notify.py")],
                                   capture_output=True, text=True, timeout=180)
                out = (r.stdout or "").strip() or (r.stderr or "").strip()[-200:]
                to = (settings().get("smtp") or {}).get("notify_to") or \
                     settings().get("support_email", "")
                if r.returncode == 0:
                    audit(getattr(self, "user", "-"), "digest_run", to)
                    return self._send(200, {"ok": True, "to": to, "output": out})
                return self._send(400, {"ok": False, "error": out})
            except Exception as e:
                return self._send(400, {"ok": False, "error": str(e)})
        if path == "/api/smtp/test":
            to = str(body.get("to", "")).strip()
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
                return self._send(400, {"error": "收件地址不合法"})
            try:
                send_mail(to, "[KampongFlow] SMTP 测试",
                          "这是一封测试邮件。收到说明 SMTP 配置可用。")
                audit(getattr(self, "user", "-"), "smtp_test", to)
                return self._send(200, {"ok": True})
            except Exception as e:
                return self._send(400, {"error": "发送失败：%s" % e})
        if path == "/api/updates":
            act = str(body.get("action", "check"))
            if act not in ("check", "apply"):
                return self._send(400, {"error": "未知操作"})
            if _update_state["running"]:
                return self._send(409, {"error": "已有更新任务在运行"})
            threading.Thread(target=run_update, args=(act,), daemon=True).start()
            return self._send(202, {"ok": True, "action": act})
        if path == "/api/portals":
            return self._portal_create(body)
        if path == "/api/portals/revoke":
            return self._portal_revoke(body)
        if path == "/api/dns/delegation":
            slug = str(body.get("slug", "")).strip().lower()
            if not SLUG_RE.match(slug) or not (SITES / slug).exists():
                return self._send(400, {"error": "站点不存在"})
            return self._send(200, dns_delegation(slug))
        if path == "/api/domain/manage":
            slug = str(body.get("slug", "")).strip().lower()
            if not SLUG_RE.match(slug) or not (SITES / slug).exists():
                return self._send(400, {"error": "站点不存在"})
            cur = read_domain(slug)
            exp = str(body.get("expires", cur["expires"])).strip()
            if exp and not re.match(r"^\d{4}-\d{2}-\d{2}$", exp):
                return self._send(400, {"error": "到期日期格式应为 YYYY-MM-DD"})
            data = {
                "registrar": str(body.get("registrar", cur["registrar"]))[:40],
                "expires": exp,
                "auto_renew": bool(body.get("auto_renew", cur["auto_renew"])),
                "owner": "us" if str(body.get("owner", cur["owner"])) == "us" else "client",
                "note": str(body.get("note", cur["note"]))[:120],
            }
            write_domain(slug, data)
            return self._send(200, {"ok": True, "domain": data})
        if path == "/api/clients/save":
            slug = str(body.get("slug", "")).strip().lower()
            if not SLUG_RE.match(slug) or not (SITES / slug).exists():
                return self._send(400, {"error": "站点不存在"})
            data = clients()
            cur = client_of(slug)
            for k in ("contact", "phone", "email", "uen", "address", "agreement_no",
                      "agreement_date", "service_start", "service_end", "notes", "owner"):
                if k in body:
                    cur[k] = str(body[k])[:120]
            for k in ("agreement_date", "service_start", "service_end"):
                v = cur.get(k) or ""
                if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                    return self._send(400, {"error": "%s 格式应为 YYYY-MM-DD" % k})
            if "scope" in body and isinstance(body["scope"], list):
                cur["scope"] = [str(x)[:30] for x in body["scope"]][:12]
            try:
                cur["annual_fee"] = max(0, float(body.get("annual_fee", cur.get("annual_fee", 0))))
            except Exception:
                pass
            before = client_of(slug)
            data[slug] = cur
            _write(CLIENTS_F, data)
            audit(getattr(self, "user", "-"), "client_save", slug,
                  diff_summary(before, cur))
            return self._send(200, {"ok": True, "client": cur})

        if path == "/api/ledger":
            slug = str(body.get("slug", "")).strip().lower()
            if not SLUG_RE.match(slug) or not (SITES / slug).exists():
                return self._send(400, {"error": "站点不存在"})
            etype = "cost" if body.get("type") == "cost" else "topup"
            if etype == "topup" and getattr(self, "user_role", "ops") not in ("admin", "finance"):
                return self._send(403, {"error": "只有财务或管理员可以记录收入"})
            try:
                amount = abs(float(body.get("amount", 0)))
            except Exception:
                return self._send(400, {"error": "金额必须是数字"})
            if amount <= 0:
                return self._send(400, {"error": "金额必须大于 0"})
            entry = add_ledger(slug, etype, amount,
                               str(body.get("category", "其他"))[:20],
                               body.get("note", ""), getattr(self, "user", ""))
            return self._send(200, {"ok": True, "entry": entry})

        if path == "/api/password":
            return self._password_save(body)
        if path == "/api/mfa":
            return self._mfa_save(body)
        if path == "/api/smtp":
            return self._smtp_save(body)
        if path == "/api/roles":
            return self._roles_save(body)
        if path == "/api/users":
            return self._users_save(body)
        if path == "/api/dns/check":
            slug = str(body.get("slug", "")).strip().lower()
            if not SLUG_RE.match(slug) or not (SITES / slug).exists():
                return self._send(400, {"error": "站点不存在"})
            return self._send(200, dns_check(slug))
        if path == "/api/dns/enable":
            return self._dns_enable(body)
        if path == "/api/dns/record":
            return self._dns_record(body)
        if path == "/api/dns/delete":
            return self._dns_delete(body)
        if path == "/api/renew":
            return self._renew(body)
        if path == "/api/suspend":
            return self._suspend(body)
        if path == "/api/shares":
            return self._share_create(body)
        if path == "/api/shares/revoke":
            return self._share_revoke(body)
        if path == "/api/publish":
            return self._publish(body)
        if path == "/api/media/delete":
            return self._media_delete(body)
        if path == "/api/spec":
            return self._spec_save(body)
        if path == "/api/design":
            return self._design_save(body)
        if path == "/api/plan/save":
            return self._plan_save(body)
        return self._send(404, {"error": "not found"})

    def _create(self, body):
        company = str(body.get("company", "")).strip()[:60]
        domain = str(body.get("domain", "")).strip().lower()[:80]
        slug = str(body.get("slug", "")).strip().lower()
        plan_id = str(body.get("plan_id", "")).strip()

        if not company:
            return self._send(400, {"error": "客户名称不能为空"})
        if not DOMAIN_RE.match(domain):
            return self._send(400, {"error": "域名格式不对，示例 example.sg"})
        if not SLUG_RE.match(slug):
            return self._send(400, {"error": "slug 只能用小写字母、数字和短横线，2-20 位"})
        if (SITES / slug).exists():
            return self._send(409, {"error": f"slug {slug} 已存在"})
        with _lock:
            if slug in _live:
                return self._send(409, {"error": "该站点正在开通中"})

        industry = str(body.get("industry", "")).strip()
        if industry and industry not in INDUSTRIES:
            return self._send(400, {"error": "无效的行业模板"})
        plan = next((p for p in plans() if p["id"] == plan_id), None)
        if not plan:
            return self._send(400, {"error": "请选择一个有效套餐"})

        port = free_port()
        if not port:
            return self._send(507, {"error": "没有空闲端口了"})

        inv = self._make_invoice(slug, company, domain, plan)
        threading.Thread(target=self._run_provision,
                         args=(company, domain, slug, port, plan, industry), daemon=True).start()
        return self._send(202, {"slug": slug, "port": port, "state": "provisioning",
                                "invoice": inv["no"]})

    def _run_provision(self, company, domain, slug, port, plan, industry=""):
        provision(company, domain, slug, port, plan["name"], plan["price"], industry, plan["id"])
        mp = SITES / slug / "meta.json"
        try:
            meta = json.loads(mp.read_text())
            meta["plan"] = plan["name"]
            meta["plan_id"] = plan["id"]
            mp.write_text(json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass

    def _make_invoice(self, slug, company, domain, plan, kind="new", years=0):
        s = settings()
        with _file_lock:
            invs = invoices()
            no = next_invoice_no()
            subtotal = float(plan["price"])
            gst = round(subtotal * s["gst_rate"], 2) if s.get("gst_enabled") else 0.0
            inv = {
                "no": no, "slug": slug, "company": company, "domain": domain,
                "plan_id": plan["id"], "plan_name": plan["name"],
                "plan_specs": plan.get("specs", ""),
                "subtotal": subtotal, "gst": gst, "total": round(subtotal + gst, 2),
                "status": "unpaid",
                "issued_at": datetime.now(SGT).strftime("%Y-%m-%d %H:%M"),
                "paid_at": "",
                "kind": kind,
                "years": years,
            }
            invs.append(inv)
            _write(INVOICES_F, invs)
        return inv

    def _issue(self, slug):
        slug = str(slug).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        if any(i["slug"] == slug for i in invoices()):
            return self._send(409, {"error": "该站点已有账单"})
        meta = load_meta(slug)
        plan = next((p for p in plans() if p["id"] == meta.get("plan_id")), None)
        if not plan:
            plan = {"id": "custom", "name": meta.get("plan", "Custom"),
                    "price": 0, "specs": "补开账单"}
        inv = self._make_invoice(slug, meta.get("company", slug),
                                 meta.get("domain", ""), plan)
        return self._send(201, inv)

    def _pay(self, no):
        with _file_lock:
            invs = invoices()
            inv = next((i for i in invs if i["no"] == no), None)
            if not inv:
                return self._send(404, {"error": "没有这张账单"})
            inv["status"] = "paid"
            inv["paid_at"] = datetime.now(SGT).strftime("%Y-%m-%d %H:%M")
            _write(INVOICES_F, invs)
        try:
            add_ledger(inv["slug"], "topup", inv.get("total", 0),
                       "服务费", "账单 %s 已付款" % inv["no"], getattr(self, "user", ""))
        except Exception:
            pass
        _extend_on_payment(inv)
        return self._send(200, inv)

    def _media_delete(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        name = str(body.get("name", "")).strip()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$", name) or ".." in name:
            return self._send(400, {"error": "文件名不合法"})
        p = SITES / slug / "html" / MEDIA_DIR / name
        if not p.is_file():
            return self._send(404, {"error": "文件不存在"})
        used = [i["used_by"] for i in media_list(slug) if i["name"] == name]
        if used and used[0] and not body.get("force"):
            return self._send(409, {"error": "该图片仍在页面中使用：" + "、".join(used[0]),
                                    "used_by": used[0]})
        removed = []
        targets = [p] + [q for q in p.parent.glob(p.stem + "-*" + p.suffix)]
        for q in targets:
            try:
                q.unlink()
                removed.append(q.name)
            except OSError as e:
                if q is p:
                    return self._send(500, {"error": str(e)})
        return self._send(200, {"ok": True, "deleted": name})

    def _portal_get(self, path):
        m = re.match(r"^/portal/([A-Za-z0-9_-]+)/invoice/([A-Za-z0-9-]+)\.pdf$", path)
        if m:
            slug = portal_slug(m.group(1))
            if not slug:
                return self._send(404, "<h1>链接无效</h1>", "text/html; charset=utf-8")
            inv = next((i for i in invoices() if i["no"] == m.group(2) and i["slug"] == slug), None)
            if not inv:
                return self._send(404, "<h1>账单不存在</h1>", "text/html; charset=utf-8")
            log_access(slug, "invoice", m.group(1), inv.get("no", ""), self)
            return self._send(200, invoice_pdf(inv), "application/pdf",
                              {"Content-Disposition": 'attachment; filename="%s.pdf"' % inv["no"]})

        m = re.match(r"^/portal/([A-Za-z0-9_-]+)$", path)
        if m:
            token = m.group(1)
            slug = portal_slug(token)
            if not slug:
                return self._send(404, "<h1>链接无效或已停用</h1>", "text/html; charset=utf-8")
            if not portal_check_cookie(token, self.headers.get("Cookie")):
                qs0 = self.path.split("?", 1)[1] if "?" in self.path else ""
                err = "访问码不正确" if "e=1" in qs0 else ""
                log_access(slug, "lock", token, "需要访问码", self)
                return self._send(200, pin_form(token, err), "text/html; charset=utf-8")
            log_access(slug, "view", token, "查看门户", self)
            msg = ""
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            if "ok=1" in qs:
                msg = '<div class="note">续费申请已提交，我们已经生成账单，收到付款后会立即延长服务期。</div>'
            elif "ok=2" in qs:
                msg = '<div class="note">当前服务期还很充足，暂时不需要续费。如需提前续期请联系我们。</div>'
            return self._send(200, portal_html(token, slug, msg), "text/html; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def _form_body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n else b""
        except Exception:
            return {}
        out = {}
        for pair in raw.decode("utf-8", "replace").split("&"):
            k, _, v = pair.partition("=")
            if k:
                from urllib.parse import unquote_plus
                out[unquote_plus(k)] = unquote_plus(v)
        return out

    def _portal_post(self):
        path = self.path.split("?")[0]

        m = re.match(r"^/portal/([A-Za-z0-9_-]+)/unlock$", path)
        if m:
            token = m.group(1)
            if not portal_slug(token):
                return self._send(404, "<h1>链接无效</h1>", "text/html; charset=utf-8")
            if attempts_blocked(token):
                log_access(portal_slug(token) or "-", "blocked", token, "尝试过多被锁定", self)
                return self._send(429, pin_form(token, "尝试次数过多，请 15 分钟后再试"),
                                  "text/html; charset=utf-8")
            form = self._form_body()
            pin = str(form.get("pin", "")).strip()
            p = portals().get(token) or {}
            ok = bool(pin) and bool(p.get("pin_hash")) and \
                hmac_compare(pin, p)
            record_attempt(token, ok)
            log_access(portal_slug(token) or "-",
                       "unlock_ok" if ok else "unlock_fail", token,
                       "" if ok else "访问码错误", self)
            if not ok:
                self.send_response(303)
                self.send_header("Location", "/portal/%s?e=1" % token)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            cookie, _ = portal_cookie(token)
            self.send_response(303)
            self.send_header("Location", "/portal/%s" % token)
            self.send_header("Set-Cookie",
                             "%s; Path=/portal/%s; Max-Age=43200; HttpOnly; SameSite=Lax"
                             % (cookie, token))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        m = re.match(r"^/portal/([A-Za-z0-9_-]+)/renew$", path)
        if not m:
            return self._send(404, {"error": "not found"})
        token = m.group(1)
        if not portal_check_cookie(token, self.headers.get("Cookie")):
            return self._send(403, "<h1>请先输入访问码</h1>", "text/html; charset=utf-8")
        slug = portal_slug(token)
        if not slug:
            return self._send(404, "<h1>链接无效</h1>", "text/html; charset=utf-8")
        # 同一站点已有未付款的续费账单就不重复开
        dl = days_left(slug)
        if dl is not None and dl > 300:
            log_access(slug, "renew_same", token, "期限充足未开单", self)
            self.send_response(303)
            self.send_header("Location", "/portal/%s?ok=2" % token)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        pending = [i for i in invoices() if i.get("slug") == slug
                   and i.get("kind") == "renewal" and i.get("status") != "paid"]
        if not pending:
            b = read_billing(slug)
            plan = next((p for p in plans() if p["id"] == b.get("plan_id")), None)
            if not plan:
                plan = {"id": "renewal", "name": "Renewal", "price": 0, "specs": "Annual renewal"}
            meta = load_meta(slug)
            self._make_invoice(slug, meta.get("company", slug), meta.get("domain", ""),
                               dict(plan, name=plan["name"] + " · 续费 1 年"),
                               kind="renewal", years=1)
        log_access(portal_slug(token) or "-", "renew", token, "发起续费", self)
        self.send_response(303)
        self.send_header("Location", "/portal/%s?ok=1" % token)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _public(self, path):
        m = re.match(r"^/sa/([A-Za-z0-9_-]+)/(.+)$", path)
        if m:
            token, rel = m.group(1), m.group(2)
            s = share_for(token)
            if not s:
                return self._send(404, {"error": "链接无效或已过期"})
            root = (SITES / s["slug"] / "html").resolve()
            if rel == "style.css":
                f = root / "wp-content" / "themes" / "kampong" / "style.css"
            elif rel.startswith("uploads/"):
                f = root / "wp-content" / rel
            else:
                return self._send(404, {"error": "not found"})
            try:
                f = f.resolve()
                if not str(f).startswith(str(root)) or not f.is_file():
                    return self._send(404, {"error": "not found"})
            except Exception:
                return self._send(404, {"error": "not found"})
            ctype = {".css": "text/css; charset=utf-8", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                     ".gif": "image/gif", ".svg": "image/svg+xml"}.get(
                         f.suffix.lower(), "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype)

        m = re.match(r"^/s/([A-Za-z0-9_-]+)(?:/([a-z0-9-]*))?$", path)
        if m:
            token = m.group(1)
            page = m.group(2) or "home"
            s = share_for(token)
            if not s:
                return self._send(404, "<h1>链接无效或已过期</h1>", "text/html; charset=utf-8")
            allowed = s.get("pages") or []
            if allowed and page not in allowed:
                page = allowed[0]
            html = preview_html(s["slug"], page,
                                base="/s/%s" % token, asset="/sa/%s" % token, public=True)
            return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def _shares_list(self, slug):
        out = []
        for token, s in shares().items():
            if s.get("slug") != slug:
                continue
            out.append({"token": token, "url": "/s/%s" % token,
                        "created": s.get("created", ""), "expires": s.get("expires", ""),
                        "active": bool(s.get("active")),
                        "alive": share_for(token) is not None,
                        "note": s.get("note", "")})
        out.sort(key=lambda x: x.get("created", ""), reverse=True)
        return out

    def _share_create(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        try:
            days = int(body.get("days", 14))
        except Exception:
            days = 14
        days = max(1, min(365, days))
        import secrets
        token = secrets.token_urlsafe(12)
        exp = (datetime.now(SGT) + timedelta(days=days)).strftime("%Y-%m-%d")
        with _file_lock:
            data = shares()
            data[token] = {"slug": slug, "active": True,
                           "created": datetime.now(SGT).strftime("%Y-%m-%d"),
                           "expires": exp, "note": str(body.get("note", ""))[:60],
                           "pages": []}
            _write(SHARES_F, data)
        return self._send(200, {"token": token, "url": "/s/%s" % token, "expires": exp})

    def _share_revoke(self, body):
        token = str(body.get("token", "")).strip()
        with _file_lock:
            data = shares()
            if token not in data:
                return self._send(404, {"error": "链接不存在"})
            data[token]["active"] = False
            _write(SHARES_F, data)
        return self._send(200, {"ok": True})

    def _drain(self, length, cap=16 * 1024 * 1024):
        """把未读的请求体读掉，否则客户端会收到连接重置而不是 413。"""
        left = min(length, cap)
        try:
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
        except Exception:
            pass

    def _upload(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        slug = ""
        for kv in qs.split("&"):
            if kv.startswith("slug="):
                slug = kv[5:].lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})

        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if "multipart/form-data" not in ctype or not m:
            return self._send(400, {"error": "需要 multipart/form-data"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return self._send(400, {"error": "空请求"})
        if length > MAX_UPLOAD + 65536:
            self._drain(length)
            return self._send(413, {"error": "文件过大（上限 8MB）"})

        raw = self.rfile.read(length)
        name, data = parse_multipart(raw, m.group(1).encode())
        if not data:
            return self._send(400, {"error": "没有收到文件"})

        ext = sniff_image(data)
        if not ext:
            return self._send(415, {"error": "只支持 JPG / PNG / WebP / GIF"})

        original = len(data)
        w = h = 0
        variants = {}
        try:
            data, w, h, variants = to_webp_variants(data)
            ext = ".webp"
        except Exception:
            pass  # 压缩失败就用原图，不阻断上传

        outdir = SITES / slug / "html" / MEDIA_DIR
        outdir.mkdir(parents=True, exist_ok=True)
        fname = f"{slug}-{int(time.time())}{ext}"
        (outdir / fname).write_bytes(data)
        try:
            (outdir / fname).chmod(0o644)
        except OSError:
            pass

        srcset = []
        for vw, vbytes in sorted(variants.items()):
            vname = fname[:-5] + f"-{vw}{ext}"
            (outdir / vname).write_bytes(vbytes)
            try:
                (outdir / vname).chmod(0o644)
            except OSError:
                pass
            srcset.append({"url": f"/{MEDIA_DIR}/{vname}", "w": vw})
        srcset.append({"url": f"/{MEDIA_DIR}/{fname}", "w": w})

        return self._send(200, {"url": f"/{MEDIA_DIR}/{fname}", "name": fname,
                                "size": len(data), "original": original,
                                "width": w, "height": h,
                                "srcset": [x for x in srcset if x["w"] > 0]})

    def _portal_create(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        import secrets
        with _file_lock:
            data = portals()
            for tok in [k for k, v in data.items() if v["slug"] == slug]:
                data[tok]["active"] = False
            pin = str(body.get("pin") or "").strip()
            if not (pin.isdigit() and 4 <= len(pin) <= 8):
                pin = "%06d" % secrets.randbelow(1000000)
            salt = secrets.token_hex(8)
            token = secrets.token_urlsafe(10)
            data[token] = {"slug": slug, "active": True,
                           "created": datetime.now(SGT).strftime("%Y-%m-%d"),
                           "pin_salt": salt, "pin_hash": pin_hash(pin, salt)}
            _write(PORTAL_F, data)
        return self._send(200, {"token": token, "url": "/portal/%s" % token, "pin": pin})

    def _portal_revoke(self, body):
        token = str(body.get("token", "")).strip()
        with _file_lock:
            data = portals()
            if token not in data:
                return self._send(404, {"error": "链接不存在"})
            data[token]["active"] = False
            _write(PORTAL_F, data)
        return self._send(200, {"ok": True})

    def _smtp_save(self, body):
        if getattr(self, "user_role", "ops") != "admin":
            return self._send(403, {"error": "只有管理员可以改邮件设置"})
        cur = settings()
        s = dict(cur.get("smtp") or {})
        for k in ("host", "user", "from", "api_key", "provider"):
            if k in body:
                s[k] = str(body[k]).strip()[:120]
        for k in ("port",):
            if k in body:
                try:
                    s[k] = int(body[k]) or 587
                except Exception:
                    s[k] = 587
        if "tls" in body:
            s["tls"] = bool(body["tls"])
        if s.get("provider") not in ("smtp", "resend", "sendgrid"):
            s["provider"] = "smtp"
        pw = str(body.get("pass", ""))
        if pw and pw != "********":
            s["pass"] = pw
        cur["smtp"] = s
        _write(SETTINGS_F, cur)
        audit(getattr(self, "user", "-"), "smtp_save", s.get("host", ""))
        return self._send(200, {"ok": True})

    def _roles_save(self, body):
        if getattr(self, "user_role", "ops") != "admin":
            return self._send(403, {"error": "只有管理员可以改权限"})
        role = str(body.get("role", "")).strip()
        if role not in DEFAULT_ROLES:
            return self._send(400, {"error": "未知角色"})
        write = body.get("write")
        if write is None or (isinstance(write, list) and len(write) == 0):
            write = None if role == "admin" else []
        if not isinstance(write, list):
            return self._send(400, {"error": "写入权限必须是列表"})
        write = [str(x)[:60] for x in write][:40]
        saved = _read(ROLES_F, {})
        saved[role] = {"label": DEFAULT_ROLES[role]["label"], "write": write}
        _write(ROLES_F, saved)
        audit(getattr(self, "user", "-"), "roles_save", role,
              "%d 条规则" % len(write) if write is not None else "全部允许")
        return self._send(200, {"ok": True, "role": role, "write": write})

    def _password_save(self, body):
        u = getattr(self, "user", "")
        users = load_users()
        if u not in users:
            return self._send(400, {"error": "账号不存在"})
        old = str(body.get("old", ""))
        new = str(body.get("new", ""))
        if not check_login(u, old):
            audit(u, "password_change", "旧密码错误")
            return self._send(400, {"error": "旧密码不正确"})
        prob = password_problem(u, new)
        if prob:
            return self._send(400, {"error": prob})
        if new == old:
            return self._send(400, {"error": "新密码不能与旧密码相同"})
        import secrets as _s
        salt = _s.token_hex(8)
        users[u]["salt"] = salt
        users[u]["hash"] = pin_hash(new, salt)
        users[u]["pwd_changed"] = datetime.now(SGT).strftime("%Y-%m-%d")
        _write(USERS_F, users)
        # 踢掉该账号的其他会话，保留当前
        keep = (cookie_value(self.headers.get("Cookie"), "kf_sid") or "").split(".")[0]
        drop = [sid for sid, s in SESSIONS.items() if s.get("user") == u and sid != keep]
        for sid in drop:
            SESSIONS.pop(sid, None)
        save_sessions()
        audit(u, "password_change", "已改密，踢掉 %d 个会话" % len(drop))
        return self._send(200, {"ok": True, "killed": len(drop)})

    def _mfa_save(self, body):
        u = getattr(self, "user", "")
        users = load_users()
        if u not in users:
            return self._send(400, {"error": "账号不存在"})
        act = str(body.get("action", "enable"))
        code = str(body.get("code", "")).strip()
        if act == "enable":
            sec = PENDING_MFA.get(u)
            if not sec:
                return self._send(400, {"error": "请先刷新页面获取密钥"})
            if not totp_verify(sec, code):
                return self._send(400, {"error": "验证码不正确，请确认手机时间准确"})
            users[u]["mfa_secret"] = sec
            codes = gen_recovery()
            users[u]["recovery"] = hash_recovery(codes, users[u].get("salt", ""))
            _write(USERS_F, users)
            PENDING_MFA.pop(u, None)
            audit(u, "mfa_enable", "")
            return self._send(200, {"ok": True, "enabled": True, "recovery": codes})
        if act == "regen":
            if not totp_verify(users[u].get("mfa_secret", ""), code):
                return self._send(400, {"error": "验证码不正确"})
            codes = gen_recovery()
            users[u]["recovery"] = hash_recovery(codes, users[u].get("salt", ""))
            _write(USERS_F, users)
            audit(u, "recovery_regen", "10 个新码")
            return self._send(200, {"ok": True, "recovery": codes})

        if act == "disable":
            if not totp_verify(users[u].get("mfa_secret", ""), code):
                return self._send(400, {"error": "验证码不正确"})
            users[u].pop("mfa_secret", None)
            _write(USERS_F, users)
            audit(u, "mfa_disable", "")
            return self._send(200, {"ok": True, "enabled": False})
        return self._send(400, {"error": "未知操作"})

    def _login(self):
        form = self._form_body()
        u = str(form.get("user", "")).strip()
        pw = str(form.get("pw", ""))
        code = str(form.get("code", "")).strip()
        nxt = str(form.get("next", "/")) or "/"
        if not nxt.startswith("/"):
            nxt = "/"
        ip = self.client_address[0] if self.client_address else ""
        ipwait = ip_blocked(ip)
        if ipwait > 0:
            audit(u or "-", "login_ip_blocked", "%s 还需 %d 秒" % (ip, ipwait))
            return self._send(200, login_page(
                "该网络登录失败次数过多，请 %d 分钟后再试" % max(1, ipwait // 60), nxt),
                "text/html; charset=utf-8")
        wait = locked_for(u)
        if wait > 0:
            audit(u or "-", "login_locked", "还需 %d 秒" % wait)
            return self._send(200, login_page(
                "失败次数过多，请 %d 分钟后再试" % max(1, wait // 60), nxt),
                "text/html; charset=utf-8")
        if not check_login(u, pw):
            left = note_fail(u)
            note_ip_fail(ip)
            audit(u or "-", "login_fail", "%s%s" % (ip, " 已锁定" if left else ""))
            msg = ("失败次数过多，账号已锁定 %d 分钟" % (left // 60)) if left else "用户名或密码不正确"
            return self._send(200, login_page(msg, nxt), "text/html; charset=utf-8")
        entry = load_users().get(u) or {}
        secret = entry.get("mfa_secret")
        used_recovery = False
        if secret:
            if totp_verify(secret, code):
                pass
            else:
                idx = match_recovery(entry, code) if code else -1
                if idx >= 0:
                    users_all = load_users()
                    users_all[u]["recovery"] = list(users_all[u].get("recovery") or [])
                    users_all[u]["recovery"].pop(idx)
                    _write(USERS_F, users_all)
                    used_recovery = True
                    audit(u, "recovery_used", "剩余 %d" % len(users_all[u]["recovery"]))
                else:
                    audit(u, "login_fail", "验证码错误")
                    return self._send(200, login_page("两步验证码不正确", nxt),
                                      "text/html; charset=utf-8")
        clear_fails(u)
        try:
            _us = load_users()
            if u in _us:
                _us[u]["last_login"] = datetime.now(SGT).strftime("%Y-%m-%d %H:%M")
                _write(USERS_F, _us)
        except Exception:
            pass
        cookie = new_session(u)
        audit(u, "login_ok", "MFA" if secret else "密码")
        self.send_response(303)
        self.send_header("Location", nxt)
        self.send_header("Set-Cookie",
                         "kf_sid=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax"
                         % (cookie, SESSION_TTL))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _users_save(self, body):
        if getattr(self, "user_role", "ops") != "admin":
            return self._send(403, {"error": "只有管理员可以管理账号"})
        act = str(body.get("action", "add"))
        uname = re.sub(r"[^a-z0-9_.-]", "", str(body.get("user", "")).lower())[:24]
        users = load_users()
        if act == "add":
            if not uname or uname in users:
                return self._send(400, {"error": "用户名已存在或为空"})
            import secrets as _s
            pw = _s.token_urlsafe(9)
            salt = _s.token_hex(8)
            users[uname] = {"name": str(body.get("name", uname))[:30],
                            "role": ("admin" if body.get("role") == "admin"
                                     else "finance" if body.get("role") == "finance" else "ops"),
                            "salt": salt, "hash": pin_hash(pw, salt), "active": True,
                            "created": datetime.now(SGT).strftime("%Y-%m-%d")}
            _write(USERS_F, users)
            return self._send(200, {"ok": True, "user": uname, "password": pw})
        if uname not in users:
            return self._send(404, {"error": "用户不存在"})
        if act == "disable":
            if uname == getattr(self, "user", ""):
                return self._send(400, {"error": "不能停用自己"})
            users[uname]["active"] = False
        elif act == "enable":
            users[uname]["active"] = True
        elif act == "unlock":
            clear_fails(uname)
            audit(getattr(self, "user", "-"), "unlock", uname)
            return self._send(200, {"ok": True, "user": uname})
        elif act == "reset_mfa":
            users[uname].pop("mfa_secret", None)
            users[uname].pop("recovery", None)
            _write(USERS_F, users)
            for sid in [k for k, v in SESSIONS.items() if v.get("user") == uname]:
                SESSIONS.pop(sid, None)
            save_sessions()
            audit(getattr(self, "user", "-"), "mfa_reset", uname, "已踢掉该账号全部会话")
            return self._send(200, {"ok": True, "user": uname,
                                    "message": "已重置，该账号下次用密码登录"})
        elif act == "reset":
            import secrets as _s
            pw = _s.token_urlsafe(9)
            salt = _s.token_hex(8)
            users[uname]["salt"] = salt
            users[uname]["hash"] = pin_hash(pw, salt)
            users[uname]["pwd_changed"] = datetime.now(SGT).strftime("%Y-%m-%d")
            _write(USERS_F, users)
            # 密码被重置意味着旧凭据可能已泄露，踢掉该账号全部会话
            killed = 0
            for sid in [k for k, v in SESSIONS.items() if v.get("user") == uname]:
                SESSIONS.pop(sid, None)
                killed += 1
            if killed:
                save_sessions()
            audit(getattr(self, "user", "-"), "password_reset", uname,
                  "踢掉 %d 个会话" % killed)
            return self._send(200, {"ok": True, "user": uname, "password": pw,
                                    "sessions_killed": killed})
        else:
            return self._send(400, {"error": "未知操作"})
        _write(USERS_F, users)
        return self._send(200, {"ok": True, "user": uname})

    def _dns_enable(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        m = dnsmod()
        zones = m.load_zones()
        if zones.get(slug):
            return self._send(409, {"error": "该站点已有 DNS 区"})
        meta = load_meta(slug)
        domain = (meta.get("domain") or "").strip().lower()
        if not domain:
            return self._send(400, {"error": "站点没有配置域名"})
        ip = str(body.get("ip") or "").strip() or "101.204.233.11"
        zones[slug] = m.new_zone(domain, ip)
        m.save_zones(zones)
        return self._send(200, {"ok": True, "domain": domain})

    def _dns_record(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        name = str(body.get("name", "@")).strip() or "@"
        rtype = str(body.get("type", "A")).strip().upper()
        value = str(body.get("value", "")).strip()
        try:
            ttl = max(60, min(86400, int(body.get("ttl", 300))))
        except Exception:
            ttl = 300
        if rtype not in ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV"):
            return self._send(400, {"error": "不支持的记录类型"})
        if not value:
            return self._send(400, {"error": "记录值不能为空"})
        if not re.match(r"^(@|\*|[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*)$",
                        name.lower()):
            return self._send(400, {"error": "记录名不合法"})
        m = dnsmod()
        zones = m.load_zones()
        z = zones.get(slug)
        if not z:
            return self._send(400, {"error": "请先启用 DNS 托管"})
        if len(z.get("records") or []) >= MAX_DNS_RECORDS:
            return self._send(400, {"error": "该域名的记录数已达上限（%d 条）"
                                              % MAX_DNS_RECORDS})
        z["records"].append({"name": name, "type": rtype, "ttl": ttl, "value": value})
        m.save_zones(zones)
        return self._send(200, {"ok": True})

    def _dns_delete(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        try:
            idx = int(body.get("index", -1))
        except Exception:
            idx = -1
        m = dnsmod()
        zones = m.load_zones()
        z = zones.get(slug)
        if not z or not (0 <= idx < len(z["records"])):
            return self._send(404, {"error": "记录不存在"})
        rec = z["records"][idx]
        if rec["type"] in ("SOA", "NS") and rec["name"] == "@":
            return self._send(400, {"error": "SOA / NS 记录不可删除"})
        z["records"].pop(idx)
        m.save_zones(zones)
        return self._send(200, {"ok": True})

    def _renew(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        try:
            years = max(1, min(5, int(body.get("years", 1))))
        except Exception:
            years = 1
        b = read_billing(slug)
        plan = next((p for p in plans() if p["id"] == b.get("plan_id")), None)
        if not plan:
            plan = {"id": "renewal", "name": "Renewal", "price": 0, "specs": "Annual renewal"}
        meta = load_meta(slug)
        base = b.get("expires") or datetime.now(SGT).strftime("%Y-%m-%d")
        dl = days_left(slug)
        if dl is not None and dl < 0:
            base = datetime.now(SGT).strftime("%Y-%m-%d")
        b["expires"] = add_years(base, years)
        b["status"] = "active"
        (SITES / slug / "billing.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))
        inv = self._make_invoice(slug, meta.get("company", slug), meta.get("domain", ""),
                                 dict(plan, name=(plan["name"] + " · 续费 %d 年" % years)))
        return self._send(200, {"ok": True, "expires": b["expires"], "invoice": inv["no"]})

    def _suspend(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        action = str(body.get("action", "stop"))
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        if action not in ("stop", "start"):
            return self._send(400, {"error": "未知操作"})
        try:
            r = subprocess.run(["docker", "compose", action], cwd=str(SITES / slug),
                               capture_output=True, text=True, timeout=180)
            ok = r.returncode == 0
        except Exception:
            ok = False
        b = read_billing(slug)
        b["status"] = "suspended" if action == "stop" else "active"
        (SITES / slug / "billing.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))
        return self._send(200 if ok else 500,
                          {"ok": ok, "status": b["status"],
                           "error": "" if ok else "容器操作失败"})

    def _spec_save(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        page = str(body.get("page", "")).strip()
        sections = body.get("sections")
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"ok": False, "error": "站点不存在"})
        if not isinstance(sections, list) or not page:
            return self._send(400, {"ok": False, "error": "缺少 page 或 sections"})

        draft = read_draft(slug)
        target = next((p for p in draft.get("pages", []) if p["slug"] == page), None)
        if not target:
            return self._send(404, {"ok": False, "error": "页面不存在"})

        res = self._render_check(slug, page, target.get("title", page), sections)
        if not res.get("ok"):
            return self._send(400, {
                "ok": False, "error": "；".join(res.get("errors", ["校验未通过"])),
                "stage": res.get("stage", "")})

        target["sections"] = sections
        draft_path(slug).write_text(json.dumps(draft, ensure_ascii=False, indent=1))
        return self._send(200, {"ok": True, "length": res.get("length"),
                                "dirty": is_dirty(slug), "message": "已保存到草稿"})

    def _render_check(self, slug, page, title, sections, write=False):
        tmp = CONSOLE / ".tmp-page.json"
        tmp.write_text(json.dumps({"title": title, "sections": sections}, ensure_ascii=False))
        try:
            args = [sys.executable, str(BASE / "core" / "kf_sections.py"),
                    "--site", str(SITES / slug), "--page-slug", page, "--save", str(tmp)]
            if not write:
                args.append("--dry-run")
            r = subprocess.run(args, capture_output=True, text=True, timeout=300)
            out = (r.stdout or "").strip().splitlines()
            return json.loads(out[-1]) if out else {"ok": False, "errors": [(r.stderr or "")[-200:]]}
        except Exception as e:
            return {"ok": False, "stage": "exception", "errors": [str(e)]}
        finally:
            tmp.unlink(missing_ok=True)

    def _publish(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        page_slug = str(body.get("page", "")).strip()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"ok": False, "error": "站点不存在"})

        draft = read_draft(slug)
        pages = draft.get("pages", [])
        targets = [p for p in pages if p["slug"] == page_slug] if page_slug else pages
        if not targets:
            return self._send(404, {"ok": False, "error": "草稿里没有这一页"})

        failed = []
        for page in targets:
            res = self._render_check(slug, page["slug"], page.get("title", page["slug"]),
                                     page.get("sections", []), write=True)
            if not res.get("ok"):
                failed.append({"page": page["slug"],
                               "error": "；".join(res.get("errors", ["失败"]))})
                break
        if failed:
            return self._send(400, {"ok": False, "error": "发布中断，页面未被改动",
                                    "failed": failed})

        live = read_spec(slug)
        live_pages = live.get("pages", [])
        for page in targets:
            cur = next((p for p in live_pages if p["slug"] == page["slug"]), None)
            if cur is None:
                live_pages.append(json.loads(json.dumps(page)))
            else:
                cur["sections"] = json.loads(json.dumps(page.get("sections", [])))
                cur["title"] = page.get("title", cur.get("title", page["slug"]))
        live["pages"] = live_pages
        spec_path(slug).write_text(json.dumps(live, ensure_ascii=False, indent=1))
        return self._send(200, {"ok": True, "pages": len(targets), "dirty": is_dirty(slug)})

    def _design_save(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        tokens = sanitize_design(body)
        before = _read(SITES / slug / "design.json", {})
        ok = apply_design(slug, tokens)
        audit(getattr(self, "user", "-"), "design_save", slug,
              diff_summary((before or {}).get("palette", {}), (tokens or {}).get("palette", {})))
        return self._send(200 if ok else 500,
                          {"ok": ok, "tokens": tokens,
                           "error": "" if ok else "已写入文件，但同步到 WordPress 失败"})

    def _plan_save(self, body):
        pid = re.sub(r"[^a-z0-9-]", "", str(body.get("id", "")).lower())[:20]
        if not pid:
            return self._send(400, {"error": "套餐 ID 必填且只能用小写字母数字"})
        try:
            price = float(body.get("price", 0))
        except Exception:
            return self._send(400, {"error": "价格必须是数字"})
        item = {"id": pid, "name": str(body.get("name", pid))[:40], "price": price,
                "period": str(body.get("period", "首年"))[:20],
                "specs": str(body.get("specs", ""))[:120],
                "dns": bool(body.get("dns", True))}
        with _file_lock:
            ps = plans()
            ps = [p for p in ps if p["id"] != pid] + [item]
            old = next((p for p in ps if p["id"] == pid), {})
            _write(PLANS_F, ps)
        audit(getattr(self, "user", "-"), "plan_save", pid, diff_summary(old, item))
        return self._send(200, item)


if __name__ == "__main__":
    CONSOLE.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) >= 3 and sys.argv[1] == "--reset-mfa":
        try:
            ensure_admin()
        except Exception:
            pass
        _u = sys.argv[2]
        _users = load_users()
        if _u in _users:
            _users[_u].pop("mfa_secret", None)
            _users[_u].pop("recovery", None)
            _write(USERS_F, _users)
            print("已重置 %s 的两步验证，下次可用密码登录" % _u)
        else:
            print("账号不存在：%s" % _u)
        sys.exit(0)

    def serve_https():
        import ssl
        cert = CONSOLE / "tls" / "cert.pem"
        key = CONSOLE / "tls" / "key.pem"
        if not cert.exists():
            return
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert), str(key))
            s = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), Handler)
            s.socket = ctx.wrap_socket(s.socket, server_side=True)
            print("HTTPS on 0.0.0.0:%d" % HTTPS_PORT, flush=True)
            s.serve_forever()
        except Exception as e:
            print("https failed:", e, flush=True)

    threading.Thread(target=serve_https, daemon=True).start()
    try:
        load_ipfails()
    except Exception:
        pass
    try:
        load_fails()
    except Exception:
        pass
    try:
        load_sessions()
    except Exception:
        pass
    try:
        ensure_admin()
    except Exception as e:
        print("users init failed:", e, flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"KampongFlow console v2 on 0.0.0.0:{PORT}", flush=True)
    srv.serve_forever()
