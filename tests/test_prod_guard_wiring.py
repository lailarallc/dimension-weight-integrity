"""The prod guard sits in front of every write path to Postgres.

`load_raw` drops and recreates raw tables and `dbt build` writes marts, both at
localhost:5432 by default -- a `fly proxy` tunnel to production when one is open.
These tests fake a flyctl listener and assert nothing connects.
"""

import importlib.util
import pathlib

import pytest

from data_gen import prod_guard, shared

ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture
def fly_tunnel(monkeypatch):
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setattr(prod_guard, "_listener", lambda port: "flyctl")


def test_get_db_connection_refuses_fly_tunnel(fly_tunnel, monkeypatch):
    monkeypatch.setattr(shared.psycopg2, "connect", lambda **kw: pytest.fail("connected"))
    with pytest.raises(prod_guard.ProdDatabaseError):
        shared.get_db_connection()


def test_get_db_connection_guards_the_configured_port(monkeypatch):
    seen = []
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setenv("CINDERHAVEN_DB_PORT", "15432")
    monkeypatch.setattr(prod_guard, "_listener", lambda port: seen.append(port) or "flyctl")
    with pytest.raises(prod_guard.ProdDatabaseError):
        shared.get_db_connection()
    assert seen == [15432]


def test_dbt_build_refuses_before_running_dbt(fly_tunnel, monkeypatch):
    dagster = pytest.importorskip("dagster")
    spec = importlib.util.spec_from_file_location("dwi_assets", ROOT / "dagster" / "assets.py")
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)
    monkeypatch.setattr(assets.subprocess, "run", lambda *a, **kw: pytest.fail("dbt ran"))
    with pytest.raises(prod_guard.ProdDatabaseError):
        assets.dbt_build(dagster.build_asset_context())
