import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("check_comments", ROOT / "tools" / "check_comments.py")
assert _SPEC is not None and _SPEC.loader is not None
check_comments = importlib.util.module_from_spec(_SPEC)
sys.modules["check_comments"] = check_comments
_SPEC.loader.exec_module(check_comments)


def test_python_comments_are_found_but_directives_are_not():
    source = (
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        "import os  # noqa: F401\n"
        "value = 1  # type: ignore[assignment]\n"
        "try:  # pragma: no cover - platform specific\n"
        "    pass\n"
        "except OSError:\n"
        "    pass\n"
        "text = '# not a comment'\n"
        "# a real comment\n"
        "total = 2  # an inline comment\n"
    )
    assert check_comments.scan("module.py", source) == [(10, "# a real comment"), (11, "# an inline comment")]


def test_extensionless_python_entry_point_is_scanned():
    assert check_comments.scan("dp-lookup-pro", "#!/usr/bin/env python3\n# hello\n") == [(2, "# hello")]


def test_hash_comments_skip_strings_and_pinned_action_versions():
    source = (
        '- uses: actions/setup@0123abcd # v10.3.3\nname: "build #1"\n# explain the step\nrun: echo hi # trailing note\n'
    )
    assert check_comments.scan(".github/workflows/ci.yml", source) == [
        (3, "# explain the step"),
        (4, "# trailing note"),
    ]


def test_template_comments_are_found():
    assert check_comments.scan("a.js", "const url = 'https://x';\n// note\nlet a = 1; // why\n") == [
        (2, "// note"),
        (3, "let a = 1; // why"),
    ]
    assert check_comments.scan("a.css", "* { margin: 0; }\n/* panel */\n") == [(2, "/* panel */")]
    assert check_comments.scan("a.html", "<div>\n<!-- hud -->\n</div>\n") == [(2, "<!-- hud -->")]


def test_ratchet_blocks_increases_and_reports_reductions():
    current = {"a.py": [(1, "# x"), (2, "# y")], "b.py": [(1, "# z")], "new.py": [(4, "# n")]}
    baseline = {"a.py": 2, "b.py": 3, "gone.py": 1}
    over, lowered = check_comments.compare(current, baseline)
    assert set(over) == {"new.py"}
    assert lowered == {"b.py": 1, "gone.py": 0}


def test_written_baseline_drops_cleaned_files(tmp_path):
    path = tmp_path / "baseline.json"
    check_comments.write_baseline({"b.py": 1, "a.py": 0}, path)
    assert check_comments.load_baseline(path) == {"b.py": 1}


def test_repository_matches_the_comment_baseline():
    over, lowered = check_comments.compare(check_comments.collect(), check_comments.load_baseline())
    assert not over, f"new code comments: {over}"
    assert not lowered, f"run tools/check_comments.py --update to lock in: {lowered}"
