# Capaciteitstarief (BE) voor Home Assistant

[![Validate](https://github.com/johan71gent/ha-capacity-tariff/actions/workflows/validate.yml/badge.svg)](https://github.com/johan71gent/ha-capacity-tariff/actions/workflows/validate.yml)
[![Tests](https://github.com/johan71gent/ha-capacity-tariff/actions/workflows/tests.yml/badge.svg)](https://github.com/johan71gent/ha-capacity-tariff/actions/workflows/tests.yml)
[![HACS](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)

Bewaakt je **maandpiek** onder het Vlaamse capaciteitstarief (Fluvius). De digitale meter berekent
het kwartiergemiddelde en de maandpiek zelf; deze integratie voegt toe wat de meter *niet* doet:

- **voorspelt** hoe het lopende kwartier eindigt en hoeveel vermogen je **nog mag trekken** (marge);
- levert twee **binary sensors** voor automations: *piek in gevaar* en *piek wordt gebroken*;
- rekent de **kost** uit (deze maand, op jaarbasis, gemiddelde van 12 maandpieken);
- houdt de piekhistoriek **herstart-bestendig** bij, met correctie- en importservices;
- werkt met elke bestaande P1-integratie (DSMR, HomeWizard, Slimmelezer, ESPHome …) — geen eigen hardware-uitlezing.

*English: monitors the Flemish (Belgium) capacity-tariff monthly peak in Home Assistant — prediction, remaining margin, automation triggers, cost. Uses the meter's own P1 values as source of truth; falls back to its own quarter-hour calculation. UI in Dutch and English.*

## Installatie

**HACS (aanbevolen):** HACS → Integraties → ⋮ → *Custom repositories* → `https://github.com/johan71gent/ha-capacity-tariff` (categorie *Integration*) → installeren → Home Assistant herstarten.

**Handmatig:** kopieer `custom_components/capacity_tariff/` naar `config/custom_components/` en herstart.

Daarna: *Instellingen → Apparaten & diensten → Integratie toevoegen → "Capaciteitstarief (BE)"*.

## Configuratie

**Stap 1 – bronnen** (bestaande entiteiten):

| Veld | Verplicht | Wat kies je |
|---|---|---|
| Afgenomen vermogen (W) | ja | Momentaan importvermogen, bv. DSMR *Power consumption* (1.7.0) of HomeWizard *Active power*. Negatief (injectie) telt als 0. Drijft de voorspelling. |
| Meter: lopend kwartiergemiddelde | aanbevolen | DSMR (België) *Current average demand* / HomeWizard *Average demand* — OBIS 1-0:1.4.0. Exact wat Fluvius factureert. |
| Meter: piek van de lopende maand | aanbevolen | DSMR *Maximum demand current month* / HomeWizard *Peak demand current month* — OBIS 1-0:1.6.0. Wordt de officiële maandpiek. |
| Importtellers (kWh) | fallback | Eén of meer cumulatieve importregisters (1.8.1 + 1.8.2 mogen apart; ze worden opgeteld). Gebruikt als de meterwaarden er niet zijn. |

**Stap 2 – tarief en drempels:** capaciteitstarief in €/kW/jaar (zie je Fluvius-factuur; leeg = geen kostsensoren), waarschuwingsdrempel in % van de doelpiek (default 90), minimaal gefactureerde piek (default 2,5 kW). Alles is later aanpasbaar via *Configureren*.

Bronvoorrang per grootheid: **meter-eigen sensor › kWh-register › tijdgewogen vermogen**.

## Entiteiten

| Entiteit | Eenheid | Betekenis |
|---|---|---|
| `sensor.…_kwartiervermogen_lopend` | W | Lopend kwartiergemiddelde (attributen: bron, dekking, resterende seconden) |
| `sensor.…_kwartier_voorspelling` | W | Verwacht kwartiergemiddelde als het huidige vermogen aanhoudt |
| `sensor.…_kwartier_marge` | W | Wat je de rest van het kwartier nog constant mag trekken zonder de doelpiek te breken; negatief = te laat. **De sensor voor automations** |
| `sensor.…_laatste_kwartier` | W | Laatst afgesloten kwartier (attributen: bron, dekking, kwaliteitsvlaggen, laatste gap) |
| `sensor.…_maandpiek` | kW | Piek van deze maand, minimaal 2,5 kW (attributen: bron, top-5 kwartieren) |
| `sensor.…_maandpiek_tijdstip` | tijdstip | Wanneer die piek viel |
| `sensor.…_doelpiek` | kW | `max(2,5 kW, maandpiek, streefpiek)` — waartegen marge en waarschuwingen gemeten worden |
| `sensor.…_gemiddelde_piek_12_maanden` | kW | Voortschrijdend gemiddelde van 12 maandpieken (ontbrekende maanden = 2,5 kW) |
| `sensor.…_capaciteitskost_deze_maand` | € | `maandpiek × tarief / 12` |
| `sensor.…_capaciteitskost_per_jaar` | € | `gemiddelde 12 m × tarief` |
| `binary_sensor.…_piek_in_gevaar` | – | Voorspelling > drempel % × doelpiek |
| `binary_sensor.…_piek_wordt_gebroken` | – | Wiskundig zeker: zelfs bij 0 W de rest van het kwartier wordt de doelpiek overschreden |
| `number.…_streefpiek` | kW | Optioneel doel voor deze maand (0 = geen). "Ik aanvaard tot 4 kW" ⇒ marge/waarschuwingen tegen 4 kW |

## Services

| Service | Doel |
|---|---|
| `capacity_tariff.set_month_peak` | Maandpiek handmatig zetten/corrigeren (`peak_kw`, optioneel `month` JJJJ-MM en `timestamp`). Overschrijft meter- en berekende waarde. |
| `capacity_tariff.reset_month` | Alles van een maand vergeten (default: lopende maand). |
| `capacity_tariff.import_history` | Vroegere maandpieken invoeren, bv. `{"2025-09": 3.1, "2025-10": 4.6}` van je factuur (`source: manual`) of uit de 13-maandshistoriek van de meter (`source: meter`), zodat het 12-maandsgemiddelde meteen klopt. |

`config_entry_id` mag weg als je één instantie hebt.

## Automations

Laadpaal pauzeren zodra de piek in gevaar komt, hervatten als het kwartier weer ruimte geeft:

```yaml
automation:
  - alias: Laadpaal pauzeren bij piekgevaar
    triggers:
      - trigger: state
        entity_id: binary_sensor.capaciteitstarief_piek_in_gevaar
        to: "on"
    actions:
      - action: switch.turn_off
        target: { entity_id: switch.laadpaal }

  - alias: Laadpaal hervatten met voldoende marge
    triggers:
      - trigger: numeric_state
        entity_id: sensor.capaciteitstarief_kwartier_marge
        above: 7500          # laadpaal trekt 7,4 kW
        for: "00:00:30"
    conditions:
      - condition: state
        entity_id: binary_sensor.capaciteitstarief_piek_in_gevaar
        state: "off"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.laadpaal }
```

Vermogen van een boiler moduleren op de marge (template):

```yaml
{{ [0, states('sensor.capaciteitstarief_kwartier_marge') | float(0) - 500] | max }}
```

## Hoe het rekent

- Kwartieren zijn klokgebonden (:00/:15/:30/:45), berekend in UTC — België heeft een heel-uur offset, dus dat klopt ook in de zomer/wintertijdnacht.
- Zonder meterwaarden: `(kWh eind − kWh begin) × 4` op de importregisters, of tijdgewogen integratie van het vermogen. Een laatst gekende waarde wordt max. 120 s "vastgehouden"; daarna telt het kwartier als gedeeltelijk gedekt en negeert de integratie het voor de piek (liever missen dan verzinnen).
- Doelpiek = `max(2,5 kW, maandpiek, streefpiek)`. Marge = `(doelpiek × 15 min − energie tot nu) / resterende tijd`. "Piek wordt gebroken" kijkt alleen naar al gemeten energie.
- Herstart middenin een kwartier wordt gereconstrueerd uit de opgeslagen registerstand; een herstart over kwartieren heen levert geen verzonnen pieken maar een `last_gap`-attribuut met de gemiddelde belasting in het gat.
- De meter-eigen maandpiek (1.6.0) wordt alleen vertrouwd voor de maand waarin hij laatst veranderde — net na de maandovergang toont die sensor nog even de vorige maand.

**"Mijn factuur zegt iets anders"** — download de *diagnostics* van de integratie: die bevat de laatste 96 kwartieren met de schatting per bron (`meter`, `energy`, `power`) en `calc_minus_meter_w`, de bron-entiteiten met hun laatste updates en de volledige opslag. Voeg dat toe aan een issue.

## Ontwikkelen

De rekenkern (`custom_components/capacity_tariff/core/`) is HA-vrij en draait overal; de HA-laag-tests hebben Home Assistant nodig (Python 3.13 + C-compiler), dus die draaien in Docker of in CI.

```bash
# kern (snel, lokaal)
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install pytest tzdata ruff
.venv/Scripts/python -m pytest             # tests/ha wordt overgeslagen zonder HA
.venv/Scripts/python -m ruff check custom_components tests

# volledige suite (kern + HA-laag) en hassfest
docker build -f Dockerfile.test -t capacity-tariff-test .
docker run --rm -v "${PWD}:/work" capacity-tariff-test
docker run --rm -v "${PWD}:/github/workspace" ghcr.io/home-assistant/hassfest
```

Ontwerpdocument: [`docs/VOORSTEL.md`](docs/VOORSTEL.md). Licentie: MIT.
