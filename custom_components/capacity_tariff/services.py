"""Services: correct a month peak, reset a month, import history."""

from __future__ import annotations

import re
from datetime import datetime

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import CapacityTariffCoordinator

SERVICE_SET_MONTH_PEAK = "set_month_peak"
SERVICE_RESET_MONTH = "reset_month"
SERVICE_IMPORT_HISTORY = "import_history"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_MONTH = "month"
ATTR_PEAK_KW = "peak_kw"
ATTR_TIMESTAMP = "timestamp"
ATTR_PEAKS = "peaks"
ATTR_SOURCE = "source"

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month(value: str) -> str:
    value = str(value)
    if not _MONTH_RE.match(value):
        raise vol.Invalid("month must be YYYY-MM")
    return value


SET_MONTH_PEAK_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_MONTH): _month,
        vol.Required(ATTR_PEAK_KW): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_TIMESTAMP): cv.datetime,
    }
)
RESET_MONTH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_MONTH): _month,
    }
)
IMPORT_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PEAKS): vol.Schema(
            {_month: vol.All(vol.Coerce(float), vol.Range(min=0))}
        ),
        vol.Optional(ATTR_SOURCE, default="manual"): vol.In(["manual", "meter"]),
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> CapacityTariffCoordinator:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry.runtime_data
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if len(entries) == 1:
        return entries[0].runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_required")


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the domain services once (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_MONTH_PEAK):
        return

    async def set_month_peak(call: ServiceCall) -> None:
        at: datetime | None = call.data.get(ATTR_TIMESTAMP)
        await _coordinator(hass, call).async_set_month_peak(
            call.data.get(ATTR_MONTH), call.data[ATTR_PEAK_KW], at
        )

    async def reset_month(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_reset_month(call.data.get(ATTR_MONTH))

    async def import_history(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_import_history(
            call.data[ATTR_PEAKS], call.data[ATTR_SOURCE]
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_MONTH_PEAK, set_month_peak, SET_MONTH_PEAK_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_RESET_MONTH, reset_month, RESET_MONTH_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_HISTORY, import_history, IMPORT_HISTORY_SCHEMA
    )
