"""Daikin SmartApp API client."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientSession

from .const import (
    API_BASE_URL,
    API_CREDENTIAL_DISCOVERY_URLS,
    AUTH_MODE_ACCESS_TOKEN,
    AUTH_MODE_ID_TOKEN,
    LOGIN_PATH,
    MODE_CODE_COOL,
    MODE_CODE_DRY,
    MODE_CODE_FAN,
    MULTIREQ_PATH,
    POWER_OFF,
    POWER_ON,
)


_LOGGER = logging.getLogger(__name__)


class DaikinAuthError(Exception):
    """Raised when auth fails."""


class DaikinApiError(Exception):
    """Raised when API calls fail."""


@dataclass(slots=True)
class DaikinUnit:
    """Current unit snapshot."""

    edge_id: str
    name: str
    mac: str
    power_code: str | None
    mode_code: str | None
    fan_code: str | None
    target_temp_c: float | None
    room_temp_c: float | None
    room_humidity_percent: int | None
    sensor_temp_1_c: float | None
    sensor_temp_2_c: float | None
    raw_status: dict[str, str]


def _child_by_pn(node: dict[str, Any], pn: str) -> dict[str, Any] | None:
    for child in node.get("pch", []):
        if isinstance(child, dict) and child.get("pn") == pn:
            return child
    return None


def _children_to_map(node: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in node.get("pch", []):
        if not isinstance(child, dict):
            continue
        key = child.get("pn")
        if not key:
            continue
        if "pv" in child:
            out[str(key)] = str(child.get("pv"))
    return out


def _decode_hex_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _decode_hex_signed_byte(value: str | None) -> int | None:
    n = _decode_hex_int(value)
    if n is None:
        return None
    if n >= 0x80:
        n -= 0x100
    return n


def _decode_hex_half_degree(value: str | None) -> float | None:
    n = _decode_hex_int(value)
    if n is None:
        return None
    return round(n / 2.0, 1)


def _decode_hex_le_i16_half_degree(value: str | None) -> float | None:
    """Decode little-endian signed 16-bit value as half-degree Celsius."""
    if not value or len(value) != 4:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    n = int.from_bytes(raw, byteorder="little", signed=True)
    return round(n / 2.0, 1)


class DaikinApiClient:
    """Thin API wrapper around captured endpoints."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        client_id: str | None,
        client_secret: str | None,
        client_uuid: str,
        auth_mode: str = AUTH_MODE_ID_TOKEN,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._client_id = client_id
        self._client_secret = client_secret
        self._client_uuid = client_uuid
        self._auth_mode = auth_mode
        self._base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._units: dict[str, DaikinUnit] = {}

    @property
    def units(self) -> dict[str, DaikinUnit]:
        return self._units

    @property
    def client_id(self) -> str | None:
        return self._client_id

    @property
    def client_secret(self) -> str | None:
        return self._client_secret

    @staticmethod
    def _extract_client_credentials(payload: Any) -> tuple[str, str] | None:
        """Find client_id/client_secret string pair in nested response payloads."""
        queue: list[Any] = [payload]
        id_keys = {"client_id", "clientid"}
        secret_keys = {"client_secret", "clientsecret"}
        while queue:
            node = queue.pop()
            if isinstance(node, dict):
                lowered = {str(k).lower(): v for k, v in node.items()}
                cid = lowered.get("client_id") or lowered.get("clientid")
                csec = lowered.get("client_secret") or lowered.get("clientsecret")
                if isinstance(cid, str) and isinstance(csec, str) and cid and csec:
                    return cid.strip(), csec.strip()
                for k, v in lowered.items():
                    if k in id_keys | secret_keys:
                        continue
                    if isinstance(v, (dict, list)):
                        queue.append(v)
            elif isinstance(node, list):
                queue.extend(node)
        return None

    @staticmethod
    def _extract_client_credentials_from_text(text: str) -> tuple[str, str] | None:
        if not text:
            return None
        id_match = re.search(r"client[_-]?id['\"\\s:=]+([A-Za-z0-9._-]{8,})", text, re.IGNORECASE)
        sec_match = re.search(
            r"client[_-]?secret['\"\\s:=]+([A-Za-z0-9._-]{16,})",
            text,
            re.IGNORECASE,
        )
        if not id_match or not sec_match:
            return None
        return id_match.group(1), sec_match.group(1)

    async def async_resolve_client_credentials(self) -> tuple[str, str]:
        """Resolve app client_id/client_secret from Daikin server responses."""
        if self._client_id and self._client_secret:
            return self._client_id, self._client_secret

        payload_variants: list[dict[str, Any]] = [
            {"user_id": self._username, "password": self._password, "uuid": self._client_uuid},
            {"username": self._username, "password": self._password, "uuid": self._client_uuid},
            {"user_id": self._username, "password": self._password},
            {"username": self._username, "password": self._password},
        ]
        for url in API_CREDENTIAL_DISCOVERY_URLS:
            for payload in payload_variants:
                status, data, text = await self._request(
                    "POST", url, json_body=payload, auth=False
                )
                if isinstance(data, dict):
                    resolved = self._extract_client_credentials(data)
                    if resolved:
                        self._client_id, self._client_secret = resolved
                        _LOGGER.debug("Resolved client credentials from %s", url)
                        return resolved
                resolved = self._extract_client_credentials_from_text(text)
                if resolved:
                    self._client_id, self._client_secret = resolved
                    _LOGGER.debug("Resolved client credentials from %s text payload", url)
                    return resolved
                # Some endpoints return non-200 with useful JSON/text payloads.
                if status in (400, 401, 403) and text:
                    resolved = self._extract_client_credentials_from_text(text)
                    if resolved:
                        self._client_id, self._client_secret = resolved
                        _LOGGER.debug("Resolved client credentials from %s error payload", url)
                        return resolved

        raise DaikinAuthError("Could not resolve app client credentials from server.")

    def _token_candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if self._auth_mode == AUTH_MODE_ACCESS_TOKEN:
            if self._access_token:
                candidates.append((AUTH_MODE_ACCESS_TOKEN, self._access_token))
            if self._id_token:
                candidates.append((AUTH_MODE_ID_TOKEN, self._id_token))
        else:
            if self._id_token:
                candidates.append((AUTH_MODE_ID_TOKEN, self._id_token))
            if self._access_token:
                candidates.append((AUTH_MODE_ACCESS_TOKEN, self._access_token))
        return candidates

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, str]:
        url = urljoin(f"{self._base_url}/", path.lstrip("/"))
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "user-agent": "DaikinMobileController/2.0.0 CFNetwork/3860.100.1 Darwin/25.0.0",
        }
        if auth:
            candidates = self._token_candidates()
            if not candidates:
                raise DaikinAuthError("No auth token available.")
            headers["authorization"] = f"Bearer {candidates[0][1]}"
        if extra_headers:
            headers.update(extra_headers)

        async with self._session.request(
            method, url, headers=headers, json=json_body
        ) as resp:
            text = await resp.text()
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = None
            return resp.status, data, text

    async def async_login(self) -> None:
        await self.async_resolve_client_credentials()
        body = {
            "client_secret": self._client_secret,
            "user_id": self._username,
            "uuid": self._client_uuid,
            "password": self._password,
            "client_id": self._client_id,
            "grant_type": "password",
        }
        status, data, text = await self._request(
            "POST", LOGIN_PATH, json_body=body, auth=False
        )
        if status != 200 or not isinstance(data, dict):
            raise DaikinAuthError(f"Login failed: HTTP {status} body={text[:300]}")
        if data.get("rsc") != 2000:
            raise DaikinAuthError(
                f"Login rejected: rsc={data.get('rsc')} error={data.get('error')}"
            )
        self._access_token = data.get("access_token")
        self._id_token = data.get("id_token")
        self._refresh_token = data.get("refresh_token")
        if not self._access_token and not self._id_token:
            raise DaikinAuthError("Login succeeded but no token fields were returned.")

    async def _ensure_auth(self) -> None:
        if not self._id_token and not self._access_token:
            await self.async_login()

    async def _multireq(self, method: str, requests_payload: list[dict[str, Any]]) -> Any:
        await self._ensure_auth()
        last_status = 0
        last_text = ""
        for attempt in range(2):
            for mode, token in self._token_candidates():
                status, data, text = await self._request(
                    method,
                    MULTIREQ_PATH,
                    json_body={"requests": requests_payload},
                    auth=False,
                    extra_headers={"authorization": f"Bearer {token}"},
                )
                last_status, last_text = status, text
                if status == 200 and isinstance(data, dict):
                    # Lock onto whichever token type works.
                    self._auth_mode = mode
                    _LOGGER.debug("Daikin multireq authorized via %s", mode)
                    return data
            # Refresh login and retry both token types once.
            await self.async_login()
        raise DaikinApiError(
            f"multireq failed after token fallback: HTTP {last_status} body={last_text[:300]}"
        )

    def _merge_unit_edge(self, units: dict[str, DaikinUnit], edge: dict[str, Any], edge_id: str) -> None:
        name = ""
        mac = ""
        for node in edge.get("pch", []):
            if not isinstance(node, dict):
                continue
            if node.get("pn") == "adp_d":
                for child in node.get("pch", []):
                    if isinstance(child, dict) and child.get("pn") == "name":
                        name = str(child.get("pv") or "")
            elif node.get("pn") == "adp_i":
                for child in node.get("pch", []):
                    if isinstance(child, dict) and child.get("pn") == "mac":
                        mac = str(child.get("pv") or "")

        existing = units.get(edge_id)
        if existing:
            if name:
                existing.name = name
            if mac:
                existing.mac = mac
            return
        units[edge_id] = DaikinUnit(
            edge_id=edge_id,
            name=name or f"Daikin {edge_id}",
            mac=mac,
            power_code=None,
            mode_code=None,
            fan_code=None,
            target_temp_c=None,
            room_temp_c=None,
            room_humidity_percent=None,
            sensor_temp_1_c=None,
            sensor_temp_2_c=None,
            raw_status={},
        )

    async def async_fetch_units(self) -> dict[str, DaikinUnit]:
        # Request both shapes to make discovery robust across account variants.
        data = await self._multireq(
            "POST",
            [
                {"to": "/dsiot/edges?expand", "op": 2},
                {"to": "/dsiot/edges", "op": 2},
            ],
        )
        units: dict[str, DaikinUnit] = {}
        for resp in data.get("responses", []):
            if not isinstance(resp, dict):
                continue
            fr = str(resp.get("fr", ""))
            pc = resp.get("pc")
            if fr == "/dsiot/edges":
                if isinstance(pc, list):
                    for edge in pc:
                        if not isinstance(edge, dict):
                            continue
                        edge_id = str(edge.get("ri", "")).strip()
                        if edge_id:
                            self._merge_unit_edge(units, edge, edge_id)
                elif isinstance(pc, dict):
                    edge_id = str(pc.get("ri", "")).strip()
                    if edge_id:
                        self._merge_unit_edge(units, pc, edge_id)
                continue

            # Fallback: merge per-edge response fragments.
            if fr.startswith("/dsiot/edges/"):
                parts = fr.split("/")
                if len(parts) >= 4 and parts[3].isdigit() and isinstance(pc, dict):
                    edge_id = parts[3]
                    self._merge_unit_edge(units, {"pch": [pc]}, edge_id)
        _LOGGER.debug("Daikin discovery found %s units", len(units))
        return units

    async def async_fetch_status(self, edge_ids: list[str]) -> dict[str, dict[str, str]]:
        requests_payload = [
            {"op": 2, "to": f"/dsiot/edges/{edge_id}/adr_0100.dgc_status?filter=pv"}
            for edge_id in edge_ids
        ]
        data = await self._multireq("POST", requests_payload)
        out: dict[str, dict[str, str]] = {}
        for resp in data.get("responses", []):
            if not isinstance(resp, dict):
                continue
            fr = str(resp.get("fr", ""))
            if "/adr_0100.dgc_status" not in fr:
                continue
            parts = fr.split("/")
            if len(parts) < 4:
                continue
            edge_id = parts[3]
            pc = resp.get("pc")
            if not isinstance(pc, dict):
                continue
            status_root = _child_by_pn(pc, "e_1002")
            if not status_root:
                continue
            merged: dict[str, str] = {}
            for group in status_root.get("pch", []):
                if not isinstance(group, dict):
                    continue
                group_name = str(group.get("pn") or "")
                if not group_name:
                    continue
                group_map = _children_to_map(group)
                merged.update({f"{group_name}.{k}": v for k, v in group_map.items()})
            out[edge_id] = merged
        return out

    async def async_refresh(self) -> dict[str, DaikinUnit]:
        units = await self.async_fetch_units()
        if not units:
            self._units = {}
            return {}

        status_map = await self.async_fetch_status(list(units))
        for edge_id, unit in units.items():
            raw = status_map.get(edge_id, {})
            unit.raw_status = raw
            unit.mode_code = raw.get("e_3001.p_01")
            unit.fan_code = raw.get("e_3003.p_2D")
            unit.power_code = raw.get("e_A002.p_01")
            unit.target_temp_c = _decode_hex_half_degree(raw.get("e_3001.p_02"))
            room_temp = _decode_hex_signed_byte(raw.get("e_A00B.p_01"))
            unit.room_temp_c = float(room_temp) if room_temp is not None else None
            unit.room_humidity_percent = _decode_hex_int(raw.get("e_A00B.p_02"))
            unit.sensor_temp_1_c = _decode_hex_le_i16_half_degree(raw.get("e_A00B.p_05"))
            unit.sensor_temp_2_c = _decode_hex_le_i16_half_degree(raw.get("e_A00B.p_06"))

        self._units = units
        return units

    def _build_mode_patch(
        self,
        current: DaikinUnit,
        mode_code: str,
        mode_param_overrides: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        raw = current.raw_status
        patch = [{"pn": "p_01", "pv": mode_code}]
        overrides = mode_param_overrides or {}

        if mode_code == MODE_CODE_COOL:
            keys = {
                "p_02": "32",
                "p_05": "0F0000",
                "p_06": "0F0000",
                "p_09": "0700",
                "p_0C": "00",
            }
        elif mode_code == MODE_CODE_DRY:
            keys = {
                "p_22": "020000",
                "p_23": "0F0000",
                "p_27": "0A00",
                "p_31": "00",
            }
        elif mode_code == MODE_CODE_FAN:
            # Fan-only appears to require its own e_3001 parameter group.
            keys = {
                "p_24": "020000",
                "p_25": "050000",
                "p_28": "0A00",
            }
        else:
            keys = {}

        for key, default in keys.items():
            value = overrides.get(key) or raw.get(f"e_3001.{key}") or default
            # Captured writes use fixed-width payload fragments.
            if len(value) != len(default):
                value = default
            patch.append({"pn": key, "pv": value})

        # Allow explicit runtime overrides for params not in the base mode template
        # (for example fan speed and target temperature updates).
        existing_keys = {item["pn"] for item in patch}
        for key, value in overrides.items():
            if key in existing_keys or key == "p_01":
                continue
            patch.append({"pn": key, "pv": value})
        return patch

    async def async_write_state(
        self,
        edge_id: str,
        *,
        power_on: bool,
        mode_code: str | None = None,
        mode_param_overrides: dict[str, str] | None = None,
    ) -> None:
        if edge_id not in self._units:
            raise DaikinApiError(f"Unknown edge_id: {edge_id}")
        current = self._units[edge_id]
        target_mode = mode_code or current.mode_code or MODE_CODE_COOL
        fan_code = current.raw_status.get("e_3003.p_2D", "02")

        mode_patch = self._build_mode_patch(
            current, target_mode, mode_param_overrides=mode_param_overrides
        )
        body = {
            "requests": [
                {
                    "op": 3,
                    "to": f"/dsiot/edges/{edge_id}/adr_0100.dgc_status",
                    "pc": {
                        "pn": "dgc_status",
                        "pch": [
                            {
                                "pn": "e_1002",
                                "pch": [
                                    {"pn": "e_3001", "pch": mode_patch},
                                    {"pn": "e_3003", "pch": [{"pn": "p_2D", "pv": fan_code}]},
                                    {
                                        "pn": "e_A002",
                                        "pch": [
                                            {
                                                "pn": "p_01",
                                                "pv": POWER_ON if power_on else POWER_OFF,
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    },
                }
            ]
        }

        await self._ensure_auth()
        status, data, text = await self._request(
            "PUT", MULTIREQ_PATH, json_body=body, auth=True
        )
        if status == 401:
            await self.async_login()
            status, data, text = await self._request(
                "PUT", MULTIREQ_PATH, json_body=body, auth=True
            )
        if status != 200 or not isinstance(data, dict):
            raise DaikinApiError(f"Write failed: HTTP {status} body={text[:300]}")

        # Validate rsc if available.
        responses = data.get("responses", [])
        if responses and isinstance(responses, list):
            first = responses[0]
            if isinstance(first, dict):
                rsc = first.get("rsc")
                if rsc not in (2000, 2004):
                    raise DaikinApiError(f"Write rejected with rsc={rsc}")
