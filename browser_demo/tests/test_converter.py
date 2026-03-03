"""Tests for browser_demo.converter."""

from __future__ import annotations

from browser_demo.converter import extract_title, html_to_markdown


class TestHtmlToMarkdown:
    def test_basic_conversion(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "# Welcome to the Test Page" in md
        assert "**first paragraph**" in md
        assert "*emphasis*" in md

    def test_lists_converted(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "Item one" in md
        assert "Item two" in md

    def test_code_blocks_preserved(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "hello" in md
        assert "print" in md

    def test_links_converted(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "[Example]" in md
        assert "https://example.com" in md

    def test_scripts_stripped(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "console.log" not in md

    def test_styles_stripped(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "color: red" not in md

    def test_nav_stripped(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        # Nav links should be removed
        assert "Home" not in md or "About" not in md

    def test_footer_stripped(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html)
        assert "Copyright" not in md

    def test_css_selector_extracts_subtree(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html, selector="article")
        assert "Welcome to the Test Page" in md
        # Should not have nav content
        assert "Home" not in md

    def test_css_selector_no_match_falls_through(self, sample_html: str) -> None:
        # If selector matches nothing, should still return content
        md = html_to_markdown(sample_html, selector=".nonexistent-class")
        assert len(md.strip()) > 0

    def test_strip_images(self, sample_html: str) -> None:
        md = html_to_markdown(sample_html, strip_images=True)
        assert "cat.jpg" not in md

    def test_empty_html(self) -> None:
        md = html_to_markdown("")
        # Should produce minimal output, not crash
        assert isinstance(md, str)

    def test_plain_text_passthrough(self) -> None:
        md = html_to_markdown("<p>Just plain text.</p>")
        assert "Just plain text." in md

    def test_nested_headings(self) -> None:
        html = "<h1>H1</h1><h2>H2</h2><h3>H3</h3>"
        md = html_to_markdown(html)
        assert "# H1" in md
        assert "## H2" in md
        assert "### H3" in md

    def test_consecutive_blank_lines_collapsed(self) -> None:
        html = "<p>One</p><br/><br/><br/><br/><br/><p>Two</p>"
        md = html_to_markdown(html)
        # Should not have 3+ consecutive newlines (i.e., no more than one blank line)
        assert "\n\n\n" not in md

    def test_trailing_whitespace_cleaned(self) -> None:
        html = "<p>Hello    </p>"
        md = html_to_markdown(html)
        for line in md.split("\n"):
            assert line == line.rstrip()


class TestExtractTitle:
    def test_title_from_title_tag(self, sample_html: str) -> None:
        assert extract_title(sample_html) == "Test Page Title"

    def test_title_from_h1(self) -> None:
        html = "<html><body><h1>My Heading</h1></body></html>"
        assert extract_title(html) == "My Heading"

    def test_title_from_og_meta(self) -> None:
        html = '<html><head><meta property="og:title" content="OG Title" /></head><body></body></html>'
        assert extract_title(html) == "OG Title"

    def test_empty_html_returns_empty(self) -> None:
        assert extract_title("") == ""

    def test_no_title_returns_empty(self) -> None:
        assert extract_title("<html><body><p>No title here</p></body></html>") == ""
