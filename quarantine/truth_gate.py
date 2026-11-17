"""The truth quarantine gate (plan U4), ported from cinderhaven-promo-response's
`assert_no_truth_access` (testing.py:74) and Lift Math's import ban.

Two static checks over the estimation path's Python:

1. `assert_no_truth_access(*roots)`: no module imports `truth`, and no string
   constant (docstrings included) names a truth table by its schema-qualified
   name or sets a search_path that names truth.
2. `assert_no_generator_access(*roots)`: no module imports a seeder
   (`seed_*`, the answer key by another route: compute_defect_profile
   reproduces every defect the defect ledger holds), the generation package,
   U15's loader `realism_bundle`, anything under vendor/realism/, or one of
   the four spec generators by its bare module name (group 11's replayed
   trial names which SKUs the world declines), and no string constant reads a
   file there.

Changes from the source, each from the plan: the needle is every truth table,
schema-qualified, not a substring; there is no `truth.py` skip; every root
must hold Python, not just the union; the import ban names the platform's
generators, not promo-response's.

This module carries the needle, so it lives outside every scan root
(quarantine/), here and in a consumer. Stdlib only: the refresh vendors it.

Scope: this proves estimation code does not import or name truth. A read that
names none of these (a schema built from a variable) is beyond any static
check; the database role is the control for it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

#: Every table sql/truth_schema.sql creates. A test pins this to the DDL, so the
#: banned names and the real names cannot diverge.
TRUTH_TABLES = ("injection_ledger", "corruption_ledger", "promo_events", "outage_episodes",
                "defect_ledger", "consequence_chains")
FORBIDDEN_IMPORTS = ("truth",)

#: `truth.<table>` on word boundaries, and any search_path assignment naming truth.
TABLE_NEEDLE = re.compile(r"\btruth\s*\.\s*\"?(" + "|".join(TRUTH_TABLES) + r")\b", re.IGNORECASE)
SEARCH_PATH_NEEDLE = re.compile(r"search_path\s*(=|\bto\b)\s*[^;\n]*\btruth\b", re.IGNORECASE)

GENERATOR_PREFIX = "seed_"
GENERATOR_MODULES = ("generation", "realism_bundle",
                     # U15: the vendored generators import each other by bare name, so a copy can too
                     "group8_dtc", "group9_ledger", "group10_floors", "group11_compliance")
VENDOR_REALISM = "vendor/realism"


class TruthAccessViolation(AssertionError):
    """Raised when estimation-path code can reach ground truth."""


def needle_hits(text: str) -> list[str]:
    """Every needle match in a piece of text, as short descriptions."""
    hits = [f"names {m.group(0)!r}" for m in TABLE_NEEDLE.finditer(text)]
    hits += [f"search_path names truth ({m.group(0)!r})" for m in SEARCH_PATH_NEEDLE.finditer(text)]
    return hits


def python_files(*roots, exclude=()) -> list[Path]:
    """The .py files under each root. Every root must hold at least one: a gate
    run over an empty root beside a full one would pass that root vacuously."""
    files: list[Path] = []
    for entry in roots:
        root = Path(entry)
        if root.is_dir():
            found = sorted(root.rglob("*.py"))
        elif root.suffix == ".py" and root.is_file():
            found = [root]
        else:
            raise ValueError(f"not a Python file or directory: {entry}")
        if not found:
            raise ValueError(f"no Python files under {entry}: an empty root cannot be audited")
        files += found
    skip = {e.replace("\\", "/") for e in exclude}
    return [f for f in files if not any(f.as_posix().endswith(s) for s in skip)]


def _parse(path: Path) -> ast.AST:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise TruthAccessViolation(f"{path}: cannot parse to audit ({exc})") from exc


def _truth_violations(path: Path) -> list[str]:
    found = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] in FORBIDDEN_IMPORTS:
                found.append(f"line {node.lineno}: imports from {module!r}")
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORTS:
                    found.append(f"line {node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in FORBIDDEN_IMPORTS:
                    found.append(f"line {node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"line {node.lineno}: string {h}" for h in needle_hits(node.value)]
    return found


def _generator_violations(path: Path) -> list[str]:
    def banned(module: str) -> bool:
        parts = module.split(".")
        return (parts[-1].startswith(GENERATOR_PREFIX) or parts[0] in GENERATOR_MODULES
                or parts[-1] in GENERATOR_MODULES or ".".join(parts[:2]) == "vendor.realism")

    found = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module and banned(module):
                found.append(f"line {node.lineno}: imports from {module!r}")
            for alias in node.names:
                if banned(alias.name):
                    found.append(f"line {node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if banned(alias.name):
                    found.append(f"line {node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if VENDOR_REALISM in node.value.replace("\\", "/"):
                found.append(f"line {node.lineno}: reads a file under {VENDOR_REALISM}/")
    return found


def _raise(report: dict, headline: str, advice: str) -> None:
    if report:
        lines = [headline, ""]
        for target, found in report.items():
            lines.append(f"  {target}")
            lines += [f"    {item}" for item in found]
        raise TruthAccessViolation("\n".join(lines + ["", advice]))


def assert_no_truth_access(*roots, exclude=()) -> None:
    """Raise TruthAccessViolation naming every file and line that imports truth
    or names a truth table; ValueError if any root holds no Python."""
    report = {f: v for f in python_files(*roots, exclude=exclude) if (v := _truth_violations(f))}
    _raise(report, "estimation-path code can reach quarantined ground truth:",
           "An estimate that can see truth is not an estimate. Reword prose that names a truth table; "
           "an exemption is an explicit file path with a DECISIONS entry, never a directory.")


def assert_no_generator_access(*roots, exclude=()) -> None:
    """Raise TruthAccessViolation naming every import of a generator, the
    realism bundle or vendor/realism; ValueError if any root holds no Python."""
    report = {f: v for f in python_files(*roots, exclude=exclude) if (v := _generator_violations(f))}
    _raise(report, "estimation-path code reaches the generators (the answer key by another route):",
           "The seeders reproduce what truth holds. Derive what you need from the observed world.")
