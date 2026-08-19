"""Sensors: running quarter, prediction, margin, month peak, 12-month average, cost."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import CapacityTariffConfigEntry
from .const import (
    ATTR_AVERAGE_12M,
    ATTR_COVERAGE,
    ATTR_ELAPSED_S,
    ATTR_ENERGY_WH,
    ATTR_FLAGS,
    ATTR_GAP,
    ATTR_MONTH,
    ATTR_NET_AREA,
    ATTR_REMAINING_S,
    ATTR_SOURCE,
    ATTR_TARIFF,
    ATTR_TARIFF_SOURCE,
    ATTR_TARIFF_YEAR,
    ATTR_TOP,
)
from .coordinator import CapacityData, CapacityTariffCoordinator
from .entity import CapacityTariffEntity


@dataclass(frozen=True, kw_only=True)
class CapacitySensorDescription(SensorEntityDescription):
    value_fn: Callable[[CapacityData], StateType | datetime]
    attrs_fn: Callable[[CapacityData], dict[str, Any]] | None = None


def _status_attrs(data: CapacityData) -> dict[str, Any]:
    st = data.status
    if st is None:
        return {}
    return {
        ATTR_SOURCE: str(st.source),
        ATTR_ELAPSED_S: round(st.elapsed_s),
        ATTR_REMAINING_S: round(st.remaining_s),
        ATTR_COVERAGE: round(st.coverage, 3),
        ATTR_ENERGY_WH: round(st.energy_wh_estimated, 1),
        "quarter_start": st.start.isoformat(),
        "quarter_end": st.end.isoformat(),
    }


def _margin_attrs(data: CapacityData) -> dict[str, Any]:
    return {
        "target_kw": round(data.target_kw, 3),
        "goal_kw": data.goal_kw,
        "at_risk": data.at_risk,
        "certain_break": data.certain_break,
        "threshold": data.threshold,
    }


def _last_quarter_attrs(data: CapacityData) -> dict[str, Any]:
    r = data.last_result
    if r is None:
        return {}
    attrs: dict[str, Any] = {
        "quarter_start": r.start.isoformat(),
        "quarter_end": r.end.isoformat(),
        ATTR_SOURCE: str(r.source),
        ATTR_COVERAGE: round(r.coverage, 3),
        "max_gap_seconds": round(r.max_gap_s),
        ATTR_FLAGS: list(r.flags),
    }
    if data.gap is not None:
        attrs[ATTR_GAP] = {
            "start": data.gap.start.isoformat(),
            "end": data.gap.end.isoformat(),
            "average_w": None if data.gap.average_w is None else round(data.gap.average_w),
        }
    return attrs


def _month_peak_attrs(data: CapacityData) -> dict[str, Any]:
    mp = data.month_peak
    return {
        ATTR_MONTH: mp.month,
        "raw_kw": mp.raw_kw,
        ATTR_SOURCE: str(mp.source),
        "peak_at": mp.at.isoformat() if mp.at else None,
        ATTR_TOP: [
            {
                "kw": round(e.kw, 3),
                "at": e.at.isoformat() if e.at else None,
                "source": str(e.source),
            }
            for e in mp.top
        ],
    }


def _cost_attrs(data: CapacityData) -> dict[str, Any]:
    return {
        ATTR_TARIFF: data.tariff,
        ATTR_TARIFF_SOURCE: data.tariff_source,
        ATTR_TARIFF_YEAR: data.tariff_year,
        ATTR_NET_AREA: data.net_area,
        ATTR_AVERAGE_12M: round(data.average_12m_kw, 3),
    }


SENSORS: tuple[CapacitySensorDescription, ...] = (
    CapacitySensorDescription(
        key="quarter_running_average",
        translation_key="quarter_running_average",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda d: None if d.status is None else d.status.running_average_w,
        attrs_fn=_status_attrs,
    ),
    CapacitySensorDescription(
        key="quarter_prediction",
        translation_key="quarter_prediction",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda d: d.predicted_end_w,
    ),
    CapacitySensorDescription(
        key="quarter_margin",
        translation_key="quarter_margin",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda d: d.margin_w,
        attrs_fn=_margin_attrs,
    ),
    CapacitySensorDescription(
        key="last_quarter",
        translation_key="last_quarter",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda d: None if d.last_result is None else d.last_result.average_w,
        attrs_fn=_last_quarter_attrs,
    ),
    CapacitySensorDescription(
        key="month_peak",
        translation_key="month_peak",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=3,
        value_fn=lambda d: d.month_peak.peak_kw,
        attrs_fn=_month_peak_attrs,
    ),
    CapacitySensorDescription(
        key="month_peak_time",
        translation_key="month_peak_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.month_peak.at,
    ),
    CapacitySensorDescription(
        key="target_peak",
        translation_key="target_peak",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=3,
        value_fn=lambda d: d.target_kw,
        attrs_fn=lambda d: {"goal_kw": d.goal_kw, "month_peak_kw": d.month_peak.peak_kw},
    ),
    CapacitySensorDescription(
        key="average_peak_12m",
        translation_key="average_peak_12m",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=3,
        value_fn=lambda d: d.average_12m_kw,
    ),
    CapacitySensorDescription(
        key="cost_month",
        translation_key="cost_month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda d: d.month_cost,
        attrs_fn=_cost_attrs,
    ),
    CapacitySensorDescription(
        key="cost_year",
        translation_key="cost_year",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda d: d.year_cost,
        attrs_fn=_cost_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CapacityTariffConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(CapacityTariffSensor(coordinator, desc) for desc in SENSORS)


class CapacityTariffSensor(CapacityTariffEntity, SensorEntity):
    entity_description: CapacitySensorDescription

    def __init__(
        self, coordinator: CapacityTariffCoordinator, description: CapacitySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
