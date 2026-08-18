# Capaciteitstarief (BE) voor Home Assistant

Bewaakt de Vlaamse **maandpiek** (capaciteitstarief, Fluvius): voorspelt het lopende kwartier,
toont hoeveel vermogen je nog mag trekken, waarschuwt via binary sensors voor automations en
rekent de kost uit. Werkt met de meter-eigen P1-waarden als bron van waarheid (DSMR / HomeWizard,
OBIS `1.4.0` / `1.6.0` / `98.1.0`) en valt terug op een eigen kwartierberekening als die er niet zijn.

Ontwerp en status: [`docs/VOORSTEL.md`](docs/VOORSTEL.md).

## Status

| Mijlpaal | Inhoud | Status |
|---|---|---|
| M1 | Rekenkern `custom_components/capacity_tariff/core/` + pytest | ✅ klaar |
| M2 | HA-skelet: config flow, coordinator, storage, sensoren | ⏳ |
| M3 | Binary sensors, streefpiek, services, options, vertalingen, diagnostics | ⏳ |
| M4 | HACS-klaar, README met automation-voorbeelden, CI | ⏳ |

## Rekenkern (M1)

Pure Python, geen Home Assistant-imports, geen wandklok — elke methode krijgt de tijd mee.

```python
from custom_components.capacity_tariff.core import (
    QuarterTracker, MonthLedger, effective_target_kw, month_cost, year_cost,
)

tracker = QuarterTracker()
ledger = MonthLedger(tz=ZoneInfo("Europe/Brussels"))

# elke P1-update:
for result in tracker.on_power(now, watts):            # verplicht: momentaan vermogen
    ledger.record(result)                              # kwartier afgesloten
tracker.on_meter_average(now, meter_1_4_0_kw * 1000)   # aanbevolen: meter-eigen kwartiergemiddelde
tracker.on_energy(now, kwh_1_8_1 + kwh_1_8_2)          # fallback: import-registers

# op elke :00/:15/:30/:45:
for result in tracker.tick(now):
    ledger.record(result)

# lezen:
st = tracker.status(now)
peak = ledger.month_peak(ledger.month_key(now))         # gefloord op 2,5 kW
target_w = effective_target_kw(peak.peak_kw, goal_kw=None) * 1000
st.predicted_end_w                                     # voorspelling einde kwartier
st.margin_w(target_w)                                  # wat je nog mag trekken (W)
st.is_at_risk(target_w, 0.9), st.is_certain_break(target_w)
month_cost(peak.peak_kw, tariff), year_cost(ledger.rolling_average(key), tariff)
```

Persistentie: `tracker.to_dict()` / `QuarterTracker.from_dict(data, now)` en
`ledger.to_dict()` / `MonthLedger.from_dict(data, tz=...)` zijn JSON-serialiseerbaar; een herstart
middenin een kwartier wordt gereconstrueerd, een herstart over kwartieren heen levert een `Gap`
(met gemiddeld vermogen als het register beschikbaar is), nooit verzonnen pieken.

## Ontwikkelen

```bash
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements_test.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check custom_components tests
```
