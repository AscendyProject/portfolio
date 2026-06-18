"""Shared UTF-8 stdout emitter for all product CLIs.

Centralises the single-source-of-truth for writing rendered Markdown to
stdout as UTF-8 bytes regardless of the console's locale encoding (fixes the
cp949 UnicodeEncodeError on Korean Windows hosts).
"""

from __future__ import annotations

import sys


def emit_markdown(markdown: str) -> None:
    """Write rendered Markdown to stdout as UTF-8, regardless of the console's
    locale encoding (fixes the cp949 UnicodeEncodeError). Falls back to print()
    for text streams without a binary .buffer (e.g. io.StringIO under capture)."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(markdown.encode("utf-8") + b"\n")
    else:
        print(markdown)
