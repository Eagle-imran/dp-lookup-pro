"""Ratchet check that bans code comments.

Policy: docs/decisions/2026-11-24-no-code-comments.md. A file may keep at most
the number of comments recorded for it in tools/comment_baseline.json; every
other file must have none. Counts can only go down.

    uv run python tools/check_comments.py           # check (CI)
    uv run python tools/check_comments.py --update  # lock in removed comments

Tool directives are not comments for this rule: shebangs, encoding cookies,
noqa / type: / pragma: / fmt: / ruff: / mypy: / pyright: / nosec markers, and
pinned-action version tags such as ``# v10.3.3`` in workflow files.
Docstrings are documentation, not comments, and are allowed.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tools" / "comment_baseline.json"
EXCLUDED_PREFIXES = ("docs/", "output/", "data/")
EXTRA_PYTHON_FILES = frozenset({"dp-lookup-pro"})
HASH_SUFFIXES = frozenset({".toml", ".yml", ".yaml"})
SUFFIXES = frozenset({".py", ".js", ".css", ".html"}) | HASH_SUFFIXES

PYTHON_DIRECTIVE = re.compile(r"#\s*(noqa\b|type:|pragma:|fmt:|ruff:|mypy:|pyright:|nosec\b)")
ENCODING_COOKIE = re.compile(r"^#.*coding[:=]")
VERSION_TAG = re.compile(r"^#\s*v?\d+(\.\d+)+\s*$")

Comment = tuple[int, str]


def _python_comments(text: str) -> list[Comment]:
    found: list[Comment] = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type != tokenize.COMMENT:
            continue
        line, body = token.start[0], token.string
        if PYTHON_DIRECTIVE.search(body):
            continue
        if line == 1 and body.startswith("#!"):
            continue
        if line <= 2 and ENCODING_COOKIE.match(body):
            continue
        found.append((line, body.strip()))
    return found


def _hash_comment_start(line: str) -> int | None:
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return index
    return None


def _hash_comments(text: str) -> list[Comment]:
    found: list[Comment] = []
    for number, line in enumerate(text.splitlines(), start=1):
        start = _hash_comment_start(line)
        if start is None:
            continue
        body = line[start:].strip()
        if VERSION_TAG.match(body):
            continue
        found.append((number, body))
    return found


def _js_comments(text: str) -> list[Comment]:
    found: list[Comment] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "/*")) or (" //" in line and "://" not in line):
            found.append((number, stripped))
    return found


def _marker_comments(text: str, marker: str) -> list[Comment]:
    return [(number, line.strip()) for number, line in enumerate(text.splitlines(), start=1) if marker in line]


def scan(path: str, text: str) -> list[Comment]:
    """Return ``(line, text)`` for every banned comment in one file."""
    suffix = Path(path).suffix
    if suffix == ".py" or path in EXTRA_PYTHON_FILES:
        return _python_comments(text)
    if suffix in HASH_SUFFIXES:
        return _hash_comments(text)
    if suffix == ".js":
        return _js_comments(text)
    if suffix == ".css":
        return _marker_comments(text, "/*")
    if suffix == ".html":
        return _marker_comments(text, "<!--")
    return []


def tracked_files(root: Path = ROOT) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    return sorted(
        path
        for path in listed
        if not path.startswith(EXCLUDED_PREFIXES)
        and (Path(path).suffix in SUFFIXES or path in EXTRA_PYTHON_FILES)
        and (root / path).is_file()
    )


def collect(root: Path = ROOT, paths: Iterable[str] | None = None) -> dict[str, list[Comment]]:
    found: dict[str, list[Comment]] = {}
    for path in tracked_files(root) if paths is None else paths:
        comments = scan(path, (root / path).read_text(encoding="utf-8"))
        if comments:
            found[path] = comments
    return found


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, int]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): int(value) for key, value in data.items()}


def compare(
    current: dict[str, list[Comment]], baseline: dict[str, int]
) -> tuple[dict[str, list[Comment]], dict[str, int]]:
    """Split the result into files over their allowance and lowered baseline entries."""
    over = {path: comments for path, comments in current.items() if len(comments) > baseline.get(path, 0)}
    lowered = {
        path: len(current.get(path, [])) for path, allowed in baseline.items() if len(current.get(path, [])) < allowed
    }
    return over, lowered


def write_baseline(baseline: dict[str, int], path: Path = BASELINE_PATH) -> None:
    cleaned = {key: value for key, value in sorted(baseline.items()) if value > 0}
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when code comments are added (ratchet).")
    parser.add_argument("--update", action="store_true", help="lower the baseline to the current counts")
    args = parser.parse_args(argv)

    baseline = load_baseline()
    over, lowered = compare(collect(), baseline)

    if over:
        print("Code comments are not allowed (docs/decisions/2026-11-24-no-code-comments.md).")
        print("Delete tautologies and stale notes, move decisions to an ADR, file an issue for hacks.\n")
        for path, comments in sorted(over.items()):
            allowed = baseline.get(path, 0)
            print(f"{path}: {len(comments)} comment(s), baseline allows {allowed}")
            for line, text in comments:
                print(f"  {path}:{line}: {text[:100]}")
    if lowered and args.update:
        write_baseline({**baseline, **lowered})
        print(f"Baseline lowered for {len(lowered)} file(s).")
    elif lowered:
        print("Comments were removed. Lock in the lower counts with:")
        print("  uv run python tools/check_comments.py --update")
        for path, count in sorted(lowered.items()):
            print(f"  {path}: {baseline[path]} -> {count}")
    if over or (lowered and not args.update):
        return 1
    print(f"No new code comments ({sum(baseline.values())} remaining in the baseline).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
