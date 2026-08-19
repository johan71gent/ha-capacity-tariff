<img src="brands/capacity_tariff/logo@2x.png" alt="Capaciteitstarief" height="96">

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
- werkt met elke bestaande P1-integratie (DSMR, HomeWizard, Slimmelezer, ESPHome …) — geen eigen hardware-uitlezing;
- levert **blueprints** (verbruiker pauzeren, melding, laadstroom op marge) en een dashboardvoorbeeld.

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

**Stap 2 – tarief en drempels:**

- **Netgebied (Fluvius)**: kies je gebied en de integratie gebruikt het ingebouwde capaciteitstarief (officiële VREG-tarieflijst, incl. 6 % btw zoals op je factuur). Geen API nodig; de tabel wordt jaarlijks bijgewerkt in een release.
- **Capaciteitstarief (€/kW/jaar)**: optioneel, overschrijft de tabel (zie je Fluvius-factuur). Zonder netgebied én zonder waarde blijven de kostsensoren *onbekend*.
- Waarschuwingsdrempel in % van de pieklimiet (default 90), minimaal gefactureerde piek (default 2,5 kW).

Alles is later aanpasbaar via *Configureren*.

| Netgebied | 2026, excl. btw | incl. 6 % btw |
|---|---|---|
| Fluvius Antwerpen | 49,40 | 52,37 |
| Fluvius Halle-Vilvoorde | 56,04 | 59,41 |
| Fluvius Imewo | 54,20 | 57,45 |
| Fluvius Kempen | 56,21 | 59,58 |
| Fluvius Limburg | 49,05 | 51,99 |
| Fluvius Midden-Vlaanderen | 50,12 | 53,13 |
| Fluvius West | 57,10 | 60,53 |
| Fluvius Zenne-Dijle | 56,12 | 59,49 |

Bron: [Vlaamse Nutsregulator – distributienettarieven](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven), rij *Gemiddelde maandpiek (laagspanning met piekmeting)*. De kostsensoren tonen in hun attributen welk tarief gebruikt wordt (`tariff_source`: `manual` of `table`, `tariff_year`, `net_area`).

Bronvoorrang per grootheid: **meter-eigen sensor › kWh-register › tijdgewogen vermogen**.

## Entiteiten

De namen volgen de benamingen van je P1-meter (HomeWizard / DSMR), zodat je ze naast elkaar kunt leggen:

| Integratie (NL / EN) | P1-meter toont | Verschil |
|---|---|---|
| **Kwartiervermogen (lopend kwartier)** / Average demand (running quarter) | HomeWizard *Average demand*, DSMR *Current average demand* | zelfde grootheid; komt van de meter als je die bron koos, anders eigen schatting (attribuut `source`) |
| **Kwartiervermogen verwacht (einde kwartier)** / Average demand forecast | – | hoe het lopende kwartier eindigt als het huidige vermogen aanhoudt |
| **Nog beschikbaar vermogen (dit kwartier)** / Power still available | – | wat je de rest van het kwartier nog constant mag trekken zonder de pieklimiet te breken |
| **Kwartiervermogen (vorig kwartier)** / Average demand (last quarter) | – | laatst afgesloten kwartier |
| **Maandpiek (lopende maand)** / Peak demand current month | HomeWizard *Peak demand current month*, DSMR *Maximum demand current month* | zelfde grootheid, maar nooit lager dan de minimaal gefactureerde 2,5 kW (daarom kan hier 2,5 kW staan terwijl de meter bv. 2,425 kW toont) |
| **Pieklimiet (doel)** / Peak limit (target) | – | `max(2,5 kW, maandpiek, gewenste pieklimiet)`: hiertegen worden marge en waarschuwingen gemeten |
| **Gemiddelde maandpiek (12 maanden)** / Average peak demand (12 months) | – | wat Fluvius factureert |

| Entiteit | Eenheid | Betekenis |
|---|---|---|
| `sensor.…_kwartiervermogen_lopend_kwartier` | W | Lopend kwartiergemiddelde (attributen: bron, dekking, resterende seconden) |
| `sensor.…_kwartiervermogen_verwacht_einde_kwartier` | W | Verwacht kwartiergemiddelde als het huidige vermogen aanhoudt |
| `sensor.…_nog_beschikbaar_vermogen_dit_kwartier` | W | Wat je de rest van het kwartier nog constant mag trekken zonder de pieklimiet te breken; negatief = te laat. **De sensor voor automations** |
| `sensor.…_kwartiervermogen_vorig_kwartier` | W | Laatst afgesloten kwartier (attributen: bron, dekking, kwaliteitsvlaggen, laatste gap) |
| `sensor.…_maandpiek_lopende_maand` | kW | Piek van deze maand, minimaal 2,5 kW (attributen: bron, top-5 kwartieren) |
| `sensor.…_maandpiek_tijdstip` | tijdstip | Wanneer die piek viel |
| `sensor.…_pieklimiet_doel` | kW | `max(2,5 kW, maandpiek, gewenste pieklimiet)` |
| `sensor.…_gemiddelde_maandpiek_12_maanden` | kW | Voortschrijdend gemiddelde van 12 maandpieken (ontbrekende maanden = 2,5 kW) |
| `sensor.…_capaciteitstarief_kost_deze_maand` | € | `maandpiek × tarief / 12` |
| `sensor.…_capaciteitstarief_kost_per_jaar` | € | `gemiddelde 12 m × tarief` |
| `binary_sensor.…_maandpiek_in_gevaar` | – | Verwachting > drempel % × pieklimiet |
| `binary_sensor.…_maandpiek_wordt_overschreden` | – | Wiskundig zeker: zelfs bij 0 W de rest van het kwartier wordt de pieklimiet overschreden |
| `number.…_gewenste_pieklimiet` | kW | Optioneel doel voor deze maand (0 = geen). "Ik aanvaard tot 4 kW" ⇒ marge/waarschuwingen tegen 4 kW |

> Bestaande installaties behouden hun oude entity-id's (alleen de getoonde namen veranderen); de id's hierboven gelden voor nieuwe installaties.

## Services

| Service | Doel |
|---|---|
| `capacity_tariff.set_month_peak` | Maandpiek handmatig zetten/corrigeren (`peak_kw`, optioneel `month` JJJJ-MM en `timestamp`). Overschrijft meter- en berekende waarde. |
| `capacity_tariff.reset_month` | Alles van een maand vergeten (default: lopende maand). |
| `capacity_tariff.import_history` | Vroegere maandpieken invoeren, bv. `{"2025-09": 3.1, "2025-10": 4.6}` van je factuur (`source: manual`) of uit de 13-maandshistoriek van de meter (`source: meter`), zodat het 12-maandsgemiddelde meteen klopt. |

`config_entry_id` mag weg als je één instantie hebt.

## Blueprints (kant-en-klare automatiseringen)

Drie blueprints zitten in de repo; importeer ze met één klik en kies je entiteiten in de UI:

| Blueprint | Wat het doet | |
|---|---|---|
| **Verbruiker pauzeren bij piekgevaar** | zet een laadpaal/boiler/warmtepomp uit zodra *Maandpiek in gevaar* aangaat, en weer aan zodra er X seconden genoeg marge is voor het vermogen van die verbruiker | [![Importeer blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/johan71gent/ha-capacity-tariff/main/blueprints/automation/capacity_tariff/pause_load_on_peak_risk.yaml) |
| **Melding bij piekgevaar** | push-melding (Companion-app) met verwacht kwartiervermogen, resterende marge en maandpiek, met minimale tussentijd | [![Importeer blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/johan71gent/ha-capacity-tariff/main/blueprints/automation/capacity_tariff/notify_peak_risk.yaml) |
| **Laadstroom regelen op marge** | zet de laadstroom (A) van je laadpaal continu op wat de resterende marge toelaat: `(marge − reserve) / (230 V × fasen)`, begrensd tussen min en max | [![Importeer blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://raw.githubusercontent.com/johan71gent/ha-capacity-tariff/main/blueprints/automation/capacity_tariff/ev_current_from_margin.yaml) |

Werkt dat niet met één klik: *Instellingen → Automatiseringen → Blueprints → Blueprint importeren* en plak de URL `https://raw.githubusercontent.com/johan71gent/ha-capacity-tariff/main/blueprints/automation/capacity_tariff/<naam>.yaml`.

## Dashboard

Een compacte kaart: meter voor de marge (groen = ruimte, rood = te laat), daaronder de kerncijfers.

```yaml
type: vertical-stack
cards:
  - type: gauge
    name: Nog beschikbaar dit kwartier
    entity: sensor.capaciteitstarief_nog_beschikbaar_vermogen_dit_kwartier
    unit: W
    min: -2000
    max: 8000
    needle: true
    segments:
      - from: -2000
        color: "#d32f2f"
      - from: 0
        color: "#f9a825"
      - from: 2000
        color: "#2e7d32"
  - type: entities
    entities:
      - entity: sensor.capaciteitstarief_kwartiervermogen_lopend_kwartier
        name: Kwartiervermogen (lopend)
      - entity: sensor.capaciteitstarief_kwartiervermogen_verwacht_einde_kwartier
        name: Verwacht einde kwartier
      - entity: sensor.capaciteitstarief_maandpiek_lopende_maand
        name: Maandpiek
      - entity: sensor.capaciteitstarief_pieklimiet_doel
        name: Pieklimiet
      - entity: binary_sensor.capaciteitstarief_maandpiek_in_gevaar
        name: Piek in gevaar
      - entity: sensor.capaciteitstarief_capaciteitstarief_kost_per_jaar
        name: Kost per jaar
  - type: history-graph
    hours_to_show: 24
    entities:
      - sensor.capaciteitstarief_kwartiervermogen_vorig_kwartier
      - sensor.capaciteitstarief_maandpiek_lopende_maand
```

Pas de entity-id's aan als je een andere HA-taal gebruikt (Engelse UI: `…_power_still_available_this_quarter`, `…_peak_demand_current_month`, …).

## Automations (zelf schrijven)

Laadpaal pauzeren zodra de piek in gevaar komt, hervatten als het kwartier weer ruimte geeft:

```yaml
automation:
  - alias: Laadpaal pauzeren bij piekgevaar
    triggers:
      - trigger: state
        entity_id: binary_sensor.capaciteitstarief_maandpiek_in_gevaar
        to: "on"
    actions:
      - action: switch.turn_off
        target: { entity_id: switch.laadpaal }

  - alias: Laadpaal hervatten met voldoende marge
    triggers:
      - trigger: numeric_state
        entity_id: sensor.capaciteitstarief_nog_beschikbaar_vermogen_dit_kwartier
        above: 7500          # laadpaal trekt 7,4 kW
        for: "00:00:30"
    conditions:
      - condition: state
        entity_id: binary_sensor.capaciteitstarief_maandpiek_in_gevaar
        state: "off"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.laadpaal }
```

Vermogen van een boiler moduleren op de marge (template):

```yaml
{{ [0, states('sensor.capaciteitstarief_nog_beschikbaar_vermogen_dit_kwartier') | float(0) - 500] | max }}
```

## Naast andere tools

Deze integratie is **de bewaker, niet de sturing**: ze meet, voorspelt en geeft triggers/marge; wat je ermee aanstuurt (laadpaal, batterij, boiler) kies je zelf via automations, de blueprints hierboven of een energiebeheersysteem. Ze draait probleemloos naast EMS-integraties zoals GridPilot of Victron-sturingen. Wil je de **officiële facturatiepiek** uit *Mijn Fluvius* ernaast leggen, dan is [sander110419/Fluvius-home-assistant](https://github.com/sander110419/Fluvius-home-assistant) complementair (cloud, achteraf); deze integratie werkt realtime op je P1-data.

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
