"""Unit tests for portfolio.jd_source.load_jd.

Each test traces to a Done-when item in outcome.md via its docstring.
All tests inject a fake fetcher — no live network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.jd_source import (  # noqa: E402
    JDFetchError,
    JDFileReadError,
    JDInvalidURLError,
    _extract_pdf_text,
    load_jd,
)


# ---------------------------------------------------------------------------
# Fake pypdf injected via sys.modules so the PDF path is exercised without the
# optional dependency installed (`_extract_pdf_text` imports pypdf lazily).
# ---------------------------------------------------------------------------


def _install_fake_pypdf(monkeypatch, *, pages: list[str] | None = None, raises: bool = False, encrypted: bool = False):
    import types

    module = types.ModuleType("pypdf")

    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class PdfReader:
        def __init__(self, _stream) -> None:
            if raises:
                raise ValueError("malformed PDF")
            self.is_encrypted = encrypted
            self.pages = [_Page(t) for t in (pages or [])]

    module.PdfReader = PdfReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", module)


# ---------------------------------------------------------------------------
# Done-when: URL branch with https:// — fetcher called once, returns article text
# ---------------------------------------------------------------------------


def test_https_url_calls_fetcher_once_and_returns_article_text():
    """'URL branch with https://...: the fetcher is called exactly once with the
    URL parse_web_source returned; the value load_jd returns is derived from the
    fetched HTML title + body, not raw HTML.'"""
    calls: list[str] = []

    def fake_fetcher(url: str) -> str:
        calls.append(url)
        return "<html><head><title>Senior Python Engineer</title></head><body>We need Python skills.</body></html>"

    result = load_jd("https://jobs.example.com/python-eng", fetcher=fake_fetcher)

    assert len(calls) == 1
    # The returned string must include article text, not raw HTML
    assert "<html>" not in result
    assert "Senior Python Engineer" in result or "Python skills" in result


# ---------------------------------------------------------------------------
# Done-when: URL branch with http:// — also accepted
# ---------------------------------------------------------------------------


def test_http_url_also_accepted():
    """'URL branch with http://...: also accepted (scheme allowlist matches
    parse_web_source).'"""

    def fake_fetcher(url: str) -> str:
        return "<html><head><title>Job Post</title></head><body>Go developer needed.</body></html>"

    result = load_jd("http://jobs.example.com/go-eng", fetcher=fake_fetcher)
    assert "Job Post" in result or "Go developer" in result


# ---------------------------------------------------------------------------
# Done-when: file branch — fetcher never called, reads utf-8
# ---------------------------------------------------------------------------


def test_file_branch_reads_file_and_never_calls_fetcher(tmp_path):
    """'File branch with a real tmp_path file: read with encoding="utf-8", the
    injected fetcher is never called.'"""
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text("Looking for a backend engineer with Python experience.", encoding="utf-8")

    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    result = load_jd(str(jd_file), fetcher=recording_fetcher)
    assert result == "Looking for a backend engineer with Python experience."
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: colon-in-path is not a URL — treated as file branch
# ---------------------------------------------------------------------------


def test_colon_in_path_is_file_branch_not_url(tmp_path):
    """'Colon-in-path (notes:jd.txt): treated as the file branch (scheme is
    notes, not http/https); the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    # notes:jd.txt has scheme "notes" — routes to file branch
    # It will fail with JDFileReadError since the path doesn't exist,
    # but the key assertion is that fetcher is never called.
    with pytest.raises(JDFileReadError):
        load_jd("notes:jd.txt", fetcher=recording_fetcher)
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: non-http(s) scheme routed to file branch, fetcher not called
# ---------------------------------------------------------------------------


def test_ftp_scheme_routes_to_file_branch_fetcher_not_called():
    """'Non-http(s) scheme (ftp://...): treated as the file branch (scheme is not
    in ("http","https")); the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDFileReadError):
        load_jd("ftp://files.example.com/jd.txt", fetcher=recording_fetcher)
    assert calls == []


def test_file_scheme_routes_to_file_branch_fetcher_not_called():
    """'file:///etc/passwd: scheme is "file", not http/https, so routes to the
    file branch; the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDFileReadError):
        load_jd("file:///etc/passwd_nonexistent_xyz", fetcher=recording_fetcher)
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: SSRF guard — localhost/private-IP raises JDInvalidURLError, fetcher not called
# ---------------------------------------------------------------------------


def test_ssrf_localhost_raises_invalid_url_error():
    """'SSRF guard: http://localhost/... causes load_jd to raise JDInvalidURLError
    (wrapping the ValueError from parse_web_source); the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDInvalidURLError):
        load_jd("http://localhost/jd.txt", fetcher=recording_fetcher)
    assert calls == []


def test_ssrf_127_0_0_1_raises_invalid_url_error():
    """'SSRF guard: http://127.0.0.1/... causes load_jd to raise JDInvalidURLError;
    the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDInvalidURLError):
        load_jd("http://127.0.0.1/jd", fetcher=recording_fetcher)
    assert calls == []


def test_ssrf_private_ip_raises_invalid_url_error():
    """'SSRF guard: a private-IP host causes load_jd to raise JDInvalidURLError;
    the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDInvalidURLError):
        load_jd("http://192.168.1.1/jd", fetcher=recording_fetcher)
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: fetcher failure raises JDFetchError, no print/sys.exit
# ---------------------------------------------------------------------------


def test_fetcher_runtime_error_raises_jd_fetch_error(capsys):
    """'Fetcher failure: a fetcher that raises RuntimeError causes load_jd to
    raise JDFetchError; load_jd does not print and does not call sys.exit.'"""

    def failing_fetcher(url: str) -> str:
        raise RuntimeError("connection refused")

    with pytest.raises(JDFetchError) as exc_info:
        load_jd("https://jobs.example.com/eng", fetcher=failing_fetcher)

    assert "connection refused" in str(exc_info.value)
    # load_jd must not print anything
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Done-when: file-read failure raises JDFileReadError, fetcher not called
# ---------------------------------------------------------------------------


def test_missing_file_raises_jd_file_read_error():
    """'File-read failure: when the path does not exist, load_jd raises
    JDFileReadError; the fetcher is never called.'"""
    calls: list[str] = []

    def recording_fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(JDFileReadError):
        load_jd("/nonexistent/path/jd.txt", fetcher=recording_fetcher)
    assert calls == []


# ---------------------------------------------------------------------------
# Done-when: typed exception identity — three distinct classes, not aliases
# ---------------------------------------------------------------------------


def test_typed_exception_classes_are_distinct():
    """'Typed exception identity: JDFileReadError, JDInvalidURLError, and
    JDFetchError are distinct classes (not aliases), so the CLI except clauses
    are unambiguous.'"""
    assert JDFileReadError is not JDInvalidURLError
    assert JDFileReadError is not JDFetchError
    assert JDInvalidURLError is not JDFetchError

    # All subclass Exception
    assert issubclass(JDFileReadError, Exception)
    assert issubclass(JDInvalidURLError, Exception)
    assert issubclass(JDFetchError, Exception)

    # Catching one does not catch the others
    with pytest.raises(JDInvalidURLError):
        try:
            raise JDInvalidURLError("test")
        except JDFileReadError:
            pass  # must NOT be caught here


# ---------------------------------------------------------------------------
# Done-when: PDF --jd files are detected by signature and extracted to text
# ---------------------------------------------------------------------------


def test_pdf_file_detected_by_signature_and_extracted(tmp_path, monkeypatch):
    """A local file whose bytes start with the %PDF signature routes to the PDF
    extractor (NOT utf-8 decode) and the fetcher is never called."""
    pdf = tmp_path / "jd"  # no .pdf extension — detection is by bytes, not name
    pdf.write_bytes(b"%PDF-1.4\n<<binary garbage that is not utf-8 \xff\xfe>>")

    monkeypatch.setattr("portfolio.jd_source._extract_pdf_text", lambda data: "python backend engineer")

    fetched: list[str] = []
    result = load_jd(str(pdf), fetcher=lambda u: fetched.append(u) or "")
    assert result == "python backend engineer"
    assert fetched == []  # local file → fetcher untouched


def test_extract_pdf_text_joins_pages(monkeypatch):
    """_extract_pdf_text joins per-page text from pypdf."""
    _install_fake_pypdf(monkeypatch, pages=["Python backend.", "Kubernetes, Go."])
    assert _extract_pdf_text(b"%PDF-1.4 ...") == "Python backend.\nKubernetes, Go."


def test_extract_pdf_text_empty_is_rejected(monkeypatch):
    """An image-only/scanned PDF (no extractable text) raises JDFileReadError so
    the caller never proceeds on an empty JD."""
    _install_fake_pypdf(monkeypatch, pages=["", "   "])
    with pytest.raises(JDFileReadError, match="no extractable text"):
        _extract_pdf_text(b"%PDF-1.4 ...")


def test_extract_pdf_text_malformed_pdf_wrapped(monkeypatch):
    """A pypdf error on a malformed PDF is wrapped as JDFileReadError, not raised raw."""
    _install_fake_pypdf(monkeypatch, raises=True)
    with pytest.raises(JDFileReadError, match="could not read the PDF"):
        _extract_pdf_text(b"%PDF-1.4 ...")


def test_pdf_encrypted_rejected_ir001(monkeypatch):
    """An encrypted PDF --jd is refused with an actionable error (codex IR-001)."""
    _install_fake_pypdf(monkeypatch, pages=["secret"], encrypted=True)
    with pytest.raises(JDFileReadError, match="encrypted"):
        _extract_pdf_text(b"%PDF-1.4 ...")


def test_pdf_too_many_pages_rejected_ir001(monkeypatch):
    """A PDF --jd exceeding the page cap is refused (resource limit, codex IR-001)."""
    monkeypatch.setattr("portfolio.jd_source._PDF_MAX_PAGES", 2)
    _install_fake_pypdf(monkeypatch, pages=["a", "b", "c"])  # 3 > 2
    with pytest.raises(JDFileReadError, match="too many pages"):
        _extract_pdf_text(b"%PDF-1.4 ...")


def test_pdf_text_cap_rejected_ir001(monkeypatch):
    """Extracted text exceeding the char cap is refused (resource limit, codex IR-001)."""
    monkeypatch.setattr("portfolio.jd_source._PDF_MAX_TEXT_CHARS", 10)
    _install_fake_pypdf(monkeypatch, pages=["x" * 11])
    with pytest.raises(JDFileReadError, match="char limit"):
        _extract_pdf_text(b"%PDF-1.4 ...")


def test_jd_file_too_large_rejected_ir001(tmp_path, monkeypatch):
    """A --jd file larger than the byte cap is refused before its bytes are read
    (codex IR-001 — preflight size check via stat, not after loading into memory)."""
    monkeypatch.setattr("portfolio.jd_source._JD_MAX_BYTES", 16)
    big = tmp_path / "jd.txt"
    big.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(JDFileReadError, match="too large"):
        load_jd(str(big), fetcher=lambda u: "")


def test_extract_pdf_text_missing_pypdf_gives_actionable_error(monkeypatch):
    """When the optional 'pypdf' dependency is absent, the error names it and the
    fallback (convert to text) rather than surfacing a raw ImportError."""
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import pypdf → ImportError
    with pytest.raises(JDFileReadError, match="pypdf"):
        _extract_pdf_text(b"%PDF-1.4 ...")


# ---------------------------------------------------------------------------
# codex IR-003: real-PDF fixtures (not fake pypdf) — exercise the actual parser
# against the limit/encryption/empty paths. Gated on pypdf being installed.
# ---------------------------------------------------------------------------


def test_real_empty_pdf_rejected_ir003(tmp_path):
    """A REAL empty PDF (pypdf-generated, no extractable text) is rejected."""
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    p = tmp_path / "blank.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    with pytest.raises(JDFileReadError, match="no extractable text"):
        load_jd(str(p), fetcher=lambda u: "")


def test_real_truncated_pdf_wrapped_ir003(tmp_path):
    """A REAL truncated PDF is wrapped as JDFileReadError, not raised raw."""
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    p = tmp_path / "trunc.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])  # cut it in half
    with pytest.raises(JDFileReadError):
        load_jd(str(p), fetcher=lambda u: "")


def test_real_encrypted_pdf_rejected_ir003(tmp_path):
    """A REAL encrypted PDF is refused (codex IR-001/IR-003), not silently empty."""
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    p = tmp_path / "enc.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    with pytest.raises(JDFileReadError, match="encrypted"):
        load_jd(str(p), fetcher=lambda u: "")


def test_real_too_many_pages_rejected_ir003(tmp_path, monkeypatch):
    """A REAL multi-page PDF over the page cap is rejected (resource limit)."""
    pypdf = pytest.importorskip("pypdf")
    monkeypatch.setattr("portfolio.jd_source._PDF_MAX_PAGES", 2)
    writer = pypdf.PdfWriter()
    for _ in range(3):  # 3 > 2
        writer.add_blank_page(width=72, height=72)
    p = tmp_path / "many.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    with pytest.raises(JDFileReadError, match="too many pages"):
        load_jd(str(p), fetcher=lambda u: "")
