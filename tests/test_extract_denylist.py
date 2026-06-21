"""Tests for the evidence denylist in portfolio/extract.py (issue #35).

Each test traces to a Done-when item in outcome.md.
"""

from __future__ import annotations

import json

import pytest

from portfolio.extract import _is_denied_ref, parse_authored_pr_evidence, parse_pr_evidence
from portfolio.model import Portfolio
from rating.profile import profile


# ---------------------------------------------------------------------------
# Helper: _is_denied_ref — one positive + one negative per class
# ---------------------------------------------------------------------------


class TestDeniedDirSegments:
    """Done-when: denylist constant covers build-output dirs at ANY depth;
    helper returns True for denied dir segments, False for authored paths."""

    @pytest.mark.parametrize(
        "ref",
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
    def test_denied_dir_segment_positive(self, ref: str) -> None:
        """Done-when (a): any segment exactly equals a denied dir name → denied."""
        assert _is_denied_ref(ref) is True

    @pytest.mark.parametrize(
        "ref",
        [
            "src/app.py",
            "src/components/target.ts",  # "target.ts" ≠ "target"
            "build.gradle",  # "build.gradle" ≠ "build"
            "pom.xml",
            "Makefile",
            "src/main/java/com/example/Foo.java",
        ],
    )
    def test_denied_dir_segment_negative(self, ref: str) -> None:
        """Done-when (a) over-match guard: filename segments that contain a
        denied word but are not equal to it must NOT be denied."""
        assert _is_denied_ref(ref) is False


class TestDeniedExactFilenames:
    """Done-when: denied exact metadata filenames matched on FINAL segment."""

    @pytest.mark.parametrize("ref", [".classpath", ".project", ".springBeans"])
    def test_exact_filename_positive(self, ref: str) -> None:
        """Done-when (b): final segment exactly matches → denied."""
        assert _is_denied_ref(ref) is True

    @pytest.mark.parametrize(
        "ref",
        [
            "src/.classpath.bak",  # ends with something extra
            "src/project.py",  # similar but not exact
            "springBeans.xml",  # ".springBeans" ≠ "springBeans.xml"
        ],
    )
    def test_exact_filename_negative(self, ref: str) -> None:
        """Done-when (b): names that merely resemble denied names are kept."""
        assert _is_denied_ref(ref) is False


class TestDeniedImlSuffix:
    """Done-when: *.iml suffix denied on final segment."""

    @pytest.mark.parametrize("ref", ["Module.iml", "teamTest.iml", "subdir/project.iml"])
    def test_iml_suffix_positive(self, ref: str) -> None:
        """Done-when (b): final segment ends with .iml → denied."""
        assert _is_denied_ref(ref) is True

    def test_iml_suffix_negative(self) -> None:
        """Done-when (b): .iml must be a SUFFIX, not substring in middle."""
        assert _is_denied_ref("src/iml_utils.py") is False


class TestDeniedMetaInfMaven:
    """Done-when: META-INF/maven consecutive segment pair denied at ANY depth."""

    @pytest.mark.parametrize(
        "ref",
        [
            "module/META-INF/maven/com.example/foo/pom.properties",
            "subdir/nested/META-INF/maven/group/artifact/pom.xml",
            "target/META-INF/maven/com.example/teamTest/pom.xml",
        ],
    )
    def test_meta_inf_maven_nested_positive(self, ref: str) -> None:
        """Done-when: META-INF/maven denied even when nested deep in the path."""
        assert _is_denied_ref(ref) is True

    def test_meta_inf_services_negative(self) -> None:
        """Done-when: META-INF NOT immediately followed by maven → kept."""
        assert _is_denied_ref("src/META-INF/services/foo") is False


class TestDeniedM2eWtp:
    """Done-when: m2e-wtp segment denied at ANY depth."""

    @pytest.mark.parametrize(
        "ref",
        [
            "m2e-wtp/web-resources/META-INF/MANIFEST.MF",
            "nested/sub/m2e-wtp/web-resources/something",
        ],
    )
    def test_m2e_wtp_nested_positive(self, ref: str) -> None:
        """Done-when: m2e-wtp segment denied at any depth."""
        assert _is_denied_ref(ref) is True

    def test_m2e_wtp_negative(self) -> None:
        """Done-when: path without m2e-wtp is not denied by this rule."""
        assert _is_denied_ref("src/main/resources/web.xml") is False


class TestOwnerRepoPrefixStripping:
    """Done-when: helper strips <owner>/<repo>: prefix on FIRST ":" only."""

    @pytest.mark.parametrize(
        "ref",
        [
            "Anna-Seo/TeamTestRepository:teamTest/target/classes/log4j.xml",
            "Anna-Seo/TeamTestRepository:wrapper/META-INF/maven/x/y/pom.properties",
            "Anna-Seo/TeamTestRepository:nested/sub/m2e-wtp/web-resources/something",
            "Anna-Seo/TeamTestRepository:.classpath",
            "Anna-Seo/TeamTestRepository:Module.iml",
        ],
    )
    def test_prefix_stripped_denied(self, ref: str) -> None:
        """Done-when: <owner>/<repo>: prefix is stripped before segment matching."""
        assert _is_denied_ref(ref) is True

    @pytest.mark.parametrize(
        "ref",
        [
            "Anna-Seo/TeamTestRepository:src/app.py",
            "Anna-Seo/TeamTestRepository:src/components/target.ts",
            "Anna-Seo/TeamTestRepository:build.gradle",
        ],
    )
    def test_prefix_stripped_kept(self, ref: str) -> None:
        """Done-when: prefix-stripped authored paths are NOT denied."""
        assert _is_denied_ref(ref) is False

    def test_first_colon_only(self) -> None:
        """Done-when: split on FIRST ":" only — colons in path do not confuse matching."""
        # Artificial but legal: path segment happens to contain a colon (URL-like)
        # After first split: path = "some/path:with:colons/file.py"
        # segments = ["some", "path:with:colons", "file.py"] → all kept
        assert _is_denied_ref("owner/repo:some/path:with:colons/file.py") is False

    def test_meta_inf_maven_with_prefix(self) -> None:
        """Done-when (nested META-INF/maven with owner/repo prefix)."""
        assert _is_denied_ref("Anna-Seo/TeamTestRepository:wrapper/META-INF/maven/x/y/pom.properties") is True

    def test_meta_inf_services_with_prefix_kept(self) -> None:
        """Done-when: META-INF NOT followed by maven with prefix → kept."""
        assert _is_denied_ref("Anna-Seo/TeamTestRepository:src/META-INF/services/foo") is False


# ---------------------------------------------------------------------------
# parse_pr_evidence — filtering
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

    def test_pr_records_preserved(self) -> None:
        """Done-when: kind="pr" records are NOT affected even when every file is denied."""
        denied = ["target/classes/Foo.class", ".idea/workspace.xml"]
        ev = parse_pr_evidence(_make_pr_json(denied))
        pr_refs = [e.ref for e in ev if e.kind == "pr"]
        assert pr_refs == ["PR#1"]

    def test_kept_authored_files(self) -> None:
        """Done-when: authored file refs (no denied segment) are kept."""
        authored = ["src/main.py", "tests/test_app.py", "README.md"]
        ev = parse_pr_evidence(_make_pr_json(authored))
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert file_refs == set(authored)

    def test_over_match_guard(self) -> None:
        """Done-when: segment over-match guard — filenames containing denied words are kept;
        a path WITH a denied dir segment is dropped.

        KEPT: src/components/target.ts, build.gradle, pom.xml, Makefile
        DROPPED: src/build/page.tsx (the "build" dir segment matches at depth 1)
        """
        paths = [
            "src/components/target.ts",  # KEPT
            "build.gradle",  # KEPT
            "pom.xml",  # KEPT
            "Makefile",  # KEPT
            "src/build/page.tsx",  # DROPPED
        ]
        ev = parse_pr_evidence(_make_pr_json(paths))
        file_refs = {e.ref for e in ev if e.kind == "file"}
        assert "src/components/target.ts" in file_refs
        assert "build.gradle" in file_refs
        assert "pom.xml" in file_refs
        assert "Makefile" in file_refs
        assert "src/build/page.tsx" not in file_refs


# ---------------------------------------------------------------------------
# parse_authored_pr_evidence — filtering
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

    def test_denied_files_dropped(self) -> None:
        """Done-when: denied paths under <owner>/<repo>: prefix are excluded."""
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

    def test_pr_records_preserved(self) -> None:
        """Done-when: kind="pr" records are NOT affected even when every file is denied."""
        search_json, files_by_pr = _make_authored_json(self.OWNER_REPO, ["target/Foo.class"])
        ev = parse_authored_pr_evidence(search_json, files_by_pr)
        pr_refs = [e.ref for e in ev if e.kind == "pr"]
        assert pr_refs == [f"{self.OWNER_REPO}#1"]

    def test_meta_inf_maven_denied(self) -> None:
        """Done-when: META-INF/maven at nested depth denied after prefix stripping."""
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
        """Done-when: all four nested positive cases from outcome.md are denied."""
        cases = [
            "module/META-INF/maven/com.example/foo/pom.properties",
            "subdir/nested/META-INF/maven/group/artifact/pom.xml",
            "nested/sub/m2e-wtp/web-resources/something",
            "Anna-Seo/TeamTestRepository:wrapper/META-INF/maven/x/y/pom.properties",
        ]
        for ref in cases:
            assert _is_denied_ref(ref) is True, f"Expected {ref!r} to be denied"

    def test_meta_inf_services_not_denied(self) -> None:
        """Done-when: src/META-INF/services/foo is kept (META-INF NOT followed by maven)."""
        assert _is_denied_ref("src/META-INF/services/foo") is False


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
        prefix = f"{_OWNER_REPO}:"
        for path in _DENIED_46:
            ref = f"{prefix}{path}"
            assert _is_denied_ref(ref) is True, f"Expected {ref!r} to be denied"

    def test_4_authored_paths_all_kept(self) -> None:
        """Sanity: every path in _AUTHORED_4 is NOT denied by the helper."""
        prefix = f"{_OWNER_REPO}:"
        for path in _AUTHORED_4:
            ref = f"{prefix}{path}"
            assert _is_denied_ref(ref) is False, f"Expected {ref!r} to be kept"
