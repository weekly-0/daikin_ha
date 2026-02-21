"""Daikin SmartApp integration."""

from __future__ import annotations

from typing import Any
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er

from .api import DaikinApiClient
from .const import CONF_AUTH_MODE, CONF_CLIENT_UUID, DOMAIN, PLATFORMS
from .coordinator import DaikinCoordinator


DaikinConfigEntry = ConfigEntry[dict[str, Any]]
_LOGGER = logging.getLogger(__name__)


async def _async_cleanup_legacy_power_buttons(
    hass: HomeAssistant, entry: DaikinConfigEntry
) -> None:
    """Remove legacy Power I/O button entities from prior releases."""
    ent_reg = er.async_get(hass)
    stale_entities = [
        ent
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if ent.domain == "button"
        and ent.unique_id
        and (
            ent.unique_id.endswith("_power_on_i")
            or ent.unique_id.endswith("_power_off_o")
        )
    ]
    for ent in stale_entities:
        _LOGGER.debug("Removing legacy entity %s (%s)", ent.entity_id, ent.unique_id)
        ent_reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Set up Daikin SmartApp from config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = DaikinApiClient(
        session=async_get_clientsession(hass),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        client_id=entry.data.get(CONF_CLIENT_ID),
        client_secret=entry.data.get(CONF_CLIENT_SECRET),
        client_uuid=entry.data[CONF_CLIENT_UUID],
        auth_mode=entry.data.get(CONF_AUTH_MODE, "id_token"),
    )
    coordinator = DaikinCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    await _async_cleanup_legacy_power_buttons(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
