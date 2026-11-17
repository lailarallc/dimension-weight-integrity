"""Language-agnostic text scan for truth access (plan U4, egress path 3).

The AST gate is precise and Python-only. R, Quarto, notebooks, shell, SQL and
workflow YAML are outside it; this scan reads every text file under its roots
for the gate's needle, plus dbt's `source('truth', ...)`. Breadth here,
precision there.

Stdlib only; vendored into consumers beside truth_gate.py by the refresh.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from .truth_gate import SEARCH_PATH_NEEDLE, TABLE_NEEDLE
except ImportError:  # vendored as loose files in a consumer's quarantine/
    from truth_gate import SEARCH_PATH_NEEDLE, TABLE_NEEDLE

DBT_SOURCE_NEEDLE = re.compile(r"source\(\s*['\"]truth['\"]")
SKIP_DIRS = {".git", "__pycache__", "target", "dbt_packages", "logs", "node_modules", ".venv"}


class TextScanViolation(AssertionError):
    pass


def text_files(*roots) -> list[Path]:
    files: list[Path] = []
    for entry in roots:
        root = Path(entry)
        if root.is_file():
            found = [root]
        elif root.is_dir():
            found = sorted(p for p in root.rglob("*") if p.is_file()
                           and not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1]))
        else:
            raise ValueError(f"no such scan root: {entry}")
        if not found:
            raise ValueError(f"no files under {entry}: an empty root cannot be scanned")
        files += found
    return files


NEEDLES = ((TABLE_NEEDLE, "names"), (SEARCH_PATH_NEEDLE, "search_path names truth"),
           (DBT_SOURCE_NEEDLE, "reads dbt source"))


def scan_text(text: str) -> list[str]:
    """Every needle hit in `text`, with its line number."""
    return [f"line {text.count(chr(10), 0, m.start()) + 1}: {label} {m.group(0)!r}"
            for rx, label in NEEDLES for m in rx.finditer(text)]


def assert_no_truth_text(*roots, exempt=(), base: Path | None = None) -> None:
    """Fail on any text file under `roots` that names a truth table, a truth
    search_path or dbt's truth source. `exempt` holds explicit file paths,
    relative to `base`."""
    skip = {e.replace("\\", "/") for e in exempt}
    report = {}
    for f in text_files(*roots):
        rel = f.relative_to(base).as_posix() if base else f.as_posix()
        if rel in skip:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary
        hits = scan_text(text)
        if hits:
            report[rel] = hits
    if report:
        lines = ["files name quarantined ground truth:", ""]
        for rel, hits in report.items():
            lines.append(f"  {rel}")
            lines += [f"    {h}" for h in hits]
        raise TextScanViolation("\n".join(lines))

