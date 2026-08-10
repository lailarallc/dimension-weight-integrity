"""Demo golden-file lock.

The deployed demo (dimensions.lailarallc.com) renders the committed JSON exports
in frontend/src/data/. The full pipeline that produces them needs Postgres + the
four system extracts, so it cannot be reproduced in a plain checkout — which is
exactly why the demo output must be pinned as a golden here. If any headline
figure the live site shows drifts during the client-mode conversion, this fails.

Two layers:
  1. A byte-level SHA-256 lock on each exported file (catches ANY drift).
  2. Explicit, human-readable golden figures (says WHAT changed when it breaks).

Other suites (test_readme_figures, test_e2e_reconciliation, test_cost_math)
assert these numbers foot against each other and the prose. This suite instead
freezes them as literals, so "the demo is bit-for-bit unchanged" is a single,
independent guarantee rather than an emergent property of the other checks.
"""

import hashlib
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "frontend" / "src" / "data"

# Byte-level lock. Regenerate deliberately (and update these) only when the demo
# is intended to change — never silently.
GOLDEN_SHA256 = {
    "hero.json": "9cee4493226f7a4cf091c2a95b09deda3ed120c049c83d4d784280ed8d4bfee0",
    "all_skus.json": "01d736be4ece8153754d21e5e3ed577441dc0f384f9a2b1f779e3dbfa84dc628",
}


@pytest.fixture(scope="module")
def hero():
    return json.loads((DATA_DIR / "hero.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def all_skus():
    return json.loads((DATA_DIR / "all_skus.json").read_text(encoding="utf-8"))


class TestExportBytesAreLocked:
    """A checksum lock: the deployed JSON must be byte-identical to the golden."""

    @pytest.mark.parametrize("name", ["hero.json", "all_skus.json"])
    def test_exported_file_sha256_is_locked(self, name):
        actual = hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest()
        assert actual == GOLDEN_SHA256[name], (
            f"{name} changed (sha256 {actual[:16]}...). If this is an intended "
            f"demo change, update GOLDEN_SHA256 and the figures below in the same "
            f"commit; otherwise the demo has drifted and must be restored."
        )


class TestHeroFiguresAreLocked:
    """The hero SKU (CHP-AS-002) numbers the story is built around."""

    def test_hero_identity(self, hero):
        assert hero["hero_sku"]["sku"] == "CHP-AS-002"
        assert hero["hero_sku"]["product_name"] == "Roasted Garlic Marinara"

    def test_measurement_of_record_physics(self, hero):
        mor = hero["hero_sku"]["measurement_of_record"]
        assert mor["source"] == "wms"
        assert mor["case_cube_ft3"] == 0.29052734375
        assert mor["density_lb_per_ft3"] == 74.00336134453782
        assert mor["freight_class"] == 50.0

    def test_gdsn_reclassification(self, hero):
        gdsn = hero["hero_sku"]["freight_by_system"]["gdsn"]
        assert gdsn["density"] == 37.97802197802198
        assert gdsn["freight_class"] == 55.0

    def test_cost_drivers(self, hero):
        assert hero["cost"]["ltl_reclass"]["per_unit_delta"] == 0.39
        assert hero["cost"]["ltl_reclass"]["annual_units"] == 10851.0
        assert hero["cost"]["ltl_reclass"]["annual_cost"] == 4231.89
        assert hero["cost"]["parcel_reweigh"]["annual_cost"] == 394.0
        assert hero["cost"]["compliance_cb"]["annual_cost"] == 240.0

    def test_hero_total(self, hero):
        total = sum(d["annual_cost"] for d in hero["cost"].values())
        assert total == 4865.89


class TestPortfolioFiguresAreLocked:
    """The 50-SKU roll-up shown on the portfolio panel."""

    def test_aggregate(self, all_skus):
        agg = all_skus["aggregate"]
        assert agg["total_annual_cost"] == 208310.87
        assert agg["skus_with_class_mismatch"] == 27
        assert agg["total_skus"] == 50
        assert len(all_skus["skus"]) == 50
