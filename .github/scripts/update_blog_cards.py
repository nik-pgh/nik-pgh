#!/usr/bin/env python3
"""Fetch blog + YouTube content and render full-width two-column cards in README."""

import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html import escape
from html.parser import HTMLParser
from pathlib import Path


BLOG_URL = "https://nik-pgh.github.io/nik-posts/posts"
BASE_URL = "https://nik-pgh.github.io"
PLACEHOLDER_IMG = "https://raw.githubusercontent.com/nik-pgh/nik-pgh/main/assets/blog-placeholder.avif"

YOUTUBE_CHANNEL_ID = "UCXkXJZVNrzh4o8UatfVKb9g"
YOUTUBE_FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
YOUTUBE_THUMB_URL = "https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

README_PATH = Path(__file__).resolve().parents[2] / "README.md"
BLOG_START_MARKER = "<!-- BLOG-POST-LIST:START -->"
BLOG_END_MARKER = "<!-- BLOG-POST-LIST:END -->"
YT_START_MARKER = "<!-- BEGIN YOUTUBE-CARDS -->"
YT_END_MARKER = "<!-- END YOUTUBE-CARDS -->"
MAX_ITEMS = 6


class BlogPostParser(HTMLParser):
    """Parse the /posts timeline page to extract post data including thumbnails."""

    def __init__(self):
        super().__init__()
        self.posts = []
        self._current = {}
        self._in_post = False
        self._in_thumbnail = False
        self._in_title_link = False
        self._in_date = False
        self._in_read_time = False
        self._capture = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")

        if "timeline-post" in classes:
            self._in_post = True
            self._current = {}

        if not self._in_post:
            return

        if "post-thumbnail" in classes:
            self._in_thumbnail = True

        if self._in_thumbnail and tag == "img":
            src = attrs_dict.get("src", "")
            if src:
                if src.startswith("http"):
                    self._current["image"] = src
                else:
                    self._current["image"] = BASE_URL + src

        if tag == "a" and attrs_dict.get("href", "").endswith(".html"):
            self._in_title_link = True
            href = attrs_dict["href"]
            if not href.startswith("http"):
                href = BASE_URL + href
            self._current["url"] = href
            self._capture = ""

        if tag == "span" and "post-date" in classes:
            self._in_date = True
            self._capture = ""

        if tag == "span" and "read-time" in classes:
            self._in_read_time = True
            self._capture = ""

    def handle_endtag(self, tag):
        if self._in_thumbnail and tag == "div":
            self._in_thumbnail = False

        if self._in_title_link and tag == "a":
            self._current["title"] = self._capture.strip()
            self._in_title_link = False

        if self._in_date and tag == "span":
            raw = self._capture.strip()
            self._current["date"] = raw.replace("Published: ", "")
            self._in_date = False

        if self._in_read_time and tag == "span":
            self._current["read_time"] = self._capture.strip()
            self._in_read_time = False

        if self._in_post and tag == "article" and "title" in self._current:
            self.posts.append(self._current)
            self._current = {}
            self._in_post = False

    def handle_data(self, data):
        if self._in_title_link or self._in_date or self._in_read_time:
            self._capture += data


def _urlopen(url):
    """Open URL with SSL fallback for macOS."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, timeout=30)
    except urllib.error.URLError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=30, context=ctx)


def format_date(date_str):
    """Convert 2025-01-19 to Jan 19, 2025."""
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if not match:
        return date_str
    year, month, day = match.groups()
    return f"{months[int(month) - 1]} {int(day)}, {year}"


def fetch_blog_posts():
    """Fetch blog posts from nik-posts page."""
    with _urlopen(BLOG_URL) as resp:
        html = resp.read().decode("utf-8")

    parser = BlogPostParser()
    parser.feed(html)

    posts = []
    for post in parser.posts[:MAX_ITEMS]:
        date = format_date(post.get("date", ""))
        read_time = post.get("read_time", "")
        meta_parts = [p for p in [date, read_time] if p]
        posts.append(
            {
                "title": post.get("title", "Untitled"),
                "url": post.get("url", "#"),
                "image": post.get("image", PLACEHOLDER_IMG),
                "meta": " · ".join(meta_parts),
            }
        )

    return posts


def fetch_youtube_videos():
    """Fetch latest channel videos from YouTube Atom feed."""
    with _urlopen(YOUTUBE_FEED_URL) as resp:
        xml_text = resp.read().decode("utf-8")

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    root = ET.fromstring(xml_text)
    videos = []

    for entry in root.findall("atom:entry", ns)[:MAX_ITEMS]:
        title = (entry.findtext("atom:title", default="Untitled", namespaces=ns) or "").strip()
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()

        url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("rel") == "alternate":
                url = link.attrib.get("href", "")
                break

        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"

        videos.append(
            {
                "title": title,
                "url": url or "#",
                "image": YOUTUBE_THUMB_URL.format(video_id=video_id) if video_id else "",
                "meta": format_date(published[:10]),
            }
        )

    return videos


def _render_cell(item, align, width_pct):
    title = item.get("title", "Untitled")
    url = item.get("url", "#")
    image = item.get("image", "") or PLACEHOLDER_IMG
    meta = item.get("meta", "")

    safe_title = escape(title)
    safe_url = escape(url, quote=True)
    safe_image = escape(image, quote=True)
    safe_meta = escape(meta)

    return (
        f'<td align="{align}" width="{width_pct}%" valign="top">\n'
        f'  <a href="{safe_url}"><img src="{safe_image}" width="94%" style="width:94%;height:140px;object-fit:cover" alt="{safe_title}"></a><br>\n'
        f'  <a href="{safe_url}"><strong>{safe_title}</strong></a><br>\n'
        f"  <sub>{safe_meta}</sub>\n"
        f"</td>"
    )


def generate_cards(items, columns=3):
    """Generate full-width cards in a 3-column grid with edge alignment."""
    if not items:
        return "No items found."

    columns = max(1, columns)
    width_pct = round(100 / columns, 2)
    aligns = ["left", "center", "right"]

    rows = []
    for i in range(0, len(items), columns):
        chunk = items[i : i + columns]
        cells = []

        for col_idx in range(columns):
            if col_idx < len(chunk):
                align = aligns[col_idx] if col_idx < len(aligns) else "left"
                cells.append(_render_cell(chunk[col_idx], align, width_pct))
            else:
                align = aligns[col_idx] if col_idx < len(aligns) else "left"
                cells.append(f'<td align="{align}" width="{width_pct}%"></td>')

        rows.append("<tr>\n" + "\n".join(cells) + "\n</tr>")

    return '<table width="100%" cellspacing="0" cellpadding="0">\n' + "\n".join(rows) + "\n</table>"


def replace_section(readme, start_marker, end_marker, body):
    pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
    replacement = start_marker + "\n" + body + "\n" + end_marker
    return re.sub(pattern, replacement, readme, flags=re.DOTALL)


def update_readme(blog_cards_html, youtube_cards_html):
    """Replace content between markers in README."""
    readme = README_PATH.read_text(encoding="utf-8")

    readme = replace_section(readme, BLOG_START_MARKER, BLOG_END_MARKER, blog_cards_html)
    readme = replace_section(readme, YT_START_MARKER, YT_END_MARKER, youtube_cards_html)

    README_PATH.write_text(readme, encoding="utf-8")
    print("README.md updated with blog and YouTube cards.")


def main():
    posts = fetch_blog_posts()
    videos = fetch_youtube_videos()

    print(f"Found {len(posts)} blog posts.")
    print(f"Found {len(videos)} YouTube videos.")

    blog_cards_html = generate_cards(posts)
    youtube_cards_html = generate_cards(videos)
    update_readme(blog_cards_html, youtube_cards_html)


if __name__ == "__main__":
    main()
