"""Pydantic models for web clips."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Self
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field


class ClipMetadata(BaseModel):
    """Metadata stored in YAML frontmatter of a clip file."""

    clip_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    url: str
    title: str = ""
    clipped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)
    selector: str | None = None
    content_hash: str = ""

    def compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content and store it."""
        self.content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self.content_hash


class ClipRecord(BaseModel):
    """A complete clip: metadata + markdown content."""

    metadata: ClipMetadata
    content: str

    @property
    def clip_id(self) -> str:
        return self.metadata.clip_id

    @property
    def url(self) -> str:
        return self.metadata.url

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def tags(self) -> list[str]:
        return self.metadata.tags

    def to_frontmatter_markdown(self) -> str:
        """Serialize to markdown with YAML frontmatter."""
        meta_dict = {
            "clip_id": self.metadata.clip_id,
            "url": self.metadata.url,
            "title": self.metadata.title,
            "clipped_at": self.metadata.clipped_at.isoformat(),
            "tags": self.metadata.tags,
            "selector": self.metadata.selector,
            "content_hash": self.metadata.content_hash,
        }
        frontmatter = yaml.dump(meta_dict, default_flow_style=False, sort_keys=False)
        return f"---\n{frontmatter}---\n\n{self.content}"

    @classmethod
    def from_frontmatter_markdown(cls, text: str) -> Self:
        """Parse a markdown file with YAML frontmatter into a ClipRecord."""
        match = re.match(r"^---\n(.*?)\n---\n\n?(.*)", text, re.DOTALL)
        if not match:
            raise ValueError("Invalid frontmatter format: missing --- delimiters")
        raw_meta = yaml.safe_load(match.group(1))
        content = match.group(2)
        metadata = ClipMetadata(
            clip_id=raw_meta.get("clip_id", ""),
            url=raw_meta.get("url", ""),
            title=raw_meta.get("title", ""),
            clipped_at=datetime.fromisoformat(raw_meta["clipped_at"])
            if raw_meta.get("clipped_at")
            else datetime.now(timezone.utc),
            tags=raw_meta.get("tags", []),
            selector=raw_meta.get("selector"),
            content_hash=raw_meta.get("content_hash", ""),
        )
        return cls(metadata=metadata, content=content)

    def filename(self) -> str:
        """Generate a filesystem-safe filename from the clip metadata."""
        date_str = self.metadata.clipped_at.strftime("%Y-%m-%d")
        # Slugify the title
        slug = re.sub(r"[^\w\s-]", "", self.metadata.title.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")
        if not slug:
            slug = self.metadata.clip_id
        # Truncate to reasonable length
        slug = slug[:80]
        return f"{date_str}_{slug}.md"


class FetchResult(BaseModel):
    """Result of a Playwright page fetch."""

    url: str
    final_url: str  # After redirects
    title: str
    html: str
    status_code: int = 200

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400
