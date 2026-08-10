"""Physical-attribute computations for a case: cube, density, NMFC freight class,
parcel DIM weight, billable weight.

These are physics and published standards — computed, never asserted (per CLAUDE.md,
the "exact vs parameter split is the credibility core"). The pipeline computes the
same quantities in dbt macros; this pure-Python module lets client mode run the same
math on a client's item master without a database.

The NMFC density scale here MUST match dbt/macros/density_to_nmfc_class.sql and the
canonical band table in tests/test_cost_math.py. tests/test_client_mode.py parses the
dbt macro and asserts this module agrees, so a third copy cannot silently drift.
"""

from __future__ import annotations

import math

# Canonical NMFC density -> freight-class scale. A CASE returns the FIRST match,
# so order (descending threshold) is load-bearing.
NMFC_BANDS: list[tuple[float, float]] = [
    (50.0, 50), (35.0, 55), (30.0, 60), (22.5, 65),
    (15.0, 70), (13.5, 77.5), (12.0, 85), (10.5, 92.5),
    (9.0, 100), (8.0, 110), (7.0, 125), (6.0, 150),
    (5.0, 175), (4.0, 200), (3.0, 250), (2.0, 300),
    (1.0, 400),
]
NMFC_FALLBACK_CLASS: float = 500


def cube_ft3(length_in: float, width_in: float, height_in: float) -> float:
    """Case cube in cubic feet from inch dimensions."""
    return (length_in * width_in * height_in) / 1728.0


def density_lb_per_ft3(weight_lb: float, cube: float) -> float:
    """Density = weight / cube. Caller guards cube > 0."""
    return weight_lb / cube


def density_to_nmfc_class(density: float) -> float:
    """Map density (lb/ft^3) to an NMFC freight class."""
    for threshold, nmfc_class in NMFC_BANDS:
        if density >= threshold:
            return nmfc_class
    return NMFC_FALLBACK_CLASS


def dim_weight_lb(length_in: float, width_in: float, height_in: float, divisor: float) -> float:
    """Dimensional weight: each dimension is rounded UP to the next inch (carrier rule)."""
    return (math.ceil(length_in) * math.ceil(width_in) * math.ceil(height_in)) / divisor


def billable_weight_lb(actual_weight: float, dim_weight: float) -> int:
    """Billable weight: the greater of actual and DIM, rounded up to the next pound."""
    return math.ceil(max(actual_weight, dim_weight))
