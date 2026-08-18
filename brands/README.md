# Brand assets (icon / logo)

Home Assistant and HACS do **not** load icons from the integration itself; they come from the
central [home-assistant/brands](https://github.com/home-assistant/brands) repository. Until the
brands PR is merged the integration shows a placeholder icon — that is expected.

`capacity_tariff/` contains the files in the exact layout brands expects for a custom integration:

| File | Size | Use |
|---|---|---|
| `icon.png` / `icon@2x.png` | 256×256 / 512×512 | Integration icon (light backgrounds) |
| `dark_icon.png` / `dark_icon@2x.png` | 256×256 / 512×512 | Icon on dark themes |
| `logo.png` / `logo@2x.png` | 128 h / 256 h | Wordmark for the integration page |
| `dark_logo.png` / `dark_logo@2x.png` | 128 h / 256 h | Wordmark on dark themes |

Concept: a lightning bolt (consumption) under a ceiling bar (the capacity limit / monthly peak).
Amber `#F6A21B`, navy `#1F3A5F`, light `#E8EEF5`. Regenerate with `python brands/make_brand.py`
(needs Pillow; wordmark uses Bahnschrift).

## Submitting to home-assistant/brands

1. Fork <https://github.com/home-assistant/brands>.
2. Copy `brands/capacity_tariff/` to `custom_integrations/capacity_tariff/` in the fork
   (all eight PNG files, no other files).
3. Open a PR titled "Add capacity_tariff (custom integration)". Requirements checked by their CI:
   PNG, transparent background, icon square 256×256 with @2x 512×512, logo height ≤ 256, ≥ 128.
4. After merge the icon appears in HA/HACS within a day (CDN cache).
