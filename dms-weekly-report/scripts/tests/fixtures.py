"""Shared test fixtures for dms-weekly-report tests."""

from core.bom_parser import BOMItem


# BOM fixture items
BOM_MODULE = BOMItem(code="M001", name="Sales module Trina TSM-415DE09RS 415W", qty=100, unit="pcs")
BOM_INVERTER = BOMItem(code="I001", name="Inverter SUN2000-50KTL-M3 50kW", qty=2, unit="set")
BOM_BATTERY = BOMItem(code="B001", name="Battery LG RESU10H 9.8kWh", qty=5, unit="set")

# Sample items list for aggregation tests
SAMPLE_BOM_ITEMS = [BOM_MODULE, BOM_INVERTER, BOM_BATTERY]


def compare_floats(a, b, tol=0.01):
    """Compare two floats within tolerance."""
    return abs(a - b) < tol
