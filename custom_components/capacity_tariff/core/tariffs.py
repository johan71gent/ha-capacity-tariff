"""Built-in capacity-tariff table per Flemish distribution area.

There is no API for these rates. The Vlaamse Nutsregulator publishes one tariff
sheet per distribution area every year (PDF/XLSX):
https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven

The value used is "Tarieven voor het netgebruik – afnameklanten op laagspanningsnet
met piekmeting – Gemiddelde maandpiek", in EUR/kW/year **excluding VAT**.
Households pay 6 % VAT on electricity, which is what the invoice shows.

Update this table once a year (new sheets appear in November/December).
"""

from __future__ import annotations

VAT_RATE = 0.06

#: Distribution areas (key -> label). Keys are stable config values.
NET_AREAS: dict[str, str] = {
    "fluvius_antwerpen": "Fluvius Antwerpen",
    "fluvius_halle_vilvoorde": "Fluvius Halle-Vilvoorde",
    "fluvius_imewo": "Fluvius Imewo",
    "fluvius_kempen": "Fluvius Kempen",
    "fluvius_limburg": "Fluvius Limburg",
    "fluvius_midden_vlaanderen": "Fluvius Midden-Vlaanderen",
    "fluvius_west": "Fluvius West",
    "fluvius_zenne_dijle": "Fluvius Zenne-Dijle",
}

#: year -> area -> EUR/kW/year excl. VAT (source: VREG tariff sheets "<area> - <year> - ELEK").
CAPACITY_TARIFFS_EXCL_VAT: dict[int, dict[str, float]] = {
    2026: {
        "fluvius_antwerpen": 49.4036563,
        "fluvius_halle_vilvoorde": 56.0428955,
        "fluvius_imewo": 54.2009816,
        "fluvius_kempen": 56.2069857,
        "fluvius_limburg": 49.0469384,
        "fluvius_midden_vlaanderen": 50.1239818,
        "fluvius_west": 57.0995726,
        "fluvius_zenne_dijle": 56.1228635,
    },
}


def available_years() -> list[int]:
    """Years present in the table, ascending."""
    return sorted(CAPACITY_TARIFFS_EXCL_VAT)


def lookup_tariff(area: str | None, year: int, incl_vat: bool = True) -> tuple[float, int] | None:
    """Tariff for ``area`` in ``year`` as (EUR/kW/year, year_used).

    Falls back to the most recent year that is available (sheets for a new year
    appear late in the previous year), so the integration keeps working until
    the table is updated. Returns None for unknown areas.
    """
    if not area or area not in NET_AREAS:
        return None
    years = available_years()
    candidates = [y for y in years if y <= year] or years
    year_used = candidates[-1]
    value = CAPACITY_TARIFFS_EXCL_VAT[year_used].get(area)
    if value is None:
        return None
    if incl_vat:
        value *= 1 + VAT_RATE
    return round(value, 4), year_used
