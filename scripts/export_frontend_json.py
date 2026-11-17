"""Export dbt mart data to static JSON for the frontend.

Queries Postgres marts and produces hero.json (one showcased SKU) and
all_skus.json (portfolio roll-up). The frontend displays these precomputed
values; it does not recompute freight physics client-side.

Usage:
    python scripts/export_frontend_json.py
    python scripts/export_frontend_json.py --output-dir frontend/src/data
"""

import argparse
import decimal
import json
import pathlib

import psycopg2.extras

from data_gen.shared import get_db_connection


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super().default(obj)


MART_GOVERNED_MASTER = "dimension_weight_integrity.fct_governed_product_master"
MART_DIVERGENCE = "dimension_weight_integrity.fct_attribute_divergence"
MART_FREIGHT_CLASS = "dimension_weight_integrity.fct_freight_class_by_system"
MART_COSTS = "dimension_weight_integrity.fct_dimension_cost"


def query_mart(cur, table, sku=None):
    """Select all rows from a mart table, optionally filtered to one SKU.

    `table` is a trusted internal constant (one of the MART_* names), not
    user input, so interpolating it into the query is safe.
    """
    query = f"select * from {table}"
    if sku:
        cur.execute(query + " where sku = %s", (sku,))
    else:
        cur.execute(query)
    return [dict(row) for row in cur.fetchall()]


def build_hero_json(cur, hero_sku):
    master = query_mart(cur, MART_GOVERNED_MASTER, hero_sku)
    if not master:
        raise ValueError(f"Hero SKU {hero_sku} not found in governed master")
    master = master[0]

    divergence = query_mart(cur, MART_DIVERGENCE, hero_sku)
    freight = query_mart(cur, MART_FREIGHT_CLASS, hero_sku)
    costs = query_mart(cur, MART_COSTS, hero_sku)

    systems = {}
    for row in divergence:
        sys = row["system"]
        if sys not in systems:
            systems[sys] = {"system": sys, "divergences": []}
        systems[sys]["divergences"].append({
            "field": row["field"],
            "system_value": row["system_value"],
            "mor_value": row["mor_value"],
            "abs_delta": row["abs_delta"],
            "pct_delta": row["pct_delta"],
            "flagged": row["flagged"],
        })

    freight_by_system = {}
    for row in freight:
        freight_by_system[row["system"]] = {
            "density": row["density_lb_per_ft3"],
            "freight_class": row["freight_class"],
        }

    cost_by_driver = {}
    for row in costs:
        cost_by_driver[row["cost_driver"]] = {
            "per_unit_delta": row["per_unit_delta"],
            "annual_units": row["annual_units"],
            "annual_cost": row["annual_cost"],
            "basis": row["basis"],
        }

    return {
        "hero_sku": {
            "sku": master["sku"],
            "product_name": master["product_name"],
            "measurement_of_record": {
                "source": master["mor_source"],
                "case_gross_weight_lb": master["case_gross_weight_lb"],
                "case_length_in": master["case_length_in"],
                "case_width_in": master["case_width_in"],
                "case_height_in": master["case_height_in"],
                "case_cube_ft3": master["case_cube_ft3"],
                "density_lb_per_ft3": master["density_lb_per_ft3"],
                "freight_class": master["freight_class"],
            },
            "systems": list(systems.values()),
            "freight_by_system": freight_by_system,
        },
        "cost": cost_by_driver,
        "paradox": {
            "ops_fix": {
                "description": "Align GDSN dimensions to physical case measurements",
                "effect": "Retail freight class improves; DTC parcel leak unchanged",
            },
            "dtc_fix": {
                "description": "Correct Shopify weight to actual parcel gross weight",
                "effect": "Parcel back-billing eliminated; quoted shipping cost rises",
            },
        },
    }


def build_all_skus_json(cur):
    masters = query_mart(cur, MART_GOVERNED_MASTER)
    costs = query_mart(cur, MART_COSTS)
    divergences = query_mart(cur, MART_DIVERGENCE)
    freight = query_mart(cur, MART_FREIGHT_CLASS)

    cost_by_sku = {}
    for row in costs:
        sku = row["sku"]
        if sku not in cost_by_sku:
            cost_by_sku[sku] = {"drivers": {}, "total_annual_cost": 0}
        cost_by_sku[sku]["drivers"][row["cost_driver"]] = {
            "per_unit_delta": row["per_unit_delta"],
            "annual_units": row["annual_units"],
            "annual_cost": row["annual_cost"],
        }
        cost_by_sku[sku]["total_annual_cost"] += float(row["annual_cost"] or 0)

    # GDSN freight class per SKU, for the true class-mismatch count below.
    gdsn_class_by_sku = {
        row["sku"]: row["freight_class"] for row in freight if row["system"] == "gdsn"
    }

    div_by_sku = {}
    for row in divergences:
        sku = row["sku"]
        if sku not in div_by_sku:
            div_by_sku[sku] = []
        div_by_sku[sku].append({
            "system": row["system"],
            "field": row["field"],
            "abs_delta": row["abs_delta"],
            "flagged": row["flagged"],
        })

    skus = []
    for m in masters:
        sku = m["sku"]
        sku_cost = cost_by_sku.get(sku, {"drivers": {}, "total_annual_cost": 0})
        skus.append({
            "sku": sku,
            "product_name": m["product_name"],
            "case_gross_weight_lb": m["case_gross_weight_lb"],
            "freight_class": m["freight_class"],
            "density_lb_per_ft3": m["density_lb_per_ft3"],
            "cost": sku_cost,
            "divergence_count": len([d for d in div_by_sku.get(sku, []) if d["flagged"]]),
        })

    # Count every SKU whose GDSN-published freight class differs from the
    # measurement-of-record class — not just the ones that cost money. A
    # DOWNWARD class shift is a real data mismatch but its LTL cost floors at 0
    # (fct_dimension_cost.sql), so counting cost > 0 undercounts mismatches and
    # contradicts the "SKUs with freight class mismatch" label the UI shows.
    class_mismatch_count = sum(
        1 for m in masters
        if gdsn_class_by_sku.get(m["sku"]) is not None
        and gdsn_class_by_sku[m["sku"]] != m["freight_class"]
    )

    return {
        "skus": skus,
        "aggregate": {
            "total_annual_cost": sum(s["cost"]["total_annual_cost"] for s in skus),
            "skus_with_class_mismatch": class_mismatch_count,
            "total_skus": len(skus),
        },
    }


def export(output_dir, hero_sku):
    conn = get_db_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            hero_data = build_hero_json(cur, hero_sku)
            all_skus_data = build_all_skus_json(cur)
    finally:
        conn.close()

    output_path = pathlib.Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    hero_path = output_path / "hero.json"
    with open(hero_path, "w", encoding="utf-8") as f:
        json.dump(hero_data, f, cls=DecimalEncoder, indent=2)

    all_path = output_path / "all_skus.json"
    with open(all_path, "w", encoding="utf-8") as f:
        json.dump(all_skus_data, f, cls=DecimalEncoder, indent=2)

    print(f"Exported hero.json ({hero_path.stat().st_size} bytes)")
    print(f"Exported all_skus.json ({all_path.stat().st_size} bytes)")
    return hero_path, all_path


def main():
    from data_gen.shared import HERO_SKU_ID

    parser = argparse.ArgumentParser(description="Export frontend JSON from dbt marts")
    parser.add_argument(
        "--output-dir",
        default="frontend/src/data",
        help="Output directory for JSON files",
    )
    args = parser.parse_args()
    export(args.output_dir, HERO_SKU_ID)


if __name__ == "__main__":
    main()
