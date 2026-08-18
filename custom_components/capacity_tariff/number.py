"""Number entity: the goal peak for the running month (kW). 0 = no goal."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CapacityTariffConfigEntry
from .coordinator import CapacityTariffCoordinator
from .entity import CapacityTariffEntity

GOAL_DESCRIPTION = NumberEntityDescription(
    key="goal_peak",
    translation_key="goal_peak",
    device_class=NumberDeviceClass.POWER,
    native_unit_of_measurement=UnitOfPower.KILO_WATT,
    native_min_value=0.0,
    native_max_value=50.0,
    native_step=0.1,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CapacityTariffConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([GoalPeakNumber(entry.runtime_data)])


class GoalPeakNumber(CapacityTariffEntity, NumberEntity):
    """The peak the user accepts this month; margin and warnings are measured against
    ``max(floor, month peak, goal)``. Persisted with the peaks, so it survives restarts."""

    entity_description = GOAL_DESCRIPTION

    def __init__(self, coordinator: CapacityTariffCoordinator) -> None:
        super().__init__(coordinator, GOAL_DESCRIPTION.key)

    @property
    def native_value(self) -> float:
        return self.coordinator.goal_kw or 0.0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_goal(value)
