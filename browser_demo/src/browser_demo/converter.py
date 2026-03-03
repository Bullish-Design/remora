"""HTML-to-markdown conversion with optional CSS selector filtering."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import markdownify


# Tags that add no value in markdown output
_STRIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "canvas", "video", "audio", "form", "button", "input"}

# Attributes to remove from all tags (reduce noise before conversion)
_STRIP_ATTRS = {"class", "id", "style", "data-*", "aria-*", "role", "onclick", "onload"}


def html_to_markdown(
    html: str,
    *,
    selector: str | None = None,
    strip_images: bool = False,
    heading_style: str = "ATX",
) -> str:
    """Convert HTML to clean markdown.

    Args:
        html: Raw HTML string.
        selector: Optional CSS selector to extract a specific subtree.
        strip_images: If True, remove all img tags before conversion.
        heading_style: "ATX" (# style) or "SETEXT" (underline style).

    Returns:
        Clean markdown string.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Apply CSS selector if provided
    if selector:
        selected = soup.select(selector)
        if selected:
            # Wrap selected elements in a new container
            new_soup = BeautifulSoup("", "html.parser")
            container = new_soup.new_tag("div")
            for el in selected:
                container.append(el.extract())
            soup = BeautifulSoup(str(container), "html.parser")
        # If selector matches nothing, fall through to full page

    # Strip unwanted elements
    _strip_noise(soup, strip_images=strip_images)

    # Convert to markdown
    md = markdownify(str(soup), heading_style=heading_style, strip=["img"] if strip_images else None)

    # Clean up the output
    md = _clean_markdown(md)

    return md


def extract_title(html: str) -> str:
    """Extract the page title from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # Try <title> tag first
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    # Try first <h1>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    # Try og:title meta
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and isinstance(og, Tag) and og.get("content"):
        return str(og["content"]).strip()
    return ""


def _strip_noise(soup: BeautifulSoup, *, strip_images: bool = False) -> None:
    """Remove noisy elements from the soup in-place."""
    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove unwanted tags
    tags_to_strip = _STRIP_TAGS.copy()
    if strip_images:
        tags_to_strip.add("img")

    for tag_name in tags_to_strip:
        for el in soup.find_all(tag_name):
            el.decompose()

    # Remove nav, footer, header, aside (common chrome)
    for tag_name in ("nav", "footer", "aside"):
        for el in soup.find_all(tag_name):
            el.decompose()

    # Strip data-* and aria-* attributes from all tags
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        attrs_to_remove = []
        for attr in list(tag.attrs.keys()):
            if attr.startswith("data-") or attr.startswith("aria-") or attr in {"class", "id", "style", "role"}:
                attrs_to_remove.append(attr)
        for attr in attrs_to_remove:
            del tag[attr]


def _clean_markdown(md: str) -> str:
    """Post-process markdown to clean up common issues."""
    # Remove trailing whitespace from each line first (before blank line collapsing)
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    # Collapse 3+ consecutive newlines into 2 (one blank line)
    md = re.sub(r"\n{3,}", "\n\n", md)
    # Ensure single newline at end
    md = md.strip() + "\n"
    return md
