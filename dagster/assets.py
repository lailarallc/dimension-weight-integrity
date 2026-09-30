"""Dagster assets for the dimension & weight integrity pipeline.

Asset graph: generate_source_extracts → load_raw → dbt_build → export_frontend_json
"""

import pathlib
import subprocess

from dagster import asset, AssetExecutionContext

from data_gen import prod_guard
from data_gen.shared import db_host_port, get_db_connection, load_csvs_to_raw, RAW_TABLES, DATA_DIR


PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DBT_DIR = PROJECT_ROOT / "dbt"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "src" / "data"



@asset(description="Generate synthetic dimension divergence CSVs for 50 SKUs × 4 systems")
def generate_source_extracts(context: AssetExecutionContext):
    result = subprocess.run(
        ["python", "-m", "data_gen.generate_dimension_mess"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Data generation failed: {result.stderr}")
    context.log.info(result.stdout.strip())
    return {f: str(DATA_DIR / f) for f in RAW_TABLES.values()}


@asset(deps=[generate_source_extracts], description="Load generated CSVs into Postgres raw tables")
def load_raw(context: AssetExecutionContext):
    conn = get_db_connection()
    try:
        load_csvs_to_raw(conn, DATA_DIR, RAW_TABLES, log=context.log.info)
    finally:
        conn.close()
    context.log.info(f"Loaded {len(RAW_TABLES)} raw tables")


@asset(deps=[load_raw], description="Run dbt build (models + tests)")
def dbt_build(context: AssetExecutionContext):
    host, port = db_host_port()
    prod_guard.check(host=host, port=port)  # dbt connects on its own; guard before it runs
    result = subprocess.run(
        ["dbt", "build", "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR)],
        capture_output=True, text=True, cwd=str(DBT_DIR),
    )
    context.log.info(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"dbt build failed: {result.stderr}")


@asset(deps=[dbt_build], description="Export dbt marts to frontend JSON files")
def export_frontend_json(context: AssetExecutionContext):
    result = subprocess.run(
        ["python", "scripts/export_frontend_json.py", "--output-dir", str(FRONTEND_DATA_DIR)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Export failed: {result.stderr}")
    context.log.info(result.stdout.strip())
