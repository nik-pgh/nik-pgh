#!/usr/bin/env python3
"""Generate stable local assets for dynamic README sections (blog + YouTube)."""

from __future__ import annotations

import base64
import datetime as dt
import mimetypes
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path


BLOG_URL = "https://nik-pgh.github.io/nik-posts/posts"
BLOG_BASE_URL = "https://nik-pgh.github.io"
YOUTUBE_CHANNEL_ID = "UCXkXJZVNrzh4o8UatfVKb9g"
YOUTUBE_FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"

ROOT = Path(__file__).resolve().parents[2]
README_PATH = ROOT / "README.md"
ASSET_DIR = ROOT / "assets" / "generated"
BLOG_ASSET_REL = "assets/generated/latest-posts.svg"
YT_ASSET_REL = "assets/generated/latest-videos.svg"

BLOG_START = "<!-- BLOG-POST-LIST:START -->"
BLOG_END = "<!-- BLOG-POST-LIST:END -->"
YT_START = "<!-- BEGIN YOUTUBE-CARDS -->"
YT_END = "<!-- END YOUTUBE-CARDS -->"

MAX_ITEMS = 6


@dataclass
class ContentItem:
    title: str
    url: str
    meta: str
    image_url: str
    image_data_uri: str | None = None


class BlogPostParser(HTMLParser):
    """Parses nik-posts timeline HTML into structured post entries."""

    def __init__(self):
        super().__init__()
        self.posts: list[dict[str, str]] = []
        self._in_post = False
        self._in_thumbnail = False
        self._in_title_link = False
        self._in_date = False
        self._in_read_time = False
        self._capture = ""
        self._current: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "") or ""

        if "timeline-post" in classes:
            self._in_post = True
            self._current = {}

        if not self._in_post:
            return

        if "post-thumbnail" in classes:
            self._in_thumbnail = True

        if self._in_thumbnail and tag == "img":
            src = attrs_dict.get("src") or ""
            if src:
                self._current["image"] = resolve_url(src, BLOG_BASE_URL)

        if tag == "a":
            href = attrs_dict.get("href") or ""
            if href.endswith(".html"):
                self._in_title_link = True
                self._current["url"] = resolve_url(href, BLOG_BASE_URL)
                self._capture = ""

        if tag == "span" and "post-date" in classes:
            self._in_date = True
            self._capture = ""

        if tag == "span" and "read-time" in classes:
            self._in_read_time = True
            self._capture = ""

    def handle_endtag(self, tag: str) -> None:
        if self._in_thumbnail and tag == "div":
            self._in_thumbnail = False

        if self._in_title_link and tag == "a":
            self._current["title"] = self._capture.strip()
            self._in_title_link = False

        if self._in_date and tag == "span":
            raw = self._capture.strip()
            self._current["date"] = raw.replace("Published:", "").strip()
            self._in_date = False

        if self._in_read_time and tag == "span":
            self._current["read_time"] = self._capture.strip()
            self._in_read_time = False

        if self._in_post and tag == "article" and self._current.get("title"):
            self.posts.append(self._current)
            self._current = {}
            self._in_post = False

    def handle_data(self, data: str) -> None:
        if self._in_title_link or self._in_date or self._in_read_time:
            self._capture += data


def resolve_url(url: str, base: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urllib.parse.urljoin(base + "/", url)


def open_url(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def format_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.strftime("%b %-d, %Y")
        except ValueError:
            continue
    return value


def parse_blog_posts(html: str, limit: int = MAX_ITEMS) -> list[ContentItem]:
    parser = BlogPostParser()
    parser.feed(html)

    items: list[ContentItem] = []
    for post in parser.posts[:limit]:
        date = format_date(post.get("date", ""))
        read_time = post.get("read_time", "")
        meta = " · ".join(x for x in (date, read_time) if x)
        items.append(
            ContentItem(
                title=post.get("title", "Untitled"),
                url=post.get("url", "#"),
                meta=meta,
                image_url=post.get("image", ""),
            )
        )
    return items


def parse_youtube_feed(feed_xml: str, limit: int = MAX_ITEMS) -> list[ContentItem]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    root = ET.fromstring(feed_xml)
    items: list[ContentItem] = []

    for entry in root.findall("atom:entry", ns)[:limit]:
        title = (entry.findtext("atom:title", default="Untitled", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        meta = format_date(published)

        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        link_url = ""
        for link in entry.findall("atom:link", ns):
            if (link.attrib.get("rel") or "") == "alternate":
                link_url = link.attrib.get("href", "")
                break
        if not link_url and video_id:
            link_url = f"https://www.youtube.com/watch?v={video_id}"

        thumb_el = entry.find("media:group/media:thumbnail", ns)
        image_url = ""
        if thumb_el is not None:
            image_url = thumb_el.attrib.get("url", "")
        if not image_url and video_id:
            image_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

        items.append(
            ContentItem(
                title=title,
                url=link_url or "#",
                meta=meta,
                image_url=image_url,
            )
        )

    return items


def fetch_image_data_uri(url: str) -> str | None:
    if not url:
        return None
    try:
        with open_url(url, timeout=20) as resp:
            data = resp.read()
            content_type = resp.headers.get_content_type() or ""
    except Exception:
        return None

    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(url)
        content_type = guessed or "image/jpeg"

    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def split_lines(text: str, max_chars: int = 36, max_lines: int = 2) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(".") + "…"

    return lines


def render_section_svg(
    output_path: Path,
    heading: str,
    subheading: str,
    items: list[ContentItem],
    accent: str,
    background: str,
    card_tint: str,
) -> None:
    width, height = 960, 720
    pad = 24
    gap = 20
    header_y = 120
    cols = 2

    render_items = items[:MAX_ITEMS]
    rows = max(1, (len(render_items) + cols - 1) // cols)
    available_h = height - header_y - pad
    card_h = int((available_h - gap * (rows - 1)) / rows)
    card_w = int((width - pad * 2 - gap) / 2)
    image_h = max(88, int(card_h * 0.58))

    svg: list[str] = []
    svg.append('<?xml version="1.0" encoding="UTF-8"?>')
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    svg.append("<defs>")
    svg.append(
        "<style>"
        "text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Helvetica, Arial, sans-serif; }"
        ".title { font-size: 36px; font-weight: 700; fill: #f8fafc; }"
        ".subtitle { font-size: 16px; fill: #cbd5e1; }"
        ".card-title { font-size: 17px; font-weight: 650; fill: #f8fafc; }"
        ".card-meta { font-size: 13px; fill: #94a3b8; }"
        ".ph { font-size: 16px; font-weight: 600; fill: #e2e8f0; }"
        "</style>"
    )
    svg.append("</defs>")

    svg.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{background}" />')
    svg.append(f'<rect x="{pad}" y="{pad}" width="76" height="6" rx="3" fill="{accent}" />')
    svg.append(f'<text class="title" x="{pad}" y="74">{escape(heading)}</text>')
    svg.append(f'<text class="subtitle" x="{pad}" y="102">{escape(subheading)}</text>')

    if not render_items:
        svg.append(f'<rect x="{pad}" y="{header_y}" width="{width - pad*2}" height="{height - header_y - pad}" rx="16" fill="{card_tint}" />')
        svg.append(f'<text class="ph" x="{width//2}" y="{height//2}" text-anchor="middle">No recent items found</text>')
    else:
        for idx, item in enumerate(render_items):
            row = idx // cols
            col = idx % cols
            x = pad + col * (card_w + gap)
            y = header_y + row * (card_h + gap)
            clip_id = f"clip-{idx}"

            svg.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="14" fill="{card_tint}" />')
            svg.append(f'<clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="{card_w}" height="{image_h}" rx="14" /></clipPath>')

            if item.image_data_uri:
                svg.append(
                    f'<image href="{item.image_data_uri}" x="{x}" y="{y}" width="{card_w}" height="{image_h}" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{clip_id})" />'
                )
            else:
                svg.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{image_h}" rx="14" fill="#334155" />')
                svg.append(
                    f'<text class="ph" x="{x + card_w/2}" y="{y + image_h/2 + 6}" text-anchor="middle">No preview</text>'
                )

            text_y = y + image_h + 28
            for line_idx, line in enumerate(split_lines(item.title, max_chars=38, max_lines=2)):
                svg.append(
                    f'<text class="card-title" x="{x + 16}" y="{text_y + line_idx * 22}">{escape(line)}</text>'
                )

            meta_y = y + card_h - 16
            svg.append(f'<text class="card-meta" x="{x + 16}" y="{meta_y}">{escape(item.meta)}</text>')

    svg.append("</svg>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def build_section_markup(asset_path: str, asset_alt: str, asset_link: str, items: list[ContentItem]) -> str:
    lines = [
        f"[![{asset_alt}]({asset_path})]({asset_link})",
        "",
    ]

    if items:
        for item in items[:4]:
            title = item.title.replace("[", "").replace("]", "")
            meta = f" · {item.meta}" if item.meta else ""
            lines.append(f"- [{title}]({item.url}){meta}")
    else:
        lines.append("- No recent items found")

    return "\n".join(lines)


def replace_section(readme: str, start_marker: str, end_marker: str, body: str) -> str:
    pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
    replacement = f"{start_marker}\n{body}\n{end_marker}"
    return re.sub(pattern, replacement, readme, flags=re.DOTALL)


def update_readme(blog_items: list[ContentItem], video_items: list[ContentItem]) -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    blog_markup = build_section_markup(
        asset_path=BLOG_ASSET_REL,
        asset_alt="Latest blog posts snapshot",
        asset_link=BLOG_URL,
        items=blog_items,
    )
    yt_markup = build_section_markup(
        asset_path=YT_ASSET_REL,
        asset_alt="Latest YouTube videos snapshot",
        asset_link=f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}/videos",
        items=video_items,
    )

    readme = replace_section(readme, BLOG_START, BLOG_END, blog_markup)
    readme = replace_section(readme, YT_START, YT_END, yt_markup)

    README_PATH.write_text(readme, encoding="utf-8")


def hydrate_images(items: list[ContentItem]) -> None:
    for item in items:
        item.image_data_uri = fetch_image_data_uri(item.image_url)


def main() -> None:
    try:
        with open_url(BLOG_URL) as resp:
            blog_html = resp.read().decode("utf-8", errors="replace")
        blog_items = parse_blog_posts(blog_html, limit=MAX_ITEMS)
    except Exception as exc:
        print(f"[warn] blog fetch failed: {exc}")
        blog_items = []

    try:
        with open_url(YOUTUBE_FEED_URL) as resp:
            feed_xml = resp.read().decode("utf-8", errors="replace")
        video_items = parse_youtube_feed(feed_xml, limit=MAX_ITEMS)
    except Exception as exc:
        print(f"[warn] youtube fetch failed: {exc}")
        video_items = []

    hydrate_images(blog_items)
    hydrate_images(video_items)

    render_section_svg(
        output_path=ASSET_DIR / "latest-posts.svg",
        heading="Latest Blog Posts",
        subheading="Fresh writing, auto-rendered as a stable local asset.",
        items=blog_items,
        accent="#f97316",
        background="#0b1120",
        card_tint="#162033",
    )

    render_section_svg(
        output_path=ASSET_DIR / "latest-videos.svg",
        heading="Latest YouTube Videos",
        subheading="Recent uploads, generated daily for consistent GitHub rendering.",
        items=video_items,
        accent="#ef4444",
        background="#0b1120",
        card_tint="#1f1f3a",
    )

    update_readme(blog_items, video_items)

    print(f"Generated {BLOG_ASSET_REL} and {YT_ASSET_REL}")
    print(f"Blog items: {len(blog_items)} | YouTube items: {len(video_items)}")


if __name__ == "__main__":
    main()
