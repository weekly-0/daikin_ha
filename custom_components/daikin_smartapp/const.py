"""Constants for Daikin SmartApp integration."""

from datetime import timedelta
from typing import Mapping

DOMAIN = "daikin_smartapp"
PLATFORMS: list[str] = ["climate", "sensor", "switch"]

API_BASE_URL = "https://proddit.ditdeneb.com"
API_CREDENTIAL_DISCOVERY_URLS: tuple[str, ...] = (
    "https://scr.dspsph.com/common/login",
    "https://proddit.ditdeneb.com/common/login",
)

LOGIN_PATH = "/premise/dsiot/login"
MULTIREQ_PATH = "/dsiot/multireq"

CONF_CLIENT_UUID = "client_uuid"
CONF_AUTH_MODE = "auth_mode"

# The app primarily uses id_token for Authorization in captured calls.
AUTH_MODE_ID_TOKEN = "id_token"
AUTH_MODE_ACCESS_TOKEN = "access_token"

UPDATE_INTERVAL = timedelta(seconds=30)

MODE_CODE_COOL = "0200"
MODE_CODE_DRY = "0500"
# Confirmed from packet capture: fan-only operation mode.
MODE_CODE_FAN = "0000"

# Power lives under e_A002.p_01
POWER_OFF = "00"
POWER_ON = "01"

# Fan speed labels/codes from capture.
FAN_SPEED_NAME_TO_CODE: dict[str, str] = {
    "Auto": "0A00",
    "Indoor Unit Quiet": "0B00",
    "Level 1": "0300",
    "Level 2": "0400",
    "Level 3": "0500",
    "Level 4": "0600",
    "Level 5": "0700",
}
FAN_SPEED_CODE_TO_NAME: dict[str, str] = {v: k for k, v in FAN_SPEED_NAME_TO_CODE.items()}

# Fan speed parameter key is mode-specific.
MODE_FAN_SPEED_PARAM_KEY: dict[str, str] = {
    MODE_CODE_COOL: "p_09",
    MODE_CODE_DRY: "p_27",
    MODE_CODE_FAN: "p_28",
}
ALL_FAN_SPEED_PARAM_KEYS: tuple[str, ...] = ("p_09", "p_27", "p_28")


def normalize_hex_code(value: str | None, width: int = 4) -> str | None:
    """Return an uppercase fixed-width prefix from hex-like payload fragments."""
    if not value:
        return None
    normalized = str(value).upper()
    if len(normalized) < width:
        return None
    return normalized[:width]


def fan_speed_param_key_for_mode(mode_code: str | None) -> str | None:
    """Return the e_3001 parameter key used for fan speed for a given mode code."""
    if not mode_code:
        return None
    return MODE_FAN_SPEED_PARAM_KEY.get(mode_code)


def extract_fan_speed_code(
    raw_status: Mapping[str, str], mode_code: str | None
) -> str | None:
    """Extract mode-appropriate fan speed code from a unit raw status map."""
    preferred_key = fan_speed_param_key_for_mode(mode_code)
    keys = [preferred_key] if preferred_key else []
    keys.extend(k for k in ALL_FAN_SPEED_PARAM_KEYS if k != preferred_key)
    for key in keys:
        if not key:
            continue
        code = normalize_hex_code(raw_status.get(f"e_3001.{key}"))
        if code in FAN_SPEED_CODE_TO_NAME:
            return code
    return None
