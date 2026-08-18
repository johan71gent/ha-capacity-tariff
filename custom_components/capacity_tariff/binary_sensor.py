"""Binary sensors automations hang on: 'peak at risk' and 'peak will be exceeded'."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CapacityTariffConfigEntry
from .coordinator import CapacityData, CapacityTariffCoordinator
from .entity import CapacityTariffEntity


@dataclass(frozen=True, kw_only=True)
class CapacityBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[CapacityData], bool]


def _attrs(data: CapacityData) -> dict[str, Any]:
    return {
        "target_kw": round(data.target_kw, 3),
        "predicted_w": None if data.predicted_end_w is None else round(data.predicted_end_w),
        "margin_w": None if data.margin_w is None else round(data.margin_w),
        "remaining_seconds": None if data.status is None else round(data.status.remaining_s),
        "threshold": data.threshold,
    }


BINARY_SENSORS: tuple[CapacityBinarySensorDescription, ...] = (
    CapacityBinarySensorDescription(
        key="peak_at_risk",
        translation_key="peak_at_risk",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: d.at_risk,
    ),
    CapacityBinarySensorDescription(
        key="peak_exceeded",
        translation_key="peak_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: d.certain_break,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CapacityTariffConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(CapacityTariffBinarySensor(coordinator, desc) for desc in BINARY_SENSORS)


class CapacityTariffBinarySensor(CapacityTariffEntity, BinarySensorEntity):
    entity_description: CapacityBinarySensorDescription

    def __init__(
        self,
        coordinator: CapacityTariffCoordinator,
        description: CapacityBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _attrs(self.coordinator.data)
