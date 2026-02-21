"""Climate platform for Daikin SmartApp integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DaikinApiError, DaikinUnit
from .const import (
    ALL_FAN_SPEED_PARAM_KEYS,
    DOMAIN,
    FAN_SPEED_CODE_TO_NAME,
    FAN_SPEED_NAME_TO_CODE,
    MODE_CODE_COOL,
    MODE_CODE_DRY,
    MODE_CODE_FAN,
    POWER_ON,
    extract_fan_speed_code,
    fan_speed_param_key_for_mode,
)
from .coordinator import DaikinCoordinator


MODE_TO_CODE = {
    HVACMode.COOL: MODE_CODE_COOL,
    HVACMode.DRY: MODE_CODE_DRY,
    HVACMode.FAN_ONLY: MODE_CODE_FAN,
}
CODE_TO_MODE = {v: k for k, v in MODE_TO_CODE.items()}

SWING_TO_PARAMS = {
    SWING_BOTH: {"p_05": "0F0000", "p_06": "0F0000"},
    SWING_HORIZONTAL: {"p_05": "000000", "p_06": "0F0000"},
    SWING_VERTICAL: {"p_05": "0F0000", "p_06": "000000"},
    SWING_OFF: {"p_05": "000000", "p_06": "000000"},
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Daikin climate entities from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinCoordinator = data["coordinator"]

    entities_by_edge: dict[str, DaikinClimateEntity] = {}

    def _add_new_entities() -> None:
        new_entities: list[DaikinClimateEntity] = []
        for edge_id in coordinator.data:
            if edge_id in entities_by_edge:
                continue
            ent = DaikinClimateEntity(coordinator, edge_id)
            entities_by_edge[edge_id] = ent
            new_entities.append(ent)
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()

    @callback
    def _handle_coordinator_update() -> None:
        _add_new_entities()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class DaikinClimateEntity(CoordinatorEntity[DaikinCoordinator], ClimateEntity):
    """Daikin unit climate entity."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]
    _attr_fan_modes = list(FAN_SPEED_NAME_TO_CODE)
    _attr_swing_modes = [SWING_BOTH, SWING_HORIZONTAL, SWING_VERTICAL, SWING_OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 10.0
    _attr_max_temp = 32.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: DaikinCoordinator, edge_id: str) -> None:
        super().__init__(coordinator)
        self._edge_id = edge_id
        self._attr_unique_id = f"daikin_{edge_id}"
        # Keep this on the instance as well; some HA paths read entity attrs
        # after initialization and before class attrs are resolved as expected.
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def _unit(self) -> DaikinUnit | None:
        return self.coordinator.data.get(self._edge_id)

    @property
    def name(self) -> str | None:
        unit = self._unit
        return unit.name if unit else None

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
    def temperature_unit(self) -> str:
        """Return the temperature unit used by this entity."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self) -> HVACMode | None:
        unit = self._unit
        if not unit:
            return None
        if unit.mode_code in CODE_TO_MODE:
            return CODE_TO_MODE[unit.mode_code]
        return HVACMode.COOL

    @property
    def hvac_action(self) -> HVACAction | None:
        unit = self._unit
        if not unit:
            return None
        if unit.power_code != POWER_ON:
            return HVACAction.OFF
        if unit.mode_code == MODE_CODE_DRY:
            return HVACAction.DRYING
        if unit.mode_code == MODE_CODE_FAN:
            return HVACAction.FAN
        return HVACAction.COOLING

    @property
    def target_temperature(self) -> float | None:
        unit = self._unit
        if not unit:
            return None
        return unit.target_temp_c

    @property
    def fan_mode(self) -> str | None:
        unit = self._unit
        if not unit:
            return None
        return FAN_SPEED_CODE_TO_NAME.get(
            extract_fan_speed_code(unit.raw_status, unit.mode_code)
        )

    @property
    def swing_mode(self) -> str | None:
        unit = self._unit
        if not unit:
            return None
        p05_raw = unit.raw_status.get("e_3001.p_05", "")
        p06_raw = unit.raw_status.get("e_3001.p_06", "")
        p05 = p05_raw[:6]
        p06 = p06_raw[:6]
        if p05 == "0F0000" and p06 == "0F0000":
            return SWING_BOTH
        if p05 == "000000" and p06 == "0F0000":
            return SWING_HORIZONTAL
        if p05 == "0F0000" and p06 == "000000":
            return SWING_VERTICAL
        if p05 == "000000" and p06 == "000000":
            return SWING_OFF
        return None

    @property
    def current_temperature(self) -> float | None:
        unit = self._unit
        if not unit:
            return None
        return unit.room_temp_c

    @property
    def current_humidity(self) -> int | None:
        unit = self._unit
        if not unit:
            return None
        return unit.room_humidity_percent

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self._unit
        if not unit:
            return {}
        attrs: dict[str, Any] = {
            "edge_id": unit.edge_id,
            "mac": unit.mac,
            "power_code": unit.power_code,
            "mode_code": unit.mode_code,
            "fan_code": unit.fan_code,
            "fan_speed_code": extract_fan_speed_code(unit.raw_status, unit.mode_code),
            "fan_speed_param_key": fan_speed_param_key_for_mode(unit.mode_code),
            "fan_speed_p09": unit.raw_status.get("e_3001.p_09"),
            "fan_speed_p27": unit.raw_status.get("e_3001.p_27"),
            "fan_speed_p28": unit.raw_status.get("e_3001.p_28"),
            "swing_lr_code": unit.raw_status.get("e_3001.p_05"),
            "swing_ud_code": unit.raw_status.get("e_3001.p_06"),
            "target_temperature_c": unit.target_temp_c,
            "room_temperature_c": unit.room_temp_c,
            "room_humidity_percent": unit.room_humidity_percent,
            "sensor_temp_1_c": unit.sensor_temp_1_c,
            "sensor_temp_2_c": unit.sensor_temp_2_c,
        }
        return attrs

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        unit = self._unit
        if not unit:
            return
        try:
            if hvac_mode == HVACMode.OFF:
                await self.coordinator.client.async_write_state(
                    unit.edge_id, power_on=False
                )
            else:
                mode_code = MODE_TO_CODE.get(hvac_mode)
                if not mode_code:
                    return
                await self.coordinator.client.async_write_state(
                    unit.edge_id, power_on=True, mode_code=mode_code
                )
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err

        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        unit = self._unit
        if not unit:
            return
        speed_code = FAN_SPEED_NAME_TO_CODE.get(fan_mode)
        if not speed_code:
            return
        speed_param = fan_speed_param_key_for_mode(unit.mode_code)
        params = (
            {speed_param: speed_code}
            if speed_param
            else {key: speed_code for key in ALL_FAN_SPEED_PARAM_KEYS}
        )
        try:
            await self.coordinator.client.async_write_state(
                unit.edge_id,
                power_on=True,
                mode_param_overrides=params,
            )
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        unit = self._unit
        if not unit:
            return
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        try:
            temp_c = float(temperature)
        except (TypeError, ValueError):
            return

        # Daikin p_02 encodes target temp in 0.5C steps as hex.
        half_steps = int(round(temp_c * 2))
        if half_steps < 0 or half_steps > 0xFF:
            return
        p02_hex = f"{half_steps:02X}"

        try:
            await self.coordinator.client.async_write_state(
                unit.edge_id,
                power_on=True,
                mode_param_overrides={"p_02": p02_hex},
            )
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        unit = self._unit
        if not unit:
            return
        params = SWING_TO_PARAMS.get(swing_mode)
        if not params:
            return
        try:
            await self.coordinator.client.async_write_state(
                unit.edge_id,
                power_on=True,
                mode_param_overrides=params,
            )
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        unit = self._unit
        if not unit:
            return
        try:
            await self.coordinator.client.async_write_state(unit.edge_id, power_on=True)
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        unit = self._unit
        if not unit:
            return
        try:
            await self.coordinator.client.async_write_state(unit.edge_id, power_on=False)
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()
