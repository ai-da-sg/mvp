#!/usr/bin/env python3
"""kf_sections.py — 区块协议与渲染器。

页面 = 有序区块列表，每个区块是一个带 type 的 JSON 对象。
渲染器把区块翻译成 WordPress 区块标记（不需要页面构建器）。

支持的 type:
  hero / cards / split / stats / cta / band / gallery / quotes / table / list / rich
"""
import html
import json
import re
import sys
from pathlib import Path

REG = "docker.m.daocloud.io/library/wordpress:cli-php8.3"

# ---------------------------------------------------------------- 安全工具
def esc(v):
    """HTML 文本转义。所有来自结构化数据的字段都必须经过它。"""
    return html.escape("" if v is None else str(v), quote=True)


_SAFE_URL = re.compile(r"^(https?:|mailto:|tel:|/|\.|#)")

def safe_url(v):
    """只放行安全协议与相对路径，挡掉 javascript: / data: 等。"""
    u = str(v or "").strip()
    if not u:
        return "#"
    if _SAFE_URL.match(u):
        return esc(u)
    return "#"


# rich 块：允许 HTML，但剔除脚本、事件处理器与危险协议
_RICH_DROP = re.compile(r"<(script|style|iframe|object|embed|form|meta|link)\b.*?"
                        r"(</\1>|$)", re.I | re.S)
_RICH_ON = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|\'[^\']*\'|[^\s>]+)", re.I)
_RICH_JS = re.compile(r"(href|src|action)\s*=\s*(\"\'?)\s*(javascript|data|vbscript):[^\"\'>]*",
                      re.I)


def sanitize_rich(v):
    """rich 块允许 HTML，但必须净化掉脚本与事件处理器。"""
    t = str(v or "")
    t = _RICH_DROP.sub("", t)
    t = _RICH_ON.sub("", t)
    t = _RICH_JS.sub(r"\1=\"#\"", t)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    return t

# 渲染上下文：当前站点根目录（用于探测多尺寸变体）
_CTX = {"site": None}

_WIDTH_CACHE = {}


def _img_size(path):
    key = str(path)
    if key in _WIDTH_CACHE:
        return _WIDTH_CACHE[key]
    try:
        from PIL import Image
        with Image.open(path) as im:
            size = (im.width, im.height)
    except Exception:
        size = (0, 0)
    _WIDTH_CACHE[key] = size
    return size


def _img_width(path):
    return _img_size(path)[0]


SAFE_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,19}$")


def _safe_site_path(src):
    """把 src 解析成站点 html 目录内的真实路径，越界返回 None。"""
    site = _CTX.get("site")
    if not site:
        return None
    try:
        root = (Path(site) / "html").resolve()
        p = (root / str(src).lstrip("/")).resolve()
        if p != root and root not in p.parents:
            return None          # 目录穿越
        return p
    except Exception:
        return None


def _srcset(src):
    """根据磁盘上的变体生成 srcset，没有变体则返回空串。"""
    site = _CTX.get("site")
    if not site:
        return ""
    p = _safe_site_path(src)
    if p is None or not p.exists():
        return ""
    main_w = _img_width(p)
    if not main_w:
        return ""
    entries = []
    for q in sorted(p.parent.glob(p.stem + "-*" + p.suffix)):
        m = re.search(r"-(\d+)$", q.stem)
        if m:
            entries.append((int(m.group(1)), q.name))
    url_dir = src.rsplit("/", 1)[0]
    entries = [(w, f"{url_dir}/{n}") for w, n in entries]
    if not entries:
        return ""          # 没有变体就不输出 srcset
    entries.append((main_w, src))
    entries.sort()
    return ", ".join(f"{u} {w}w" for w, u in entries)


def img_tag(src, alt="", sizes="100vw", cls="", loading="lazy"):
    attrs = f'src="{esc(src)}" alt="{esc(alt)}" loading="{loading}"'
    if cls:
        attrs = f'class="{esc(cls)}" ' + attrs
    ss = _srcset(src)
    if ss:
        attrs += f' srcset="{ss}" sizes="{sizes}"'
    site = _CTX.get("site")
    if site:
        sp = _safe_site_path(src)
        if sp is not None:
            w, h = _img_size(sp)
            if w and h:
                attrs += f' width="{w}" height="{h}"'
    return f"<img {attrs}>"


# ---------------------------------------------------------------- 基础标记
def hx(level, text, cls=""):
    attr = {"level": level}
    if cls:
        attr["className"] = cls
    c = f' class="wp-block-heading {cls}"'.replace("  ", " ") if cls else ' class="wp-block-heading"'
    return (f'<!-- wp:heading {json.dumps(attr)} -->\n'
            f'<h{level}{c}>{esc(text)}</h{level}>\n<!-- /wp:heading -->\n')


def pp(text, cls=""):
    attr = json.dumps({"className": cls}) if cls else "{}"
    c = f' class="{cls}"' if cls else ""
    return f'<!-- wp:paragraph {attr} -->\n<p{c}>{esc(text)}</p>\n<!-- /wp:paragraph -->\n'


def grp(cls, inner):
    return (f'<!-- wp:group {json.dumps({"className": cls})} -->\n'
            f'<div class="wp-block-group {cls}">\n{inner}</div>\n<!-- /wp:group -->\n')


def btn(label, url):
    return ('<!-- wp:buttons -->\n<div class="wp-block-buttons">'
            '<!-- wp:button -->\n<div class="wp-block-button">'
            f'<a class="wp-block-button__link wp-element-button" href="{safe_url(url)}">'
            f'{esc(label)}</a>'
            '</div>\n<!-- /wp:button --></div>\n<!-- /wp:buttons -->\n')


def ul(items, cls="kf-list"):
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return f'<!-- wp:list {json.dumps({"className": cls})} -->\n<ul class="wp-block-list {cls}">{lis}</ul>\n<!-- /wp:list -->\n'


def raw(html):
    return f"<!-- wp:html -->\n{html}\n<!-- /wp:html -->\n"


def section(cls, inner):
    return grp(f"kf-section {cls}".strip(), grp("kf-container", inner))


# ---------------------------------------------------------------- 区块渲染
def r_hero(s):
    body = pp(s["kicker"], "kf-kicker") + hx(1, s["title"]) + pp(s.get("text", ""))
    if s.get("cta"):
        body += btn(s["cta"]["label"], s["cta"].get("href", "/contact/"))
    if s.get("badges"):
        spans = "".join(f'<span class="kf-badge">{esc(b)}</span>' for b in s["badges"])
        body += raw(f'<div class="kf-badges">{spans}</div>')
    copy = grp("kf-hero-copy", body)
    if s.get("art"):
        art = ('<div class="kf-art"><div class="blob b1"></div><div class="blob b2"></div>'
               '<div class="ring"></div><div class="gem g1"></div><div class="gem g2"></div>'
               '<div class="gem g3"></div></div>')
        return grp("kf-hero", grp("kf-container", grp("kf-hero-grid", copy + raw(art))))
    return grp("kf-hero", grp("kf-container", copy))


def r_cards(s):
    items = ""
    for i, it in enumerate(s["items"], 1):
        items += grp("kf-card gem" if s.get("accent") else "kf-card",
                     f'<p class="kf-num">{i}</p>\n' + hx(3, it["title"]) + pp(it.get("text", "")))
    head = ""
    if s.get("eyebrow") or s.get("title"):
        head = pp(s.get("eyebrow", ""), "kf-eyebrow") + hx(2, s.get("title", ""))
    if s.get("lead"):
        head += pp(s["lead"], "kf-lead")
    if s.get("center"):
        head = grp("kf-center", head)
    return section(s.get("bg", ""), head + grp("kf-grid", items))


def r_split(s):
    left = ""
    if s.get("eyebrow"):
        left += pp(s["eyebrow"], "kf-eyebrow")
    left += hx(2, s.get("title", "")) + pp(s.get("text", ""))
    if s.get("cta"):
        left += btn(s["cta"]["label"], s["cta"].get("href", "/contact/"))
    right = grp("kf-panel", ul(s.get("items", []))) if s.get("items") else ""
    if s.get("image"):
        right = raw(img_tag(s["image"], s.get("alt", ""), "(max-width:900px) 100vw, 50vw", "kf-split-img"))
    return section(s.get("bg", ""), grp("kf-split", left + right))


def r_stats(s):
    cells = "".join(grp("kf-stat", f'<p><b>{esc(v)}</b></p>' + pp(l)) for v, l in
                    [(i["value"], i["label"]) for i in s["items"]])
    return section("tight " + s.get("bg", ""), grp("kf-stats", cells))


def r_cta(s):
    inner = grp("kf-cta", hx(2, s["title"]) + pp(s.get("text", "")) +
                (btn(s["button"], s.get("href", "/contact/")) if s.get("button") else ""))
    return section("tight", inner)


def r_band(s):
    return section("tight", raw(
        f'<div class="kf-band">{img_tag(s["src"], s.get("alt", ""), "100vw")}'
        f'<div class="kf-band-cap">{esc(s.get("caption", ""))}</div></div>'))


def r_gallery(s):
    cells = "".join(
        f'<div class="kf-shot">{img_tag(i["src"], i["label"], "(max-width:820px) 100vw, 33vw")}'
        f'<span>{esc(i["label"])}</span></div>' for i in s["items"])
    body = raw(f'<div class="kf-gallery">{cells}</div>')
    if s.get("note"):
        body += pp(s["note"], "kf-note")
    head = (pp(s.get("eyebrow", ""), "kf-eyebrow") + hx(2, s.get("title", ""))) if s.get("title") else ""
    return section(s.get("bg", ""), head + body)


def r_quotes(s):
    def one(q):
        av = raw(f'<div class="kf-avatar">{esc(q.get("initial", "•"))}</div>') if q.get("initial") else ""
        return grp("kf-quote", av + pp(f"\u201c{q['text']}\u201d") +
                   (pp(f"\u2014 {q['by']}", "kf-by") if q.get("by") else ""))

    head = pp(s.get("eyebrow", ""), "kf-eyebrow") + hx(2, s.get("title", ""))
    if s.get("lead"):
        head += pp(s["lead"], "kf-lead")
    items = s["items"]
    if s.get("grid") and len(items) >= 2:
        body = grp("kf-quote-grid", "".join(one(q) for q in items))
    else:
        body = "".join(one(q) for q in items)
    return section(s.get("bg", "alt"), head + body)


def r_table(s):
    th = "".join(f"<th>{esc(h)}</th>" for h in s["headers"])
    tr = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in s["rows"])
    body = raw(f'<table class="kf-table"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>')
    if s.get("note"):
        body += pp(s["note"], "kf-note")
    head = pp(s.get("eyebrow", ""), "kf-eyebrow") + hx(2, s.get("title", ""))
    if s.get("lead"):
        head += pp(s["lead"], "kf-lead")
    return section(s.get("bg", "alt"), head + body)


def r_list(s):
    head = pp(s.get("eyebrow", ""), "kf-eyebrow") + hx(2, s.get("title", ""))
    if s.get("lead"):
        head += pp(s["lead"], "kf-lead")
    return section(s.get("bg", ""), head + ul(s["items"]))


def r_form(s):
    head = ""
    if s.get("eyebrow"):
        head += pp(s["eyebrow"], "kf-eyebrow")
    if s.get("title"):
        head += hx(2, s["title"])
    if s.get("lead"):
        head += pp(s["lead"], "kf-lead")
    block = ('<!-- wp:shortcode -->\n[kf_contact_form submit="%s"]\n<!-- /wp:shortcode -->\n'
             % esc(s.get("submit") or "Send message"))
    return section(s.get("bg", ""), head + block)


def r_rich(s):
    # rich 块允许 HTML，但必须净化掉脚本与事件处理器
    return section(s.get("bg", ""), raw(sanitize_rich(s["html"])))


RENDERERS = {
    "hero": r_hero, "cards": r_cards, "split": r_split, "stats": r_stats,
    "cta": r_cta, "band": r_band, "gallery": r_gallery, "quotes": r_quotes,
    "table": r_table, "list": r_list, "rich": r_rich, "form": r_form,
}

BLOCK_TYPES = list(RENDERERS)


def render_sections(sections, site=None):
    _CTX["site"] = site
    out = []
    for s in sections:
        fn = RENDERERS.get(s.get("type"))
        if not fn:
            continue
        try:
            out.append(fn(s))
        except KeyError as e:
            out.append(pp(f"[区块缺少字段: {e}]", "kf-note"))
    return "".join(out)






# ---------------------------------------------------------------- 表单 schema
BG = {"k": "bg", "label": "背景", "type": "select",
      "options": [["", "默认"], ["alt", "浅色交替"], ["tight", "紧凑"]]}

SCHEMAS = {
    "hero": {"label": "首屏", "fields": [
        {"k": "kicker", "label": "顶部小字", "type": "text"},
        {"k": "title", "label": "主标题", "type": "text"},
        {"k": "text", "label": "说明文字", "type": "textarea"},
        {"k": "cta", "label": "按钮", "type": "cta"},
        {"k": "badges", "label": "标签胶囊", "type": "strings"},
        {"k": "art", "label": "显示宝石插画", "type": "bool"},
    ]},
    "cards": {"label": "卡片网格", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "lead", "label": "引导文字", "type": "textarea"},
        {"k": "items", "label": "卡片", "type": "items",
         "itemFields": [{"k": "title", "label": "标题", "type": "text"},
                        {"k": "text", "label": "说明", "type": "textarea"}]},
        {"k": "center", "label": "标题居中", "type": "bool"},
        {"k": "accent", "label": "品牌色顶条", "type": "bool"},
        BG,
    ]},
    "split": {"label": "左右分栏", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "text", "label": "正文", "type": "textarea"},
        {"k": "items", "label": "右侧要点", "type": "strings"},
        {"k": "cta", "label": "按钮", "type": "cta"},
        {"k": "image", "label": "改用图片（留空则显示要点）", "type": "image"},
        BG,
    ]},
    "stats": {"label": "数字条", "fields": [
        {"k": "items", "label": "数字", "type": "items",
         "itemFields": [{"k": "value", "label": "数值", "type": "text"},
                        {"k": "label", "label": "说明", "type": "text"}]},
        BG,
    ]},
    "cta": {"label": "行动区", "fields": [
        {"k": "title", "label": "标题", "type": "text"},
        {"k": "text", "label": "说明", "type": "textarea"},
        {"k": "button", "label": "按钮文字", "type": "text"},
        {"k": "href", "label": "按钮链接", "type": "text"},
    ]},
    "band": {"label": "整幅照片", "fields": [
        {"k": "src", "label": "图片地址", "type": "image"},
        {"k": "caption", "label": "图片说明", "type": "text"},
        {"k": "alt", "label": "替代文字（无障碍）", "type": "text"},
    ]},
    "gallery": {"label": "图片网格", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "items", "label": "图片", "type": "items",
         "itemFields": [{"k": "label", "label": "说明", "type": "text"},
                        {"k": "src", "label": "图片地址", "type": "image"}]},
        {"k": "note", "label": "底部备注", "type": "text"},
        BG,
    ]},
    "quotes": {"label": "评价", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "lead", "label": "引导文字", "type": "text"},
        {"k": "grid", "label": "三列网格", "type": "bool"},
        {"k": "items", "label": "评价条目", "type": "items",
         "itemFields": [{"k": "text", "label": "内容", "type": "textarea"},
                        {"k": "by", "label": "署名", "type": "text"},
                        {"k": "initial", "label": "头像字母", "type": "text"}]},
        BG,
    ]},
    "table": {"label": "表格", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "lead", "label": "引导文字", "type": "text"},
        {"k": "table", "label": "表格内容", "type": "table"},
        {"k": "note", "label": "底部备注", "type": "text"},
        BG,
    ]},
    "list": {"label": "要点列表", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "lead", "label": "引导文字", "type": "textarea"},
        {"k": "items", "label": "要点", "type": "strings"},
        BG,
    ]},
    "form": {"label": "联系表单", "fields": [
        {"k": "eyebrow", "label": "小标题", "type": "text"},
        {"k": "title", "label": "大标题", "type": "text"},
        {"k": "lead", "label": "引导文字", "type": "text"},
        {"k": "submit", "label": "按钮文字", "type": "text"},
        BG,
    ]},
    "rich": {"label": "自定义 HTML", "fields": [
        {"k": "html", "label": "HTML 内容", "type": "html"},
        BG,
    ]},
}

# ---------------------------------------------------------------- 校验与安全写入
MIN_HTML = 400          # 渲染结果低于这个长度视为异常
KEEP_RATIO = 0.6        # 写入后长度不得低于写入前这个比例


def validate_sections(sections):
    """结构校验：类型必须已知、必填字段不能全空。"""
    errs = []
    if not isinstance(sections, list) or not sections:
        return ["区块列表为空"]
    for i, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            errs.append(f"第 {i} 块不是对象")
            continue
        t = sec.get("type")
        if t not in RENDERERS:
            errs.append(f"第 {i} 块类型未知：{t}")
            continue
        need = {
            "hero": ["title"], "cards": ["items"], "table": ["headers", "rows"],
            "quotes": ["items"], "gallery": ["items"], "band": ["src"],
            "list": ["items"], "cta": ["title"], "split": ["title"], "rich": ["html"],
        }.get(t, [])
        for f in need:
            if not sec.get(f):
                errs.append(f"第 {i} 块（{t}）缺少 {f}")
    return errs


def page_id(site, slug):
    r = wp(site, "post", "list", "--post_type=page", "--name=" + slug, "--field=ID", "--format=ids")
    ids = [x for x in r.stdout.split() if x.isdigit()]
    return ids[0] if ids else None


def get_content(site, pid):
    """wp-cli 的 --field 输出会多一个结尾换行，去掉它，保证快照与原文一致。"""
    r = wp(site, "post", "get", str(pid), "--field=post_content")
    out = r.stdout
    return out[:-1] if out.endswith("\n") else out


def backup(site, slug, sections, content_meta=None):
    import time
    # slug 会进文件路径和 glob 模式，必须先做白名单校验
    if not SAFE_SLUG.match(str(slug or "")):
        raise ValueError("非法 slug：%r" % slug)
    d = Path(site) / ".backups"
    d.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    f = d / f"{slug}-{stamp}.json"
    f.write_text(json.dumps({"slug": slug, "saved_at": stamp,
                             "sections": sections, **(content_meta or {})},
                            ensure_ascii=False, indent=1))
    # 每页只保留最近 40 份，避免长期堆积
    olds = sorted(d.glob(f"{slug}-*.json"))
    for old in olds[:-40]:
        try:
            old.unlink()
        except OSError:
            pass
    return f


def save_page(site, slug, sections, title=None, spec_all=None, write=True):
    """校验 → 快照 → 写入 → 回读校验 → 失败则回滚。返回结果字典。"""
    errs = validate_sections(sections)
    if errs:
        return {"ok": False, "stage": "validate", "rolled_back": False, "errors": errs}

    html = render_sections(sections, site=site)
    if len(html) < MIN_HTML:
        return {"ok": False, "stage": "render", "rolled_back": False,
                "errors": [f"渲染结果过短（{len(html)} 字符），疑似内容异常"]}

    if not write:
        return {"ok": True, "stage": "dry-run", "rolled_back": False, "errors": [],
                "length": len(html), "sections": len(sections)}

    pid = page_id(site, slug)
    if not pid:
        return {"ok": False, "stage": "lookup", "rolled_back": False,
                "errors": ["找不到对应页面"]}

    before = get_content(site, pid)
    backup(site, slug, sections, {"post_id": pid, "content_before": before})

    args = ["post", "update", pid, "-"]
    if title:
        args.append("--post_title=" + title)
    r = wp(site, *args, stdin=html)
    if r.returncode != 0:
        return {"ok": False, "stage": "write", "rolled_back": False,
                "errors": [(r.stderr or r.stdout).strip()[:300]]}

    after = get_content(site, pid)
    problems = []
    if len(after) < MIN_HTML:
        problems.append(f"写入后内容过短（{len(after)} 字符）")
    if len(after) < len(html) * KEEP_RATIO:
        problems.append(f"写入后内容缩水（{len(html)} → {len(after)}）")
    if "wp-block" not in after and "kf-" not in after:
        problems.append("写入后页面不含任何区块标记")

    if problems:
        wp(site, "post", "update", pid, "-", stdin=before)
        restored = get_content(site, pid)
        return {"ok": False, "stage": "verify", "rolled_back": True,
                "errors": problems,
                "restored": len(restored) == len(before),
                "length": len(after)}

    return {"ok": True, "stage": "done", "rolled_back": False, "errors": [],
            "length": len(after), "sections": len(sections)}

# ---------------------------------------------------------------- 命令行
def wp(site, *args, stdin=None):
    import subprocess
    cmd = ["docker", "run", "--rm", "-i",
           "--env-file", f"{site}/wp.env",
           "--network", f"kf-{Path(site).name}_default",
           "-v", f"{site}/html:/var/www/html",
           "--user", "33:33", REG, "wp", *args]
    return subprocess.run(cmd, capture_output=True, text=True, input=stdin)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--spec", default=None, help="site-spec.json 路径")
    ap.add_argument("--only", default=None, help="只渲染某一页 slug")
    ap.add_argument("--save", default=None, help="保存模式：传入页面 JSON 文件")
    ap.add_argument("--page-slug", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stdout-html", action="store_true")
    a = ap.parse_args()

    site = Path(a.site).resolve()

    # 页面 slug 会进文件路径与 glob 模式，必须白名单
    if a.page_slug and not SAFE_SLUG.match(a.page_slug):
        print("非法 page-slug: %r" % a.page_slug, file=sys.stderr)
        sys.exit(2)
    if a.only and not SAFE_SLUG.match(a.only):
        print("非法 only: %r" % a.only, file=sys.stderr)
        sys.exit(2)

    if a.save:
        payload = json.loads(Path(a.save).read_text())
        if a.stdout_html:
            print(render_sections(payload["sections"], site=str(site)))
            return
        res = save_page(str(site), a.page_slug, payload["sections"], payload.get("title"),
                        write=not a.dry_run)
        print(json.dumps(res, ensure_ascii=False))
        return

    spec_path = Path(a.spec) if a.spec else site / "site-spec.json"
    spec = json.loads(spec_path.read_text())

    for page in spec["pages"]:
        if a.only and page["slug"] != a.only:
            continue
        html = render_sections(page["sections"], site=str(site))
        r = wp(site, "post", "list", "--post_type=page", "--name=" + page["slug"],
               "--field=ID", "--format=ids")
        ids = [x for x in r.stdout.split() if x.isdigit()]
        if not ids:
            print(f"跳过 {page['slug']}：找不到页面")
            continue
        r2 = wp(site, "post", "update", ids[0], "-", "--post_title=" + page["title"], stdin=html)
        print(f"{page['slug']}: " + (r2.stdout.strip() or r2.stderr.strip()[:120]))


if __name__ == "__main__":
    main()
