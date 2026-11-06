#!/usr/bin/env python3
"""KampongFlow 管理后台 v2 — 站点 / 套餐 / 账单 / PDF 导出。

单文件，依赖：reportlab（用于中文 PDF）。
"""
import base64
import hmac as _h
import sys
import time
import importlib.util
import html as _htmlesc
import csv
import qrcode
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import kf_ai
import kf_prompts
import kf_styles
import kf_sso
import kf_domain_vault
import kf_mcp
import kf_automation
import kf_tool_runtime
import kf_providers
import kf_builtin_tools
import kf_dns_provider
import kf_stepup
import kf_workflows

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
PROV    = BASE / "tools" / "kf_provision.sh"
CONSOLE = BASE / "console"
PORT    = int(os.environ.get("KF_PORT", "18090"))
HTTPS_PORT = int(os.environ.get("KF_HTTPS_PORT", "18443"))
# 监听地址：默认只绑回环，反代在前面时不会裸露在公网
BIND    = os.environ.get("KF_BIND", "127.0.0.1")
# 可信代理白名单：只有这些来源的 X-Forwarded-For 才被采信
TRUSTED_PROXIES = tuple(
    x.strip() for x in os.environ.get("KF_TRUSTED_PROXIES", "").split(",") if x.strip())
# 强制 HTTPS（决定 Cookie 是否加 Secure）
FORCE_HTTPS = os.environ.get("KF_FORCE_HTTPS", "0") == "1"
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


def consume_totp(user, secret, code, purpose):
    """Called inside auth_transaction: verification and replay state are atomic."""
    import hashlib
    if not secret or not re.fullmatch(r"[0-9]{6}", code or ""):
        return False
    now = int(time.time() // 30)
    counter = next((i for i in (now, now-1, now+1) if _h.compare_digest(_totp(secret, i), code)), None)
    if counter is None: return False
    path = CONSOLE / "login-mfa.json"
    data = kf_ai.read_json(path, {})
    key = purpose + ":" + user
    version = hashlib.sha256(secret.encode()).hexdigest()
    old = data.get(key, {})
    if old.get("secret_version") == version and counter <= old.get("counter", -1):
        return False
    data[key] = {"secret_version": version, "counter": counter}
    kf_ai.atomic_json(path, data)
    return True


def auth_transaction(fn):
    from functools import wraps
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with kf_domain_vault.DomainVault(BASE).locked():
            # Recovery consumption, MFA changes and password changes share a lock.
            load_fails(); load_ipfails()
            return fn(self, *args, **kwargs)
    return wrapped


def revoke_other_sessions(user, cookie_header=None):
    keep = (cookie_value(cookie_header, "kf_sid") or "").split(".")[0]
    for sid in [sid for sid, value in SESSIONS.items() if value.get("user") == user and sid != keep]:
        SESSIONS.pop(sid, None)
    save_sessions()


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


def mfa_qr_data(uri):
    """Render enrollment locally; never send the TOTP secret to a third party."""
    buf = io.BytesIO()
    qrcode.make(uri, box_size=6, border=4).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def totp_new_secret():
    import base64, secrets as _s
    return base64.b32encode(_s.token_bytes(20)).decode().rstrip("=")


ROLES_F = CONSOLE / "roles.json"

DEFAULT_ROLES = {
    "admin": {"label": "管理员", "write": None},
    "ops": {"label": "运营", "write": [
        "/api/spec", "/api/design", "/api/media/", "/api/dns/", "/api/domain/manage",
        "/api/clients/save", "/api/shares", "/api/publish", "/api/create", "/api/suspend",
        "/api/mfa", "/api/invoice/issue", "/api/ledger", "/api/ai/build", "/api/wordpress/login", "/api/domain/accounts", "/api/automation/",
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


def can_read(role, path):
    if role == "admin": return True
    if role not in ("ops", "finance"): return False
    if path in ("/api/users", "/api/security", "/api/smtp", "/api/updates", "/health/ip") or path.startswith("/api/audit"):
        return False
    if role == "ops": return True
    return (path in ("/", "/api/state", "/api/mfa", "/api/roles", "/api/clients", "/api/renewals",
                     "/api/domains", "/api/wordpress/sites", "/export/invoices.csv")
            or path.startswith(("/api/ledger/", "/api/invoice/"))
            or path in ("/ai.js", "/prompts.js", "/domains.js", "/mcp.js", "/automation.js", "/providers.js"))


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


def proxy_secret():
    """反代与后台之间的共享密钥。

    只有带上正确密钥的请求才被当作来自反代，
    这样本机进程无法靠伪造 X-Forwarded-For 绕过限流。
    """
    env = os.environ.get("KF_PROXY_SECRET", "")
    if env:
        return env
    try:
        return (CONSOLE / "proxy.secret").read_text().strip()
    except Exception:
        return ""


def client_ip(handler):
    """取真实客户端 IP。

    直连时用 socket 地址；经反代进来且密钥正确时采信 X-Forwarded-For。
    密钥不对就退回到直连地址，伪造的头一律无效。
    """
    try:
        peer = handler.client_address[0] if handler.client_address else ""
    except Exception:
        peer = ""
    if TRUSTED_PROXIES and peer in TRUSTED_PROXIES:
        sec = proxy_secret()
        given = handler.headers.get("X-KF-Proxy-Secret", "")
        if sec and given and _h.compare_digest(given, sec):
            xff = handler.headers.get("X-Forwarded-For", "")
            if xff:
                first = xff.split(",")[0].strip()
                if first:
                    return first
    return peer


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


def csrf_token(cookie_header):
    """Session-bound token, never an authentication credential by itself."""
    import hashlib
    value = cookie_value(cookie_header, "kf_sid") or ""
    if not session_user(cookie_header):
        return ""
    return _h.new(portal_secret(), ("csrf:" + value).encode(), hashlib.sha256).hexdigest()


def safe_next(value):
    return value if (isinstance(value, str) and value.startswith("/") and not value.startswith("//")
                     and not any(ord(c) <= 32 or c == "\\" for c in value) and len(value) < 2000) else "/"


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

if FONT == "STSong-Light":
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT, italic=FONT, boldItalic=FONT)

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

# 密钥单独放一个 600 文件，不与普通配置混在一起
SECRETS_F = CONSOLE / "secrets.json"


def load_secrets():
    """读取密钥。优先环境变量，其次 600 权限的 secrets.json。"""
    env = {}
    for k in ("KF_SMTP_API_KEY", "KF_SMTP_PASS", "KF_SMTP_USER"):
        v = os.environ.get(k)
        if v:
            env[k[len("KF_SMTP_"):].lower()] = v
    stored = _read(SECRETS_F, {}) if SECRETS_F.exists() else {}
    out = dict(stored)
    out.update(env)          # 环境变量优先
    return out


def save_secrets(d):
    tmp = SECRETS_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(SECRETS_F)
    try:
        SECRETS_F.chmod(0o600)
    except OSError:
        pass


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
    """普通设置 + 密钥合并。返回的对象含密钥，只能在服务端内部用。"""
    if not SETTINGS_F.exists():
        _write(SETTINGS_F, DEFAULT_SETTINGS)
    s = dict(DEFAULT_SETTINGS)
    s.update(_read(SETTINGS_F, {}))
    smtp = dict(s.get("smtp") or {})
    sec = load_secrets()
    if sec.get("api_key"):
        smtp["api_key"] = sec["api_key"]
    if sec.get("pass"):
        smtp["pass"] = sec["pass"]
    if sec.get("user"):
        smtp["user"] = sec["user"]
    s["smtp"] = smtp
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


def design_vars(slug, tokens=None):
    d = tokens if tokens is not None else _read(SITES / slug / "design.json", {})
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
        "--kf-overlay": (d.get("photos") or {}).get("overlay", "0.46") if re.fullmatch(r"(?:0(?:\.\d{1,2})?|1(?:\.0{1,2})?)", str((d.get("photos") or {}).get("overlay", "0.46"))) else "0.46",
    }
    return ":root{" + "".join(f"{k}:{val};" for k, val in v.items()) + "}" + kf_styles.advanced_css(d)


def style_preview_html(body):
    """Render an isolated local sample using the same section renderer and theme."""
    import html as _html
    import base64
    tokens = kf_styles.normalize_tokens(body.get('tokens', {}))
    recipe = kf_styles.normalize_recipe(body)
    name = kf_ai.text(body.get('name', 'Untitled style'), '模板名称', 80, True)
    samples = {
        'hero': {'kicker':'YOUR BRAND / LOCAL TEMPLATE', 'title':name,
                 'text':'A considered first impression. Replace this sample with your business story.',
                 'art':True, 'cta':{'label':'Explore our work','href':'#sample-content'}},
        'cards': {'title':'Designed around your needs', 'items':[
            {'title':'Thoughtful details','text':'Use this space to explain a real service or benefit.'},
            {'title':'A clear process','text':'Guide visitors through the next step with confidence.'},
            {'title':'Room to grow','text':'Adapt the content and layout to fit your business.'}]},
        'split': {'title':'A story worth sharing', 'text':'Use a strong visual and a short introduction to explain what makes your approach distinctive.',
                  'items':['Your approach','Your experience','Your next chapter']},
        'gallery': {'title':'Selected work','items':[{'src':'/template-sample-%d.svg'%i,'label':'Sample composition %d'%i} for i in range(1,4)]},
        'quotes': {'title':'In their words','items':[{'text':'A testimonial belongs here only when supplied and approved by a real customer.','by':'Sample placeholder'}]},
        'table': {'title':'The details, at a glance','headers':['Offering','Details'],'rows':[['Your service','Add a verified description'],['Your next option','Add confirmed information']]},
        'list': {'title':'What comes next','items':['Explore the options','Ask a question','Plan your next step']},
        'rich': {'html':'<h2>Space for your story</h2><p>A flexible section for an introduction, an announcement or an editorial passage.</p>'},
        'form': {'title':'Get in touch','submit':'Send enquiry'},
        'stats': {'items':[{'value':'—','label':'Add verified metrics'},{'value':'—','label':'Replace sample values'}]},
        'band': {'src':'/template-sample-1.svg','alt':'Original abstract sample artwork','caption':'Local placeholder artwork'},
        'cta': {'title':'Let’s begin a conversation','text':'One clear next step, in your own words.','button':'Get in touch','href':'#sample-content'},
    }
    sections=[dict(samples[k],type=k) for k in recipe['blueprint'] or ['hero','cards','split','cta']]
    content=ks().render_sections(sections)
    content=re.sub(r'\[kf_contact_form[^\]]*\]', '<div class="kf-form"><label>Your name<input disabled placeholder="Sample form"></label><label>Email<input disabled placeholder="you@example.com"></label><button class="kf-btn" disabled>Preview only</button></div>', content)
    for i in range(1,4):
        svg=('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">'
             '<rect width="800" height="600" fill="%s"/><circle cx="%d" cy="240" r="180" fill="%s"/>'
             '<path d="M0 600 400 250 800 600Z" fill="%s"/></svg>')%(tokens['palette']['bg'],200*i,tokens['palette']['accent'],tokens['palette']['primary'])
        content=content.replace('/template-sample-%d.svg'%i,'data:image/svg+xml;base64,'+base64.b64encode(svg.encode()).decode())
    css=(BASE/'theme/kampong/style.css').read_text()+'\n'+design_vars('',tokens)+'\n'+(BASE/'theme/kampong/reference.css').read_text()
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; img-src data:; style-src &#39;unsafe-inline&#39;; form-action &#39;none&#39;; base-uri &#39;none&#39;">'
            '<title>'+_html.escape(name)+'</title><style>'+css+'</style></head><body class="kf-style-reference">'
            '<header class="kf-header"><div class="kf-container kf-header-inner"><b class="kf-logo">'+_html.escape(name)+'</b></div></header>'
            '<main id="sample-content" class="kf-main"><div class="kf-content">'+content+'</div></main>'
            '<footer class="kf-footer"><div class="kf-container">Local template preview · Sample content</div></footer></body></html>')


# Untrusted previews/assets must never execute with the console's origin privileges.
PREVIEW_HEADERS = {"Content-Security-Policy":
    "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; "
    "img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"}


def preview_asset(slug, rel):
    """Fixed theme CSS or an image strictly within uploads, including after symlinks."""
    root = (SITES / slug / "html").resolve()
    if rel == "style.css":
        parent = root / "wp-content" / "themes" / "kampong"
        f = parent / "style.css"
        ctype = "text/css; charset=utf-8"
    else:
        from urllib.parse import unquote
        rel = unquote(rel)
        if not rel.startswith("uploads/") or "\\" in rel or any(part in (".", "..", "") for part in rel.split("/")):
            raise FileNotFoundError()
        parent = root / "wp-content" / "uploads"
        f = parent / rel[len("uploads/"):]
        ctype = {".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".png":"image/png",
                 ".webp":"image/webp", ".gif":"image/gif", ".svg":"image/svg+xml"}.get(f.suffix.lower())
        if not ctype:
            raise FileNotFoundError()
    parent = parent.resolve()
    f = f.resolve()
    if root not in parent.parents or parent not in f.parents or not f.is_file():
        raise FileNotFoundError()
    return f, ctype


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
    for linked_page in pages:
        link_slug = linked_page["slug"]
        body = body.replace('href="/%s/"' % link_slug, 'href="%s/%s"' % (base, link_slug))
    body = body.replace('href="/"', 'href="%s/home"' % base)
    # Preview assets must stay under their authenticated or share-token route.
    body = body.replace('/wp-content/uploads/', asset + '/uploads/')
    body = re.sub(r'\[kf_contact_form\b[^\]]*\]',
                  '<p class="kf-note">Form preview only. Publish the page to test submissions.</p>', body)

    lis = []
    for p in pages:
        href = "%s/%s" % (base, p["slug"])
        cls = ' class="current-menu-item"' if p["slug"] == page["slug"] else ""
        lis.append('<li%s><a href="%s">%s</a></li>'
                   % (cls, href, esc(p.get("title", p["slug"]))))
    nav = "".join(lis)

    label = "客户预览" if public else "预览"
    note = "仅供审阅，尚未上线" if public else "未发布的草稿"
    extra = ""  # Local container ports are not public URLs.
    company = esc(meta.get("company", ""))
    title = "%s · %s · %s" % (label, esc(page.get("title", "")), company)
    preview_design = draft.get("design") or site_design(slug)
    preset = preview_design.get('preset', '')
    body_class = 'wp-theme-kampong'
    reference_css = ''
    if preset == 'reference':
        body_class += ' kf-style-reference'
        reference_css = (BASE / 'theme' / 'kampong' / 'reference.css').read_text()
    if preset in ('nursery', 'robotics', 'wellness'):
        body_class += ' kf-showcase kf-style-' + preset

    return "".join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="robots" content="noindex">',
        "<title>%s</title>" % title,
        '<link rel="stylesheet" href="%s/style.css">' % asset,
        "<style>", design_vars(slug, preview_design), reference_css,
        ".kf-pvbar{position:sticky;top:0;z-index:99;background:#161b22;color:#e6edf3;",
        "font:13px/1.5 -apple-system,Segoe UI,sans-serif;padding:7px 14px;",
        "display:flex;gap:14px;align-items:center;flex-wrap:wrap}",
        ".kf-pvbar b{color:#d29922}.kf-pvbar a{color:#58a6ff;text-decoration:none}",
        '</style></head><body class="%s">' % body_class,
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
            ip = client_ip(handler)
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
<script src="/locale.js"></script><script src="/appearance.js"></script>
<style>
*{box-sizing:border-box}
html,body{min-height:100%%}
body{margin:0;min-height:100vh;min-height:100dvh;display:flex;align-items:center;
 justify-content:center;background:#0d1117;color:#e6edf3;
 font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif;
 padding:20px;box-sizing:border-box}
.box{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:28px;width:100%%;max-width:360px}
h1{font-size:18px;margin:0 0 4px}p.sub{color:#8b949e;font-size:13px;margin:0 0 18px}
label{display:block;font-size:12px;color:#8b949e;margin-bottom:5px}
input{width:100%%;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#e6edf3;
 padding:11px 12px;font-size:16px;margin-bottom:12px}
button{width:100%%;padding:12px;border:0;border-radius:8px;background:#238636;color:#fff;
 font-size:15px;font-weight:650;cursor:pointer}
.err{background:#3d1d1d;color:#f85149;border-radius:8px;padding:9px 12px;font-size:13px;margin-bottom:14px}
</style></head><body><div class="box">
<h1>KampongFlow</h1><p class="sub">员工登录</p>
%s
<form method="post" action="/login">
<input type="hidden" name="next" value="%s">
<label for="loginUser">用户名</label><input id="loginUser" name="user" autocomplete="username" autofocus required>
<label for="loginPassword">密码</label><input id="loginPassword" name="pw" type="password" autocomplete="current-password" required>
<label for="loginCode">验证码或恢复码（已开启两步验证时填写）</label>
<input id="loginCode" name="code" autocomplete="one-time-code" maxlength="32" autocapitalize="none" spellcheck="false" aria-describedby="codeHelp">
<details id="codeHelp" style="font-size:13px;color:#8b949e;margin:0 0 16px"><summary>无法使用验证器？使用恢复码</summary>
<p>输入验证器中的 6 位数字，或粘贴一枚完整恢复码（xxxx-xxxx）。恢复码只能使用一次。</p></details>
<button type="submit">登录</button>
</form></div></body></html>""" % (('<div class="err" role="alert">%s</div>' % err) if err else "", next_url)


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
    result = _read(PRESETS_F, {})
    # Reusable visual directions, separate from model-generated page content.
    for name, primary, dark, accent, bg, ink, muted, heading, radius in [
        ('nursery', '#985039', '#503a2d', '#a47b22', '#fff9ef', '#302d27', '#625b4f', 'rounded', '24px'),
        ('robotics', '#354ac6', '#101d35', '#167565', '#f4f6fc', '#18253a', '#536077', 'sans', '12px'),
        ('wellness', '#356553', '#213e35', '#8b633a', '#f7f6ef', '#263a30', '#586457', 'serif', '16px'),
    ]:
        result.setdefault(name, {'preset': name, 'palette': {'primary': primary, 'primaryDark': dark,
            'accent': accent, 'bg': bg, 'surface': '#ffffff', 'ink': ink, 'muted': muted, 'deep': dark},
            'shape': {'radius': radius, 'button': '999px' if name == 'nursery' else '8px'},
            'type': {'heading': heading}, 'layout': {'pad': '72px'}, 'photos': {'overlay': '0.25'}})
    return result


def site_design(slug):
    d = _read(SITES / slug / "design.json", {})
    return d if isinstance(d, dict) else {}


COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEN_RE = re.compile(r"^\d{1,3}px$")
HEADS = {"sans", "serif", "rounded", "mono"}


def sanitize_design(body):
    if body.get("preset") == "reference":
        return kf_styles.normalize_tokens(body)
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
    try:
        if tokens.get("preset") == "reference":
            # Install only our scoped support files; preserve the site's existing theme.
            install = ("$dir=WP_CONTENT_DIR.'/mu-plugins'; "
                       "if(!is_dir($dir)&&!mkdir($dir,0755,true)){throw new Exception('mkdir failed');} "
                       "foreach(['reference-plugin.php'=>'kf-reference-style.php','reference.css'=>'kf-reference-style.css'] as $src=>$dst){"
                       "if(!copy('/kf-reference/'.$src,$dir.'/'.$dst)){throw new Exception('copy failed');}}")
            support = subprocess.run(
                ["docker", "run", "--rm", "--env-file", str(site / "wp.env"),
                 "--network", f"kf-{slug}_default", "-v", f"{site}/html:/var/www/html",
                 "-v", f"{BASE}/theme/kampong:/kf-reference:ro", "--user", "33:33", WPCLI_IMG,
                 "wp", "eval", install], capture_output=True, text=True, timeout=150)
            if support.returncode != 0:
                return False
        result = subprocess.run(
            ["docker", "run", "--rm", "--env-file", str(site / "wp.env"),
             "--network", f"kf-{slug}_default",
             "-v", f"{site}/html:/var/www/html", "--user", "33:33", WPCLI_IMG,
             "wp", "option", "update", "kf_design", json.dumps(tokens, ensure_ascii=False)],
            capture_output=True, text=True, timeout=150)
        if result.returncode != 0:
            return False
        kf_ai.atomic_json(site / "design.json", tokens)
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
    with _SITE_RESERVATION_LOCK:
        used = set(_SITE_RESERVATIONS.values())
        for d in SITES.iterdir() if SITES.exists() else []:
            if d.is_dir():
                used.add(int(load_meta(d.name).get("port") or 0))
    import socket
    for p in range(18080, 18200):
        if p not in used:
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
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
            cfg = kf_sso.SSOStore(BASE).config()
            if cfg.get("console_url"):
                result = subprocess.run([sys.executable, str(BASE / "tools" / "kf_sso_install.py"),
                    "--base", str(BASE), "--slug", slug, "--console-url", cfg["console_url"],
                    "--site-url", "https://" + domain], capture_output=True, text=True, timeout=240)
                if result.returncode:
                    raise kf_ai.AIError("站点已开通，但统一登录接入失败；请修复后再交付")
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
<meta name="kf-csrf" content="__KF_CSRF__">
<script>
// Every same-origin mutation carries the server-issued session token.
const kfFetch = window.fetch.bind(window);
window.fetch = (input, init={}) => {
  const url = new URL(input instanceof Request ? input.url : String(input), location.href);
  const method = (init.method || input.method || 'GET').toUpperCase();
  if(url.origin === location.origin && !['GET','HEAD','OPTIONS'].includes(method)){
    const headers = new Headers(init.headers || input.headers || {});
    headers.set('X-KF-CSRF', document.querySelector('meta[name="kf-csrf"]').content);
    init = {...init, headers};
  }
  return kfFetch(input, init);
};
document.addEventListener('click', async event => {
  if(!event.target.closest('a[href="/logout"]')) return;
  event.preventDefault();
  const r=await fetch('/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(r.ok) location.href='/login';
});
</script>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KampongFlow 控制台</title>
<script src="/locale.js"></script><script src="/appearance.js"></script>
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
input,select{background:var(--input,#0d1117);border:1px solid var(--line);border-radius:6px;color:var(--fg);
padding:8px 10px;font-size:14px;width:100%}
.field{flex:1;min-width:130px}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:14px;
cursor:pointer;font-weight:500}
button.ghost{background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);padding:5px 10px;font-size:12.5px}
button:disabled{opacity:.5;cursor:default}
.msg{margin-top:12px;font-size:13px}
.msg.bad{color:var(--bad);background:transparent}.msg.ok{color:var(--ok);background:transparent}
.hidden{display:none}
footer{margin-top:26px;color:var(--dim);font-size:12px}
.sec-list{margin-top:14px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.sec-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line);
  background:var(--card);font-size:13px;cursor:pointer}
.sec-row:last-child{border-bottom:none}
.sec-row.on{background:var(--callout,#1c2530);box-shadow:inset 3px 0 0 var(--acc)}
.sec-row .t{font-family:ui-monospace,Menlo,monospace;color:var(--acc);min-width:74px}
.sec-row .s{flex:1;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sec-row button{background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);border-radius:5px;
  padding:2px 7px;font-size:12px;cursor:pointer}
.lead-card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;margin-bottom:9px}
.lead-top{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px}
.lead-top b{color:var(--fg)}
.lead-top .t{color:var(--dim);font-size:11.5px;margin-left:auto}
.lead-msg{margin-top:7px;font-size:13px;color:var(--fg);white-space:pre-wrap;line-height:1.6}
.lead-meta{margin-top:6px;font-size:12px;color:var(--dim);font-family:ui-monospace,Menlo,monospace}
.badge-warn{background:#d2992222;color:#d29922;border-radius:4px;padding:1px 6px;font-size:11px}
.callout{background:var(--callout,#1c2530);border:1px solid var(--line);border-left:3px solid var(--acc);
  border-radius:8px;padding:10px 14px;font-size:12.5px;color:var(--dim);line-height:1.7}
.dom-row{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.dom-row .h{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dom-row .name{font-family:ui-monospace,Menlo,monospace;color:var(--acc);font-size:13px}
.dom-row .hint{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--dim);
  margin-top:6px;word-break:break-all}
.dom-row button{background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);
  border-radius:5px;padding:3px 9px;font-size:12px;cursor:pointer}
.share-row{display:flex;gap:10px;align-items:center;padding:10px 12px;background:var(--card);
  border:1px solid var(--line);border-radius:8px;margin-bottom:8px;font-size:12.5px;flex-wrap:wrap}
.share-row .u{font-family:ui-monospace,Menlo,monospace;color:var(--acc);flex:1;word-break:break-all}
.share-row .dead{color:var(--dim);text-decoration:line-through}
.share-row button{background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);
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
.tile img{width:100%;height:120px;object-fit:cover;display:block;background:var(--input,#0d1117)}
.tile .meta{padding:8px 10px;font-size:11.5px;color:var(--dim);line-height:1.5}
.tile .meta b{display:block;color:var(--fg);font-size:12px;font-weight:500;word-break:break-all}
.tile .ops{display:flex;gap:6px;padding:0 10px 10px}
.tile .ops button{flex:1;background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);
  border-radius:5px;padding:4px 0;font-size:11.5px;cursor:pointer}
.tile .ops button.del{color:#f85149;border-color:#5c2b2b}
.used{display:inline-block;background:#1f6feb22;color:#58a6ff;border-radius:4px;padding:1px 5px;font-size:10.5px}
.form-area{margin-top:12px}
.fld{margin-bottom:10px}
.fld label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px}
.fld input[type=text],.fld textarea,.fld select{width:100%;background:var(--input,#0d1117);border:1px solid var(--line);
  border-radius:6px;color:var(--fg);padding:8px 10px;font-size:13.5px}
.fld textarea{min-height:64px;resize:vertical}
.fld .row2{display:flex;gap:8px}
.fld .row2 input{flex:1}
.fld .sub{display:flex;gap:6px;margin-bottom:6px;align-items:flex-start}
.fld .sub .grow{flex:1;display:flex;flex-direction:column;gap:6px}
.fld .sub button{background:var(--surface,#21262d);border:1px solid var(--line);color:var(--fg);border-radius:5px;
  padding:3px 8px;font-size:12px;cursor:pointer;height:30px}
.fld .add{background:#1f6feb22;border:1px dashed #388bfd;color:var(--acc);border-radius:6px;
  padding:6px 10px;font-size:12.5px;cursor:pointer;width:100%;margin-top:2px}
.fld .imgnote{font-size:11.5px;color:var(--dim);margin-top:5px}
.fld .thumb{width:100%;max-height:110px;object-fit:cover;border-radius:8px;margin-top:6px;border:1px solid var(--line)}
.fld .chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fg)}
.adv{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
.adv summary{cursor:pointer;font-size:12.5px;color:var(--dim)}
.json-edit{width:100%;min-height:160px;background:var(--input,#0d1117);border:1px solid var(--line);border-radius:8px;
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

/* Console navigation and shared interaction tokens. */
.wrap{max-width:1440px;padding:24px 24px 64px}
.console-shell{display:grid;grid-template-columns:216px minmax(0,1fr);gap:28px;align-items:start}
.sidebar{position:sticky;top:20px;max-height:calc(100dvh - 40px);overflow-y:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
#mcpForm fieldset{min-inline-size:0;border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
#aiContextOptions label,#mcpPurposes label{display:inline-block;margin:6px 14px 6px 0}
#providerForm textarea,#providerForm input,#providerForm select{max-width:100%;box-sizing:border-box}#providerForm textarea{width:100%;background:var(--input,#0d1117);color:var(--fg);border:1px solid var(--line);padding:10px}#providerForm fieldset{min-inline-size:0;margin:16px 0;border:1px solid var(--line)}#providerForm label{margin:8px 0}#mcpForm textarea,#workflowDNS{width:100%;max-width:100%;padding:10px;background:var(--input,#0d1117);color:var(--fg);border:1px solid var(--line);border-radius:6px;resize:vertical}
#p-automation pre,#mcpResult pre{max-height:360px;overflow:auto}
#p-automation .field{min-width:min(180px,100%)}
#p-automation summary,#mcpForm summary{padding:10px 0;cursor:pointer}
#p-automation .dom-row{overflow-wrap:anywhere}
.nav-group{border-bottom:1px solid var(--line);padding:6px 0}.nav-group:last-child{border:0}
.nav-group summary{cursor:pointer;padding:12px 8px;font-size:13px;font-weight:650;color:var(--dim)}
.submenu{display:flex;flex-direction:column;gap:4px;padding:2px 0 10px}
.tab{display:block;text-align:left;width:100%;border:0;border-radius:7px;min-height:42px;padding:10px 14px;background:transparent;color:var(--dim);font:inherit;font-size:14px}
.tab:hover{background:var(--surface,#21262d);color:var(--fg)}.tab.on{background:#1c2d42;color:#9acbff;box-shadow:inset 3px 0 var(--acc)}
.workspace{min-width:0}.page-heading{display:flex;justify-content:space-between;gap:12px;margin-bottom:20px;align-items:center}
.breadcrumb{font-size:12px;color:var(--dim);margin-bottom:4px}.page-heading h2{font-size:24px;margin:0}
.nav-toggle{display:none}.skip-link{position:fixed;left:12px;top:-80px;z-index:100;background:var(--card);padding:12px}.skip-link:focus{top:12px}
:where(a,button,input,select,textarea,summary,[tabindex]):focus-visible{outline:2px solid var(--acc);outline-offset:3px}
input[type=checkbox],input[type=radio]{width:18px;height:18px;flex:0 0 18px;padding:0;vertical-align:middle;accent-color:var(--acc)}
label{font-size:13px}input,select,textarea{min-width:0}button{min-height:40px}button.ghost{min-height:36px}
button.danger{color:#ff9c96;border-color:#8b3e39}.hint{font-size:13px;color:var(--dim);line-height:1.65}
.editor-actions{position:sticky;bottom:12px;z-index:5;display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);padding:12px;border-radius:10px;margin-top:16px;box-shadow:0 8px 24px #0005}
.sec-row .section-select{display:flex;align-items:center;gap:10px;min-width:0;flex:1;text-align:left;border:0;background:transparent;min-height:42px}
.sec-row button{min-width:36px;min-height:36px}.sec-row .section-select .s{white-space:normal}
#editorGlobalState{font-size:12px;color:var(--warn)}[hidden]{display:none!important}
@media(max-width:900px){
 .wrap{padding:16px 12px 72px}.console-shell{grid-template-columns:minmax(0,1fr);gap:18px}
 .sidebar{position:static;max-height:none;padding:8px}.nav-toggle{display:block;width:100%;text-align:left;min-height:44px!important;font-size:14px!important}
 .nav-groups:not(.expanded){display:none}.nav-groups.expanded{display:block;padding-top:8px}
 .tab{min-height:44px}.page-heading h2{font-size:21px}
}
@media(max-width:600px){
 .formrow{flex-direction:column;align-items:stretch}.formrow>.field{flex:1 1 auto!important;width:100%;min-width:0}
 input,select,.fld input[type=text],.fld textarea{font-size:16px}.field>button,button.ghost{min-height:44px}
 tbody td[data-label]::before{content:attr(data-label);display:block;color:var(--dim);font-size:12px;margin-top:6px}
 .editor-actions{position:static}.editor-actions button{flex:1;min-height:44px}.sec-row{padding:8px;gap:4px}.sec-row .t{min-width:0}
 .sec-row button{min-width:40px;min-height:44px}.sec-row .section-select{flex-wrap:wrap}
}

.page-help{margin:0 0 16px;color:var(--dim);font-size:13px;max-width:76ch}
.page-help>summary{display:list-item;width:fit-content;min-height:44px;align-content:center;cursor:pointer;color:var(--dim)}
.page-help[open]>summary{color:var(--fg)}
.help-content{border-left:2px solid var(--line);padding:0 0 0 16px;line-height:1.7}
.help-content p{margin:0 0 10px}.help-content .callout{margin:0}
.optional-options{margin:16px 0;border:1px solid var(--line);border-radius:10px}
.optional-options>summary{min-height:48px;padding:12px 16px;box-sizing:border-box;cursor:pointer;font-weight:600}
.optional-content{padding:0 16px 16px}
.page-help>summary:focus-visible,.optional-options>summary:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:4px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{scroll-behavior:auto!important}}
</style></head><body><div class="wrap">
<div class="topbar">
  <div>
    <h1><span class="brand-mark" aria-hidden="true">K</span>KampongFlow</h1>
  </div>
  <div class="who"><span id="whoami">—</span> <a href="/logout">退出</a></div>
</div>
<a class="skip-link" href="#workspace">跳转到主要内容</a>
<div class="console-shell">
<aside class="sidebar" aria-label="控制台导航">
<button type="button" id="navToggle" class="ghost nav-toggle" aria-expanded="false" aria-controls="navGroups">导航菜单 · 站点总览</button>
<nav id="navGroups" class="nav-groups" aria-label="主导航与二级菜单">
<details class="nav-group" data-group="0" open><summary><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/></svg>站点运营</summary><div class="submenu"><button type="button" class="tab" data-t="automation" aria-controls="p-automation">运营助手</button><button type="button" class="tab on" data-t="sites" aria-controls="p-sites">站点总览</button><button type="button" class="tab" data-t="domain" aria-controls="p-domain">域名管理</button><button type="button" class="tab" data-t="dns" aria-controls="p-dns">DNS 解析</button><button type="button" class="tab" data-t="maint" aria-controls="p-maint">运行维护</button></div></details>
<details class="nav-group" data-group="1"><summary><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16-1 5 5-1L21 7l-6-6L4 16ZM13 3l6 6"/></svg>内容建站</summary><div class="submenu"><button type="button" class="tab" data-t="ai" aria-controls="p-ai">AI 建站</button><button type="button" class="tab" data-t="styles" aria-controls="p-styles">风格模板</button><button type="button" class="tab" data-t="prompts" aria-controls="p-prompts">提示词库</button><button type="button" class="tab" data-t="layout" aria-controls="p-layout">页面编辑</button><button type="button" class="tab" data-t="design" aria-controls="p-design">视觉设计</button><button type="button" class="tab" data-t="media" aria-controls="p-media">媒体素材</button><button type="button" class="tab" data-t="share" aria-controls="p-share">预览分享</button></div></details>
<details class="nav-group" data-group="2"><summary><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2"/></svg>客户与财务</summary><div class="submenu"><button type="button" class="tab" data-t="client" aria-controls="p-client">客户管理</button><button type="button" class="tab" data-t="leads" aria-controls="p-leads">咨询线索</button><button type="button" class="tab" data-t="billing" aria-controls="p-billing">账单收款</button><button type="button" class="tab" data-t="plans" aria-controls="p-plans">套餐设置</button></div></details>
<details class="nav-group" data-group="3"><summary><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="m9 3 6 0 1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z"/></svg>系统设置</summary><div class="submenu"><button type="button" class="tab" data-t="llm" aria-controls="p-llm">设置 LLM</button><button type="button" class="tab" data-t="providers" aria-controls="p-providers">供应商账号</button><button type="button" class="tab" data-t="mcp" aria-controls="p-mcp">MCP 管理</button><button type="button" class="tab" data-t="team" aria-controls="p-team">团队与安全</button></div></details></nav></aside>
<main id="workspace" class="workspace" tabindex="-1">
<div class="page-heading"><div><div class="breadcrumb" id="breadcrumb">站点运营 / 站点总览</div><h2 id="pageTitle" tabindex="-1">站点总览</h2></div><span id="editorGlobalState" role="status"></span><button id="newSite" type="button" onclick="openSiteCreate()">新建站点</button></div>
<div id="globalMsg" class="msg hidden" role="alert" tabindex="-1"></div>

<div id="p-sites">
<div class="stats" id="stats"></div>
<div class="site-toolbar">
<div class="search-field"><label for="siteSearch">搜索站点</label><input type="search" id="siteSearch" placeholder="站点、客户或域名" oninput="renderSites()"></div>
<div class="status-field"><label for="siteStatus">运行状态</label><select id="siteStatus" onchange="renderSites()"><option value="">全部状态</option><option value="active">运行中</option><option value="provisioning">开通中</option><option value="failed">失败</option><option value="stopped">已停止</option></select></div>
<label class="mine-filter"><input type="checkbox" id="onlyMine" onchange="renderSites()">只看我负责的</label>
</div>
<table><thead><tr><th>站点</th><th>客户 / 域名</th><th class="sm-hide">负责人</th><th class="sm-hide">套餐</th><th>状态</th><th class="sm-hide">账单</th><th>到期</th><th>操作</th></tr></thead>
<tbody id="rows"><tr><td colspan="8" style="color:var(--dim)">加载中…</td></tr></tbody></table>
<details id="siteCreate" class="site-create"><summary>新建站点</summary><form id="f"><div class="formrow">
<div class="field"><label>客户名称</label><input name="company" placeholder="Tanjong Pte Ltd" required></div>
<div class="field"><label>域名</label><input name="domain" placeholder="example.sg" required></div>
<div class="field"><label>站点标识（自动建议，可修改）</label><input name="slug" placeholder="例如 tanjong" pattern="[a-z][a-z0-9-]{1,19}" title="2–20 位小写字母、数字或连字符，以字母开头" required></div>
<div class="field"><label>套餐</label><select name="plan_id" id="planSel"></select></div>
<div class="field"><label>行业模板</label><select name="industry" id="indSel"></select></div>
<button id="btn">下单并开通</button>
</div><div class="msg" id="msg"></div></form></details>
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



<div id="p-ai" class="hidden">
<details class="page-help"><summary>建站说明</summary><div class="help-content"><p class="hint">描述企业、服务与风格，自动生成整站页面草稿。预览、调整后发布到网站。</p><p class="hint">模板影响内容结构与语气；配色、字体仍由视觉模板负责。模拟模式用于流程验证，不代表真实模型效果。</p><p class="hint">读取公开页面与样式，提取颜色、字体和布局线索。不复制原站品牌或图片；动态页面可能无法完整分析。</p><p class="hint">风格随生成内容一起保存到草稿，预览确认后发布；模板更新不会改变已经生成的网站。</p></div></details>
<div class="callout" id="aiModeNotice">GPT 模拟模式无需密钥；真实模型请由管理员配置。</div>
<form id="aiBuildForm">
<div class="formrow">
<div class="field"><label for="aiMode">建站方式</label><select id="aiMode"><option value="existing">为已有站点生成</option><option value="new">新建站点并生成</option></select></div>
<div class="field" id="aiExistingWrap"><label for="aiSite">选择站点</label><select id="aiSite"></select></div>
<div class="field"><label for="aiProfile">模型配置</label><select id="aiProfile"></select></div>
<div class="field"><label for="aiLanguage">页面语言</label><select id="aiLanguage"><option value="zh">中文</option><option value="en">English</option></select></div>
</div>
<div id="aiNewFields" class="hidden"><div class="formrow">
<div class="field"><label for="aiCompany">企业名称</label><input id="aiCompany" maxlength="60" placeholder="例如：海湾设计工作室"></div>
<div class="field"><label for="aiDomain">域名</label><input id="aiDomain" maxlength="80" placeholder="example.com"></div>
<div class="field"><label for="aiSlug">站点标识</label><input id="aiSlug" maxlength="20" pattern="[a-z][a-z0-9-]{1,19}" placeholder="bay-studio"></div>
<div class="field"><label for="aiPlan">套餐</label><select id="aiPlan"></select></div>
<div class="field"><label for="aiIndustry">基础行业（未选择风格模板时使用）</label><select id="aiIndustry"></select></div>
</div><p class="hint">新站会创建 WordPress、数据库和套餐账单，内容先保存为草稿。</p></div>
<div class="formrow"><div class="field"><label for="aiStyleTemplate">本次生成使用的风格</label><select id="aiStyleTemplate"><option value="">保持站点当前风格</option></select></div><button type="button" class="ghost" id="aiStyleManage">管理风格模板</button></div>
<div class="fld" style="margin-top:16px"><label for="aiBrief">建站要求 / 额外补充</label><textarea id="aiBrief" required maxlength="6000" rows="6" placeholder="介绍主营业务、目标客户和希望访客完成的操作。"></textarea></div>
<fieldset class="prompt-composer" style="margin-top:20px;border:1px solid var(--line);border-radius:10px;padding:16px">
<legend>提示词方案</legend>
<div class="formrow"><div class="field"><label for="aiPromptCategory">场景分类</label><select id="aiPromptCategory"><option value="">全部场景</option></select></div><div class="field"><label for="aiPromptTemplate">选择模板</label><select id="aiPromptTemplate"><option value="">自由输入（不使用模板）</option></select></div></div>
<p id="aiPromptDescription" class="hint">选择场景模板后，填写真实业务资料并调整模块组合。</p>
<div id="aiPromptFields" class="hidden"><div class="formrow">
<div class="field"><label for="promptAudience">目标客户</label><input id="promptAudience" maxlength="1500"></div><div class="field"><label for="promptGoal">主要转化目标</label><input id="promptGoal" maxlength="1500"></div></div>
<div class="fld"><label for="promptServices">主营服务 / 产品（必填）</label><textarea id="promptServices" rows="3" maxlength="1500" placeholder="填写真实提供的服务或产品"></textarea></div>
<div class="field"><label for="promptTone">品牌语气</label><input id="promptTone" maxlength="1500"></div>
<div class="fld"><label for="promptFacts">已核实资料与联系方式（选填）</label><textarea id="promptFacts" rows="3" maxlength="1500" placeholder="仅填写可公开且已核实的案例、地址、时间、价格或联系方式"></textarea></div>
<details><summary>调整模块与顺序</summary><div id="aiPromptModules"></div></details>
<button type="button" class="ghost" id="aiPromptPreviewBtn" style="margin-top:12px">预览组合后的提示词</button>
<details id="aiPromptPreviewBox"><summary>最终提示词预览</summary><textarea id="aiPromptPreview" class="json-edit" readonly aria-label="组合后的提示词"></textarea></details>
<div id="aiPromptMsg" class="msg" role="status"></div></div>

</fieldset>
<details id="aiReferenceOptions" class="optional-options"><summary>参考网站与风格模板</summary><div class="optional-content">
<div class="formrow"><div class="field"><label for="aiReferenceUrl">参考网站地址</label><input id="aiReferenceUrl" type="url" maxlength="2000" placeholder="https://example.com"></div><button type="button" id="aiAnalyzeStyle">分析参考风格</button></div>


<div id="aiStyleResult" class="hidden"><p id="aiStyleSummary"></p><div id="aiStyleSwatches" style="display:flex;gap:8px;flex-wrap:wrap"></div><p id="aiStyleWarnings" class="hint"></p><details><summary>分析依据</summary><pre id="aiStyleEvidence" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details><button type="button" class="ghost" id="aiStyleSaveAnalysis">编辑并保存为模板</button></div>

<div id="aiStyleMsg" class="msg" role="status" aria-live="polite"></div>
</div></details>
<details id="aiContextOptions" class="optional-options"><summary>建站参考资料（已有站点，可选）</summary><div class="optional-content"><label><input type="checkbox" value="client">客户资料</label><label><input type="checkbox" value="brand">品牌与风格</label><label><input type="checkbox" value="pages">现有页面</label><label><input type="checkbox" value="media">素材目录</label><p class="hint">所选资料会发送至当前模型服务商，请先确认可用于建站。</p><label><input id="aiAutoResearch" type="checkbox">允许 AI 自动查询已授权的 MCP 只读资料（最多 4 次）</label><div id="aiContextList"></div><button type="button" class="ghost" id="aiChooseContext">从运营助手选择 MCP 资料</button></div></details>

<label id="aiReplaceWrap" class="hint" style="display:block;margin:12px 0"><input id="aiReplace" type="checkbox"> 允许替换未发布草稿（原草稿会备份）</label>
<button id="aiGenerate" type="submit">生成整站草稿</button><span id="aiBuildMsg" class="msg" role="status" aria-live="polite"></span>
</form>
<h3 style="margin-top:28px">建站任务</h3>
<div id="aiJobs" aria-live="polite"></div>

</div>

<div id="p-styles" class="hidden"><section id="styleManager">
<div class="formrow"><div class="field"><label for="styleSearch">搜索模板名称或分类</label><input id="styleSearch" type="search"></div><div class="field"><label for="styleStatus">模板状态</label><select id="styleStatus"><option value="">全部状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select></div><button type="button" id="styleNew">新建模板</button><button type="button" class="ghost" id="styleImport">导入模板</button><input id="styleImportFile" type="file" accept="application/json,.json" hidden><button type="button" class="ghost" id="styleRefresh">刷新模板</button></div>
<div id="styleLibrary" class="style-library"></div><section id="stylePreviewPanel" class="hidden"><div class="formrow"><h3>模板预览</h3><label for="stylePreviewWidth">预览宽度</label><select id="stylePreviewWidth"><option value="100%">桌面</option><option value="375px">手机</option></select><button type="button" class="ghost" id="stylePreviewClose">关闭预览</button></div><p class="hint">本地示例内容，用于检查布局与配色，不代表已生成的网站。</p><iframe id="stylePreviewFrame" title="风格模板预览" sandbox="" referrerpolicy="no-referrer"></iframe></section>
<form id="styleEditForm" class="hidden" style="margin-top:16px">
<h3>编辑风格模板</h3>
<div class="formrow"><div class="field"><label for="styleName">模板名称</label><input id="styleName" required maxlength="80"></div><div class="field"><label for="styleCategory">分类</label><input id="styleCategory" maxlength="40" placeholder="例如：教育、科技、医疗"></div></div>
<div class="formrow"><div class="field"><label for="styleIndustry">基础行业</label><select id="styleIndustry"></select></div><div class="field"><label for="styleTags">标签（逗号分隔）</label><input id="styleTags" maxlength="400"></div></div><div class="fld"><label for="styleSource">参考来源</label><input id="styleSource" type="url" maxlength="2000"></div>
<div class="fld"><label for="styleSummary">风格说明</label><textarea id="styleSummary" maxlength="1500" rows="2"></textarea></div>
<div class="fld"><label for="styleGuidance">内容生成指导</label><textarea id="styleGuidance" maxlength="2400" rows="3"></textarea></div>
<div id="styleColors" class="formrow"></div>
<div class="formrow"><div class="field"><label for="styleHeading">标题字体</label><select id="styleHeading"><option value="sans">无衬线</option><option value="serif">衬线</option><option value="rounded">圆润</option><option value="mono">等宽</option></select></div><div class="field"><label for="styleRadius">卡片圆角（px）</label><input id="styleRadius" type="number" min="0" max="999" required></div><div class="field"><label for="stylePad">区块间距（px）</label><input id="stylePad" type="number" min="24" max="120" required></div></div>
<details class="optional-options"><summary>高级视觉参数</summary><div class="optional-content"><div id="styleAdvanced" class="formrow"></div><div class="formrow"><div class="field"><label for="styleButtonRadius">按钮圆角（px）</label><input id="styleButtonRadius" type="number" min="0" max="999"></div><div class="field"><label for="styleOverlay">图片遮罩（0–1）</label><input id="styleOverlay" type="number" min="0" max="1" step="0.01"></div></div></div></details>
<details class="optional-options"><summary>页面结构与特殊要求</summary><div class="optional-content"><p class="hint">调整首页区块的顺序；结构与生成指导会随模板版本保存并发送给建站模型。</p><div class="formrow"><div class="field"><label for="styleBlockType">区块类型</label><select id="styleBlockType"></select></div><button type="button" class="ghost" id="styleAddBlock">添加区块</button></div><div id="styleBlueprint"></div></div></details>
<details class="optional-options"><summary>高级 JSON 编辑</summary><div class="optional-content"><p class="hint">可编辑完整模板参数；应用前会校验格式、范围和文字对比度。</p><textarea id="styleJSON" class="json-edit" aria-label="模板 JSON"></textarea><button type="button" class="ghost" id="styleApplyJSON">应用 JSON</button><button type="button" class="ghost" id="styleSyncJSON">从表单更新 JSON</button></div></details>
<button type="button" class="ghost" id="stylePreviewEdit">预览当前修改</button>
<label><input id="styleEnabled" type="checkbox" checked>启用此模板</label>
<button type="submit">保存风格模板</button><button type="button" class="ghost" id="styleCancel">取消</button>
</form><div id="styleManageMsg" class="msg" role="status"></div></section></div>

<div id="p-llm" class="hidden"><details open id="aiSettings" style="margin-top:28px"><summary style="cursor:pointer">服务商与模型配置（管理员）</summary>
<details class="page-help"><summary>模型配置说明</summary><div class="help-content"><p class="hint">可保存多套模型。API 地址支持服务商 Base URL 或完整接口地址；模型 ID 按服务商提供的名称填写。密钥仅保存在服务器。</p></div></details>
<div id="aiProfilesList"></div>
<form id="aiConfigForm" style="margin-top:16px">
<div class="formrow">
<div class="field"><label for="aiPreset">快速填写</label><select id="aiPreset"><option value="">自定义配置</option></select></div>
<div class="field"><label for="aiConfigId">配置 ID</label><input id="aiConfigId" required maxlength="40" pattern="[a-z0-9][a-z0-9_-]{0,39}" placeholder="my-provider"></div>
<div class="field"><label for="aiConfigName">显示名称</label><input id="aiConfigName" required maxlength="80" placeholder="我的建站模型"></div>
<div class="field"><label for="aiProtocol">接口协议</label><select id="aiProtocol"><option value="openai_chat">OpenAI 兼容 Chat Completions</option><option value="openai_responses">OpenAI Responses</option><option value="anthropic">Anthropic Messages</option><option value="gemini">Gemini GenerateContent</option></select></div>
</div>
<div class="formrow">
<div class="field" style="flex:2"><label for="aiBaseUrl">API Base URL / 完整接口地址</label><input id="aiBaseUrl" type="url" required maxlength="500" placeholder="https://api.example.com/v1"></div>
<div class="field"><label for="aiModel">模型 ID</label><input id="aiModel" required maxlength="150" placeholder="填写服务商提供的模型 ID"></div>
<div class="field"><label for="aiKey">API Key（留空保留原密钥）</label><input id="aiKey" type="password" autocomplete="new-password" maxlength="4096" placeholder="本地服务可留空"></div>
</div>
<div class="formrow">
<div class="field"><label for="aiTimeout">请求超时（秒）</label><input id="aiTimeout" type="number" min="5" max="300" value="120" required></div>
<div class="field"><label for="aiMaxTokens">最大输出 Token</label><input id="aiMaxTokens" type="number" min="256" max="32768" value="8192" required></div>
<div class="field"><label for="aiTokenParameter">Chat 接口输出长度参数</label><select id="aiTokenParameter"><option value="max_tokens">max_tokens（常见兼容接口）</option><option value="max_completion_tokens">max_completion_tokens</option><option value="none">不发送（使用服务商默认值）</option></select></div>
</div>
<label class="hint"><input id="aiJsonMode" type="checkbox"> 启用 JSON 输出模式（仅在服务商支持时勾选）</label>
<label class="hint" style="margin-left:16px"><input id="aiClearKey" type="checkbox"> 清除已保存密钥</label>
<div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button type="submit">保存配置</button><button type="button" class="ghost" id="aiResetConfig">新建配置</button><span id="aiConfigMsg" class="msg" role="status"></span></div>
</form></details></div>
<div id="p-automation" class="hidden">
<details class="page-help"><summary>操作流程说明</summary><div class="help-content"><p class="hint">查询资料与健康状态、生成草稿，或先预览再确认发布、DNS 修改和邮件发送。执行记录用于核对结果与恢复流程。</p></div></details>
<div class="formrow"><div class="field"><label for="autoSite">站点</label><select id="autoSite"></select></div><div class="field"><label for="autoPurpose">功能</label><select id="autoPurpose"><option value="build">AI 建站</option><option value="dns">DNS</option><option value="mail">邮件</option><option value="maintenance">运营巡检</option></select></div><button id="autoRefresh" type="button" class="ghost">刷新记录</button></div>
<form id="autoForm"><div class="formrow"><div class="field"><label for="autoSource">工具来源</label><select id="autoSource"><option value="builtin">MVP 内置业务</option></select></div><div class="field"><label for="autoTool">操作</label><select id="autoTool"></select></div></div>
<div id="autoFields"></div><button type="submit" id="autoPrepare">生成操作预览</button><div id="autoMsg" class="msg" role="status"></div></form>
<section id="autoReview" class="hidden" style="margin-top:20px" aria-live="polite"></section>
<details id="autoDNSConfig" style="margin-top:24px"><summary>DNS 执行服务商（管理员）</summary><p class="hint">仅为当前站点配置。Cloudflare 请使用仅授权对应 Zone 的 DNS API Token。其他服务商请先在系统设置保存账号；AWS 填 Hosted Zone ID，Google 填 Managed Zone 名称，Azure / 阿里云 / 腾讯云填区域域名。保存配置不会修改解析。</p>
<form id="autoDNSForm"><div class="formrow"><div class="field"><label for="autoDNSProvider">服务商</label><select id="autoDNSProvider"><option value="disabled">未启用</option><option value="local">本机权威 DNS</option><option value="cloudflare">Cloudflare</option><option value="aws">AWS Route 53</option><option value="azure">Azure DNS</option><option value="gcp">Google Cloud DNS</option><option value="aliyun">阿里云 DNS</option><option value="tencent">腾讯云 DNSPod</option><option value="namecom">Name.com</option><option value="webnic">WebNIC</option><option value="cpanel">通用 cPanel</option></select></div><div class="field"><label for="autoDNSAccount">供应商账号</label><select id="autoDNSAccount"><option value="">使用下方 Cloudflare Token / 本机</option></select></div><div class="field"><label for="autoDNSZone">DNS 区域（Zone ID / Managed Zone 名称 / 区域域名）</label><input id="autoDNSZone" maxlength="253"></div><div class="field"><label for="autoDNSToken">API Token（留空保留）</label><input id="autoDNSToken" type="password" autocomplete="new-password"></div></div><label><input id="autoDNSClear" type="checkbox">清除凭据</label><button type="submit">保存 DNS 执行配置</button><div id="autoDNSMsg" class="msg" role="status"></div></form></details>
<details style="margin-top:24px"><summary>创建网站交付流程</summary><p class="hint">为当前站点生成草稿，预览确认后发布，再执行所选 DNS 变更、检查 HTTPS，最后预览确认交付邮件。已完成步骤不会重复执行。</p>
<form id="workflowForm"><div class="fld"><label for="workflowBrief">建站要求</label><textarea id="workflowBrief" rows="4" maxlength="6000" required></textarea></div><div class="formrow"><div class="field"><label for="workflowProfile">模型配置 ID（留空使用默认）</label><input id="workflowProfile"></div><div class="field"><label for="workflowRecipient">交付邮件收件人（留空跳过发送）</label><input id="workflowRecipient" type="email"></div></div><label><input id="workflowInherit" type="checkbox">沿用 AI 建站页当前选择的提示词、风格和参考资料（须为同一站点）</label><label><input id="workflowReplace" type="checkbox">允许替换当前未发布草稿（旧草稿会备份）</label>
<details><summary>可选 DNS 变更</summary><label for="workflowDNS">变更数组（JSON，最多 5 条）</label><textarea id="workflowDNS" rows="4" spellcheck="false">[]</textarea><p class="hint">每条包含 operation（add/update/delete）、record_id（修改/删除）和 record（新增/修改）。留空数组保持现有解析。每项变更会在执行前单独预览确认。</p></details>
<button type="submit">创建交付流程</button><div id="workflowMsg" class="msg" role="status"></div></form></details>
<h3>交付流程</h3><div id="autoWorkflows"></div>
<details id="autoMailConfig"><summary>本站点邮件发送账号（管理员）</summary><form id="autoMailForm"><label for="autoMailAccount">邮件供应商账号</label><select id="autoMailAccount"></select><p class="hint">未绑定时使用系统默认发送配置。绑定后影响运营助手与交付流程的邮件；保存不会发送邮件。</p><button type="submit">保存邮件账号绑定</button><div id="autoMailMsg" class="msg" role="status"></div></form></details><h3>操作记录</h3><div id="autoActions"></div>
</div>
<div id="p-providers" class="hidden">
<details class="page-help"><summary>账号与权限说明</summary><div class="help-content"><p class="hint">统一管理云平台、DNS 和邮件账号。凭据加密保存且不回显；为每个账号选择站点与能力，再在运营助手绑定使用。云资源清单覆盖账号授权范围，IAM / RAM / RBAC 应同时限制实际资源。</p></div></details>
<div class="formrow"><div class="field"><label for="providerSearch">搜索供应商账号</label><input id="providerSearch" type="search"></div><button id="providerNew" type="button">添加供应商账号</button><button id="providerRefresh" type="button" class="ghost">刷新</button></div>
<div id="providerList"></div><div id="providerMsg" class="msg" role="status"></div>
<form id="providerForm" class="hidden"><h3>供应商账号配置</h3><div class="formrow"><div class="field"><label for="providerId">账号 ID</label><input id="providerId" required pattern="[a-z][a-z0-9_-]{1,39}"></div><div class="field"><label for="providerName">账号名称</label><input id="providerName" required></div><div class="field"><label for="providerKind">供应商</label><select id="providerKind"></select></div></div>
<div id="providerFields" class="formrow"></div><fieldset><legend>允许使用的能力</legend><div id="providerCaps"></div></fieldset><label for="providerSites">允许使用的站点（可多选）</label><select id="providerSites" multiple size="4" style="width:100%"></select><label><input id="providerEnabled" type="checkbox" checked>启用账号</label><div><button type="submit">保存供应商账号</button><button type="button" class="ghost" id="providerCancel">取消</button></div><div id="providerFormMsg" class="msg" role="status"></div></form>
<details><summary>供应商能力对照</summary><div id="providerMatrix" style="overflow:auto"></div><p class="hint">通用 SMTP 可连接支持密码或应用密码认证的企业邮箱；OAuth-only SMTP 尚未支持。AWS role 使用服务器 SDK 凭据链，keys 使用所填凭据。复杂 DNS 路由、云主机创建/销毁、CDN 配置和数据库迁移不在本页直接执行范围内。</p></details></div>
<div id="p-mcp" class="hidden">
<details class="page-help"><summary>连接与权限说明</summary><div class="help-content"><p class="hint">管理远程 MCP 服务，测试连接并查看工具、资源及提示词。配置用途、站点范围与白名单后，可在运营助手调用，并将只读结果用于 AI 建站。</p><p class="hint">支持公开 HTTPS（443 端口）的 Streamable HTTP，协议 2025-06-18 / 2025-03-26；认证支持无认证、Bearer Token 或已保存的 AWS / Cloudflare 账号。暂不支持本地 stdio、旧 SSE 端点或 OAuth 登录。</p></div></details>

<div class="formrow"><div class="field"><label for="mcpPreset">官方 MCP 预设</label><select id="mcpPreset"><option value="">请选择</option><option value="cloudflare-docs">Cloudflare 文档</option><option value="cloudflare-api">Cloudflare API</option><option value="aws-knowledge">AWS Knowledge</option><option value="aws-api">AWS MCP（新加坡）</option><option value="custom">其他标准 HTTPS MCP</option></select></div><button id="mcpUsePreset" type="button" class="ghost">使用预设</button></div><div class="formrow"><div class="field"><label for="mcpSearch">搜索 MCP 名称、地址或说明</label><input id="mcpSearch" type="search"></div><button id="mcpRefresh" type="button" class="ghost">刷新</button><button id="mcpNew" type="button">添加 MCP 服务</button></div>
<div id="mcpList" style="margin-top:16px"></div><div id="mcpMsg" class="msg" role="status"></div>
<form id="mcpForm" class="hidden"><h3 id="mcpFormTitle">MCP 服务配置</h3>
<div class="formrow"><div class="field"><label for="mcpId">配置 ID</label><input id="mcpId" required pattern="[a-z][a-z0-9_-]{1,39}" maxlength="40"></div><div class="field"><label for="mcpName">服务名称</label><input id="mcpName" required maxlength="80"></div></div>
<div class="fld"><label for="mcpUrl">MCP 服务地址</label><input id="mcpUrl" type="url" required maxlength="2000" placeholder="https://example.com/mcp"></div>
<div class="fld"><label for="mcpAccount">供应商账号认证（可选）</label><select id="mcpAccount"><option value="">使用下方 Bearer Token / 无认证</option></select></div><div class="fld"><label for="mcpToken">Bearer Token（留空保留原凭据）</label><input id="mcpToken" type="password" maxlength="4096" autocomplete="new-password"></div>
<label><input id="mcpClear" type="checkbox">清除已保存凭据</label>
<div class="fld"><label for="mcpDescription">服务说明</label><textarea id="mcpDescription" rows="3" maxlength="1000"></textarea></div>
<label><input id="mcpEnabled" type="checkbox" checked>启用此服务</label>
<fieldset><legend>允许使用范围</legend><div id="mcpPurposes"><label><input type="checkbox" value="build">AI 建站</label><label><input type="checkbox" value="dns">DNS</label><label><input type="checkbox" value="mail">邮件</label><label><input type="checkbox" value="maintenance">运营巡检</label></div>
<label for="mcpSites">允许访问的站点（可多选）</label><select id="mcpSites" multiple size="4" style="width:100%"></select>
<p class="hint">未选择用途和站点时仅可测试连接。工具权限由管理员配置，外部服务的描述不会自动授予执行权限。</p>
<div class="formrow"><div class="field"><label for="mcpLimit">每小时调用上限</label><input id="mcpLimit" type="number" min="1" max="120" value="30"></div><div class="field"><label for="mcpTimeout">调用超时（秒）</label><input id="mcpTimeout" type="number" min="5" max="45" value="30"></div></div>
<details><summary>工具与资料白名单</summary><p class="hint">工具规则包含 name、mode 和 bindings。mode 为 read（自动只读）、confirm（确认执行）或 totp（确认并验证）。bindings 可将 domain 绑定为 $domain、站点参数绑定为 $site。仅将已确认无副作用的工具设为 read。</p>
<label for="mcpToolRules">工具规则（JSON 数组）</label><textarea id="mcpToolRules" rows="6" spellcheck="false" placeholder='[{"name":"search","mode":"read","bindings":{"domain":"$domain"}}]'></textarea>
<label for="mcpResources">允许读取的资源 URI（每行一项）</label><textarea id="mcpResources" rows="3"></textarea>
<label for="mcpPrompts">允许获取的提示词名称（每行一项）</label><textarea id="mcpPrompts" rows="3"></textarea></details></fieldset>
<div><button type="submit">保存 MCP 服务</button><button type="button" class="ghost" id="mcpCancel">取消</button></div><div id="mcpFormMsg" class="msg" role="status"></div></form>
<section id="mcpResult" class="hidden" style="margin-top:20px" aria-live="polite"></section>
</div>
<div id="p-prompts" class="hidden">
<details class="page-help"><summary>提示词使用说明</summary><div class="help-content"><p class="hint">模板定义场景，模块组织目标、结构、风格、文案与检查标准。运营可选择使用；管理员可编辑、复制、停用并恢复历史版本。</p></div></details>
<div class="formrow"><div class="field"><label for="promptLibraryKind">查看</label><select id="promptLibraryKind"><option value="templates">场景模板</option><option value="modules">可复用模块</option></select></div><div class="field"><label for="promptLibrarySearch">搜索名称、分类或用途</label><input id="promptLibrarySearch" type="search"></div><button class="ghost" id="promptLibraryRefresh">刷新</button><button class="ghost" id="promptLibraryExport">导出提示词库</button><button id="promptLibraryNew">新建</button></div>
<div id="promptLibraryList" style="margin-top:16px"></div><div id="promptLibraryMsg" class="msg" role="status"></div>
<form id="promptEditForm" class="hidden">
<h3 id="promptEditTitle">编辑条目</h3>
<div class="formrow"><div class="field"><label for="promptEditId">ID</label><input id="promptEditId" required pattern="[a-z][a-z0-9_-]{1,39}" maxlength="40"></div><div class="field"><label for="promptEditName">名称</label><input id="promptEditName" required maxlength="80"></div><div class="field"><label for="promptEditCategory">分类</label><input id="promptEditCategory" required maxlength="40" list="promptCategories"><datalist id="promptCategories"></datalist></div></div>
<div class="fld"><label for="promptEditDescription">用途说明</label><input id="promptEditDescription" maxlength="300"></div>
<div class="fld"><label for="promptEditBody">提示词内容</label><textarea id="promptEditBody" rows="6" required maxlength="2400"></textarea><p class="hint">可用变量：{{audience}}、{{services}}、{{goal}}、{{tone}}、{{facts}}。不在提示词中保存密钥或私人资料。</p></div>
<div id="promptEditTemplateFields"><label>默认模块（按下列顺序组合）</label><div id="promptEditModules"></div><div class="fld"><label for="promptEditDefaults">默认业务变量（JSON，可留空）</label><textarea id="promptEditDefaults" rows="3" placeholder='{"audience":"企业客户","goal":"提交咨询","tone":"专业清晰"}'></textarea></div></div>
<label><input type="checkbox" id="promptEditEnabled" checked> 启用</label>
<button type="submit">保存新版本</button><button type="button" class="ghost" id="promptEditCancel">取消编辑</button><span id="promptEditMsg" class="msg" role="status"></span>
<div id="promptEditHistory" style="margin-top:12px"></div></form>
<details style="margin-top:24px"><summary>设计依据与使用边界</summary><div id="promptSources"></div><p class="hint">这些模板是根据公开实践整理的起点，并非经过模型效果排名的“最佳提示词”。请用真实业务资料生成草稿，核对事实和页面后再发布。模板只生成当前平台支持的内容，不实现支付、库存或预约系统。</p></details>
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
<div class="editor-actions" aria-label="保存与发布">
<button class="ghost" id="lSave">保存全部改动</button>
<button class="ghost" id="lPreview">保存并预览</button>
<button class="ghost" id="lDiff">查看改动</button>
<button id="lPublish">发布本页</button>
<button class="ghost" id="lPublishAll">全部发布</button>
<span id="lDirty" class="pill"></span>
<span id="lMsg" class="msg" role="status" aria-live="polite"></span>
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
<p class="hint">密码查看需 TOTP 验证。</p>
<div class="formrow"><div class="field"><label for="domainSearch">搜索域名、机构、用户名或配置</label><input id="domainSearch" type="search"></div><button id="domainRefresh" type="button" class="ghost">刷新</button></div>
<div id="dList" style="margin-top:14px"></div>
<div class="msg" id="dMsg" role="status"></div>
<form id="domainAccountForm" class="hidden" style="margin-top:20px">
<h3 id="domainAccountTitle">管理机构账号</h3>
<div class="formrow"><div class="field"><label for="domainAccountSite">所属域名</label><select id="domainAccountSite" required></select></div><div class="field"><label for="domainAccountCategory">机构类型</label><select id="domainAccountCategory"><option value="registrar">域名注册商</option><option value="dns">DNS 服务商</option><option value="hosting">托管服务商</option><option value="other">其他机构</option></select></div></div>
<div class="formrow"><div class="field"><label for="domainAccountProvider">管理机构名称</label><input id="domainAccountProvider" required maxlength="120" placeholder="例如 Cloudflare"></div><div class="field"><label for="domainAccountUrl">管理后台地址</label><input id="domainAccountUrl" type="url" maxlength="2000" placeholder="https://dash.cloudflare.com/"></div></div>
<div class="formrow"><div class="field"><label for="domainAccountUsername">用户名 / 登录邮箱</label><input id="domainAccountUsername" maxlength="300" autocomplete="off"></div><div class="field"><label for="domainAccountPassword">设置新密码（留空保留已保存密码）</label><input id="domainAccountPassword" type="password" maxlength="4096" autocomplete="new-password"></div></div>
<label><input id="domainAccountClear" type="checkbox">清除已保存的密码</label>
<div class="fld"><label for="domainAccountConfig">配置信息</label><textarea id="domainAccountConfig" rows="6" maxlength="12000" placeholder="记录 DNS 地址、NS 服务器、解析配置、账号归属和操作说明"></textarea><p class="hint">配置信息可直接查询，请勿在此填写密码、API 密钥或恢复码。</p></div>
<button type="submit">保存管理账号</button><button type="button" class="ghost" id="domainAccountCancel">取消</button><span id="domainAccountMsg" class="msg" role="status"></span>
</form>
<dialog id="domainRevealDialog" style="width:min(480px,calc(100vw - 32px));border:1px solid var(--line);border-radius:14px;padding:24px;background:var(--card);color:var(--fg)">
<form id="domainRevealForm"><h3>验证 TOTP 后显示密码</h3><p id="domainRevealLabel"></p>
<label for="domainRevealCode">当前 MVP 账号的 6 位 TOTP 验证码</label><input id="domainRevealCode" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required style="width:100%;margin:10px 0">
<p class="hint">恢复码不能用于显示密码。同一枚验证码只能成功使用一次。</p>
<button type="submit" id="domainRevealSubmit">验证并显示</button><button type="button" class="ghost" id="domainRevealClose">关闭</button>
<div id="domainRevealMsg" class="msg" role="status" aria-live="polite"></div>
<div id="domainSecretWrap" class="hidden" style="margin-top:16px"><label for="domainSecretValue">已保存密码（30 秒后自动隐藏）</label><input id="domainSecretValue" type="text" readonly autocomplete="off" style="width:100%;margin-top:8px"><button type="button" class="ghost" id="domainSecretHide">立即隐藏</button></div>
</form></dialog>
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
<p class="hint">每周一 09:00 自动检查更新。</p><details class="page-help"><summary>更新检查说明</summary><div class="help-content"><div class="callout">镜像更新检查：拉取 wordpress / mariadb / wp-cli 三个镜像，比对运行中容器的 image ID。定时任务每周一 09:00 自动执行。</div></div></details>
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
<div class="callout">仅管理员可管理账号；修改会记录在操作日志中。</div>
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
  <div data-user-content class="preview" id="pv">
    <div class="pv-hero" id="pvHero"><div class="pv-kicker">PRESCHOOL · SINGAPORE</div>
      <div class="pv-h1">Little Gems</div>
      <div class="pv-p">A play-based bilingual preschool.</div>
      <div class="pv-btn" id="pvBtn">Book a Visit</div></div>
    <div class="pv-card" id="pvCard"><b>Character</b><div class="pv-small">Grounded in solid character.</div></div>
  </div>
  <div data-user-content class="preview" style="font-size:12.5px;color:#8b949e">
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
</main></div></div>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money=n=>'S$ '+Number(n||0).toLocaleString('en-SG',{minimumFractionDigits:0});
let STATE={sites:[],invoices:[],plans:[]};
let ROLE='ops';
function applyRole(){
  const hidden = ROLE==='finance'
    ? ['automation','ai','styles','prompts','layout','design','media','share','dns','maint','team','llm','mcp','providers']
    : (ROLE==='admin' ? [] : ['team','llm','mcp','providers']);
  document.querySelectorAll('.tab').forEach(el=>{
    el.style.display = hidden.includes(el.dataset.t) ? 'none' : '';
  });
  const f=$('#f'); if(f) f.style.display = (ROLE==='finance') ? 'none' : '';
  $('#siteCreate').hidden=ROLE==='finance';$('#newSite').hidden=ROLE==='finance'||CURRENT_TAB!=='sites';
  syncNavigation();
}
function badge(s){const m={active:['ok','运行中'],provisioning:['warn','开通中'],failed:['bad','失败'],stopped:['bad','已停止']};
 const [c,t]=m[s]||['warn',s];return `<span class="dot ${c}"></span>${t}`}
let CURRENT_TAB='sites', NAV_READY=false;
function navigateTo(key, updateHistory=true){
 const t=[...document.querySelectorAll('.tab')].find(x=>x.dataset.t===key);
 if(!t || t.style.display==='none') return false;
 if(CURRENT_TAB==='styles'&&key!=='styles'&&typeof styleCanLeave==='function'&&!styleCanLeave())return false;
 if(EDITOR_BUSY){ showGlobalError('正在保存或发布，请稍候再切换页面。'); return false; }
 if(CURRENT_TAB==='layout' && !commitJson())return false;
 $('#globalMsg').classList.add('hidden');
 CURRENT_TAB=key;
 $('#newSite').hidden=ROLE==='finance'||key!=='sites';
 document.querySelectorAll('.tab').forEach(x=>{x.classList.toggle('on',x===t);if(x===t)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});
 document.querySelectorAll('.tab').forEach(x=>$('#p-'+x.dataset.t).classList.toggle('hidden',x!==t));
 t.closest('details').open=true;
 $('#pageTitle').textContent=t.dataset.label||t.textContent;
 $('#breadcrumb').textContent=(t.closest('details').dataset.label||t.closest('details').querySelector('summary').textContent)+' / '+(t.dataset.label||t.textContent);
 $('#navToggle').textContent='导航菜单 · '+(t.dataset.label||t.textContent);
 $('#navGroups').classList.remove('expanded');$('#navToggle').setAttribute('aria-expanded','false');
 if(updateHistory && location.hash!=='#'+key) history.pushState(null,'','#'+key);
 try{sessionStorage.setItem('kf-console-tab',key);}catch(_){}
 const initializers={styles:()=>styleLoad(),providers:()=>loadProviders(),automation:()=>loadAutomation(),llm:()=>aiLoadConfig(),mcp:()=>loadMCP(),ai:()=>initAI(),prompts:()=>initPrompts(),design:()=>initDesign(),layout:()=>{const slug=window.aiEditorTarget;window.aiEditorTarget=null;return initLayout(slug);},media:()=>initMedia(),share:()=>initShare(),domain:()=>initDomain(),leads:()=>initLeads(),maint:()=>initMaint(),client:()=>initClient(),team:()=>initTeam(),dns:()=>initDns()};
 Promise.resolve().then(()=>initializers[key]?.()).catch(e=>showGlobalError(e.message));
 if(updateHistory){$('#pageTitle').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
 return true;
}
function syncNavigation(){
 document.querySelectorAll('.nav-group').forEach(g=>g.hidden=![...g.querySelectorAll('.tab')].some(t=>t.style.display!=='none'));
 if(!NAV_READY){
  NAV_READY=true;let saved='';try{saved=sessionStorage.getItem('kf-console-tab')||'';}catch(_){}
  const key=location.hash.slice(1)||saved||'sites';if(!navigateTo(key,false))navigateTo('sites',false);
 }else if(document.querySelector('.tab.on')?.style.display==='none')navigateTo('sites');
}
function showGlobalError(message){const e=$('#globalMsg');e.textContent=message;e.classList.remove('hidden');}
document.querySelectorAll('.tab').forEach(t=>{t.dataset.label=t.textContent;t.onclick=()=>navigateTo(t.dataset.t);});
document.querySelectorAll('.nav-group').forEach(g=>g.dataset.label=g.querySelector('summary').textContent);
$('#navToggle').onclick=()=>{const open=$('#navGroups').classList.toggle('expanded');$('#navToggle').setAttribute('aria-expanded',String(open));};
$('.sidebar').addEventListener('keydown',e=>{if(e.key==='Escape'){$('#navGroups').classList.remove('expanded');$('#navToggle').setAttribute('aria-expanded','false');$('#navToggle').focus();}});
window.addEventListener('popstate',()=>{if(NAV_READY && !navigateTo(location.hash.slice(1)||'sites',false))history.replaceState(null,'','#'+CURRENT_TAB);});
function setStableHtml(element, html){
 if(element._renderedHtml===html)return;
 element._renderedHtml=html;element.innerHTML=html;
}
function openSiteCreate(){
 if(ROLE==='finance')return;
 $('#siteCreate').open=true;$('#f input[name=company]').focus();
}
function clearSiteFilters(){
 $('#siteSearch').value='';$('#siteStatus').value='';$('#onlyMine').checked=false;renderSites();$('#siteSearch').focus();
}
function renderSites(){
  let s=(STATE.sites||[]);
  if($('#onlyMine') && $('#onlyMine').checked && STATE.me){
    s=s.filter(x=>x.owner===STATE.me);
  }
  const query=$('#siteSearch').value.trim().toLocaleLowerCase();
  const status=$('#siteStatus').value;
  s=s.filter(x=>(!status||x.state===status)&&(!query||[x.slug,x.company,x.domain].some(v=>String(v||'').toLocaleLowerCase().includes(query))));
  const html=s.length? s.map(x=>`<tr>
  <td class="mono">${esc(x.slug)}</td>
  <td><b data-user-content>${esc(x.company)}</b><div class="mono" style="color:var(--dim)">${esc(x.domain)}</div></td>
  <td class="sm-hide" style="font-size:12.5px;color:var(--dim)">${esc(x.owner)||'—'}</td>
  <td class="sm-hide">${esc(x.plan)||'-'}</td>
  <td>${badge(x.state)}<details class="hint"><summary>运行详情</summary><div class="mono">HTTP ${x.http||'-'} · ${x.running}/2</div></details>
   ${x.message?`<div style="color:var(--bad);font-size:11.5px">${esc(x.message)}</div>`:''}</td>
  <td class="sm-hide">${x.invoice?`<a href="/api/invoice/${encodeURIComponent(x.invoice)}/pdf">${esc(x.invoice)}</a>
   <div style="color:var(--dim);font-size:11.5px">${x.invoice_status==='paid'?'已付':'待付'}</div>`
   :`<button class="ghost" onclick="issue('${esc(x.slug)}')">开票</button>`}</td>
  <td>${expiryCell(x)}</td>
  <td>${x.http===200?`<a href="http://${location.hostname}:${x.port}/" target="_blank">打开</a>　`:''}
   <a href="/api/site/${encodeURIComponent(x.slug)}/handover.pdf">交接单</a>
   ${STATE.wordpress?.[x.slug]?.enabled?`<a class="kf-wp-entry" href="${esc(STATE.wordpress[x.slug].url)}/?kf_mvp_sso=begin" target="_blank" rel="noopener">进入 WordPress 后台</a>`:''}
   <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
     ${ROLE==='finance'?'':`<button class="ghost" onclick="renewSite('${esc(x.slug)}')">续费</button>
     <button class="ghost" onclick="toggleSuspend('${esc(x.slug)}','${x.billing_status||'active'}')">${x.billing_status==='suspended'?'恢复':'暂停'}</button>`}
   </div></td></tr>`).join('')
  :(STATE.sites||[]).length?'<tr><td colspan="8" class="empty-results"><p>没有匹配的站点</p><button class="ghost" onclick="clearSiteFilters()">清除筛选</button></td></tr>'
  :'<tr><td colspan="8" style="text-align:center;padding:28px 12px">'
    +'<div style="color:var(--dim);font-size:13px;margin-bottom:10px">还没有站点，先开通一个</div>'
    +(ROLE==='finance'?'':'<button onclick="openSiteCreate()">开通站点</button>')+'</td></tr>';
  setStableHtml($('#rows'),html);
}

async function load(){
 const r=await fetch('/api/state');if(!r.ok)throw Error(r.status===401?'登录已过期，请重新登录':'暂时无法获取状态');STATE=await r.json();
 ROLE=STATE.role||'ops'; applyRole();
 try {STATE.wordpress=(await (await fetch('/api/wordpress/sites')).json()).sites||{};} catch(_){STATE.wordpress={};}
 if($('#whoami')) $('#whoami').textContent=(STATE.me||'')+'（'+({admin:'管理员',ops:'运营',finance:'财务'}[ROLE]||ROLE)+'）';
 const s=STATE.sites||[];
 $('#stats').innerHTML=`<div class="stat"><b>${s.length}</b><span>站点</span></div>
  <div class="stat"><b>${s.filter(x=>x.state==='active').length}</b><span>运行中</span></div>
  <div class="stat"><b>${s.filter(x=>x.http===200).length}</b><span>HTTP 正常</span></div>`;
 renderSites();
 const oldPlan=$('#planSel').value,oldIndustry=$('#indSel').value;
 $('#planSel').innerHTML=(STATE.plans||[]).map(p=>`<option value="${p.id}">${esc(p.name)} — ${money(p.price)}</option>`).join('');
 $('#indSel').innerHTML=(STATE.industries||[]).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');
 if([...$('#planSel').options].some(o=>o.value===oldPlan))$('#planSel').value=oldPlan;
 if([...$('#indSel').options].some(o=>o.value===oldIndustry))$('#indSel').value=oldIndustry;
 const iv=STATE.invoices||[];
 const paid=iv.filter(i=>i.status==='paid'),unpaid=iv.filter(i=>i.status!=='paid');
 $('#billStats').innerHTML=`<div class="stat"><b>${money(paid.reduce((a,b)=>a+b.total,0))}</b><span>已收款</span></div>
  <div class="stat"><b>${money(unpaid.reduce((a,b)=>a+b.total,0))}</b><span>待收款</span></div>
  <div class="stat"><b>${iv.length}</b><span>账单数</span></div>`;
 const billHtml=iv.length?iv.map(i=>`<tr>
  <td class="mono">${esc(i.no)}</td><td data-user-content>${esc(i.company)}</td><td>${esc(i.plan_name)}</td>
  <td class="mono">${money(i.total)}</td>
  <td><span class="pill" style="color:${i.status==='paid'?'var(--ok)':'var(--warn)'}">${i.status==='paid'?'已付款':'待付款'}</span></td>
  <td class="mono" style="color:var(--dim)">${esc(i.issued_at)}</td>
  <td><a href="/api/invoice/${encodeURIComponent(i.no)}/pdf">PDF</a>
   ${i.status!=='paid'?`　<button class="ghost" onclick="pay('${esc(i.no)}')">标记已付</button>`:''}</td></tr>`).join('')
  :'<tr><td colspan="7" style="color:var(--dim)">暂无账单</td></tr>';
 setStableHtml($('#billRows'),billHtml);
 const planHtml=(STATE.plans||[]).map(p=>`<tr><td><b>${esc(p.name)}</b>
  <div class="mono" style="color:var(--dim);font-size:11.5px">${esc(p.id)}</div></td>
  <td class="mono">${money(p.price)} <span style="color:var(--dim)">/ ${esc(p.period)}</span></td>
  <td>${esc(p.specs)}</td><td><a href="#" onclick="editPlan('${esc(p.id)}');return false">编辑</a></td></tr>`).join('');
 setStableHtml($('#planRows'),planHtml);
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
    <div style="font-size:12px;color:var(--dim);margin:14px 0 6px">本机参考记录（${(d.zone.records||[]).length}）；公网变更将在运营助手核验真实服务商并确认</div>
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
  $('#dnMsg').textContent=r.ok?'变更方案已生成，等待确认':('失败：'+(d.error||''));
  if(d.action)openAutoAction(d.action);
}
async function delDns(i){
  const r=await fetch('/api/dns/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({slug:$('#dnSlug').value,index:i})});
  const d=await r.json();
  $('#dnMsg').className='msg '+(r.ok?'ok':'bad');
  $('#dnMsg').textContent=r.ok?'删除方案已生成，等待确认':('失败：'+(d.error||''));
  if(d.action)openAutoAction(d.action);
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
        1. 在验证器 App（Google Authenticator / 1Password）里选择扫描二维码<br>
        2. 扫描下方二维码；也可以手动输入密钥：<b style="color:var(--acc);font-family:monospace">${esc(d.secret||'')}</b>（或粘贴下面的链接）<br>
        3. 输入 App 显示的 6 位验证码完成绑定</div>
      <img src="${esc(d.qr_data||'')}" alt="两步验证绑定二维码" style="display:block;width:256px;max-width:100%;height:auto;margin-top:12px;image-rendering:pixelated">
      <div class="hint" style="margin-top:8px;overflow-wrap:anywhere">${esc(uri)}</div>
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
function initTeam(){ loadMfa(); if(STATE.role==='admin'){ loadTeam(); loadSecurity(); loadRoles(); loadAudit(); } }


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
async function initDomain(){ return loadDomainRegistry(); }

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
let EDITOR_BUSY=false, LOCAL_DIRTY=new Set(), JSON_DIRTY=false, LPAGE='';

function curPage(){ return (LSPEC.pages||[]).find(p=>p.slug===(LPAGE||$('#lPage').value)); }
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
function markPage(){const page=curPage();if(page)LOCAL_DIRTY.add(page.slug);$('#lMsg').className='msg';$('#lMsg').textContent='改动尚未保存，线上内容未变。';paintDirty();}
function syncJson(){
 if(LW){
  const page=curPage();
  if(page && LIDX>=0 && JSON.stringify(page.sections[LIDX])!==JSON.stringify(LW)){
   page.sections[LIDX]=JSON.parse(JSON.stringify(LW));markPage();
  }
  $('#lJson').value=JSON.stringify(LW,null,1);JSON_DIRTY=false;
 }
}
function commitJson(){
 if(!JSON_DIRTY)return true;
 try{
  const value=JSON.parse($('#lJson').value);
  if(!value || typeof value!=='object' || Array.isArray(value) || !LSCHEMAS[value.type])throw Error('区块类型无效');
  LW=value;syncJson();return true;
 }catch(e){$('#lMsg').className='msg bad';$('#lMsg').textContent='JSON 无效：'+e.message;$('#lJson').focus();return false;}
}
$('#lJson').oninput=()=>{JSON_DIRTY=true;paintDirty();};
window.addEventListener('beforeunload',e=>{if(LOCAL_DIRTY.size||JSON_DIRTY||EDITOR_BUSY){e.preventDefault();e.returnValue='';}});
function editorBusy(busy){
 EDITOR_BUSY=busy;
 for(const id of ['lList','lForm'])$('#'+id).inert=busy;
 for(const id of ['lSlug','lPage','lType','lAdd','lJson','lApplyJson','lSave','lPreview','lDiff','lPublish','lPublishAll'])$('#'+id).disabled=busy;
}
async function saveDrafts(){
 if(!commitJson())throw Error('请先修正 JSON');
 for(const slug of [...LOCAL_DIRTY]){
  const page=LSPEC.pages.find(p=>p.slug===slug);
  const r=await fetch('/api/spec',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:LSLUG,page:slug,sections:page.sections})});
  const d=await r.json();if(!r.ok)throw Error(d.error||'保存失败，请重试');
  LOCAL_DIRTY.delete(slug);LSPEC.dirty=true;paintDirty();
 }
}
async function editorAction(action){
 if(EDITOR_BUSY||!commitJson())return false;
 editorBusy(true);$('#lMsg').className='msg';$('#lMsg').textContent='正在处理…';
 try{await action();return true;}
 catch(e){$('#lMsg').className='msg bad';$('#lMsg').textContent=e.message;return false;}
 finally{editorBusy(false);paintDirty();}
}


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
      <button class="section-select" type="button" data-act="select" aria-pressed="${i===LIDX}" aria-label="编辑区块 ${i+1}：${esc(secSummary(s))}"><span class="t">${esc((LSCHEMAS[s.type]||{}).label||s.type)}</span>
      <span class="s" data-user-content>${esc(secSummary(s))}</span></button>
      <button type="button" data-act="up" aria-label="上移区块 ${i+1}" ${i===0?'disabled':''}>↑</button><button type="button" data-act="down" aria-label="下移区块 ${i+1}" ${i===page.sections.length-1?'disabled':''}>↓</button><button type="button" class="danger" data-act="del" aria-label="删除区块 ${i+1}">×</button>
    </div>`).join('') || '<div class="sec-row"><span class="s">这一页还没有区块</span></div>';
  box.querySelectorAll('.sec-row[data-i]').forEach(row=>{
    const i=Number(row.dataset.i);
    row.onclick=e=>{
      if(EDITOR_BUSY||!commitJson())return;
      const act=e.target.closest('button')?.dataset.act;
      if(act && act!=='select'){ e.stopPropagation(); moveSec(i,act); return; }
      LIDX=i; renderSecList(); renderForm();
    };
  });
}
function moveSec(i,act){
  const page=curPage(); if(!page) return;
  const s=page.sections;
  if(act==='del'&&!confirm('删除这个区块？保存前可以重新载入草稿恢复。'))return;
  if(act==='del'){ s.splice(i,1); LIDX=Math.min(i,s.length-1); }
  if(act==='up'&&i>0){ [s[i-1],s[i]]=[s[i],s[i-1]]; LIDX=i-1; }
  if(act==='down'&&i<s.length-1){ [s[i+1],s[i]]=[s[i],s[i+1]]; LIDX=i+1; }
  markPage();renderSecList(); renderForm();
}
function paintDirty(){
  const el=$('#lDirty');
  if(!el) return;
  el.textContent = LOCAL_DIRTY.size||JSON_DIRTY ? '未保存 · '+(LOCAL_DIRTY.size||1)+' 页' : (LSPEC.dirty ? '草稿已保存 · 未发布' : '已与线上一致');
  $('#editorGlobalState').textContent=LOCAL_DIRTY.size||JSON_DIRTY ? '页面编辑有未保存内容' : '';
  el.style.color = LOCAL_DIRTY.size||JSON_DIRTY||LSPEC.dirty ? 'var(--warn)' : 'var(--ok)';
  el.style.borderColor = LOCAL_DIRTY.size||JSON_DIRTY||LSPEC.dirty ? 'var(--warn)' : 'var(--line)';
}
async function loadSpec(slug, force=false){
 if(EDITOR_BUSY)return;
 if(!force && LSLUG===slug && LSPEC.pages.length)return;
 if((LOCAL_DIRTY.size||JSON_DIRTY)&&!confirm('当前站点还有未保存内容。载入其他草稿将丢弃这些改动，是否继续？')){$('#lSlug').value=LSLUG;return;}
 editorBusy(true);
 try{
  const r=await fetch('/api/spec/'+encodeURIComponent(slug));
  if(!r.ok)throw Error('读取草稿失败，请重试');
  const d=await r.json();
  LOCAL_DIRTY.clear();JSON_DIRTY=false;LSPEC=d.spec;LSPEC.dirty=d.dirty;LSLUG=slug;LIDX=-1;LSCHEMAS=d.schemas||{};
  await loadMedia(slug);
  $('#lPage').innerHTML=(LSPEC.pages||[]).map(p=>`<option value="${esc(p.slug)}">${esc(p.title)}</option>`).join('');
  LPAGE=$('#lPage').value;LW=null;
  $('#lType').innerHTML=d.types.map(t=>`<option value="${esc(t)}">${esc((LSCHEMAS[t]||{}).label||t)}</option>`).join('');
  renderSecList();renderForm();paintDirty();
 }catch(e){$('#lMsg').className='msg bad';$('#lMsg').textContent=e.message;$('#lSlug').value=LSLUG;}
 finally{editorBusy(false);}
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
 if(EDITOR_BUSY)return;
 const target=page?LSPEC.pages.find(p=>p.slug===page)?.title:'全部 '+LSPEC.pages.length+' 个页面';
 if(!confirm('发布站点「'+slug+'」的「'+target+'」？\n将先保存编辑内容，再更新线上页面。客户会立即看到。'))return;
 await editorAction(async()=>{
  await saveDrafts();
  const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(page?{slug,page}:{slug})});
  const d=await r.json();
  LSPEC.dirty=r.ok?d.dirty:true;
  if(!r.ok)throw Error('发布失败：'+(d.error||'请重试')+'；草稿已保留，请查看改动后重试。');
  $('#lMsg').className='msg ok';$('#lMsg').textContent='已发布 '+d.pages+' 个页面';$('#lDiffBox').classList.add('hidden');
 });
}
async function initLayout(preferredSlug){
  const sel=$('#lSlug');
  if(!sel.options.length){
    sel.innerHTML=STATE.sites.map(s=>`<option value="${s.slug}">${esc(s.company)}</option>`).join('');
    sel.onchange=()=>loadSpec(sel.value);
    $('#lPage').onchange=()=>{if(!commitJson()){$('#lPage').value=LPAGE;return;}LPAGE=$('#lPage').value;LIDX=-1;LW=null;renderSecList();renderForm();paintDirty();};
    $('#lAdd').onclick=()=>{
      if(!commitJson())return;const page=curPage(); if(!page) return;
      page.sections.push({type:$('#lType').value});
      LIDX=page.sections.length-1;markPage();renderSecList();renderForm();
    };
    $('#lApplyJson').onclick=()=>{
      try{JSON_DIRTY=true;if(commitJson())renderForm();}
      catch(e){ $('#lMsg').className='msg bad'; $('#lMsg').textContent='JSON 格式错误'; }
    };
    $('#lPreview').onclick=async()=>{
      if(EDITOR_BUSY)return;
      const page=curPage();if(!page)return;
      const preview=window.open('about:blank','_blank');if(preview)preview.opener=null;
      const ok=await editorAction(async()=>{
        await saveDrafts();
        const url='/preview/'+encodeURIComponent(LSLUG)+'/'+encodeURIComponent(page.slug);
        if(preview)preview.location.href=url;
        else throw Error('草稿已保存，请允许浏览器打开预览窗口后重试。');
        $('#lMsg').textContent='草稿已保存，预览已打开；线上未变。';
      });if(!ok&&preview)preview.close();
    };
    $('#lDiff').onclick=()=>editorAction(async()=>{await saveDrafts();await showDiff();$('#lMsg').textContent='正在比较已保存草稿与线上内容';});
    $('#lPublishAll').onclick=()=>publish(slugVal(), null);
    $('#lPublish').onclick=()=>publish(slugVal(), (curPage()||{}).slug);
    $('#lSave').onclick=()=>editorAction(async()=>{await saveDrafts();$('#lMsg').className='msg ok';$('#lMsg').textContent='全部改动已保存到草稿，线上未变。';renderSecList();});
  }
  if(preferredSlug) sel.value=preferredSlug;
  if(sel.value) await loadSpec(sel.value,!!preferredSlug);
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
  const labels={nursery:'童趣教育',robotics:'精密科技',wellness:'草木静雅'};
  ps.innerHTML='<option value="">自定义</option>'+Object.keys(DPRESETS).map(k=>`<option value="${esc(k)}">${esc(labels[k]||k)}</option>`).join('');
  fillDesign(d.tokens||{});
  ps.value=d.tokens?.preset||'';
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

let fieldSequence=0;
function enhanceAccessibility(){
 document.querySelectorAll('label:not([for])').forEach(label=>{
  if(label.querySelector('input,select,textarea')||!label.textContent.trim())return;
  const next=label.nextElementSibling;
  const controls=next?(next.matches('input,select,textarea')?[next]:[...next.querySelectorAll('input,select,textarea')]):[];
  if(controls.length===1){const c=controls[0];if(!c.id)c.id='field-'+(++fieldSequence);label.htmlFor=c.id;}
  else controls.forEach((c,i)=>{if(!c.getAttribute('aria-label'))c.setAttribute('aria-label',label.textContent+' · '+(c.placeholder||('第 '+(i+1)+' 项')));});
 });
 document.querySelectorAll('table').forEach(table=>{
  const labels=[...table.querySelectorAll('thead th')].map(h=>h.textContent.trim());
  table.querySelectorAll('tbody tr').forEach(row=>[...row.children].forEach((cell,i)=>{if(cell.colSpan===1 && labels[i] && cell.dataset.label!==labels[i])cell.dataset.label=labels[i];}));
 });
 document.querySelectorAll('.msg:not([role])').forEach(e=>e.setAttribute('role','status'));
 document.querySelectorAll('button').forEach(b=>{
  if(!b.getAttribute('aria-label') && ['×','↑','↓'].includes(b.textContent.trim()))b.setAttribute('aria-label',({'×':'删除此项','↑':'上移此项','↓':'下移此项'})[b.textContent.trim()]);
 });
}
function renderValidation(form, focus=false){
 let summary=form.querySelector('.form-error-summary');
 const invalid=[...form.elements].filter(c=>c.willValidate&&!c.validity.valid);
 form.querySelectorAll('.field-error').forEach(e=>e.remove());
 [...form.elements].forEach(c=>{c.removeAttribute('aria-invalid');if(c.dataset.errorId){const ids=(c.getAttribute('aria-describedby')||'').split(' ').filter(id=>id!==c.dataset.errorId);if(ids.length)c.setAttribute('aria-describedby',ids.join(' '));else c.removeAttribute('aria-describedby');delete c.dataset.errorId;}});
 if(!invalid.length){summary?.remove();return;}
 if(!summary){summary=document.createElement('div');summary.className='form-error-summary callout';summary.setAttribute('role','alert');summary.tabIndex=-1;form.prepend(summary);}
 summary.replaceChildren();const title=document.createElement('b');title.textContent='请检查以下 '+invalid.length+' 项';summary.append(title);
 const list=document.createElement('ul');summary.append(list);
 invalid.forEach(c=>{
  if(!c.id)c.id='field-'+(++fieldSequence);
  const label=c.labels?.[0]?.textContent.trim()||c.getAttribute('aria-label')||c.placeholder||'此字段';
  const error=document.createElement('div');error.id=c.id+'-error';error.className='field-error';error.style.color='var(--bad)';error.style.fontSize='13px';error.textContent=c.validationMessage;c.after(error);
  c.setAttribute('aria-invalid','true');c.dataset.errorId=error.id;c.setAttribute('aria-describedby',((c.getAttribute('aria-describedby')||'')+' '+error.id).trim());
  const item=document.createElement('li'),link=document.createElement('a');link.href='#'+c.id;link.textContent=label+'：'+c.validationMessage;link.onclick=e=>{e.preventDefault();c.focus();};item.append(link);list.append(item);
 });
 if(focus)summary.focus();
}
let validationFrame;
$('#workspace').addEventListener('invalid',e=>{if(!e.target.form)return;e.preventDefault();cancelAnimationFrame(validationFrame);validationFrame=requestAnimationFrame(()=>renderValidation(e.target.form,true));},true);
$('#workspace').addEventListener('input',e=>{if(e.target.form?.querySelector('.form-error-summary'))renderValidation(e.target.form);});
const accessibilityObserver=new MutationObserver(enhanceAccessibility);
accessibilityObserver.observe($('#workspace'),{childList:true,subtree:true});enhanceAccessibility();
const siteSlug=$('#f input[name=slug]'),siteDomain=$('#f input[name=domain]');
siteSlug.addEventListener('input',()=>siteSlug.dataset.manual=siteSlug.value?'yes':'');
siteDomain.addEventListener('input',()=>{if(siteSlug.dataset.manual)return;const candidate=siteDomain.value.toLowerCase().replace(/^https?:\/\//,'').split('.')[0].replace(/[^a-z0-9-]/g,'').slice(0,20);if(/^[a-z][a-z0-9-]+$/.test(candidate))siteSlug.value=candidate;});
async function refreshConsole(){try{await load();}catch(e){showGlobalError('数据刷新失败：'+e.message+'。请检查网络，稍后会自动重试。');}}
window.addEventListener('DOMContentLoaded',()=>{refreshConsole();setInterval(refreshConsole,5000);});
</script>
<script src="/ai.js"></script><script src="/prompts.js"></script><script src="/domains.js"></script><script src="/mcp.js"></script><script src="/automation.js"></script><script src="/providers.js"></script></body></html>"""


_AI = None
_AI_LOCK = threading.Lock()
_DRAFT_LOCKS = {}
_DRAFT_LOCKS_GUARD = threading.Lock()
_SITE_RESERVATIONS = {}
_SITE_RESERVATION_LOCK = threading.RLock()


def ai_store():
    global _AI
    with _AI_LOCK:
        if _AI is None:
            _AI = kf_ai.AIStore(BASE)
        return _AI


def draft_lock(slug):
    with _DRAFT_LOCKS_GUARD:
        return _DRAFT_LOCKS.setdefault(slug, threading.RLock())


def draft_operation(fn):
    def wrapped(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        with draft_lock(slug):
            if ai_store().busy(slug):
                return self._send(409, {"error": "自动建站任务正在运行，请完成后再编辑或发布"})
            return fn(self, body)
    return wrapped


def reserve_site(slug):
    with _SITE_RESERVATION_LOCK:
        if (SITES / slug).exists() or slug in _SITE_RESERVATIONS:
            raise kf_ai.AIError("该站点已存在或正在开通，请更换标识或选择已有站点")
        port = free_port()
        if not port:
            raise kf_ai.AIError("没有可用站点端口")
        _SITE_RESERVATIONS[slug] = port
        return port


def release_site(slug):
    with _SITE_RESERVATION_LOCK:
        _SITE_RESERVATIONS.pop(slug, None)


def make_invoice( slug, company, domain, plan, kind="new", years=0):
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


class BuildService:
    def __init__(self,user):
        self.user=user
        self.user_role=(load_users().get(user) or {}).get("role", "")
    def _send(self,code,data): return code,data
    _make_invoice=staticmethod(make_invoice)

    def start(self,body):
        with kf_tool_runtime.release_guard(BASE):return self._start(body)

    def _start(self, body):
        slug = kf_ai.text(body.get("slug", ""), "站点标识", 20, True).lower()
        if not SLUG_RE.fullmatch(slug):
            raise kf_ai.AIError("站点标识必须是小写字母开头的 2–20 位字母、数字或短横线")
        mode = body.get("mode", "existing")
        if mode not in ("new", "existing"):
            raise kf_ai.AIError("请选择新站点或已有站点")
        style = None
        if body.get("style_template_id"):
            style = kf_styles.StyleStore(BASE).resolve(body["style_template_id"])
        elif body.get("reference_style") is not None:
            supplied = body["reference_style"]
            if not isinstance(supplied, dict):
                raise kf_ai.AIError("参考风格必须是对象")
            style = {"tokens": kf_styles.normalize_tokens(supplied.get("tokens")),
                     "summary": kf_ai.text(supplied.get("summary", ""), "风格说明", 1500),
                     "guidance": kf_ai.text(supplied.get("guidance", ""), "风格指导", 2400),
                     "source_url": kf_styles.public_url(supplied.get("source_url")), "name": "本次参考风格"}
        selection = body.get("prompt_selection")
        brief = kf_ai.text(body.get("brief", ""), "建站要求", 6000, selection is None)
        prompt_snapshot = kf_prompts.PromptStore(BASE).compose(selection, brief) if selection is not None else None
        if prompt_snapshot:
            brief = prompt_snapshot["brief"]
        language = body.get("language", "zh")
        if language not in ("zh", "en"):
            raise kf_ai.AIError("请选择中文或英文")
        auto_research=body.get('auto_research') is True
        if auto_research and mode!='existing':raise kf_ai.AIError('自动资料查询需先选择已授权的现有站点')
        context_sources=[]
        selected=body.get('context_options',[])
        if not isinstance(selected,list) or any(x not in ('client','brand','pages','media') for x in selected):
            raise kf_ai.AIError('建站资料选择无效')
        action_ids=body.get('context_actions',[])
        if (selected or action_ids) and mode!='existing':raise kf_ai.AIError('已保存资料需选择已有站点；新站点请在建站要求中填写资料')
        if selected:
            facts=selected_site_context(slug,selected)
            context_sources.append({'source':'MVP/'+','.join(selected),'digest':kf_tool_runtime.fingerprint(facts),'data':json.dumps(facts,ensure_ascii=False)})
        if action_ids:context_sources.extend(automation_store().context_results(self.user,slug,action_ids))
        if len(json.dumps(context_sources,ensure_ascii=False))>48000:raise kf_ai.AIError('所选资料超过上下文限制，请减少资料或选择更小的资源')
        profile, key = ai_store().resolve(body.get("profile_id"))
        plan, port, industry = None, None, (style or {}).get("industry") or body.get("industry", "tech")
        with draft_lock(slug):
            if mode == "existing":
                if not (SITES / slug / "meta.json").is_file():
                    raise kf_ai.AIError("站点不存在，请先开通或选择新建站点")
                meta = load_meta(slug)
                company, domain = meta.get("company", slug), meta.get("domain", "")
                original = read_draft(slug)
                pages = original.get("pages", [])
                if is_dirty(slug) and body.get("replace_draft") is not True:
                    return self._send(409, {"error": "该站点已有未发布草稿；确认替换后再生成（旧草稿会备份）"})
            else:
                if not can_write(self.user_role, "/api/create"):
                    return self._send(403, {"error": "当前角色没有新建站点权限"})
                company = kf_ai.text(body.get("company", ""), "企业名称", 60, True)
                domain = kf_ai.text(body.get("domain", ""), "域名", 80, True).lower()
                if not DOMAIN_RE.fullmatch(domain) or industry not in INDUSTRIES:
                    raise kf_ai.AIError("域名或行业模板不合法")
                if domain in host_map():
                    raise kf_ai.AIError("该域名已有站点，请选择已有站点或使用其他域名")
                plan = next((p for p in plans() if p["id"] == body.get("plan_id")), None)
                if plan is None:
                    raise kf_ai.AIError("请选择套餐")
                import kf_template
                pages = kf_template.build_spec(industry, company, domain)
                original = None
            if not isinstance(pages, list) or not 1 <= len(pages) <= 12:
                raise kf_ai.AIError("站点需要有 1–12 个可编辑页面")
            if any(not SLUG_RE.fullmatch(p.get("slug", "")) for p in pages):
                raise kf_ai.AIError("站点页面标识不符合建站规范")
            if mode == "new":
                port = reserve_site(slug)
            try:
                job = ai_store().create_job(slug, profile, self.user, mode, prompt_snapshot)
                if auto_research:
                    job["auto_research"]=True
                    ai_store().update_job(job["id"],auto_research=True)
                if context_sources:
                    job["context"]=context_sources
                    ai_store().update_job(job["id"],context=context_sources)
                if style:
                    job["style"] = style
                    ai_store().update_job(job["id"], style=style)
                args = (job, profile, key, company, domain, brief, language, pages,
                        original, port, plan, industry)
                threading.Thread(target=self._ai_worker, args=args, daemon=True).start()
            except Exception:
                if mode == "new":
                    release_site(slug)
                raise
        audit(self.user, "ai_build", slug, "任务 %s；%s；%s" % (job["id"], profile["name"], profile["model"]))
        return self._send(202, {"job": job})


    def _ai_worker(self, job, profile, key, company, domain, brief, language,
                   pages, original, port, plan, industry):
        store, slug, jid = ai_store(), job["slug"], job["id"]
        try:
            store.update_job(jid, status="generating", message="正在模拟生成页面" if job["simulated"] else "正在调用模型生成页面")
            if job.get('auto_research'):
                store.update_job(jid,message='正在查询已授权 MCP 只读资料（最多 4 次）')
                sources=automation_store().research(job['user'],slug,brief,profile,key,jid)
                job['context']=job.get('context',[])+sources
                if len(json.dumps(job['context'],ensure_ascii=False))>48000:raise kf_ai.AIError('查询结果超过上下文限制，请缩小资料范围')
                store.update_job(jid,context=job['context'])
            if job.get("prompt") or job.get("style") or job.get("context"):
                guidance = (job.get("prompt") or {}).get("instructions", "")
                if job.get("style"):
                    guidance += kf_styles.guidance(job["style"])
                result = kf_ai.generate(profile, key, company, brief, pages, language, guidance=guidance,
                                        **({"context":job["context"]} if job.get("context") else {}))
            else:
                result = kf_ai.generate(profile, key, company, brief, pages, language)
            # Validate rendered content too, before provisioning or changing the draft.
            for page in result["pages"]:
                rendered = ks().render_sections(page["sections"])
                if len(rendered) < ks().MIN_HTML:
                    raise kf_ai.AIError("生成页面内容不足，草稿未更改")
            if job["mode"] == "new":
                store.update_job(jid, status="provisioning", message="页面已生成，正在开通 WordPress 与数据库（首次拉取镜像可能需要数分钟）")
                provision(company, domain, slug, port, plan["name"], plan["price"], industry, plan["id"])
                with _lock:
                    failed = _live.get(slug, {}).get("state") == "failed"
                if failed or not (SITES / slug / "site-spec.json").is_file():
                    raise kf_ai.AIError("站点开通失败；请查看站点状态。已有目录会保留，请修复后选择已有站点重试")
                if {p["slug"] for p in read_spec(slug).get("pages", [])} != {p["slug"] for p in pages}:
                    raise kf_ai.AIError("站点模板初始化未完成，请修复后重试")
                meta = load_meta(slug)
                meta["plan_id"] = plan["id"]
                kf_ai.atomic_json(SITES / slug / "meta.json", meta)
                inv = self._make_invoice(slug, company, domain, plan)
                store.update_job(jid, invoice=inv["no"])
            store.update_job(jid, status="saving", message="正在校验并保存草稿")
            automation_access(job['user'],slug,'build')
            with draft_lock(slug):
                current = read_draft(slug)
                if original is not None and current != original:
                    raise kf_ai.AIError("生成期间草稿已改变，本次内容未覆盖；请重新生成")
                backup = SITES / slug / ".backups" / ("ai-" + jid + ".json")
                kf_ai.atomic_json(backup, current)
                if job.get("style"):
                    result["design"] = job["style"]["tokens"]
                elif current.get("design"):
                    result["design"] = current["design"]
                result["ai"] = {"job_id": jid, "simulated": job["simulated"], "model": profile["model"],
                                "language": language, "generated_at": int(time.time()),
                                "prompt": job.get("prompt"), "style": job.get("style"),
                                "context_sources":[{k:v for k,v in src.items() if k!='data'} for src in job.get("context",[])]}
                kf_ai.atomic_json(draft_path(slug), result)
            store.update_job(jid, status="completed", message="模拟草稿已生成，请预览、编辑后发布" if job["simulated"] else "草稿已生成，请预览、编辑后发布",
                             pages=len(result["pages"]), preview="/preview/" + slug + "/home")
            audit(job["user"], "ai_complete", slug, jid)
        except kf_ai.AIError as e:
            store.update_job(jid, status="failed", message=str(e))
            audit(job["user"], "ai_failed", slug, str(e))
        except Exception as e:
            store.update_job(jid, status="failed", message="建站任务失败（%s），请检查服务日志或站点状态后重试" % type(e).__name__)
            audit(job["user"], "ai_failed", slug, type(e).__name__)
        finally:
            if job["mode"] == "new":
                release_site(slug)


def render_check( slug, page, title, sections, write=False):
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-page-", suffix=".json", dir=str(CONSOLE))
    os.close(fd)
    tmp = Path(tmp_name)
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


def publish_site(body,render):
    with kf_tool_runtime.release_guard(BASE):return _publish_site(body,render)

def _publish_site(body, render):
    slug = str(body.get('slug', '')).strip().lower()
    page_slug = str(body.get('page', '')).strip()
    if not SLUG_RE.match(slug) or not (SITES / slug).exists():
        return (400, {'ok': False, 'error': '站点不存在'})
    draft = read_draft(slug)
    pages = draft.get('pages', [])
    targets = [p for p in pages if p['slug'] == page_slug] if page_slug else pages
    if not targets:
        return (404, {'ok': False, 'error': '草稿里没有这一页'})
    if draft.get('design'):
        tokens = sanitize_design(draft['design'])
        if not apply_design(slug, tokens):
            return (500, {'ok': False, 'error': '风格同步失败，页面尚未发布，请重试'})
    failed = []
    published = []
    for page in targets:
        res = render(slug, page['slug'], page.get('title', page['slug']), page.get('sections', []), write=True)
        if not res.get('ok'):
            failed.append({'page': page['slug'], 'error': '；'.join(res.get('errors', ['失败']))})
            break
        published.append(page)
    live = read_spec(slug)
    live_pages = live.get('pages', [])
    for page in published:
        cur = next((p for p in live_pages if p['slug'] == page['slug']), None)
        if cur is None:
            live_pages.append(json.loads(json.dumps(page)))
        else:
            cur['sections'] = json.loads(json.dumps(page.get('sections', [])))
            cur['title'] = page.get('title', cur.get('title', page['slug']))
    live['pages'] = live_pages
    if draft.get('design'):
        live['design'] = draft['design']
    if 'ai' in draft:
        live['ai'] = draft['ai']
    if published:
        kf_ai.atomic_json(spec_path(slug), live)
    if failed:
        return (400, {'ok': False, 'error': '发布中断，已发布 %d 页；请检查失败页面后重试' % len(published), 'failed': failed, 'pages': len(published), 'dirty': is_dirty(slug)})
    return (200, {'ok': True, 'pages': len(published), 'dirty': is_dirty(slug)})


_AUTOMATION = None
_WORKFLOWS = None
_AUTOMATION_LOCK = threading.RLock()


def automation_context(slug):
    if not isinstance(slug,str) or not SLUG_RE.fullmatch(slug) or not (SITES/slug/'meta.json').is_file():
        raise kf_ai.AIError('请选择有效站点')
    meta=load_meta(slug)
    return {'slug':slug,'domain':kf_dns_provider.domain_name(meta.get('domain','')),'company':meta.get('company',slug)}


def automation_access(user,slug,purpose):
    entry=load_users().get(user) or {}
    if not entry.get('active') or entry.get('role') not in ('admin','ops'):
        raise kf_tool_runtime.ActionDenied('当前账号无权使用运营自动化')
    paths={'build':'/api/ai/build','dns':'/api/dns/record','mail':'/api/automation/','maintenance':'/api/automation/'}
    if not isinstance(purpose,str) or purpose not in paths or not can_write(entry['role'],paths[purpose]):
        raise kf_tool_runtime.ActionDenied('当前角色未获此功能的执行权限')
    automation_context(slug)


def automation_totp(user,code):
    secret=(load_users().get(user) or {}).get('mfa_secret')
    if not secret:raise kf_tool_runtime.ActionDenied('请先在团队与安全启用当前账号的 TOTP')
    def counter(value):
        now=int(time.time()//30)
        for n in (now,now-1,now+1):
            if _h.compare_digest(_totp(secret,n),value):return n
        return None
    kf_stepup.StepUp(BASE).verify(user,code,counter)


def selected_site_context(slug,selected):
    result={'site':automation_context(slug)}
    if 'client' in selected:
        client=client_of(slug);result['client']={k:client.get(k,'') for k in ('contact','email','phone','address','notes','scope')}
    if 'brand' in selected:result['brand']=site_design(slug)
    if 'pages' in selected:result['pages']=read_draft(slug).get('pages',[])
    if 'media' in selected:
        root=SITES/slug/'html'/'wp-content'/'uploads'
        result['media']=[{'filename':p.name,'path':str(p.relative_to(root))} for p in sorted(root.rglob('*')) if p.is_file() and p.suffix.lower() in ('.jpg','.png','.webp','.svg')][:100] if root.exists() else []
    return result


def automation_generate(item,context):
    slug=context['slug']
    with draft_lock(slug):
        if kf_tool_runtime.fingerprint(read_draft(slug))!=item['snapshot']['draft']:
            raise kf_tool_runtime.ActionConflict('草稿已改变，请重新生成操作')
        code,data=BuildService(item['user']).start(item['arguments'])
        if code>=400:raise kf_ai.AIError(data.get('error','建站任务创建失败'))
        return data


def automation_publish(item,context):
    slug=context['slug']
    with draft_lock(slug):
        if ai_store().busy(slug):raise kf_ai.AIError('建站任务正在运行，请完成后再发布')
        if kf_tool_runtime.fingerprint(read_draft(slug))!=item['snapshot']['draft']:
            raise kf_tool_runtime.ActionConflict('草稿已改变，请重新预览并确认发布')
        code,data=publish_site({'slug':slug,'page':item['arguments'].get('page','')},render_check)
        if code>=400:raise kf_ai.AIError(data.get('error','发布失败，请核实各页面状态'))
        return data


def automation_maintenance(slug):
    root=SITES/slug/'.backups'
    backups=sorted((p for p in root.glob('*') if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True) if root.exists() else []
    return {'service_days_left':days_left(slug),'latest_draft_backup':{'name':backups[0].name,'modified':int(backups[0].stat().st_mtime)} if backups else None,
            'backup_note':'仅核对草稿备份；数据库与服务器备份需按运维流程验证'}


def automation_store():
    global _AUTOMATION
    with _AUTOMATION_LOCK:
        if _AUTOMATION is None:
            providers=kf_dns_provider.DNSProviders(BASE,dnsmod())
            callbacks={'action':lambda ident,user:automation_store().actions.get(ident,user),'draft':read_draft,'context':selected_site_context,'smtp':lambda:settings().get('smtp',{}),'site_smtp':lambda slug:kf_providers.mail_config(BASE,slug,lambda:settings().get('smtp',{})),
                       'generate':automation_generate,'publish':automation_publish,'maintenance':automation_maintenance,'model':lambda pid:ai_store().resolve(pid)}
            builtins=kf_builtin_tools.BusinessTools(BASE,callbacks,providers).registry()
            _AUTOMATION=kf_automation.Automation(BASE,automation_context,automation_access,automation_totp,builtins)
        return _AUTOMATION


def workflow_store():
    global _WORKFLOWS
    with _AUTOMATION_LOCK:
        if _WORKFLOWS is None:_WORKFLOWS=kf_workflows.Workflows(BASE,automation_store(),lambda:ai_store().jobs())
        return _WORKFLOWS


class Handler(BaseHTTPRequestHandler):
    server_version = "KFConsole/0.2"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def _origin_ok(self):
        from urllib.parse import urlsplit
        origin = self.headers.get("Origin")
        if origin is None:
            referer = self.headers.get("Referer")
            if not referer:
                return self.headers.get("Sec-Fetch-Site", "") not in ("cross-site", "same-site")
            p = urlsplit(referer)
            origin = p.scheme + "://" + p.netloc
        expected = ("https" if self._is_secure() else "http") + "://" + self.headers.get("Host", "")
        return origin == expected

    def _csrf_ok(self):
        expected = csrf_token(self.headers.get("Cookie"))
        return bool(expected and self._origin_ok() and _h.compare_digest(
            self.headers.get("X-KF-CSRF", ""), expected))

    def log_message(self, fmt, *a):
        pass

    def _is_secure(self):
        """判断当前连接是否已加密。决定 Cookie 是否加 Secure。"""
        if FORCE_HTTPS:
            return True
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        if (proto == "https" and self.client_address[0] in TRUSTED_PROXIES
                and proxy_secret() and _h.compare_digest(self.headers.get("X-KF-Proxy-Secret", ""), proxy_secret())):
            return True
        return bool(getattr(self, "is_https", False))

    def _auth_ok(self):
        u = session_user(self.headers.get("Cookie"))
        if u and (load_users().get(u) or {}).get("active"):
            self.user = u
            self.user_role = (load_users().get(u) or {}).get("role", "ops")
            return True
        # Password-only Basic cannot share the browser's MFA and revocation guarantees.
        return False

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
            self.send_header("Cache-Control", "no-store")
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
        return json.loads(self.rfile.read(n) or b"{}")

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

    def _automation_get(self,path):
        if self.user_role not in ('admin','ops'):return self._send(403,{'error':'无权使用运营自动化'})
        store=automation_store()
        try:
            if path=='/api/automation/workflows':return self._send(200,{'items':workflow_store().list(self.user,self.user_role=='admin')})
            if path=='/api/automation/actions':return self._send(200,{'items':store.actions.list(self.user,self.user_role=='admin')})
            if path.startswith('/api/automation/action/'):
                item=store.actions.get(path.rsplit('/',1)[-1],None if self.user_role=='admin' else self.user)
                return self._send(200,{'item':item})
            if path=='/api/automation/providers':
                if self.user_role!='admin':return self._send(403,{'error':'仅管理员可管理供应商账号'})
                return self._send(200,{'catalog':kf_providers.CATALOG,'items':kf_providers.ProviderStore(BASE).public()})
            if path=='/api/automation/config':
                providers=kf_dns_provider.DNSProviders(BASE,dnsmod()).public() if self.user_role=='admin' else []
                return self._send(200,{'tools':[{'name':n,'purpose':v['purpose']} for n,v in store.builtins.items()],
                                       'dns_providers':providers,'can_configure':self.user_role=='admin',
                                       'provider_accounts':[{k:i[k] for k in ('id','name','provider','sites','capabilities')} for i in kf_providers.ProviderStore(BASE).public() if i['enabled']],
                                       'mail_bindings':kf_ai.read_json(BASE/'console'/'provider-bindings.json',{}) if self.user_role=='admin' else {}})
            return self._send(404,{'error':'not found'})
        except kf_tool_runtime.ActionDenied as exc:return self._send(403,{'error':str(exc)})
        except kf_ai.AIError as exc:return self._send(400,{'error':str(exc)})

    def _automation_post(self,path,body):
        if self.user_role not in ('admin','ops'):return self._send(403,{'error':'无权使用运营自动化'})
        if not isinstance(body,dict) or self.headers.get_content_type()!='application/json':return self._send(400,{'error':'请使用 JSON 请求'})
        if session_user(self.headers.get('Cookie'))!=self.user:return self._send(403,{'error':'请从 MVP 登录页登录后操作'})
        store=automation_store()
        try:
            if path=='/api/automation/providers/test':
                if self.user_role!='admin':raise kf_tool_runtime.ActionDenied('仅管理员可测试供应商账号')
                result=kf_providers.test_account(BASE,body)
                audit(self.user,'provider_test',str(body.get('id','')),result['provider'])
                return self._send(200,{'result':result})
            if path=='/api/automation/providers':
                if self.user_role!='admin':raise kf_tool_runtime.ActionDenied('仅管理员可管理供应商账号')
                if not isinstance(body.get('sites',[]),list):raise kf_ai.AIError('站点范围必须是列表')
                for slug in body.get('sites',[]):automation_context(slug)
                item=kf_providers.ProviderStore(BASE).save(body,self.user)
                audit(self.user,'provider_'+str(body.get('action','save')),item['id'],item['provider'])
                return self._send(200,{'item':item})
            if path=='/api/automation/mail-binding':
                if self.user_role!='admin':raise kf_tool_runtime.ActionDenied('仅管理员可绑定邮件账号')
                automation_context(body.get('slug'))
                item=kf_providers.bind_mail(BASE,body);audit(self.user,'provider_mail_bind',body['slug'],item['account_id'])
                return self._send(200,{'item':item})
            if path=='/api/automation/workflow/create':
                item=workflow_store().create(self.user,body)
                audit(self.user,'workflow_create',item['id'],item['slug'])
                return self._send(200,{'item':item})
            if path=='/api/automation/workflow/control':
                return self._send(200,{'item':workflow_store().control(body.get('id'),self.user,body.get('action'))})
            if path=='/api/automation/workflow/amend':
                return self._send(200,{'item':workflow_store().amend(body.get('id'),self.user,body.get('arguments'))})
            if path=='/api/automation/available':return self._send(200,{'items':store.available(self.user,body.get('slug'),body.get('purpose','build'))})
            if path=='/api/automation/prepare':
                body.pop('workflow_id',None)
                item=store.prepare_mcp(self.user,body) if body.get('server') else store.prepare_builtin(self.user,body)
            elif path=='/api/automation/execute':
                item=store.execute(self.user,body)
                if item.get('workflow_id') and item['state']=='succeeded':
                    workflow=workflow_store().get(item['workflow_id'],self.user)
                    if workflow['state']=='waiting':workflow_store().control(workflow['id'],self.user,'resume')
            elif path=='/api/automation/cancel':item=store.actions.cancel(body.get('id'),self.user)
            elif path=='/api/automation/reconcile':item=store.actions.reconcile(body.get('id'),self.user,body.get('outcome'),body.get('note',''),admin=self.user_role=='admin')
            elif path=='/api/automation/dns-provider':
                if self.user_role!='admin':raise kf_tool_runtime.ActionDenied('仅管理员可配置 DNS 执行服务商')
                item=kf_dns_provider.DNSProviders(BASE,dnsmod()).configure(body,automation_context(body.get('slug')))
            elif path=='/api/automation/dns-records':
                automation_access(self.user,body.get('slug'),'dns')
                provider,records,authority=kf_dns_provider.DNSProviders(BASE,dnsmod()).records(automation_context(body['slug']))
                return self._send(200,{'provider':provider['provider'],'records':records,'authority':authority})
            else:return self._send(404,{'error':'not found'})
            audit(self.user,'automation_'+path.rsplit('/',1)[-1],str(item.get('id',item.get('slug','')))[:80],str(item.get('state','')))
            return self._send(200,{'item':item})
        except kf_tool_runtime.ActionDenied as exc:return self._send(403,{'error':str(exc)})
        except (kf_tool_runtime.ActionConflict,kf_domain_vault.VaultConflict) as exc:return self._send(409,{'error':str(exc)})
        except kf_ai.AIError as exc:return self._send(400,{'error':str(exc)})

    def _mcp_post(self, path, body):
        if self.user_role != "admin": return self._send(403, {"error":"仅管理员可管理 MCP"})
        if not isinstance(body, dict) or self.headers.get_content_type() != "application/json":
            return self._send(400, {"error":"请使用 JSON 请求"})
        if session_user(self.headers.get("Cookie")) != self.user:
            return self._send(403, {"error":"请从 MVP 登录页登录后操作"})
        store = kf_mcp.MCPStore(BASE)
        try:
            if path == "/api/mcp/servers":
                item = store.change(body, self.user)
                audit(self.user, "mcp_" + str(body.get("action", "save")), item["id"])
                return self._send(200, {"item":item})
            if path == "/api/mcp/test":
                result = store.test(body.get("id"), body.get("version"))
                audit(self.user, "mcp_test", str(body.get("id", ""))[:40], "连接与能力查询成功")
                return self._send(200, {"result":result})
            return self._send(404, {"error":"not found"})
        except kf_domain_vault.VaultConflict as exc:
            return self._send(409, {"error":str(exc)})
        except kf_ai.AIError as exc:
            return self._send(400, {"error":str(exc)})

    def _domain_account_post(self, path, body):
        if self.user_role not in ("admin", "ops"):
            return self._send(403, {"error": "当前角色无权访问管理机构账号"})
        if not isinstance(body, dict) or self.headers.get_content_type() != "application/json":
            return self._send(400, {"error": "请使用 JSON 请求"})
        # Require the existing browser session; Basic Auth cannot reveal vault secrets.
        if session_user(self.headers.get("Cookie")) != self.user:
            return self._send(403, {"error": "请从 MVP 登录页登录后操作"})
        vault = kf_domain_vault.DomainVault(BASE)
        try:
            if path == "/api/domain/accounts/reveal":
                entry = load_users().get(self.user) or {}
                secret = entry.get("mfa_secret")
                if not secret:
                    return self._send(403, {"error": "请先在团队与安全中绑定当前账号的 TOTP 两步验证"})
                def verify(code):
                    now = int(time.time() // 30)
                    for counter in (now, now - 1, now + 1):
                        if _h.compare_digest(_totp(secret, counter), code):
                            return counter
                    return None
                password = vault.reveal(body.get("id"), self.user, body.get("code"), verify)
                audit(self.user, "domain_password_view", str(body.get("id", ""))[:40], "TOTP 验证成功")
                return self._send(200, {"password": password, "expires_in": 30}, extra={"Pragma": "no-cache"})
            if path != "/api/domain/accounts":
                return self._send(404, {"error": "not found"})
            if body.get("action") != "delete":
                slug = body.get("slug", "")
                if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or not (SITES / slug / "meta.json").is_file():
                    raise kf_ai.AIError("请选择有效站点域名")
            item = vault.change(body, self.user)
            audit(self.user, "domain_account_" + str(body.get("action", "save")), item["id"], item["slug"])
            return self._send(200, {"item": item})
        except kf_domain_vault.VaultLimited as exc:
            audit(self.user, "domain_password_denied", "", "验证频率限制")
            return self._send(429, {"error": str(exc)})
        except kf_domain_vault.VaultDenied as exc:
            audit(self.user, "domain_password_denied", "", "TOTP 验证失败")
            return self._send(403, {"error": str(exc)})
        except kf_domain_vault.VaultConflict as exc:
            return self._send(409, {"error": str(exc)})
        except kf_ai.AIError as exc:
            return self._send(400, {"error": str(exc)})

    def _wordpress_callback(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 8192:
                return self._send(413, {"error": "请求大小无效"})
            raw = self.rfile.read(size)
            result = kf_sso.SSOStore(BASE).callback(raw, self.headers, SESSIONS, load_users(),
                lambda role: can_write(role, "/api/wordpress/login"))
            return self._send(200, result)
        except (ValueError, kf_ai.AIError):
            return self._send(403, {"error": "统一登录验证失败，请返回 MVP 重新登录"})

    def _wordpress_authorize(self):
        user = session_user(self.headers.get("Cookie"))
        if not user:
            return self._send(303, "", extra={"Location": "/login?next=" + urllib.parse.quote(safe_next(self.path), safe="")})
        try:
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            slug = params.get("site", [""])[0]; challenge = params.get("challenge", [""])[0]
            sid = cookie_value(self.headers.get("Cookie"), "kf_sid").rsplit(".", 1)[0]
            store = kf_sso.SSOStore(BASE)
            token = store.issue(slug, challenge, sid, SESSIONS, load_users(), lambda role: can_write(role, "/api/wordpress/login"))
            target = store.site(slug)["url"] + "/?kf_mvp_sso=finish"
            audit(user, "wordpress_login", slug, "一次性浏览器凭证")
            page = ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                    '<title>进入 WordPress</title><p>正在进入 WordPress 后台…</p>'
                    '<form method="post" action="' + _htmlesc.escape(target, quote=True) + '">'
                    '<input type="hidden" name="ticket" value="' + token + '">'
                    '<button type="submit">继续进入 WordPress</button></form>'
                    '<script>document.forms[0].submit()</script></html>')
            return self._send(200, page, "text/html; charset=utf-8", {"Referrer-Policy": "no-referrer"})
        except kf_ai.AIError as exc:
            return self._send(403, {"error": str(exc)})

    def _ai_get(self, path):
        if self.user_role not in ("admin", "ops"):
            return self._send(403, {"error": "当前角色无权使用自动建站"})
        store = ai_store()
        if path == "/api/ai/styles":
            return self._send(200, kf_styles.StyleStore(BASE).public(self.user_role == "admin"))
        if path == "/api/ai/prompts":
            return self._send(200, kf_prompts.PromptStore(BASE).public(self.user_role == "admin"))
        if path == "/api/ai/config":
            result = store.profiles()
            if self.user_role != "admin":
                result["profiles"] = [{k: p[k] for k in ("id", "name", "model", "protocol")}
                                      for p in result["profiles"]]
                result.pop("presets", None)
            result["can_configure"] = self.user_role == "admin"
            return self._send(200, result)
        if path == "/api/ai/jobs":
            return self._send(200, {"jobs": store.jobs()})
        return self._send(404, {"error": "not found"})

    def _ai_post(self, path, body):
        if self.user_role not in ("admin", "ops"):
            return self._send(403, {"error": "当前角色无权使用自动建站"})
        if not isinstance(body, dict):
            return self._send(400, {"error": "请求必须是 JSON 对象"})
        try:
            if path == "/api/ai/styles/preview":
                return self._send(200, {"html": style_preview_html(body), "tokens": kf_styles.normalize_tokens(body.get("tokens", {})), "recipe": kf_styles.normalize_recipe(body)})
            if path == "/api/ai/styles/analyze":
                return self._send(200, kf_styles.analyze(body.get("url")))
            if path == "/api/ai/styles":
                if self.user_role != "admin":
                    return self._send(403, {"error": "只有管理员可以管理风格模板"})
                item = kf_styles.StyleStore(BASE).change(body)
                audit(self.user, "ai_style", item["id"], str(body.get("action", "save")))
                return self._send(200, {"item": item, **kf_styles.StyleStore(BASE).public(True)})
            if path == "/api/ai/prompts/preview":
                result = kf_prompts.PromptStore(BASE).compose(body.get("selection"), body.get("brief", ""))
                return self._send(200, result)
            if path == "/api/ai/prompts":
                if self.user_role != "admin":
                    return self._send(403, {"error": "只有管理员可以管理提示词库"})
                item = kf_prompts.PromptStore(BASE).change(body)
                audit(self.user, "ai_prompt", item["id"], "%s v%d" % (body.get("action", "save"), item["version"]))
                return self._send(200, kf_prompts.PromptStore(BASE).public(True))
            if path == "/api/ai/config":
                if self.user_role != "admin":
                    return self._send(403, {"error": "只有管理员可以配置模型服务商"})
                result = ai_store().configure(body)
                audit(self.user, "ai_config", str(body.get("id", "")), str(body.get("action", "save")))
                return self._send(200, result)
            if path == "/api/ai/test":
                if self.user_role != "admin":
                    return self._send(403, {"error": "只有管理员可以测试接口"})
                profile, key = ai_store().resolve(body.get("profile_id"))
                if profile["protocol"] != "mock":
                    probe = dict(profile, max_tokens=512, timeout=min(30, profile["timeout"]))
                    kf_ai.complete(probe, key, "Reply only with JSON: {\"ok\":true}", "Connection test; return JSON.")
                return self._send(200, {"ok": True, "simulated": profile["protocol"] == "mock",
                                        "message": "模拟模式可用（未调用外部模型）" if profile["protocol"] == "mock" else "接口连接成功，模型已返回内容"})
            if path == "/api/ai/build":
                return self._ai_build(body)
            return self._send(404, {"error": "not found"})
        except (kf_prompts.PromptConflict, kf_styles.StyleConflict) as e:
            return self._send(409, {"error": str(e)})
        except kf_ai.AIError as e:
            return self._send(400, {"error": str(e)})

    def _ai_build(self,body):
        code,data=BuildService(self.user).start(body)
        return self._send(code,data)


    def do_GET(self):
        if self._maybe_site():
            return
        raw = self.path.split("?")[0]
        if raw in ("/appearance.js", "/locale.js"):
            return self._send(200, (CONSOLE / raw.lstrip("/")).read_text(), "application/javascript; charset=utf-8")
        if raw == "/login":
            nxt = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("next", ["/"])[0]
            user = session_user(self.headers.get("Cookie"))
            if user and (load_users().get(user) or {}).get("active"):
                return self._send(303, "", extra={"Location": safe_next(nxt)})
            return self._send(200, login_page(next_url=safe_next(nxt)), "text/html; charset=utf-8")
        if raw == "/logout":
            if not self._guard(): return
            token = csrf_token(self.headers.get("Cookie"))
            page = '<!doctype html><meta charset="utf-8"><button id="logout">确认退出</button><script>'
            page += 'document.getElementById("logout").onclick=async()=>{const r=await fetch("/logout",{method:"POST",headers:{"Content-Type":"application/json","X-KF-CSRF":'+json.dumps(token)+'},body:"{}"});if(r.ok)location.href="/login"};</script>'
            return self._send(200, page, "text/html; charset=utf-8")
        if raw.startswith("/portal/"):
            return self._send(410, "<h1>客户门户已停用</h1><p>客户无需登录，一切由我们代管。</p>",
                              "text/html; charset=utf-8")
        if raw.startswith("/s/") or raw.startswith("/sa/"):
            return self._public(raw)
        if raw == "/wordpress/authorize":
            return self._wordpress_authorize()
        if not self._guard():
            return
        path = raw.rstrip("/") or "/"
        if not can_read(self.user_role, path):
            return self._send(403, {"error": "当前角色无权读取此信息"})
        if path == "/":
            return self._send(200, PAGE.replace("__KF_CSRF__", csrf_token(self.headers.get("Cookie"))), "text/html; charset=utf-8")
        if path in ("/ai.js", "/prompts.js", "/domains.js", "/mcp.js", "/automation.js", "/providers.js"):
            return self._send(200, (CONSOLE / path.lstrip("/")).read_text(), "application/javascript; charset=utf-8")
        if path == "/api/mcp/servers":
            if self.user_role != "admin": return self._send(403, {"error":"仅管理员可管理 MCP"})
            return self._send(200, {"items":kf_mcp.MCPStore(BASE).public()})
        if path.startswith("/api/automation/"):
            return self._automation_get(path)
        if path.startswith("/api/ai/"):
            return self._ai_get(path)
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/health/ip":
            # 诊断用：显示后端认定的客户端 IP 与是否走了反代
            return self._send(200, {"ip": client_ip(self),
                                    "peer": self.client_address[0] if self.client_address else "",
                                    "xff": self.headers.get("X-Forwarded-For", ""),
                                    "proto": self.headers.get("X-Forwarded-Proto", "")})
        if path == "/api/wordpress/sites":
            cfg = kf_sso.SSOStore(BASE).config()
            allowed = self.user_role in ("admin", "ops") and can_write(self.user_role, "/api/wordpress/login")
            return self._send(200, {"sites": {slug: {"url": item["url"], "enabled": bool(item.get("enabled") and allowed)}
                                              for slug, item in cfg["sites"].items()}})
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
                                    "staff": sorted(load_users().keys()) if self.user_role == "admin" else [self.user],
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
            return self._send(200, preview_html(slug, page), "text/html; charset=utf-8", PREVIEW_HEADERS)

        m = re.match(r"^/pa/([a-z0-9-]+)/(.+)$", path)
        if m:
            slug, rel = m.group(1), m.group(2)
            return self._preview_asset(slug, rel)

        if path == "/api/domain/accounts":
            if self.user_role not in ("admin", "ops") or not can_write(self.user_role, "/api/domain/accounts"):
                return self._send(403, {"error": "当前角色无权访问管理机构账号"})
            return self._send(200, {"items": kf_domain_vault.DomainVault(BASE).public(),
                "mfa_enabled": bool((load_users().get(self.user) or {}).get("mfa_secret"))})
        if path == "/api/domains":
            hm = host_map()
            seen = {}
            for host, e in hm.items():
                if host.startswith("www."):
                    continue
                seen[e["slug"]] = {"domain": host, "www": "www." + host,
                                   "port": e["port"], "slug": e["slug"],
                                   "https_port": HTTPS_PORT, "http_port": PORT,
                                   "company": load_meta(e["slug"]).get("company", e["slug"]),
                                   "url": "https://" + host, "manage": read_domain(e["slug"])}
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
                out["qr_data"] = mfa_qr_data(out["otpauth"])
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
        raw_path = self.path.split("?")[0]
        limit = (MAX_UPLOAD + 65536 if raw_path == "/api/upload" else
                 8192 if raw_path in ("/login", "/api/wordpress/callback") else
                 1024 * 1024 if raw_path == "/api/spec" else 65536)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1 or not 0 <= length <= limit:
                raise ValueError()
        except ValueError:
            self.close_connection = True
            return self._send(413, {"error": "请求长度无效或超过限制"})
        if raw_path != "/api/wordpress/callback" and not self._origin_ok():
            return self._send(403, {"error": "请求来源不匹配，请从管理后台操作"})
        if self.path.split("?")[0] == "/api/wordpress/callback":
            return self._wordpress_callback()
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
        if not self._csrf_ok():
            return self._send(403, {"error": "安全令牌失效，请刷新页面后重试"})
        if path == "/logout":
            sid = (cookie_value(self.headers.get("Cookie"), "kf_sid") or "").split(".")[0]
            SESSIONS.pop(sid, None); save_sessions()
            return self._send(200, {"ok": True}, extra={"Set-Cookie": "kf_sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" + ("; Secure" if self._is_secure() else "")})
        if path != "/api/upload" and self.headers.get_content_type() != "application/json":
            return self._send(415, {"error": "请使用 JSON 请求"})
        is_prompt_preview = path in ("/api/ai/prompts/preview", "/api/ai/styles/analyze", "/api/ai/styles/preview") and self.user_role in ("admin", "ops")
        if not is_prompt_preview and not can_write(getattr(self, "user_role", "ops"), path):
            audit(getattr(self, "user", "-"), "denied", path)
            return self._send(403, {"error": "当前角色无权执行此操作"})
        audit(getattr(self, "user", "-"), "POST " + path, "")

        if path == "/api/upload":
            return self._upload()

        if path.startswith(("/api/ai/", "/api/domain/accounts", "/api/mcp/", "/api/automation/")):
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._send(400, {"error": "请求长度无效"})
            if not 0 <= content_length <= 65536:
                self.close_connection = True
                return self._send(413, {"error": "请求超过 64KB 限制"})
        try:
            body = self._body()
            if not isinstance(body, dict): raise ValueError()
        except (ValueError, TypeError):
            return self._send(400, {"error": "请求必须是 JSON 对象"})

        if path.startswith("/api/automation/"):
            return self._automation_post(path, body)
        if path.startswith("/api/mcp/"):
            return self._mcp_post(path, body)
        if path.startswith("/api/domain/accounts"):
            return self._domain_account_post(path, body)
        if path.startswith("/api/ai/"):
            return self._ai_post(path, body)
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

        try:
            port = reserve_site(slug)
        except kf_ai.AIError as e:
            return self._send(409, {"error": str(e)})

        try:
            inv = self._make_invoice(slug, company, domain, plan)
        except Exception:
            release_site(slug)
            raise
        threading.Thread(target=self._run_provision,
                         args=(company, domain, slug, port, plan, industry), daemon=True).start()
        return self._send(202, {"slug": slug, "port": port, "state": "provisioning",
                                "invoice": inv["no"]})

    def _run_provision(self, company, domain, slug, port, plan, industry=""):
        try:
            provision(company, domain, slug, port, plan["name"], plan["price"], industry, plan["id"])
        finally:
            release_site(slug)
        mp = SITES / slug / "meta.json"
        try:
            meta = json.loads(mp.read_text())
            meta["plan"] = plan["name"]
            meta["plan_id"] = plan["id"]
            mp.write_text(json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass

    def _make_invoice(self,*args,**kwargs):
        return make_invoice(*args,**kwargs)

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
            if inv.get("status") == "paid":
                return self._send(200, inv)
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

    def _preview_asset(self, slug, rel):
        try:
            f, ctype = preview_asset(slug, rel)
            return self._send(200, f.read_bytes(), ctype, PREVIEW_HEADERS)
        except (OSError, ValueError):
            return self._send(404, {"error": "not found"})

    def _public(self, path):
        m = re.match(r"^/sa/([A-Za-z0-9_-]+)/(.+)$", path)
        if m:
            token, rel = m.group(1), m.group(2)
            s = share_for(token)
            if not s:
                return self._send(404, {"error": "链接无效或已过期"})
            return self._preview_asset(s["slug"], rel)

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
            return self._send(200, html, "text/html; charset=utf-8", PREVIEW_HEADERS)
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
        import secrets
        fname = f"{slug}-{int(time.time())}-{secrets.token_hex(4)}{ext}"
        try:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / fname).write_bytes(data)
        except OSError:
            return self._send(500, {"error": "媒体目录不可写，请检查站点上传目录权限"})
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
        old_target = tuple(s.get(k) for k in ("host", "port", "provider"))
        for k in ("host", "from", "provider"):
            if k in body:
                s[k] = str(body[k]).strip()[:120]
        # 密钥不进 settings.json，改写入 600 权限的 secrets.json
        sec = load_secrets()
        if "user" in body:
            sec["user"] = str(body["user"]).strip()[:120]
            s["user"] = sec["user"]
        if "api_key" in body:
            sec["api_key"] = str(body["api_key"]).strip()[:200]
            s["api_key"] = sec["api_key"]
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
        changed = old_target != tuple(s.get(k) for k in ("host", "port", "provider"))
        if changed and sec.get("pass") and not (pw and pw != "********") and not body.get("clear_password"):
            return self._send(400, {"error": "更换邮件服务器时请重新填写或清除密码"})
        if old_target[2] != s.get("provider") and sec.get("api_key") and not body.get("api_key"):
            return self._send(400, {"error": "更换邮件服务商时请重新填写或清除 API Key"})
        if s.get("provider") == "smtp" and (s.get("port", 587) not in (465, 587) or not s.get("tls", True)):
            return self._send(400, {"error": "SMTP 必须使用 TLS 465 或 STARTTLS 587"})
        if body.get("clear_password"):sec.pop("pass", None);s.pop("pass", None)
        if pw and pw != "********":
            sec["pass"] = pw
            s["pass"] = pw
        cur["smtp"] = s
        # settings.json 里只留非密钥字段
        cur["smtp"] = {k: v for k, v in s.items()
                       if k not in ("api_key", "pass", "user")}
        _write(SETTINGS_F, cur)
        save_secrets({k: v for k, v in sec.items() if v})
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

    @auth_transaction
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

    @auth_transaction
    def _mfa_save(self, body):
        u = self.user
        users = load_users()
        if u not in users: return self._send(400, {"error": "账号不存在"})
        if locked_for(u) or ip_blocked(client_ip(self)):
            return self._send(429, {"error": "验证失败过多，请稍后重试"})
        act = body.get("action", "enable")
        if act not in ("enable", "regen", "disable"):
            return self._send(400, {"error": "未知操作"})
        if act == "enable" and users[u].get("mfa_secret"):
            return self._send(409, {"error": "两步验证已经启用"})
        secret = PENDING_MFA.get(u) if act == "enable" else users[u].get("mfa_secret")
        code = body.get("code", "")
        if not isinstance(code, str) or not consume_totp(u, secret, code, "mfa-manage"):
            note_fail(u); note_ip_fail(client_ip(self))
            audit(u, "mfa_denied", "验证码无效或已使用")
            return self._send(400, {"error": "验证码无效或已使用，请等待下一枚验证码"})
        codes = None
        if act == "disable":
            users[u].pop("mfa_secret", None); users[u].pop("recovery", None)
        else:
            users[u]["mfa_secret"] = secret
            codes = gen_recovery()
            users[u]["recovery"] = hash_recovery(codes, users[u].get("salt", ""))
        _write(USERS_F, users)
        PENDING_MFA.pop(u, None)
        revoke_other_sessions(u, self.headers.get("Cookie"))
        clear_fails(u)
        audit(u, "mfa_" + act, "已撤销其他会话")
        result = {"ok": True, "enabled": act != "disable"}
        if codes is not None: result["recovery"] = codes
        return self._send(200, result)

    def _login(self):
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self._send(415, {"error": "请使用登录表单"})
        form = self._form_body()
        return self._login_form(form)

    @auth_transaction
    def _login_form(self, form):
        u = str(form.get("user", "")).strip()
        pw = str(form.get("pw", ""))
        code = str(form.get("code", "")).strip()
        nxt = str(form.get("next", "/")) or "/"
        nxt = safe_next(nxt)
        ip = client_ip(self)
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
            if consume_totp(u, secret, code, "login"):
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
                    note_fail(u); note_ip_fail(ip)
                    audit(u, "login_fail", "验证码错误或已使用")
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
                         "kf_sid=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s"
                         % (cookie, SESSION_TTL, "; Secure" if self._is_secure() else ""))
        self.send_header("Content-Length", "0")
        self.end_headers()

    @auth_transaction
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
            revoke_other_sessions(uname)
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
        def enable(zones):
            if zones.get(slug):raise kf_ai.AIError('DNS 区域已存在，请刷新')
            zones[slug]=m.new_zone(domain,ip)
        try:m.update_zones(enable)
        except kf_ai.AIError as exc:return self._send(409,{'error':str(exc)})
        return self._send(200, {"ok": True, "domain": domain})

    def _dns_record(self, body):
        if session_user(self.headers.get('Cookie'))!=self.user:return self._send(403,{'error':'请登录后准备 DNS 变更'})
        try:
            slug=body.get('slug');record={k:body.get(k) for k in ('name','type','ttl')}
            record['content']=str(body.get('value','')).strip()
            if record['type']=='MX':
                parts=record['content'].split(None,1)
                if len(parts)!=2:raise kf_ai.AIError('MX 值需包含优先级和邮件主机')
                record['priority']=int(parts[0]);record['content']=parts[1]
            item=automation_store().prepare_builtin(self.user,{'slug':slug,'tool':'dns.change','arguments':{'operation':'add','record':record}})
            return self._send(202,{'action':item,'message':'请预览并确认 DNS 变更'})
        except (ValueError,TypeError) as exc:return self._send(400,{'error':str(exc) if isinstance(exc,kf_ai.AIError) else 'DNS 记录格式无效'})

    def _dns_delete(self, body):
        if session_user(self.headers.get('Cookie'))!=self.user:return self._send(403,{'error':'请登录后准备 DNS 变更'})
        try:
            context=automation_context(body.get('slug'));zone=dnsmod().load_zones().get(context['slug'])
            index=int(body.get('index',-1))
            if not zone or not 0<=index<len(zone['records']):raise kf_ai.AIError('本机参考记录不存在，请刷新')
            old=zone['records'][index]
            _,records,_=kf_dns_provider.DNSProviders(BASE,dnsmod()).records(context)
            name=context['domain'] if old['name']=='@' else old['name'].rstrip('.') if old['name'].endswith('.') else old['name']+'.'+context['domain']
            value=old['value'].split(None,1)[-1] if old['type']=='MX' else old['value']
            matches=[r for r in records if r['name']==name and r['type']==old['type'] and r['content'].rstrip('.')==value.rstrip('.')]
            if len(matches)!=1:raise kf_ai.AIError('服务商记录与本机参考不一致，请在运营助手读取真实记录后操作')
            item=automation_store().prepare_builtin(self.user,{'slug':context['slug'],'tool':'dns.change','arguments':{'operation':'delete','record_id':matches[0]['id']}})
            return self._send(202,{'action':item,'message':'请预览并确认 DNS 删除'})
        except (ValueError,TypeError) as exc:return self._send(400,{'error':str(exc) if isinstance(exc,kf_ai.AIError) else 'DNS 记录格式无效'})

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

    @draft_operation
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

    def _render_check(self,*args,**kwargs):
        return render_check(*args,**kwargs)

    @draft_operation
    def _publish(self,body):
        try:code,data=publish_site(body,self._render_check)
        except kf_ai.AIError as exc:return self._send(409,{'error':str(exc)})
        return self._send(code,data)

    @draft_operation
    def _design_save(self, body):
        slug = str(body.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug) or not (SITES / slug).exists():
            return self._send(400, {"error": "站点不存在"})
        try:
            tokens = sanitize_design(body)
        except kf_ai.AIError as exc:
            return self._send(400, {"error": str(exc)})
        before = _read(SITES / slug / "design.json", {})
        ok = apply_design(slug, tokens)
        if ok:
            # A later manual design edit supersedes an AI style snapshot.
            for path in (spec_path(slug), draft_path(slug)):
                spec = _read(path, {})
                if "design" in spec:
                    spec["design"] = tokens
                    kf_ai.atomic_json(path, spec)
        audit(getattr(self, "user", "-"), "design_save", slug,
              diff_summary((before or {}).get("palette", {}), (tokens or {}).get("palette", {})))
        return self._send(200 if ok else 500,
                          {"ok": ok, "tokens": tokens,
                           "error": "" if ok else "同步到 WordPress 失败，设计未保存"})

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

    ai_store()  # Mark interrupted jobs only when starting the HTTP server.

    def serve_https():
        import ssl
        cert = CONSOLE / "tls" / "cert.pem"
        key = CONSOLE / "tls" / "key.pem"
        if not cert.exists():
            return
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert), str(key))
            s = ThreadingHTTPServer((BIND, HTTPS_PORT), Handler)
            s.socket = ctx.wrap_socket(s.socket, server_side=True)
            print("HTTPS on %s:%d" % (BIND, HTTPS_PORT), flush=True)
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
    automation_store()
    workflow_store()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"KampongFlow console v2 on {BIND}:{PORT}", flush=True)
    srv.serve_forever()
