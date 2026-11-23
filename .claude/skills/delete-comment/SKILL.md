---
name: delete-comment
description: Audit and remove code comments in dp-lookup-pro. Classifies every comment as tautology, stale, excuse or decision record; deletes tautologies and stale notes, files a GitHub issue for each excuse's hack, moves decision records into ADRs under docs/decisions/, and lowers the comment ratchet baseline. Use when the user runs /delete-comment, asks to clean up or audit comments, or when tools/check_comments.py fails or reports a baseline that can be lowered. Optional argument - a path or glob to limit the scope (default - the whole repository).
---

# /delete-comment

The policy is in `docs/decisions/2026-11-24-no-code-comments.md`. Code comments are
banned. Docstrings and tool directives (`noqa`, `type: ignore`, `pragma: no cover`,
`fmt:`/`ruff:`/`mypy:` markers, shebangs, `# v1.2.3` action pins) are allowed.
`tools/check_comments.py` enforces the rule with a per-file ratchet stored in
`tools/comment_baseline.json`.

## 1. Find the comments

```bash
uv run python tools/check_comments.py
```

It lists every comment over the baseline. To see comments the baseline still allows,
or to limit the run to the scope given as the argument, call
`check_comments.collect()` and filter by path:

```bash
uv run python -c "import sys; sys.path.insert(0, 'tools'); import check_comments as c; \
[print(f'{p}:{l}: {t}') for p, cs in c.collect().items() for l, t in cs]"
```

Work on a new branch. If nothing is listed, stop and say so.

## 2. Classify each comment

Read each comment with its surrounding code, then group consecutive comment lines
into one block. Give each block exactly one category:

| Category | Test | Action |
| :--- | :--- | :--- |
| **Tautology** | The code, a name, a type or a nearby docstring already says it. Section banners and numbered step labels count. | Delete |
| **Stale** | It describes an implementation, bug ID, file or behaviour that no longer exists ("previously…", "rather than the old…"). | Delete |
| **Excuse** | It justifies a workaround: test-only branches in production code, compatibility shims, unused aliases, duck typing to dodge imports, `cast()` or broad `except` explained away, silently skipped tests. | Delete and file an issue |
| **Decision record** | It records an important, non-obvious *why*: a domain rule, a data quirk, a units or projection choice, a concurrency or retry policy, a rate limit, a safety or security constraint. | Move to an ADR, then delete |

Before calling something an excuse, read the code it defends and confirm the hack is
real. For example, grep for an "alias" to see if anything uses it. If a comment only
explains a magic number or a test fixture, keep the meaning with a named constant,
variable name or `pytest.param(..., id=...)` instead of an ADR.

Show the user the table of blocks per category, with file:line, before deleting.

## 3. Act

- **Decision records:** add them to the matching ADR in `docs/decisions/` (dated
  `YYYY-MM-DD-topic.md`; reuse an existing topic file when one fits) and link any new
  ADR from `docs/decisions/README.md` and the list in the no-code-comments ADR. Name
  files and functions, not line numbers.
- **Excuses:** group comments that defend the same hack into one issue, then
  `gh issue create` with the file paths, what the workaround is, why it is wrong, and a
  concrete fix. Confirm with the user before filing.
- **Deleting:** remove whole comment lines and inline `# ...` tails. Do not leave
  extra blank lines, and keep import blocks contiguous (`uv run ruff check --fix
  --select I <file>`).

## 4. Verify and ratchet

```bash
uv run python tools/check_comments.py --update   # lower the baseline
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```

`tests/test_documentation_contract.py` checks that every link in the new ADRs
resolves. Commit the code, ADRs and `tools/comment_baseline.json` together. In the PR,
report counts per category, the issues filed, and the lines removed (`git diff
--shortstat`).

Never raise a count in `comment_baseline.json` to make the check pass. A new comment
means a new name, test or ADR is needed instead.
