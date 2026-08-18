"""Base entity: one device per config entry, all entities hang off the coordinator."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CapacityTariffCoordinator


class CapacityTariffEntity(CoordinatorEntity[CapacityTariffCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CapacityTariffCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Capaciteitstarief (BE)",
            model="Maandpiek-bewaking",
            entry_type=DeviceEntryType.SERVICE,
        )
