"""Capaciteitstarief (BE) — guard the Flemish monthly peak (capacity tariff) in Home Assistant.

The calculation core lives in ``core/`` (HA-independent, unit-tested). This package wraps it:
a push-mode coordinator fed by existing P1 entities, persistent storage and entities.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .coordinator import CapacityTariffCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type CapacityTariffConfigEntry = ConfigEntry[CapacityTariffCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CapacityTariffConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = CapacityTariffCoordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CapacityTariffConfigEntry) -> bool:
    """Unload a config entry (persists state first)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete persisted peaks when the entry is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options or sources changed: reload."""
    await hass.config_entries.async_reload(entry.entry_id)
