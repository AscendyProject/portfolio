"""Deterministic, stdlib-only SVG capability card renderer.

render_card(profile_result, grade_result, *, subject, lang="en", verify_url=None) -> str
  Returns a self-contained SVG string. XML-escaped, byte-deterministic,
  fixed dimensions, grade-band accent color. No external fonts/images/scripts.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from portfolio.i18n import LANGS

# Pinned accent-color map: grade letter → hex color.
# Same grade → same color across every call (determinism).
_GRADE_COLORS: dict[str, str] = {
    "S": "#a855f7",  # purple
    "A": "#22c55e",  # green
    "B": "#3b82f6",  # blue
    "C": "#f59e0b",  # amber
    "D": "#ef4444",  # red
}
_DEFAULT_COLOR = "#64748b"  # slate (fallback for unexpected grade letters)

# Max characters per strength-bullet line (deterministic ellipsis).
_MAX_BULLET_CHARS = 60
# Max strength bullets shown.
_MAX_BULLETS = 3

# Fixed card dimensions (pixels).
_CARD_WIDTH = 440
_CARD_HEIGHT = 220


def _accent(grade: str) -> str:
    return _GRADE_COLORS.get(grade, _DEFAULT_COLOR)


def _truncate(text: str, max_chars: int = _MAX_BULLET_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


# Escape XML entities for SVG TEXT nodes, including quotes. Default
# xml.sax.saxutils.escape leaves `"`/`'` untouched (harmless in text but the card
# contract requires an injected quote not to survive raw), so escape them too.
_ESC_QUOTES = {'"': "&quot;", "'": "&apos;"}


def _esc(text: str) -> str:
    return escape(text, _ESC_QUOTES)


def render_card(
    profile_result,
    grade_result,
    *,
    subject: str,
    lang: str = "en",
    verify_url: str | None = None,
) -> str:
    """Render a self-contained SVG capability card.

    Returns a UTF-8 SVG string with no external font references, no <script>,
    no external <image>/<link> references, and no @import. Every interpolated
    value is XML-escaped via xml.sax.saxutils.escape / quoteattr.

    Same (profile_result, grade_result, subject, lang, verify_url) inputs
    always produce byte-identical output (deterministic).
    """
    grade = grade_result.grade
    score = grade_result.score
    color = _accent(grade)

    # i18n tagline — falls back to en if the key is absent for the requested lang.
    lang_table = LANGS.get(lang, LANGS["en"])
    tagline = lang_table.get("card_tagline", LANGS["en"]["card_tagline"])

    # Enforce the no-percentile/ranking output gate on the card's OWN output (issue
    # #60), across EVERY text channel — not just bullets. A banned-term bullet is
    # dropped whole; a banned term appearing in the subject or verify_url is stripped
    # out — so the returned SVG can never carry ranking lexicon regardless of what a
    # caller hands render_card. Lazy import avoids an upward module-load dependency.
    from rating.grade import _BANNED_PERCENTILE_RE

    def _strip_banned(s: str) -> str:
        return _BANNED_PERCENTILE_RE.sub("", s)

    # Up to MAX_BULLETS grounded strength bullets from grade_result.reasoning.
    bullets: list[str] = []
    for item in grade_result.reasoning:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        text = text.strip()
        if text and not _BANNED_PERCENTILE_RE.search(text):
            bullets.append(_truncate(text))
            if len(bullets) >= _MAX_BULLETS:
                break

    # XML-escape every user-supplied string before interpolation (quotes included);
    # subject and verify_url are also stripped of any banned ranking lexicon.
    e_subject = _esc(_strip_banned(subject))
    e_tagline = _esc(tagline)
    e_grade = _esc(str(grade))
    e_score = _esc(str(score))
    aria_label = quoteattr(f"Capability rating: {grade} ({score})")

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' width="{_CARD_WIDTH}" height="{_CARD_HEIGHT}"'
            f' role="img" aria-label={aria_label}>'
        ),
        # Dark background
        f'  <rect width="{_CARD_WIDTH}" height="{_CARD_HEIGHT}" rx="10" ry="10" fill="#0f172a"/>',
        # Accent left bar
        f'  <rect x="0" y="0" width="6" height="{_CARD_HEIGHT}" rx="3" ry="3" fill="{color}"/>',
        # Grade letter (upper right)
        (
            f'  <text x="395" y="88"'
            f' font-family="system-ui,sans-serif" font-size="72" font-weight="700"'
            f' fill="{color}" text-anchor="middle">{e_grade}</text>'
        ),
        # Numeric score (below grade)
        (
            f'  <text x="395" y="112"'
            f' font-family="system-ui,sans-serif" font-size="13"'
            f' fill="#94a3b8" text-anchor="middle">{e_score}/100</text>'
        ),
        # Subject / title (upper left)
        (
            f'  <text x="24" y="38"'
            f' font-family="system-ui,sans-serif" font-size="15" font-weight="600"'
            f' fill="#f1f5f9" text-anchor="start">{e_subject}</text>'
        ),
        # Thin divider
        (f'  <line x1="24" y1="48" x2="{_CARD_WIDTH - 16}" y2="48" stroke="#1e293b" stroke-width="1"/>'),
    ]

    # Strength bullets
    bullet_y = 70
    for bullet in bullets:
        e_bullet = _esc(bullet)
        lines.append(
            f'  <text x="24" y="{bullet_y}"'
            f' font-family="system-ui,sans-serif" font-size="11"'
            f' fill="#cbd5e1" text-anchor="start">• {e_bullet}</text>'
        )
        bullet_y += 18

    # Tagline (bottom of card)
    lines.append(
        f'  <text x="24" y="{_CARD_HEIGHT - 24}"'
        f' font-family="system-ui,sans-serif" font-size="9"'
        f' fill="#475569" text-anchor="start" font-style="italic">{e_tagline}</text>'
    )

    # Optional verify URL
    if verify_url is not None:
        e_url = _esc(_strip_banned(verify_url))
        lines.append(
            f'  <text x="24" y="{_CARD_HEIGHT - 10}"'
            f' font-family="system-ui,sans-serif" font-size="9"'
            f' fill="#475569" text-anchor="start">{e_url}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)
