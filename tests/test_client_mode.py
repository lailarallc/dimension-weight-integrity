"""Client-mode tests for dimension-weight-integrity: intake, preflight, engine, report.

Adversarial fixtures per checklist §6: missing required column (blocked path),
BOM + semicolon with an Excel-mangled leading-zero SKU read as text, and a clean
file that computes freight classes and renders a branded, provenance-footed report.
Plus a drift guard tying dimension_physics.py to the production dbt macro.

Skipped if lailara_engagement isn't installed.
"""

import pathlib
import re

import pytest

pytest.importorskip("lailara_engagement")

import client_mode  # noqa: E402
import dimension_physics as phys  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).parent.parent

_CONFIG = """
client: {name: Meridian Farms}
engagement: {id: MER-2026-08}
as_of_date: 2026-07-31
demo: true
columns:
  sku: "Item #"
  case_length_in: "Case L (in)"
  case_width_in: "Case W (in)"
  case_height_in: "Case H (in)"
  case_gross_weight_lb: "Case Wt (lb)"
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "engagement.demo.yml"
    p.write_text(_CONFIG, encoding="utf-8")
    return str(p)


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return str(p)


def test_clean_file_computes_and_reports(cfg, tmp_path):
    # One dense case (hero-like: class 50) and one light-for-size case.
    src = _write(
        tmp_path, "item_master.csv",
        "Item #,Case L (in),Case W (in),Case H (in),Case Wt (lb)\n"
        "SKU-1,11.25,8.5,5.25,21.5\n"      # density 74 -> class 50
        "SKU-2,20,20,20,3\n",             # density ~0.65 -> class 500
    )
    out = str(tmp_path / "client-output")
    result = client_mode.run(cfg, src, out)
    assert result["status"] == "ok"
    assert result["computed"] == 2
    assert result["uncomputable"] == 0

    csv_text = open(result["csv"], encoding="utf-8").read()
    assert ",50," in csv_text            # hero-like row scored class 50
    assert ",500," in csv_text           # light-for-size row scored class 500

    html = open(result["report"], encoding="utf-8").read()
    assert "Meridian Farms" in html      # client header block
    assert "#f5f3ee" in html             # branded canvas
    assert "SHA-256" in html             # provenance footer
    assert "DRAFT" in html               # draft watermark


def test_missing_required_column_is_blocked(cfg, tmp_path):
    # No case weight column maps -> Data Readiness Report, no results.
    src = _write(
        tmp_path, "bad.csv",
        "Item #,Case L (in),Case W (in),Case H (in)\nSKU-1,11.25,8.5,5.25\n",
    )
    out = str(tmp_path / "out")
    result = client_mode.run(cfg, src, out)
    assert result["status"] == "blocked"
    html = open(result["readiness_report"], encoding="utf-8").read()
    assert "case_gross_weight_lb" in html


def test_bom_semicolon_and_sku_as_text(cfg, tmp_path):
    # UTF-8 BOM + semicolon delimiter + a leading-zero SKU Excel would mangle to a number.
    body = (
        "﻿Item #;Case L (in);Case W (in);Case H (in);Case Wt (lb)\n"
        "0012345;11.25;8.5;5.25;21.5\n"
    )
    src = _write(tmp_path, "bom.csv", body)
    out = str(tmp_path / "out")
    result = client_mode.run(cfg, src, out)
    assert result["status"] == "ok"
    csv_text = open(result["csv"], encoding="utf-8").read()
    assert "0012345" in csv_text         # leading zero preserved as text end to end


def test_uncomputable_row_is_disclosed_not_assumed(cfg, tmp_path):
    # A zero dimension makes cube uncomputable; the row must be excluded and disclosed.
    src = _write(
        tmp_path, "item_master.csv",
        "Item #,Case L (in),Case W (in),Case H (in),Case Wt (lb)\n"
        "SKU-1,11.25,8.5,5.25,21.5\n"
        "SKU-2,0,8.5,5.25,21.5\n",
    )
    out = str(tmp_path / "out")
    result = client_mode.run(cfg, src, out)
    assert result["status"] == "ok"
    assert result["computed"] == 1
    assert result["uncomputable"] == 1
    html = open(result["report"], encoding="utf-8").read()
    assert "not computable" in html.lower()


def test_final_flag_drops_watermark(cfg, tmp_path):
    src = _write(
        tmp_path, "item_master.csv",
        "Item #,Case L (in),Case W (in),Case H (in),Case Wt (lb)\nSKU-1,11.25,8.5,5.25,21.5\n",
    )
    out = str(tmp_path / "out")
    result = client_mode.run(cfg, src, out, final=True)
    html = open(result["report"], encoding="utf-8").read()
    assert "ll-draft" not in html


# --- Drift guard: dimension_physics.py must match the production dbt macro ---


def test_physics_nmfc_table_matches_dbt_macro():
    """The client-mode Python physics and the dbt macro encode the same NMFC scale.

    dimension_physics.py is a third encoding of the density->class table (dbt macro
    and tests/test_cost_math.py are the others). Parse the macro's branches and
    assert this module returns the same class at each breakpoint, so a copy here
    cannot silently diverge from what the pipeline computes.
    """
    macro = (REPO_ROOT / "dbt" / "macros" / "density_to_nmfc_class.sql").read_text()
    body = re.sub(r"\{#.*?#\}", "", macro, flags=re.S)
    branches = re.findall(r"when\s+.+?>=\s*([0-9.]+)\s*then\s*([0-9.]+)", body)
    assert branches, "could not parse the dbt macro branches"

    macro_pairs = [(float(t), float(c)) for t, c in branches]
    module_pairs = [(t, float(c)) for t, c in phys.NMFC_BANDS]
    assert module_pairs == macro_pairs, "dimension_physics NMFC table drifted from the dbt macro"

    # Agreement at each breakpoint and just below the lowest (the fallback class).
    for threshold, expected_class in macro_pairs:
        assert phys.density_to_nmfc_class(threshold) == expected_class
    assert phys.density_to_nmfc_class(0.5) == phys.NMFC_FALLBACK_CLASS
    assert re.search(rf"else\s+{int(phys.NMFC_FALLBACK_CLASS)}\b", body)


def test_physics_hero_case_scores_class_50():
    """Sanity anchor: the hero case (11.25 x 8.5 x 5.25, 21.5 lb) is class 50."""
    cube = phys.cube_ft3(11.25, 8.5, 5.25)
    density = phys.density_lb_per_ft3(21.5, cube)
    assert round(density, 2) == 74.00
    assert phys.density_to_nmfc_class(density) == 50
