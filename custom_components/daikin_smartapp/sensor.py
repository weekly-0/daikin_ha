"""Sensor platform for Daikin SmartApp integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DaikinUnit
from .const import DOMAIN, FAN_SPEED_CODE_TO_NAME, FAN_SPEED_NAME_TO_CODE, extract_fan_speed_code
from .coordinator import DaikinCoordinator


@dataclass(frozen=True)
class SensorDef:
    key: str
    name: str
    device_class: SensorDeviceClass | None
    unit: str | None
    state_class: SensorStateClass | None
    options: tuple[str, ...] | None
    entity_category: EntityCategory | None
    value_fn: Callable[[DaikinUnit], float | int | str | None]


SENSOR_DEFS: tuple[SensorDef, ...] = (
    SensorDef(
        key="room_temperature",
        name="Room Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        options=None,
        entity_category=None,
        value_fn=lambda u: u.room_temp_c,
    ),
    SensorDef(
        key="room_humidity",
        name="Room Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        options=None,
        entity_category=None,
        value_fn=lambda u: u.room_humidity_percent,
    ),
    SensorDef(
        key="target_temperature",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        options=None,
        entity_category=None,
        value_fn=lambda u: u.target_temp_c,
    ),
    SensorDef(
        key="fan_speed",
        name="Fan Speed",
        device_class=SensorDeviceClass.ENUM,
        unit=None,
        state_class=None,
        options=tuple(FAN_SPEED_NAME_TO_CODE),
        entity_category=None,
        value_fn=lambda u: FAN_SPEED_CODE_TO_NAME.get(
            extract_fan_speed_code(u.raw_status, u.mode_code)
        ),
    ),
    SensorDef(
        key="diag_power_code",
        name="Diag Power Code",
        device_class=None,
        unit=None,
        state_class=None,
        options=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: u.power_code,
    ),
    SensorDef(
        key="diag_mode_code",
        name="Diag Mode Code",
        device_class=None,
        unit=None,
        state_class=None,
        options=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: u.mode_code,
    ),
    SensorDef(
        key="diag_e3003_p02",
        name="Diag e3003 p02",
        device_class=None,
        unit=None,
        state_class=None,
        options=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: u.raw_status.get("e_3003.p_02"),
    ),
    SensorDef(
        key="diag_e3003_p2f",
        name="Diag e3003 p2f",
        device_class=None,
        unit=None,
        state_class=None,
        options=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: u.raw_status.get("e_3003.p_2F"),
    ),
    SensorDef(
        key="diag_e3003_p37",
        name="Diag e3003 p37",
        device_class=None,
        unit=None,
        state_class=None,
        options=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda u: u.raw_status.get("e_3003.p_37"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Daikin sensors from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinCoordinator = data["coordinator"]

    entities_by_key: dict[tuple[str, str], DaikinUnitSensor] = {}

    def _add_new_entities() -> None:
        new_entities: list[DaikinUnitSensor] = []
        for edge_id in coordinator.data:
            for sensor_def in SENSOR_DEFS:
                entity_key = (edge_id, sensor_def.key)
                if entity_key in entities_by_key:
                    continue
                ent = DaikinUnitSensor(coordinator, edge_id, sensor_def)
                entities_by_key[entity_key] = ent
                new_entities.append(ent)
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()

    @callback
    def _handle_coordinator_update() -> None:
        _add_new_entities()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class DaikinUnitSensor(CoordinatorEntity[DaikinCoordinator], SensorEntity):
    """Expose per-unit telemetry as Home Assistant sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaikinCoordinator, edge_id: str, sensor_def: SensorDef) -> None:
        super().__init__(coordinator)
        self._edge_id = edge_id
        self._def = sensor_def
        self._attr_unique_id = f"daikin_{edge_id}_{sensor_def.key}"
        self._attr_name = sensor_def.name
        self._attr_device_class = sensor_def.device_class
        self._attr_native_unit_of_measurement = sensor_def.unit
        self._attr_state_class = sensor_def.state_class
        self._attr_options = sensor_def.options
        self._attr_entity_category = sensor_def.entity_category

    @property
    def _unit(self) -> DaikinUnit | None:
        return self.coordinator.data.get(self._edge_id)

    @property
    def available(self) -> bool:
        return self._unit is not None

    @property
    def device_info(self) -> DeviceInfo:
        unit = self._unit
        return DeviceInfo(
            identifiers={(DOMAIN, self._edge_id)},
            manufacturer="Daikin",
            model="Mobile Controller Cloud Unit",
            name=unit.name if unit else f"Daikin {self._edge_id}",
        )

    @property
    def native_value(self) -> float | int | str | None:
        unit = self._unit
        if not unit:
            return None
        return self._def.value_fn(unit)
