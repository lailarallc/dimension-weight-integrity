"""Constants, RNG helpers, and DB connection for data generation."""

import csv
import decimal
import os
import pathlib

import psycopg2
import psycopg2.extras
from psycopg2 import sql

from data_gen import prod_guard

SEED = 42

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "generated"

HERO_SKU_ID = "CHP-AS-002"

# Raw source tables loaded from generated CSVs (shared by the standalone
# load_raw script and the Dagster load_raw asset).
RAW_TABLES = {
    "netsuite_items": "netsuite_items.csv",
    "wms_dimensions": "wms_dimensions.csv",
    "gdsn_published": "gdsn_published.csv",
    "shopify_products": "shopify_products.csv",
}

PRODUCT_MASTER_QUERY = """
    select
        sku,
        product_name,
        product_line,
        case_pack_qty,
        unit_weight_lbs,
        case_weight_lbs,
        case_length_in,
        case_width_in,
        case_height_in
    from raw.product_master
    where sku like 'CHP-%%'
    order by sku
"""


def load_csvs_to_raw(conn, data_dir, tables, log=print):
    """Load CSV files into Postgres raw tables as text columns.

    `tables` maps {table_name: csv_filename}. Each table is dropped (cascade,
    so dependent dbt views don't block the reload) and recreated from the CSV
    header, then populated. Commits after each table. The caller owns the
    connection's lifecycle (open/close).
    """
    with conn.cursor() as cur:
        for table_name, csv_file in tables.items():
            with open(pathlib.Path(data_dir) / csv_file, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                columns = reader.fieldnames
                tbl = sql.Identifier(table_name)
                col_ids = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
                col_defs = sql.SQL(", ").join(
                    sql.SQL("{} text").format(sql.Identifier(c)) for c in columns
                )
                cur.execute(sql.SQL("drop table if exists {} cascade").format(tbl))
                cur.execute(sql.SQL("create table {} ({})").format(tbl, col_defs))
                placeholders = sql.SQL(", ").join(sql.Placeholder() * len(columns))
                insert_stmt = sql.SQL("insert into {} ({}) values ({})").format(
                    tbl, col_ids, placeholders
                )
                rows_loaded = 0
                for row in reader:
                    cur.execute(insert_stmt, [row[c] for c in columns])
                    rows_loaded += 1
            conn.commit()
            log(f"Loaded {table_name}: {rows_loaded} rows")


def db_host_port():
    """Target Postgres host and port (shared by the connection and the dbt guard)."""
    return (os.environ.get("CINDERHAVEN_DB_HOST", "localhost"),
            int(os.environ.get("CINDERHAVEN_DB_PORT", "5432")))


def get_db_connection():
    host, port = db_host_port()
    prod_guard.check(host=host, port=port)  # refuses a fly tunnel to production
    return psycopg2.connect(
        host=host,
        port=port,
        user=os.environ.get("CINDERHAVEN_DB_USER", "postgres"),
        password=os.environ.get("CINDERHAVEN_DB_PASSWORD", ""),
        dbname=os.environ.get("CINDERHAVEN_DB_NAME", "cinderhaven"),
    )


def _coerce_numerics(row):
    """Convert Decimal/int to float for downstream arithmetic compatibility."""
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif k == "case_pack_qty" and v is not None:
            out[k] = int(v)
        else:
            out[k] = v
    return out


def fetch_product_master():
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(PRODUCT_MASTER_QUERY)
            return [_coerce_numerics(row) for row in cur.fetchall()]
    finally:
        conn.close()
