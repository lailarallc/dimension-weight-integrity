"""Client-mode CLI for dimension-weight-integrity.

Wraps the physical-attribute engine with the shared ``lailara_engagement`` scaffold
so a client's item-master export can be validated and measured locally: tolerant
CSV/XLSX intake (SKU read as text), a preflight that names the required case
dimension/weight columns via ``engagement.yml`` (Data Readiness Report if any is
missing), the physics engine (cube → density → NMFC freight class, plus an optional
DTC parcel billable-weight check) run on the validated rows, and a branded,
provenance-footed, draft-watermarked readiness summary plus a per-SKU CSV — all
written to ``client-output/`` only.

Scope note: this validates ONE item master and computes the physical attributes it
implies. The four-system divergence and dollar-cost model (ERP/WMS/GDSN/DTC) is the
dbt + Dagster + Postgres pipeline and is unchanged; it takes four extracts and a
database, so it is not driven from here. See INPUT-SPEC.md.

Usage:
    python client_mode.py --config engagement.yml --input client-data/item_master.csv \
        --out client-output [--final]
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import pathlib
from collections import Counter

import yaml

from lailara_engagement import (
    ColumnSpec,
    PreflightSpec,
    build_provenance,
    load_config,
    read_table,
    run_preflight,
    validation_status_label,
    write_report,
)
from lailara_engagement import palette as P
from lailara_engagement.provenance import Provenance

import dimension_physics as phys

TOOL = "dimension-weight-integrity"
TOOL_VERSION = "1.0"

REPO_ROOT = pathlib.Path(__file__).parent
CONFIG_PATH = REPO_ROOT / "config" / "cost_params.yml"


def _spec() -> PreflightSpec:
    """The item-master fields the physical-attribute engine consumes.

    Required = SKU + the four fields freight class is computed from. Optional fields
    are used when present and disclosed as skipped when absent.
    """
    return PreflightSpec(
        tool=TOOL,
        version=TOOL_VERSION,
        columns=[
            ColumnSpec("sku", dtype="identifier", required=True, unique=True,
                       description="row key; the SKU/item number",
                       spec_ref="INPUT-SPEC §1"),
            ColumnSpec("case_length_in", dtype="number", required=True, not_negative=True,
                       description="case length in inches", spec_ref="INPUT-SPEC §2"),
            ColumnSpec("case_width_in", dtype="number", required=True, not_negative=True,
                       description="case width in inches", spec_ref="INPUT-SPEC §2"),
            ColumnSpec("case_height_in", dtype="number", required=True, not_negative=True,
                       description="case height in inches", spec_ref="INPUT-SPEC §2"),
            ColumnSpec("case_gross_weight_lb", dtype="number", required=True, not_negative=True,
                       description="case gross weight in pounds", spec_ref="INPUT-SPEC §2"),
            # Optional columns allow blanks: present-but-partly-empty is normal for
            # them (e.g. DTC weight only on DTC-sold SKUs), so a blank cell is not a
            # readiness finding. Non-blank cells are still type-checked.
            ColumnSpec("product_name", dtype="string", required=False, allow_blank=True,
                       spec_ref="INPUT-SPEC §optional"),
            ColumnSpec("gtin", dtype="identifier", required=False, allow_blank=True,
                       spec_ref="INPUT-SPEC §optional"),
            ColumnSpec("unit_net_weight_lb", dtype="number", required=False, allow_blank=True,
                       not_negative=True, spec_ref="INPUT-SPEC §3"),
            ColumnSpec("case_pack_qty", dtype="integer", required=False, allow_blank=True,
                       spec_ref="INPUT-SPEC §optional"),
            ColumnSpec("dtc_parcel_gross_lb", dtype="number", required=False, allow_blank=True,
                       not_negative=True, spec_ref="INPUT-SPEC §3"),
        ],
    )


def _load_parcel_params() -> tuple[float, float]:
    """DTC box size and DIM divisor from config (used only for the optional parcel check)."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    parcel = cfg["parcel"]
    return float(parcel["dtc_parcel_box_in"]), float(parcel["dim_divisor"])


def _num(value):
    """Parse a numeric cell (all cells are text). Blank/unparseable -> None."""
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def compute_rows(read, mapping, *, box_in, dim_divisor):
    """Run the physics engine per row on validated input. Returns (rows, summary)."""
    frame = read.frame
    col = mapping  # canonical -> resolved client header

    def cell(canonical, i):
        header = col.get(canonical)
        if header is None:
            return None
        return frame[header].iloc[i]

    rows = []
    n = len(frame)
    for i in range(n):
        sku = str(cell("sku", i)).strip()
        length = _num(cell("case_length_in", i))
        width = _num(cell("case_width_in", i))
        height = _num(cell("case_height_in", i))
        gross = _num(cell("case_gross_weight_lb", i))

        rec = {
            "sku": sku,
            "product_name": (str(cell("product_name", i)).strip()
                             if col.get("product_name") else ""),
            "case_length_in": length,
            "case_width_in": width,
            "case_height_in": height,
            "case_gross_weight_lb": gross,
            "case_cube_ft3": None,
            "density_lb_per_ft3": None,
            "freight_class": None,
            "dtc_billable_weight_lb": None,
            "parcel_reweigh_flag": False,
            "note": "",
        }

        if None in (length, width, height) or (length == 0 or width == 0 or height == 0):
            rec["note"] = "missing/zero case dimension — cube, density and freight class not computable"
            rows.append(rec)
            continue

        cube = phys.cube_ft3(length, width, height)
        rec["case_cube_ft3"] = round(cube, 5)
        if gross is None:
            rec["note"] = "missing case gross weight — density and freight class not computable"
            rows.append(rec)
            continue

        density = phys.density_lb_per_ft3(gross, cube)
        rec["density_lb_per_ft3"] = round(density, 2)
        rec["freight_class"] = phys.density_to_nmfc_class(density)

        # Optional DTC parcel billable-weight check: only when a DTC parcel gross
        # weight is supplied. DIM weight uses the per-unit DTC box, never the case.
        parcel_gross = _num(cell("dtc_parcel_gross_lb", i)) if col.get("dtc_parcel_gross_lb") else None
        unit_net = _num(cell("unit_net_weight_lb", i)) if col.get("unit_net_weight_lb") else None
        if parcel_gross is not None:
            dim_wt = phys.dim_weight_lb(box_in, box_in, box_in, dim_divisor)
            billable = phys.billable_weight_lb(parcel_gross, dim_wt)
            rec["dtc_billable_weight_lb"] = billable
            # Reweigh exposure: the listed net understates the billable parcel weight.
            if unit_net is not None and billable > unit_net:
                rec["parcel_reweigh_flag"] = True

        rows.append(rec)

    computed = [r for r in rows if r["freight_class"] is not None]
    summary = {
        "total_skus": len(rows),
        "computed": len(computed),
        "uncomputable": len(rows) - len(computed),
        "class_distribution": dict(sorted(Counter(
            r["freight_class"] for r in computed
        ).items())),
        "parcel_reweigh_exposed": sum(1 for r in rows if r["parcel_reweigh_flag"]),
    }
    return rows, summary


def _csv_report(rows) -> str:
    buf = io.StringIO()
    fields = ["sku", "product_name", "case_length_in", "case_width_in", "case_height_in",
              "case_gross_weight_lb", "case_cube_ft3", "density_lb_per_ft3", "freight_class",
              "dtc_billable_weight_lb", "parcel_reweigh_flag", "note"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    return buf.getvalue()


def _css(draft: bool) -> str:
    draft_css = (
        ".ll-draft::before{content:'DRAFT';position:fixed;top:50%;left:50%;"
        "transform:translate(-50%,-50%) rotate(-32deg);font-family:var(--s);"
        "font-size:22vw;font-weight:700;color:rgba(204,16,10,.06);z-index:0;"
        "pointer-events:none;white-space:nowrap}" if draft else ""
    )
    return f"""
:root{{--s:{P.LL_SERIF};--f:{P.LL_SANS}}}
*{{box-sizing:border-box}}
body{{margin:0;background:{P.LL_CANVAS};color:{P.LL_TEXT};font-family:var(--f);line-height:1.6}}
.ll-page{{position:relative;z-index:1;max-width:{P.LL_MAX_WIDTH};margin:0 auto;padding:48px 24px}}
.ll-header{{border-bottom:1px solid {P.LL_GRIDLINE};padding-bottom:24px;margin-bottom:24px}}
.ll-eyebrow{{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:{P.LL_RED};font-weight:600}}
.ll-title{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:34px;margin:8px 0 16px}}
.ll-client{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 24px;font-size:14px}}
.ll-k{{display:block;color:{P.LL_TEXT_SEC};font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.ll-banner{{border-radius:2px;padding:16px 20px;margin-bottom:32px;background:{P.LL_HK_SURFACE};color:{P.LL_HK_DARK}}}
.ll-score{{font-family:var(--s);font-weight:700;font-size:22px}}
.ll-h2{{font-family:var(--s);font-weight:700;color:{P.LL_INK};font-size:22px;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.ll-table{{width:100%;border-collapse:collapse;font-size:14px}}
.ll-table th{{text-align:left;background:{P.LL_CHICAGO};color:#fff;padding:8px 12px}}
.ll-table td{{padding:8px 12px;border-bottom:1px solid {P.LL_GRIDLINE}}}
.mono{{font-family:ui-monospace,Consolas,monospace;font-size:12px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.ll-note{{font-size:13px;color:{P.LL_TEXT_SEC};margin:8px 0 24px}}
.ll-provenance{{margin-top:40px;background:{P.LL_CARD_BG};color:{P.LL_CARD_TEXT};padding:20px 24px;border-radius:2px;font-size:13px}}
.ll-prov-title{{font-family:var(--s);font-weight:700;font-size:16px;margin-bottom:8px}}
.ll-provenance div{{margin-bottom:4px;color:{P.LL_CARD_SUBTITLE}}}
.ll-provenance strong{{color:{P.LL_CARD_TEXT}}}
.ll-prov-inputs{{width:100%;border-collapse:collapse;margin-top:8px}}
.ll-prov-inputs th{{text-align:left;border-bottom:1px solid rgba(255,255,255,.12);padding:4px 8px;color:{P.LL_CARD_MUTED}}}
.ll-prov-inputs td{{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,.08);color:{P.LL_CARD_SUBTITLE}}}
.ll-prov-brand{{margin-top:12px;font-family:var(--s);color:{P.LL_CARD_MUTED}}}
{draft_css}
@media print{{body{{background:#fff}}}}
"""


def _summary_html(config, summary, rows, provenance: Provenance, *, box_in, dim_divisor,
                  draft: bool) -> str:
    esc = html.escape
    draft_class = "ll-draft" if draft else ""

    class_rows = "".join(
        f"<tr><td class=mono>Class {esc(str(int(c) if float(c).is_integer() else c))}</td>"
        f"<td class=num>{n}</td></tr>"
        for c, n in summary["class_distribution"].items()
    ) or "<tr><td colspan=2>No freight classes computed.</td></tr>"

    # Show the first rows that could not be computed, so exclusions are visible.
    excluded = [r for r in rows if r["freight_class"] is None]
    excl_rows = "".join(
        f"<tr><td class=mono>{esc(r['sku'])}</td><td>{esc(r['note'])}</td></tr>"
        for r in excluded[:15]
    )
    excl_section = (
        f"<section class=ll-section><h2 class=ll-h2>Rows not computable "
        f"({len(excluded)})</h2><p class=ll-note>These rows are excluded from the "
        f"freight-class distribution above and disclosed here rather than assumed.</p>"
        f"<table class=ll-table><thead><tr><th>SKU</th><th>Reason</th></tr></thead>"
        f"<tbody>{excl_rows}</tbody></table></section>"
        if excluded else ""
    )

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Dimension &amp; Weight Readiness — {esc(config.client_name)}</title>
<style>{_css(draft)}</style></head>
<body class="{draft_class}"><main class=ll-page>
<header class=ll-header>
  <div class=ll-eyebrow>Lailara LLC · Dimension &amp; Weight Integrity</div>
  <h1 class=ll-title>Physical Attribute Readiness Summary</h1>
  <div class=ll-client>
    <div><span class=ll-k>Client</span> {esc(config.client_name)}</div>
    <div><span class=ll-k>Engagement</span> {esc(config.engagement_id)}</div>
    <div><span class=ll-k>As of</span> {esc(config.as_of_date.isoformat())}</div>
  </div>
</header>
<section class=ll-banner>
  <div class=ll-score>{summary['computed']:,} of {summary['total_skus']:,} SKUs measured</div>
  <div>Freight class computed from case dimensions and gross weight (density → NMFC).</div>
</section>
<section class=ll-section>
  <h2 class=ll-h2>Batch summary</h2>
  <table class=ll-table>
    <tr><td>Item-master rows</td><td class=num>{summary['total_skus']:,}</td></tr>
    <tr><td>Freight class computed</td><td class=num>{summary['computed']:,}</td></tr>
    <tr><td>Not computable (missing dims/weight)</td><td class=num>{summary['uncomputable']:,}</td></tr>
    <tr><td>DTC parcel reweigh exposure</td><td class=num>{summary['parcel_reweigh_exposed']:,}</td></tr>
  </table>
  <p class=ll-note>Physics computed, not asserted: cube = L×W×H/1728; density =
  gross/cube; NMFC class from the density scale. DTC billable weight uses a
  {esc(f'{box_in:g}')}-inch box and DIM divisor {esc(f'{dim_divisor:g}')} from
  config/cost_params.yml. Rate tables and annual volumes are not applied on this
  single-file path — dollar-cost lanes need the four-system divergence the pipeline builds.</p>
</section>
<section class=ll-section>
  <h2 class=ll-h2>Freight class distribution</h2>
  <table class=ll-table><thead><tr><th>NMFC class</th><th>SKUs</th></tr></thead>
  <tbody>{class_rows}</tbody></table>
</section>
{excl_section}
{provenance.to_html()}
</main></body></html>"""


def run(config_path: str, input_path: str, out_dir: str, *, final: bool = False) -> dict:
    config = load_config(config_path)
    read = read_table(input_path)
    spec = _spec()
    report = run_preflight(read, spec, config)

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    provenance = build_provenance(
        tool=TOOL, tool_version=TOOL_VERSION, inputs=[read], config=config,
        validation_status=validation_status_label(report.status, report.n_warnings),
    )

    # Preflight gate: a missing required column -> Data Readiness Report, no results.
    if not report.passed:
        paths = write_report(report, config, str(out), provenance=provenance,
                             draft=not final, basename="data-readiness-report",
                             title="Dimension & Weight Data Readiness Report")
        return {"status": "blocked", "readiness_report": paths["html"], "report": paths["html"]}

    box_in, dim_divisor = _load_parcel_params()
    rows, summary = compute_rows(read, report.column_mapping, box_in=box_in, dim_divisor=dim_divisor)

    csv_path = out / "dimension-readiness.csv"
    csv_path.write_text(_csv_report(rows), encoding="utf-8")

    summary_path = out / "dimension-readiness-summary.html"
    summary_path.write_text(
        _summary_html(config, summary, rows, provenance,
                      box_in=box_in, dim_divisor=dim_divisor, draft=not final),
        encoding="utf-8",
    )

    return {
        "status": "ok",
        "total": summary["total_skus"],
        "computed": summary["computed"],
        "uncomputable": summary["uncomputable"],
        "csv": str(csv_path),
        "report": str(summary_path),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dimension client mode",
                                 description="Validate a client item master and compute "
                                             "physical-attribute readiness in engagement mode.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="client-output")
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args(argv)
    result = run(args.config, args.input, args.out, final=args.final)
    if result["status"] == "blocked":
        print(f"BLOCKED — data not ready. See {result['readiness_report']}")
        return 3
    print(f"measured {result['computed']}/{result['total']} SKUs "
          f"({result['uncomputable']} not computable)")
    print(f"report -> {result['report']}\ncsv    -> {result['csv']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
