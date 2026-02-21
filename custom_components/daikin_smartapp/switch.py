"""Switch platform for Daikin SmartApp integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DaikinApiError, DaikinUnit
from .const import DOMAIN, POWER_ON
from .coordinator import DaikinCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Daikin power switches from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinCoordinator = data["coordinator"]

    entities_by_edge: dict[str, DaikinPowerSwitchEntity] = {}

    def _add_new_entities() -> None:
        new_entities: list[DaikinPowerSwitchEntity] = []
        for edge_id in coordinator.data:
            if edge_id in entities_by_edge:
                continue
            ent = DaikinPowerSwitchEntity(coordinator, edge_id)
            entities_by_edge[edge_id] = ent
            new_entities.append(ent)
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()

    @callback
    def _handle_coordinator_update() -> None:
        _add_new_entities()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class DaikinPowerSwitchEntity(CoordinatorEntity[DaikinCoordinator], SwitchEntity):
    """Per-unit power switch."""

    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: DaikinCoordinator, edge_id: str) -> None:
        super().__init__(coordinator)
        self._edge_id = edge_id
        self._attr_unique_id = f"daikin_{edge_id}_power"

    @property
    def _unit(self) -> DaikinUnit | None:
        return self.coordinator.data.get(self._edge_id)

    @property
    def available(self) -> bool:
        return self._unit is not None

    @property
    def is_on(self) -> bool:
        unit = self._unit
        return bool(unit and unit.power_code == POWER_ON)

    @property
    def device_info(self) -> DeviceInfo:
        unit = self._unit
        return DeviceInfo(
            identifiers={(DOMAIN, self._edge_id)},
            manufacturer="Daikin",
            model="Mobile Controller Cloud Unit",
            name=unit.name if unit else f"Daikin {self._edge_id}",
        )

    async def async_turn_on(self, **kwargs) -> None:
        unit = self._unit
        if not unit:
            return
        try:
            await self.coordinator.client.async_write_state(unit.edge_id, power_on=True)
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        unit = self._unit
        if not unit:
            return
        try:
            await self.coordinator.client.async_write_state(unit.edge_id, power_on=False)
        except DaikinApiError as err:
            raise ValueError(f"Daikin API write failed: {err}") from err
        await self.coordinator.async_request_refresh()
