"""Tests for the evidence denylist in portfolio/extract.py (issue #35).

Each test traces to a Done-when item in outcome.md.
"""

from __future__ import annotations

import json

import pytest

from portfolio.extract import _is_denied_path, parse_authored_pr_evidence, parse_pr_evidence
from portfolio.model import Portfolio
from rating.profile import profile


# ---------------------------------------------------------------------------
# Helper: _is_denied_path — one positive + one negative per class
# ---------------------------------------------------------------------------


class TestDeniedDirSegments:
    """Done-when: denylist constant covers build-output dirs at ANY depth;
    helper returns True for denied dir segments, False for authored paths."""

    @pytest.mark.parametrize(
        "path",
        [
            "target/classes/Foo.class",
            "build/libs/app.jar",
            "dist/bundle.js",
            "out/production/Main.class",
            "bin/output.jar",
            ".next/server/app.js",
            "__pycache__/main.cpython-311.pyc",
            "node_modules/react/index.js",
            "vendor/bootstrap.min.css",
            ".venv/lib/python3.11/site-packages/requests/__init__.py",
            ".settings/org.eclipse.jdt.core.prefs",
            ".idea/workspace.xml",
            ".vscode/settings.json",
            # nested — NOT just root-level
            "teamTest/target/classes/log4j.xml",
            "src/build/page.tsx",
        ],
    )
    def test_denied_dir_segment_positive(self, path: str) -> None:
        """Done-when (a): any segment exactly equals a denied dir name → denied."""
        assert _is_denied_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/app.py",
            "src/components/target.ts",  # "target.ts" ≠ "target"
            "build.gradle",  # "build.gradle" ≠ "build"
            "pom.xml",
            "Makefile",
            "src/main/java/com/example/Foo.java",
        ],
    )
    def test_denied_dir_segment_negative(self, path: str) -> None:
        """Done-when (a) over-match guard: filename segments that contain a
        denied word but are not equal to it must NOT be denied. Combined with a
        positive denial so the test detects pre-change behavior (discriminating)."""
        assert _is_denied_path(path) is False
        assert _is_denied_path("target/classes/Foo.class") is True


class TestDeniedExactFilenames:
    """Done-when: denied exact metadata filenames matched on FINAL segment."""

    @pytest.mark.parametrize("path", [".classpath", ".project", ".springBeans"])
    def test_exact_filename_positive(self, path: str) -> None:
        """Done-when (b): final segment exactly matches → denied."""
        assert _is_denied_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/.classpath.bak",  # ends with something extra
            "src/project.py",  # similar but not exact
            "springBeans.xml",  # ".springBeans" ≠ "springBeans.xml"
        ],
    )
    def test_exact_filename_negative(self, path: str) -> None:
        """Done-when (b): names that merely resemble denied names are kept.
        Combined with a positive denial so the test fails pre-change."""
        assert _is_denied_path(path) is False
        assert _is_denied_path(".classpath") is True


class TestDeniedImlSuffix:
    """Done-when: *.iml suffix denied on final segment."""

    @pytest.mark.parametrize("path", ["Module.iml", "teamTest.iml", "subdir/project.iml"])
    def test_iml_suffix_positive(self, path: str) -> None:
        """Done-when (b): final segment ends with .iml → denied."""
        assert _is_denied_path(path) is True

    def test_iml_suffix_negative(self) -> None:
        """Done-when (b): .iml must be a SUFFIX, not substring in middle.
        Combined with a positive denial so the test fails pre-change."""
        assert _is_denied_path("src/iml_utils.py") is False
        assert _is_denied_path("Module.iml") is True


class TestDeniedMetaInfMaven:
    """Done-when: META-INF/maven consecutive segment pair denied at ANY depth."""

    @pytest.mark.parametrize(
        "path",
        [
            "module/META-INF/maven/com.example/foo/pom.properties",
            "subdir/nested/META-INF/maven/group/artifact/pom.xml",
            "target/META-INF/maven/com.example/teamTest/pom.xml",
        ],
    )
    def test_meta_inf_maven_nested_positive(self, path: str) -> None:
        """Done-when: META-INF/maven denied even when nested deep in the path."""
        assert _is_denied_path(path) is True

    def test_meta_inf_services_negative(self) -> None:
        """Done-when: META-INF NOT immediately followed by maven → kept."""
        assert _is_denied_path("src/META-INF/services/foo") is False


class TestDeniedM2eWtp:
    """Done-when: m2e-wtp segment denied at ANY depth."""

    @pytest.mark.parametrize(
        "path",
        [
            "m2e-wtp/web-resources/META-INF/MANIFEST.MF",
            "nested/sub/m2e-wtp/web-resources/something",
        ],
    )
    def test_m2e_wtp_nested_positive(self, path: str) -> None:
        """Done-when: m2e-wtp segment denied at any depth."""
        assert _is_denied_path(path) is True

    def test_m2e_wtp_negative(self) -> None:
        """Done-when: path without m2e-wtp is not denied by this rule.
        Combined with a positive denial so the test fails pre-change."""
        assert _is_denied_path("src/main/resources/web.xml") is False
        assert _is_denied_path("nested/sub/m2e-wtp/web-resources/x") is True


class TestBarePathColonHandling:
    """Done-when (IR-003): the helper takes a BARE path and does NOT colon-split.
    A single-repo bare git path may legally contain a colon — splitting on the
    first ":" would discard the leading segment(s) and mis-match a denied dir
    word in the remainder.
    """

    def test_colon_in_bare_path_not_split_kept(self) -> None:
        """Done-when (IR-003): a bare path containing a colon is split ONLY on
        "/"; its segments are taken verbatim, so "generated:target" ≠ "target"
        and the path is KEPT. Pre-change (colon-stripping helper) this returned
        True (denied) because "target/file.py" was left after the first colon."""
        assert _is_denied_path("src/generated:target/file.py") is False

    def test_colon_segments_kept(self) -> None:
        """Done-when (IR-003): multiple colons in a path segment do not confuse
        matching — segments are split only on "/"."""
        assert _is_denied_path("some/path:with:colons/file.py") is False

    def test_bare_path_with_real_denied_segment_still_dropped(self) -> None:
        """Done-when: a genuine denied dir segment is still caught regardless of
        a colon elsewhere in the path."""
        assert _is_denied_path("src/generated:foo/target/x.class") is True


# ---------------------------------------------------------------------------
# parse_pr_evidence — filtering (single-repo, BARE path refs)
# ---------------------------------------------------------------------------


def _make_pr_json(files: list[str], pr_number: int = 1) -> str:
    return json.dumps(
        [
            {
                "number": pr_number,
                "title": "Test PR",
                "url": f"https://github.com/owner/repo/pull/{pr_number}",
                "additions": 10,
                "deletions": 2,
                "files": [{"path": p} for p in files],
            }
        ]
    )


class TestParsePrEvidenceFiltering:
    """Done-when: parse_pr_evidence drops denied file refs, keeps authored ones,
    and leaves kind="pr" records untouched."""

    def test_denied_files_dropped(self) -> None:
        """Done-when: parse_pr_evidence never emits Evidence(kind="file") for denied paths."""
        denied = [
            "target/classes/log4j.xml",
            ".settings/org.eclipse.jdt.core.prefs",
            "node_modules/react/index.js",
            "module/META-INF/maven/g/a/pom.properties",
        ]
        authored = ["src/app.py", "src/components/target.ts"]
        ev = parse_pr_evidence(_make_pr_json(denied + authored))
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert file_refs == set(authored)

    def test_pr_records_preserved_with_denied_files_dropped(self) -> None:
        """Done-when (IR-002 fold): kind="pr" records are preserved AND the
        denied kind="file" refs are absent — in the SAME test, over a PR whose
        files mix denied + authored. Pre-change the denied-absence half fails
        (denied paths were still emitted as kind="file")."""
        denied = ["target/classes/Foo.class", ".idea/workspace.xml"]
        authored = ["src/main.py"]
        ev = parse_pr_evidence(_make_pr_json(denied + authored))
        # (a) PR records untouched
        pr_refs = [e.ref for e in ev if e.kind == "pr"]
        assert pr_refs == ["PR#1"]
        # (b) denied file refs absent (fails pre-change)
        file_refs = {e.ref for e in ev if e.kind == "file"}
        for d in denied:
            assert d not in file_refs
        # authored kept
        assert "src/main.py" in file_refs

    def test_over_match_keep_and_drop_combined(self) -> None:
        """Done-when (IR-002 fold): the over-match KEEP cases and the DROP cases
        are asserted together, so the test only passes when the denylist exists
        AND matches correctly. Pre-change (no denylist) the DROP assertions fail;
        an over-eager denylist would fail the KEEP assertions.

        KEPT: src/components/target.ts, build.gradle, pom.xml, Makefile
        DROPPED: src/build/page.tsx, target/classes/x.class
        """
        kept = ["src/components/target.ts", "build.gradle", "pom.xml", "Makefile"]
        dropped = ["src/build/page.tsx", "target/classes/x.class"]
        ev = parse_pr_evidence(_make_pr_json(kept + dropped))
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert file_refs == set(kept)

    def test_bare_path_with_colon_kept_regression(self) -> None:
        """Done-when (IR-003): a single-repo bare path containing a colon
        (segments ["src", "generated:target", "file.py"] — no segment equals a
        denied dir name) is KEPT. Pre-change the colon-stripping helper dropped
        it (left "target/file.py" after the first colon → "target" matched)."""
        ev = parse_pr_evidence(_make_pr_json(["src/generated:target/file.py"]))
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert "src/generated:target/file.py" in file_refs


# ---------------------------------------------------------------------------
# parse_authored_pr_evidence — filtering (author-wide, <owner>/<repo>:<path> refs)
# ---------------------------------------------------------------------------


def _make_authored_json(
    owner_repo: str,
    files: list[str],
    pr_number: int = 1,
    pr_url: str = "https://github.com/owner/repo/pull/1",
) -> tuple[str, dict[str, list[dict]]]:
    """Return (search_json, files_by_pr) for parse_authored_pr_evidence."""
    search_json = json.dumps(
        [
            {
                "number": pr_number,
                "title": "Test PR",
                "url": pr_url,
                "repository": {"nameWithOwner": owner_repo},
            }
        ]
    )
    files_by_pr = {pr_url: [{"path": p} for p in files]}
    return search_json, files_by_pr


class TestParseAuthoredPrEvidenceFiltering:
    """Done-when: parse_authored_pr_evidence drops denied <owner>/<repo>:<path> refs,
    keeps authored ones, and leaves kind="pr" records untouched."""

    OWNER_REPO = "Anna-Seo/TeamTestRepository"

    def test_denied_dropped_and_authored_kept_combined(self) -> None:
        """Done-when (IR-002 fold): in ONE test over a mixed fixture, denied
        author-wide refs are dropped AND authored refs are kept. Pre-change the
        "dropped" half fails (denied <owner>/<repo>:<path> refs were emitted)."""
        denied = [
            "teamTest/target/classes/log4j.xml",
            ".settings/org.eclipse.jdt.core.prefs",
        ]
        authored = ["src/Service.java", "web/app.ts"]
        search_json, files_by_pr = _make_authored_json(self.OWNER_REPO, denied + authored)
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        file_refs = {e.ref for e in ev if e.kind == "file"}
        expected = {f"{self.OWNER_REPO}:{p}" for p in authored}
        assert file_refs == expected

    def test_pr_records_preserved_with_denied_files_dropped(self) -> None:
        """Done-when (IR-002 fold): kind="pr" records preserved AND denied
        file refs absent in the same test, over a mixed fixture. Pre-change
        the denied-absence half fails."""
        denied = ["target/Foo.class"]
        authored = ["src/App.java"]
        search_json, files_by_pr = _make_authored_json(self.OWNER_REPO, denied + authored)
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        # PR records untouched
        pr_refs = [e.ref for e in ev if e.kind == "pr"]
        assert pr_refs == [f"{self.OWNER_REPO}#1"]
        # denied absent (fails pre-change)
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert f"{self.OWNER_REPO}:target/Foo.class" not in file_refs
        assert f"{self.OWNER_REPO}:src/App.java" in file_refs

    def test_author_wide_target_dropped(self) -> None:
        """Done-when (IR-003): an author-wide
        owner/repo:teamTest/target/classes/log4j.xml is still DROPPED — the
        helper receives the bare path component "teamTest/target/classes/..."
        and the "target" segment matches."""
        search_json, files_by_pr = _make_authored_json(self.OWNER_REPO, ["teamTest/target/classes/log4j.xml"])
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert f"{self.OWNER_REPO}:teamTest/target/classes/log4j.xml" not in file_refs

    def test_meta_inf_maven_denied(self) -> None:
        """Done-when: META-INF/maven at nested depth denied; authored kept."""
        paths = [
            "wrapper/META-INF/maven/x/y/pom.properties",  # denied
            "src/main/java/App.java",  # kept
        ]
        search_json, files_by_pr = _make_authored_json(self.OWNER_REPO, paths)
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert f"{self.OWNER_REPO}:wrapper/META-INF/maven/x/y/pom.properties" not in file_refs
        assert f"{self.OWNER_REPO}:src/main/java/App.java" in file_refs


# ---------------------------------------------------------------------------
# Nested META-INF/maven and m2e-wtp at any depth
# ---------------------------------------------------------------------------


class TestNestedDepthDenial:
    """Done-when: META-INF/maven and m2e-wtp denied at nested depths."""

    def test_meta_inf_maven_nested_cases(self) -> None:
        """Done-when: all nested positive cases from outcome.md are denied."""
        cases = [
            "module/META-INF/maven/com.example/foo/pom.properties",
            "subdir/nested/META-INF/maven/group/artifact/pom.xml",
            "nested/sub/m2e-wtp/web-resources/something",
            "wrapper/META-INF/maven/x/y/pom.properties",
        ]
        for path in cases:
            assert _is_denied_path(path) is True, f"Expected {path!r} to be denied"

    def test_meta_inf_services_not_denied(self) -> None:
        """Done-when: src/META-INF/services/foo is kept (META-INF NOT followed by maven)."""
        assert _is_denied_path("src/META-INF/services/foo") is False


# ---------------------------------------------------------------------------
# jsj0345-style regression
# ---------------------------------------------------------------------------

# 46 representative denied paths (mix of target/, .settings/, META-INF/maven/, m2e-wtp/)
_DENIED_46 = [
    # target/ (build output)
    "target/classes/log4j.xml",
    "target/classes/com/example/Foo.class",
    "target/classes/com/example/Bar.class",
    "target/generated-sources/annotations/com/example/Foo_.java",
    "target/maven-archiver/pom.properties",
    "target/surefire-reports/TEST-com.example.FooTest.xml",
    "target/test-classes/com/example/FooTest.class",
    "target/teamTest-1.0-SNAPSHOT.jar",
    "teamTest/target/classes/com/example/Service.class",
    "teamTest/target/classes/log4j.xml",
    "teamTest/target/maven-status/maven-compiler-plugin/compile/inputFiles.lst",
    # .settings/
    ".settings/org.eclipse.jdt.core.prefs",
    ".settings/org.eclipse.m2e.core.prefs",
    ".settings/org.eclipse.wst.common.component",
    ".settings/org.eclipse.wst.common.project.facet.core.xml",
    ".settings/org.eclipse.wst.jsdt.ui.superType.container",
    # META-INF/maven
    "target/META-INF/maven/com.example/teamTest/pom.xml",
    "target/META-INF/maven/com.example/teamTest/pom.properties",
    "teamTest/target/META-INF/maven/com.example/teamTest/pom.xml",
    "teamTest/target/META-INF/maven/com.example/teamTest/pom.properties",
    "module/META-INF/maven/com.example/foo/pom.properties",
    # m2e-wtp
    "m2e-wtp/web-resources/META-INF/MANIFEST.MF",
    "nested/m2e-wtp/web-resources/something",
    # exact metadata filenames
    ".classpath",
    ".project",
    "teamTest.iml",
    "Module.iml",
    # node_modules
    "node_modules/react/index.js",
    "node_modules/lodash/lodash.min.js",
    "node_modules/.bin/something",
    # vendor/
    "vendor/bootstrap.min.css",
    "vendor/jquery.js",
    # bin/
    "bin/output.jar",
    "bin/compiled.class",
    # dist/
    "dist/bundle.js",
    "dist/bundle.min.js",
    # out/
    "out/production/classes/Main.class",
    "out/test/classes/Test.class",
    # build/ directory (NOT build.gradle — those are kept)
    "build/libs/app-1.0.jar",
    "build/classes/java/main/App.class",
    # .venv
    ".venv/lib/python3.11/site-packages/requests/__init__.py",
    # __pycache__
    "__pycache__/main.cpython-311.pyc",
    "portfolio/__pycache__/extract.cpython-311.pyc",
    # .idea / .vscode
    ".idea/workspace.xml",
    ".vscode/settings.json",
]

# 4 authored source files with distinct extensions (Python, Kotlin, Java, TypeScript)
_AUTHORED_4 = [
    "src/main/java/com/example/Foo.java",
    "src/main/kotlin/Bar.kt",
    "scripts/build.py",  # "build.py" is a filename segment, not "build" — KEPT
    "web/app.ts",
]

_OWNER_REPO = "jsj0345/TeamTestRepository"
_PR_URL = "https://github.com/jsj0345/TeamTestRepository/pull/1"


def _make_regression_fixtures() -> tuple[str, dict[str, list[dict]]]:
    search_json = json.dumps(
        [
            {
                "number": 1,
                "title": "Initial commit",
                "url": _PR_URL,
                "repository": {"nameWithOwner": _OWNER_REPO},
            }
        ]
    )
    all_files = _DENIED_46 + _AUTHORED_4
    files_by_pr = {_PR_URL: [{"path": p} for p in all_files]}
    return search_json, files_by_pr


class TestJsj0345Regression:
    """Done-when: jsj0345-style case — 46 denied paths + 4 authored yield:
    - exactly 4 Evidence(kind="file") records
    - breadth value=4 / band="Narrow" / points=0
    - stack_diversity value=4 / band="Polyglot" / points=2
    """

    def test_exactly_4_file_evidence(self) -> None:
        """Done-when: only the 4 authored paths appear as kind="file" evidence."""
        search_json, files_by_pr = _make_regression_fixtures()
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        file_ev = [e for e in ev if e.kind == "file"]
        assert len(file_ev) == 4
        file_refs = {e.ref for e in file_ev}
        expected = {f"{_OWNER_REPO}:{p}" for p in _AUTHORED_4}
        assert file_refs == expected

    def test_rating_breadth_narrow(self) -> None:
        """Done-when: breadth value=4 / band="Narrow" / points=0."""
        search_json, files_by_pr = _make_regression_fixtures()
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        port = Portfolio(subject="jsj0345", evidence=ev)
        result = profile(port)
        brd = result.dimensions["breadth"]
        assert brd.value == 4
        assert brd.band == "Narrow"
        assert brd.points == 0

    def test_rating_stack_diversity_polyglot(self) -> None:
        """Done-when: stack_diversity value=4 / band="Polyglot" / points=2
        (Python .py, TypeScript .ts, Java .java, Kotlin .kt — all in _EXT_TO_LANG)."""
        search_json, files_by_pr = _make_regression_fixtures()
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        port = Portfolio(subject="jsj0345", evidence=ev)
        result = profile(port)
        div = result.dimensions["stack_diversity"]
        assert div.value == 4
        assert div.band == "Polyglot"
        assert div.points == 2

    def test_46_denied_paths_all_match(self) -> None:
        """Sanity: every path in _DENIED_46 is actually denied by the helper."""
        for path in _DENIED_46:
            assert _is_denied_path(path) is True, f"Expected {path!r} to be denied"

    def test_4_authored_paths_all_kept(self) -> None:
        """Every _AUTHORED_4 path is KEPT and every _DENIED_46 path is DENIED —
        combined in one test so it fails against pre-change behavior (where the
        denied paths were still emitted as evidence)."""
        for path in _AUTHORED_4:
            assert _is_denied_path(path) is False, f"Expected {path!r} to be kept"
        for path in _DENIED_46:
            assert _is_denied_path(path) is True, f"Expected {path!r} to be denied"
