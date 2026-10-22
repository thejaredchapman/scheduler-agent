"""Text colours meet WCAG AA (4.5:1) against the page background in both themes."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "web" / "styles.css").read_text()


def block(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"styles.css needs a {selector} block"
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", match.group(1)))


def luminance(hex_colour):
    def channel(value):
        c = int(value, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(hex_colour[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_contrast_in_both_themes():
    light, dark = block(":root"), block(':root[data-theme="dark"]')
    for theme in (light, {**light, **dark}):
        for name in ("ink", "muted", "accent"):
            assert ratio(theme[name], theme["paper"]) >= 4.5, (name, theme[name], theme["paper"])
