#!/usr/bin/env python3

import argparse
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def resolve_target_url(target):
    target = target.strip()
    if "b23.tv" in target or "/read/cv" in target:
        try:
            req = Request(target, headers=HEADERS)
            with urlopen(req, timeout=10) as resp:
                return resp.geturl()
        except Exception:
            pass
    return target


def parse_opus_id(target):
    target = resolve_target_url(target)
    m = re.search(r"(\d{12,})", target)
    if m:
        return m.group(1)
    m_cv = re.search(r"cv(\d+)", target, re.IGNORECASE)
    if m_cv:
        return m_cv.group(1)
    raise ValueError(f"Failed to extract dynamic or article ID from target: {target}")


def get_html(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_image_b64(url):
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url

    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=20) as resp:
            data = resp.read()
            mime = "image/jpeg"
            low = url.lower()
            if ".png" in low:
                mime = "image/png"
            elif ".webp" in low:
                mime = "image/webp"
            elif ".gif" in low:
                mime = "image/gif"
            return f"data:{mime};base64," + base64.b64encode(data).decode("utf-8")
    except Exception as e:
        print(f"[Warning] Failed to download image {url}: {e}", file=sys.stderr)
        return url


def render_text_nodes(nodes):
    parts = []
    for node in nodes:
        node_type = node.get("type")
        if node_type == "TEXT_NODE_TYPE_WORD" and node.get("word"):
            w = node["word"]
            text = html.escape(w.get("words", ""))
            style = w.get("style") or {}
            css_styles = []
            if w.get("color"):
                css_styles.append(f"color: {w.get('color')}")
            if style.get("background"):
                css_styles.append(f"background-color: {style.get('background')}")
            inner = text.replace("\n", "<br/>")
            if style.get("bold"):
                inner = f"<strong>{inner}</strong>"
            if style.get("italic"):
                inner = f"<em>{inner}</em>"
            if style.get("underline"):
                inner = f"<u>{inner}</u>"
            if style.get("strikethrough"):
                inner = f"<s>{inner}</s>"
            if css_styles:
                style_str = "; ".join(css_styles)
                inner = f'<span style="{style_str}">{inner}</span>'
            parts.append(inner)
        elif node.get("word"):
            parts.append(html.escape(node["word"].get("words", "")).replace("\n", "<br/>"))
        elif node.get("rich"):
            parts.append(html.escape(node["rich"].get("text", "")).replace("\n", "<br/>"))
    return "".join(parts)


def parse_opus_data(target, download_images=True):
    opus_id = parse_opus_id(target)
    url = f"https://www.bilibili.com/opus/{opus_id}"
    html_doc = get_html(url)

    idx = html_doc.find("__INITIAL_STATE__")
    if idx == -1:
        raise RuntimeError(f"Failed to locate __INITIAL_STATE__ in {url}")
    brace_idx = html_doc.find("{", idx)
    if brace_idx == -1:
        raise RuntimeError(f"Failed to parse JSON data from {url}")

    state, _ = json.JSONDecoder().raw_decode(html_doc, brace_idx)
    detail = state.get("detail", {})
    basic = detail.get("basic", {})

    title = ""
    author_name = ""
    author_face = ""
    pub_time = ""
    cover_url = ""
    paragraphs_html = []

    is_article = (basic.get("article_type") != 0 or basic.get("comment_type") == 12)
    type_label = "Article" if is_article else "Dynamic"

    modules = detail.get("modules", [])
    for mod in modules:
        if mod.get("module_title") and mod["module_title"].get("text"):
            title = mod["module_title"]["text"].strip()
        if mod.get("module_author"):
            author_name = mod["module_author"].get("name", "")
            author_face = mod["module_author"].get("face", "")
            pub_time = mod["module_author"].get("pub_time", "")
        if mod.get("module_top"):
            display = mod["module_top"].get("display", {}) or {}
            album = display.get("album", {}) or {}
            pics = album.get("pics", []) or []
            if pics:
                cover_url = pics[0].get("url", "")
        if mod.get("module_content"):
            paras = mod["module_content"].get("paragraphs", []) or []
            for p in paras:
                # 1. Text paragraph
                if p.get("text") and p["text"].get("nodes"):
                    rtext = render_text_nodes(p["text"]["nodes"])
                    if not rtext.strip() or rtext == "&nbsp;" or rtext == "\xa0":
                        paragraphs_html.append('<div class="empty-line"></div>')
                    elif p.get("heading"):
                        lvl = p["heading"].get("level", 2)
                        paragraphs_html.append(f'<h{lvl}>{rtext}</h{lvl}>')
                    elif p.get("blockquote"):
                        paragraphs_html.append(f'<blockquote>{rtext}</blockquote>')
                    else:
                        paragraphs_html.append(f'<p class="opus-p">{rtext}</p>')
                # 2. Picture
                elif p.get("pic") and p["pic"].get("pics"):
                    for pic_item in p["pic"]["pics"]:
                        p_url = pic_item.get("url", "")
                        if p_url:
                            img_src = fetch_image_b64(p_url) if download_images else p_url
                            caption = pic_item.get("comment", "")
                            cap_html = f'<div class="img-caption">{html.escape(caption)}</div>' if caption else ""
                            paragraphs_html.append(
                                f'<div class="img-box">'
                                f'<img src="{img_src}" class="content-img" />'
                                f'{cap_html}'
                                f'</div>'
                            )
                # 3. Divider line
                elif p.get("line"):
                    paragraphs_html.append('<hr class="opus-hr" />')
                # 4. Code block
                elif p.get("code"):
                    ccontent = html.escape(p["code"].get("content", ""))
                    paragraphs_html.append(f'<pre><code>{ccontent}</code></pre>')
                # 5. List
                elif p.get("list"):
                    items = p["list"].get("items", [])
                    is_ordered = p["list"].get("ordered", False)
                    tag = "ol" if is_ordered else "ul"
                    lis = [f'<li>{render_text_nodes(it.get("nodes", []))}</li>' for it in items]
                    paragraphs_html.append(f'<{tag}>{"".join(lis)}</{tag}>')

        # Fallback for dynamic content if module_content is missing
        if not paragraphs_html and mod.get("module_dynamic"):
            desc = mod["module_dynamic"].get("desc")
            if desc:
                text = desc.get("text", "") if isinstance(desc, dict) else str(desc)
                lines = [html.escape(l) for l in text.split("\n")]
                paragraphs_html.append(f'<p class="opus-p">{"<br/>".join(lines)}</p>')
            major = mod["module_dynamic"].get("major") or {}
            opus_pics = (major.get("opus") or {}).get("pics", []) or (major.get("draw") or {}).get("items", [])
            for pic_item in opus_pics:
                p_url = pic_item.get("url", "") or pic_item.get("src", "")
                if p_url:
                    img_src = fetch_image_b64(p_url) if download_images else p_url
                    paragraphs_html.append(f'<div class="img-box"><img src="{img_src}" class="content-img" /></div>')

    if not title:
        title = basic.get("title", f"{author_name}'s {type_label}")

    cover_b64 = fetch_image_b64(cover_url) if (cover_url and download_images) else cover_url
    avatar_b64 = fetch_image_b64(author_face) if (author_face and download_images) else author_face

    return {
        "id": opus_id,
        "url": url,
        "title": title,
        "type_label": type_label,
        "author_name": author_name,
        "pub_time": pub_time,
        "avatar_b64": avatar_b64,
        "cover_b64": cover_b64,
        "body_html": "\n".join(paragraphs_html),
    }


def build_full_html(doc):
    cover_tag = f'<div class="cover-box"><img src="{doc["cover_b64"]}" class="cover-img" /></div>' if doc["cover_b64"] else ""
    avatar_tag = f'<img src="{doc["avatar_b64"]}" class="author-avatar" />' if doc["avatar_b64"] else ""

    article_html = f"""
    <article class="opus-card">
        {cover_tag}
        <h1 class="opus-title">{html.escape(doc['title'])}</h1>
        <div class="author-bar">
            {avatar_tag}
            <div class="author-info">
                <div class="author-name">{html.escape(doc['author_name'])} <span class="badge">{doc['type_label']}</span></div>
                <div class="pub-meta">{html.escape(doc['pub_time'])} · <a href="{doc['url']}">{doc['url']}</a></div>
            </div>
        </div>
        <div class="opus-content">
            {doc['body_html']}
        </div>
    </article>
    """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(doc['title'])}</title>
<style>
@page {{
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
}}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: #18191c;
    line-height: 1.8;
    font-size: 15px;
    margin: 0;
    padding: 0;
}}
.opus-card {{
    margin-bottom: 30px;
}}
.cover-box {{
    width: 100%;
    margin-bottom: 20px;
    border-radius: 8px;
    overflow: hidden;
}}
.cover-img {{
    width: 100%;
    max-height: 380px;
    object-fit: cover;
    display: block;
}}
.opus-title {{
    font-size: 24px;
    font-weight: 700;
    line-height: 1.4;
    color: #18191c;
    margin: 0 0 16px 0;
}}
.author-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 16px;
    margin-bottom: 20px;
    border-bottom: 1px solid #e3e5e7;
}}
.author-avatar {{
    width: 44px;
    height: 44px;
    border-radius: 50%;
    object-fit: cover;
}}
.author-name {{
    font-size: 15px;
    font-weight: 600;
    color: #18191c;
}}
.badge {{
    font-size: 11px;
    font-weight: normal;
    color: #00aeec;
    background: #e5f7fd;
    padding: 2px 6px;
    border-radius: 4px;
    margin-left: 6px;
}}
.pub-meta {{
    font-size: 12px;
    color: #9499a0;
    margin-top: 2px;
}}
.pub-meta a {{
    color: #9499a0;
    text-decoration: none;
}}
.opus-content {{
    font-size: 15px;
    line-height: 1.85;
}}
.opus-p {{
    margin: 12px 0;
    word-break: break-word;
}}
.empty-line {{
    height: 12px;
}}
.img-box {{
    margin: 18px 0;
    text-align: center;
    page-break-inside: avoid;
}}
.content-img {{
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}
.img-caption {{
    font-size: 12px;
    color: #9499a0;
    margin-top: 6px;
}}
blockquote {{
    margin: 16px 0;
    padding: 10px 16px;
    background: #f6f7f8;
    border-left: 4px solid #00aeec;
    color: #61666d;
    border-radius: 0 4px 4px 0;
}}
hr.opus-hr {{
    border: none;
    border-top: 1px solid #e3e5e7;
    margin: 24px 0;
}}
pre {{
    background: #f6f7f8;
    padding: 12px;
    border-radius: 6px;
    font-family: monospace;
    overflow-x: auto;
}}
</style>
</head>
<body>
{article_html}
</body>
</html>"""


def find_chrome():
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ]
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path
    return None


def convert_html_to_pdf(html_path, output_pdf_path):
    chrome = find_chrome()
    if chrome:
        cmd = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output_pdf_path}",
            html_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(output_pdf_path):
            raise RuntimeError(f"Chrome PDF conversion failed (exit {res.returncode}): {res.stderr}")
        return

    # Fallback to weasyprint
    if shutil.which("weasyprint"):
        res = subprocess.run(["weasyprint", html_path, output_pdf_path], capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(output_pdf_path):
            raise RuntimeError(f"WeasyPrint PDF conversion failed: {res.stderr}")
        return

    if shutil.which("uvx"):
        res = subprocess.run(["uvx", "weasyprint", html_path, output_pdf_path], capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(output_pdf_path):
            raise RuntimeError(f"uvx weasyprint PDF conversion failed: {res.stderr}")
        return

    raise RuntimeError(
        "No suitable PDF engine found. Please install google-chrome, chromium, or weasyprint (supports uvx weasyprint)."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Bilibili dynamic or article (opus) content with images and export to a PDF file."
    )
    parser.add_argument(
        "target",
        help="Bilibili dynamic or article URL or ID (e.g. https://www.bilibili.com/opus/1234796522049110041)",
    )
    parser.add_argument(
        "output",
        help="Output PDF file path",
    )

    args = parser.parse_args()

    doc = parse_opus_data(args.target, download_images=True)
    full_html = build_full_html(doc)

    abs_output_path = os.path.abspath(args.output)
    output_dir = os.path.dirname(abs_output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    temp_html_fd, html_path = tempfile.mkstemp(suffix=".html", prefix="bili_opus_")
    with os.fdopen(temp_html_fd, "w", encoding="utf-8") as f:
        f.write(full_html)

    try:
        convert_html_to_pdf(html_path, abs_output_path)
    finally:
        if os.path.exists(html_path):
            try:
                os.remove(html_path)
            except OSError:
                pass

    file_size = os.path.getsize(abs_output_path)
    print(
        f"Success: exported [{doc['type_label']}] '{doc['title']}' to PDF ({file_size} bytes).\n"
        f"Output saved to: {abs_output_path}"
    )


if __name__ == "__main__":
    main()
