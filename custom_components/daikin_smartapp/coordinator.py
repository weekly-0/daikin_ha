"""Data coordinator for Daikin SmartApp."""

from __future__ import annotations

from typing import Any
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DaikinApiClient, DaikinApiError, DaikinAuthError, DaikinUnit
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DaikinCoordinator(DataUpdateCoordinator[dict[str, DaikinUnit]]):
    """Coordinate Daikin data updates."""

    def __init__(self, hass: HomeAssistant, client: DaikinApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, DaikinUnit]:
        try:
            return await self.client.async_refresh()
        except (DaikinAuthError, DaikinApiError) as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected update error: {err}") from err
