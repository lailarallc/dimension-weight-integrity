#!/usr/bin/env python3
"""Refresh this repo's vendored canon + gate from the cinderhaven-data-platform.

Copies the platform's synced artifacts into this repo:
  reference/canonical_values.json  (the machine-readable canon; tests read it)
  reference/supersedes.txt         (retired-figure list; the drift gate reads it)
  reference/retailer_display_labels.json (public labels for trade partners;
                                    tool UIs and check_retailer_labels.py read it)
  scripts/check_canonical_drift.py (the drift gate itself — synced so every repo
                                    runs the SAME, current gate implementation)
  scripts/refresh_canonical.py     (this script — self-syncs so the next refresh
                                    is always the latest version)
  quarantine/truth_gate.py, quarantine/text_scan.py
                                   (the truth quarantine gate; a consumer runs
                                    it over its own estimation code. A copy of
                                    this script older than the gate delivers the
                                    new script first and the gate on the next run)

The platform regenerates the two reference artifacts on every
`verify_canonical.py` run; the two scripts are maintained in the platform's
scripts/. This is a DEV-TIME tool: run it after the canon or gate changes,
review the diff, commit the vendored copies. It is NOT part of CI (the vendored
files are committed).

Platform location resolution, in order:
  1. $CINDERHAVEN_PLATFORM (path to the platform repo root)
  2. common relative layouts from this repo
Fails loudly if it can't find the platform — never silently vendors nothing.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# (platform-relative source dir, artifact filename, repo-relative dest dir)
ARTIFACTS = (
    ("reference", "canonical_values.json", "reference"),
    ("reference", "supersedes.txt", "reference"),
    ("reference", "retailer_display_labels.json", "reference"),
    ("scripts", "check_canonical_drift.py", "scripts"),
    ("scripts", "check_retailer_labels.py", "scripts"),
    ("scripts", "refresh_canonical.py", "scripts"),
    # The truth quarantine gate (plan U4): lands in the consumer's own
    # quarantine/, outside its estimation code, as loose files.
    ("quarantine", "truth_gate.py", "quarantine"),
    ("quarantine", "text_scan.py", "quarantine"),
)

CANDIDATES = [
    os.environ.get("CINDERHAVEN_PLATFORM", ""),
    REPO / ".." / ".." / "active datasources" / "cinderhaven-data-platform",
    REPO / ".." / "cinderhaven-data-platform",
    REPO / ".." / ".." / "cinderhaven-data-platform",
]


def find_platform() -> Path:
    for c in CANDIDATES:
        if not c:
            continue
        p = Path(c).expanduser()
        if (p / "reference" / "canonical_values.yml").exists():
            return p.resolve()
    print(
        "ERROR: could not locate cinderhaven-data-platform. Set "
        "CINDERHAVEN_PLATFORM to its repo root and retry.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> int:
    platform = find_platform()
    missing = [f"{sd}/{name}" for sd, name, _ in ARTIFACTS
               if not (platform / sd / name).exists()]
    if missing:
        print(
            f"ERROR: {platform.name} is missing {missing}. Run its "
            f"scripts/verify_canonical.py first (it emits the reference "
            f"artifacts); the scripts live in the platform's scripts/.",
            file=sys.stderr,
        )
        return 1
    for src_dir, name, dest_dir in ARTIFACTS:
        (REPO / dest_dir).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(platform / src_dir / name, REPO / dest_dir / name)
        print(f"  vendored {dest_dir}/{name}  <-  {platform.name}")
    print("done. Review `git diff reference/ scripts/ quarantine/` and commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
