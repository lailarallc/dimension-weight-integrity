#!/usr/bin/env python3
"""Flag real retailer/distributor names that sit beside a Cinderhaven dollar figure.

Rule (2026-11-05): on public surfaces, a Cinderhaven dollar figure never shares a
sentence or table row with a real trade-partner name; use the label from
reference/retailer_display_labels.json. A real name may stay for the partner's own
published rule, code, fee, or window when no Cinderhaven dollar figure is beside it.

Usage:  python scripts/check_retailer_labels.py <file-or-dir> [...]
Checks .md/.mdx/.html/.txt files that mention "Cinderhaven". A line can opt out
with the marker `label-ok` (for a published fee schedule or rule quoted with its
own dollar amounts). Synced from cinderhaven-data-platform by refresh_canonical.py.
Exit: 0 clean, 1 violations, 2 misconfigured.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "reference" / "retailer_display_labels.json"
EXTS = {".md", ".mdx", ".html", ".txt"}
DOLLAR = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:[KkMmBb]\b|million|thousand)?")
def load_names() -> list[str]:
    if not LABELS.exists():
        print(f"ERROR: {LABELS} missing; run scripts/refresh_canonical.py", file=sys.stderr)
        sys.exit(2)
    data = json.loads(LABELS.read_text(encoding="utf-8"))
    partners = [v for grp in ("retailers", "distributors", "other_partners")
                for k, v in data.get(grp, {}).items()
                if not k.startswith("_") and v["name"] != v["label"]]
    names = [v["name"] for v in partners]
    # All-caps forms appear in IDs and codes (RET-KROGER-S0021, DPO-KEHE-...). Not a plain
    # case-insensitive match: "sprouts" the vegetable is not Sprouts the retailer.
    names += [n.upper() for n in names]
    # Codes the upper-cased name misses (WMT, KGR, WHOLEFOODS, DPI, the WALMARTUS EDI
    # partner code) are aliases in the map, so a new tool code is a map edit, not a gate edit.
    names += [a for v in partners for a in v.get("aliases", [])]
    return sorted(set(names), key=len, reverse=True)


def segments(text: str):
    """Yield (line_no, segment) for prose paragraphs and table rows about Cinderhaven.

    Prose is split into sentences (the file already names Cinderhaven); a table
    row is checked only if its table names Cinderhaven.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            if any("Cinderhaven" in x for x in lines[i:j]):
                for k in range(i, j):
                    if "label-ok" not in lines[k]:
                        yield k + 1, lines[k]
            i = j
            continue
        line = lines[i]
        if "label-ok" not in line:
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[(*])", line):
                yield i + 1, s
        i += 1


def check(path: Path, name_re: re.Pattern) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Cinderhaven" not in text:
        return []
    out = []
    for n, seg in segments(text):
        seg_nolinks = re.sub(r"\]\([^)]*\)", "]", seg)
        if not name_re.search(seg_nolinks) or not DOLLAR.search(seg_nolinks):
            continue
        cites_source = "](http" in seg
        if cites_source and not re.search(r"Cinderhaven|\bits\b", seg_nolinks):
            continue
        out.append(f"{path}:{n}: {seg.strip()[:160]}")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    names = load_names()
    name_re = re.compile(r"\b(" + "|".join(re.escape(x) for x in names) + r")\b")
    files = []
    for a in argv:
        p = Path(a)
        files += [f for f in p.rglob("*") if f.suffix in EXTS] if p.is_dir() else [p]
    bad = [v for f in sorted(files) for v in check(f, name_re)]
    for b in bad:
        print(b)
    print(f"check_retailer_labels: {'clean' if not bad else str(len(bad)) + ' violation(s)'} "
          f"({len(files)} files)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
