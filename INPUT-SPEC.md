# INPUT-SPEC — dimension-weight-integrity (client mode)

What to hand the physical-attribute readiness check in a client engagement. Written so
a client's IT/data person can produce the file without a call.

## The file

- **One item-master export: CSV or XLSX.** Read via `lailara_engagement`'s tolerant
  reader: UTF-8 / UTF-8-BOM / latin-1; comma / semicolon / tab; leading blank rows and
  trailing junk dropped; header whitespace trimmed; Excel dates/numbers rendered as text.
- **One row per SKU (per case configuration).** Extra columns are ignored.
- This is the client's item master — the case dimensions and weights one system holds.
  The full four-system divergence and cost model (ERP vs WMS vs GDSN vs DTC) is the dbt
  pipeline's job and takes four extracts; client mode validates one file and computes the
  per-SKU physical attributes (cube, density, freight class) it implies.

## Required columns

These are the fields freight class is computed from — the "case dimensions + weights" the
readiness check exists to validate. If any is missing, the run produces a **Data Readiness
Report** naming it instead of results.

| Canonical | Type | Required | Used for |
|---|---|---|---|
| `sku` | identifier (text) | yes | Row key; deduplicated and reported per SKU. §1 |
| `case_length_in` | number | yes | Case length (inches) → cube → density → freight class. §2 |
| `case_width_in` | number | yes | Case width (inches). §2 |
| `case_height_in` | number | yes | Case height (inches). §2 |
| `case_gross_weight_lb` | number (≥ 0) | yes | Case gross weight (lb) → density → freight class. §2 |

- **Identifiers read as text.** `sku` keeps leading zeros; a numeric-looking SKU is never
  parsed to a number.
- **Dimensions and weights are numeric and non-negative.** Zero or blank case dimensions
  make cube (and therefore density and freight class) uncomputable for that row; those rows
  are counted and disclosed, never silently assumed.

## Optional columns

Present → used; absent → skipped and disclosed. None blocks the run.

| Canonical | Type | Used for |
|---|---|---|
| `product_name` | string | Human label in the report. |
| `gtin` | identifier (text) | Carried through for cross-reference; not validated here (see the GTIN validator tool). |
| `unit_net_weight_lb` | number (≥ 0) | DTC parcel billable-weight check, when a DTC parcel gross weight is also supplied. §3 |
| `case_pack_qty` | integer | Units per case; reported for context. |
| `dtc_parcel_gross_lb` | number (≥ 0) | Actual DTC parcel weight → DIM/billable-weight vs listed net → parcel reweigh exposure. §3 |

## Column mapping (engagement.yml)

If the client's headers are not the canonical names, map them. A case/whitespace-insensitive
exact match (e.g. `Case Length (in)` → `case_length_in`) is auto-detected and disclosed;
anything else must be mapped here.

```yaml
client:
  name: "Meridian Farms"
engagement:
  id: "MER-2026-08"
as_of_date: "2026-07-31"
columns:
  sku: "Item #"
  case_length_in: "Case L (in)"
  case_width_in: "Case W (in)"
  case_height_in: "Case H (in)"
  case_gross_weight_lb: "Case Wt (lb)"
```

## Run

```bash
# with lailara_engagement installed: pip install -e ../engagement-template/lib
python client_mode.py --config engagement.yml --input client-data/item_master.csv \
    --out client-output [--final]
```

Outputs to `client-output/` (gitignored):
- `dimension-readiness-summary.html` — branded, provenance-footed (input SHA-256, row
  counts, `as_of_date`, config hash), DRAFT-watermarked until `--final`.
- `dimension-readiness.csv` — per-SKU cube, density, and freight class.
- or `data-readiness-report.html` if a required column is missing.

## What is computed vs configured

- **Computed (physics/standards, never asserted):** case cube, density, NMFC freight
  class, DTC DIM weight, billable weight. Same math as the dbt macros (`dimension_physics.py`).
- **Configured (`config/cost_params.yml`):** the DTC box size and DIM divisor used for the
  optional parcel check. Rate tables and annual volumes are **not** applied on the
  single-file client path — dollar-cost lanes need the four-system divergence the pipeline
  builds, so client mode reports physical readiness, not a cost estimate.
