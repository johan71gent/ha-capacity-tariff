"""Built-in tariff table."""

from custom_components.capacity_tariff.core.tariffs import (
    CAPACITY_TARIFFS_EXCL_VAT,
    NET_AREAS,
    VAT_RATE,
    available_years,
    lookup_tariff,
)


def test_table_complete_for_every_year():
    for year, table in CAPACITY_TARIFFS_EXCL_VAT.items():
        assert set(table) == set(NET_AREAS), year
        assert all(20 < v < 200 for v in table.values()), year


def test_lookup_incl_vat_matches_invoice_values():
    # Fluvius West 2026: 57.0995726 excl. -> 60.53 incl. 6 %
    tariff, year = lookup_tariff("fluvius_west", 2026)
    assert year == 2026
    assert round(tariff, 2) == 60.53
    excl, _ = lookup_tariff("fluvius_west", 2026, incl_vat=False)
    assert round(excl * (1 + VAT_RATE), 2) == round(tariff, 2)


def test_lookup_falls_back_to_latest_known_year():
    latest = available_years()[-1]
    assert lookup_tariff("fluvius_imewo", latest + 5)[1] == latest
    # before the first year: use the earliest available rather than nothing
    assert lookup_tariff("fluvius_imewo", 2000)[1] == available_years()[0]


def test_lookup_unknown_area():
    assert lookup_tariff(None, 2026) is None
    assert lookup_tariff("mars", 2026) is None
