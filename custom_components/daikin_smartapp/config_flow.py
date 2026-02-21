"""Config flow for Daikin Mobile Controller integration."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DaikinApiClient, DaikinAuthError
from .const import AUTH_MODE_ID_TOKEN, CONF_AUTH_MODE, CONF_CLIENT_UUID, DOMAIN


async def _validate_credentials(
    hass: HomeAssistant,
    username: str,
    password: str,
    client_uuid: str,
) -> dict[str, Any]:
    client = DaikinApiClient(
        session=async_get_clientsession(hass),
        username=username,
        password=password,
        client_id=None,
        client_secret=None,
        client_uuid=client_uuid,
        auth_mode=AUTH_MODE_ID_TOKEN,
    )
    await client.async_login()
    units = await client.async_refresh()
    if not client.client_id or not client.client_secret:
        raise DaikinAuthError("Client credential discovery did not return values.")
    return {
        "unit_count": len(units),
        CONF_CLIENT_ID: client.client_id,
        CONF_CLIENT_SECRET: client.client_secret,
    }


class DaikinSmartAppConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Daikin Mobile Controller."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):  # type: ignore[override]
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            client_uuid = uuid.uuid4().hex.upper()

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            try:
                info = await _validate_credentials(
                    self.hass,
                    username,
                    password,
                    client_uuid,
                )
            except DaikinAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Daikin Mobile Controller ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_CLIENT_ID: info[CONF_CLIENT_ID],
                        CONF_CLIENT_SECRET: info[CONF_CLIENT_SECRET],
                        CONF_CLIENT_UUID: client_uuid,
                        CONF_AUTH_MODE: AUTH_MODE_ID_TOKEN,
                        "unit_count": info["unit_count"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
