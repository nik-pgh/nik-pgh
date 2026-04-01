#!/usr/bin/env python3
"""Fetch blog posts from nik-posts and generate card-style HTML for README."""

import re
import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


BLOG_URL = "https://nik-pgh.github.io/nik-posts/posts"
BASE_URL = "https://nik-pgh.github.io"
PLACEHOLDER_IMG = "https://raw.githubusercontent.com/nik-pgh/nik-pgh/main/assets/blog-placeholder.avif"
README_PATH = Path(__file__).resolve().parents[2] / "README.md"
START_MARKER = "<!-- BLOG-POST-LIST:START -->"
END_MARKER = "<!-- BLOG-POST-LIST:END -->"
MAX_POSTS = 6
THUMB_WIDTH = 250
THUMB_HEIGHT = 140


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
        self._in_excerpt = False
        self._capture = ""
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")

        # Detect timeline-post wrapper
        if "timeline-post" in classes:
            self._in_post = True
            self._current = {}

        if not self._in_post:
            return

        # Thumbnail image
        if "post-thumbnail" in classes:
            self._in_thumbnail = True

        if self._in_thumbnail and tag == "img":
            src = attrs_dict.get("src", "")
            if src:
                self._current["image"] = src

        # Title link inside post-info h4
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

        if tag == "p" and ("post-excerpt" in classes or "post-summary" in classes):
            self._in_excerpt = True
            self._capture = ""

    def handle_endtag(self, tag):
        if self._in_thumbnail and tag == "div":
            self._in_thumbnail = False

        if self._in_title_link and tag == "a":
            self._current["title"] = self._capture.strip()
            self._in_title_link = False

        if self._in_date and tag == "span":
            raw = self._capture.strip()
            # Strip "Published: " prefix if present
            self._current["date"] = raw.replace("Published: ", "")
            self._in_date = False

        if self._in_read_time and tag == "span":
            self._current["read_time"] = self._capture.strip()
            self._in_read_time = False

        if self._in_excerpt and tag == "p":
            self._current["excerpt"] = self._capture.strip()
            self._in_excerpt = False

        # End of a timeline-post article
        if self._in_post and tag == "article" and "title" in self._current:
            self.posts.append(self._current)
            self._current = {}
            self._in_post = False

    def handle_data(self, data):
        if self._in_title_link or self._in_date or self._in_read_time or self._in_excerpt:
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


def fetch_posts():
    """Fetch and parse blog posts from the /posts timeline page."""
    with _urlopen(BLOG_URL) as resp:
        html = resp.read().decode("utf-8")

    parser = BlogPostParser()
    parser.feed(html)
    return parser.posts[:MAX_POSTS]


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


def generate_cards(posts):
    """Generate HTML table cards for blog posts with optional thumbnails."""
    if not posts:
        return "No blog posts found."

    rows = []
    for i in range(0, len(posts), 2):
        cells = []
        for post in posts[i : i + 2]:
            title = post.get("title", "Untitled")
            url = post.get("url", "#")
            date = format_date(post.get("date", ""))
            read_time = post.get("read_time", "")
            image = post.get("image", "")

            meta_parts = [p for p in [date, read_time] if p]
            meta = " · ".join(meta_parts)

            img_src = image if image else PLACEHOLDER_IMG
            img_html = (
                f'  <a href="{url}">'
                f'<img src="{img_src}" width="{THUMB_WIDTH}" height="{THUMB_HEIGHT}"'
                f' style="object-fit:cover" alt="{title}"></a><br>\n'
            )

            cell = (
                f'<td align="left" width="50%">\n'
                f"{img_html}"
                f'  <a href="{url}"><strong>{title}</strong></a><br>\n'
                f"  <sub>{meta}</sub>\n"
                f"</td>"
            )

            cells.append(cell)

        if len(cells) == 1:
            cells.append('<td width="50%"></td>')

        row = "<tr>\n" + "\n".join(cells) + "\n</tr>"
        rows.append(row)

    return "<table>\n" + "\n".join(rows) + "\n</table>"


def update_readme(cards_html):
    """Replace content between markers in README."""
    readme = README_PATH.read_text(encoding="utf-8")

    pattern = re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER)
    replacement = START_MARKER + "\n" + cards_html + "\n" + END_MARKER
    new_readme = re.sub(pattern, replacement, readme, flags=re.DOTALL)

    if new_readme != readme:
        README_PATH.write_text(new_readme, encoding="utf-8")
        print("README.md updated with blog post cards.")
    else:
        print("No changes to README.md.")


def main():
    posts = fetch_posts()
    print(f"Found {len(posts)} blog posts:")
    for p in posts:
        img = "with image" if p.get("image") else "no image"
        print(f"  - {p.get('title')} ({img})")

    cards_html = generate_cards(posts)
    update_readme(cards_html)


if __name__ == "__main__":
    main()
