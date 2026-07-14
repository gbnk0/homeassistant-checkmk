"""Config flow for the Checkmk integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import selector

from .const import (
    CONF_HOST_EXCLUDE,
    CONF_HOST_INCLUDE,
    CONF_SELECTED_HOSTS,
    CONF_SELECTED_SERVICES,
    CONF_SERVICE_EXCLUDE,
    CONF_SERVICE_FILTER,
    CONF_SERVICE_INCLUDE,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from .utils import (
    invalid_regex_patterns,
    match_any,
    selection_allows,
    split_terms,
)

_LOGGER = logging.getLogger(__name__)

CONF_SITE = "site"
CONF_PROTOCOL = "protocol"
CONF_PORT = "port"


def _text_selector():
    return selector({"text": {"multiline": True}})


def _password_selector():
    return selector({"text": {"type": "password"}})


def _multi_select(options: list[str]):
    return selector(
        {
            "select": {
                "options": [{"value": option, "label": option} for option in options],
                "multiple": True,
                "mode": "dropdown",
            }
        }
    )


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    protocol = defaults.get(CONF_PROTOCOL, "https")
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_SITE, default=defaults.get(CONF_SITE, "")): str,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(
                CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")
            ): _password_selector(),
            vol.Optional(CONF_PROTOCOL, default=protocol): vol.In(["http", "https"]),
            vol.Optional(
                CONF_PORT,
                default=defaults.get(CONF_PORT, 443 if protocol == "https" else 80),
            ): int,
            vol.Optional(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, False),
            ): bool,
        }
    )


def _host_schema(hosts: list[str], defaults: dict[str, Any]) -> vol.Schema:
    selected = defaults.get(CONF_SELECTED_HOSTS)
    include_default = defaults.get(CONF_HOST_INCLUDE, "")
    if selected is None:
        include = split_terms(include_default)
        selected = [host for host in hosts if include and match_any(host, include)]
        if selected:
            include_default = ""
    selected = [host for host in selected if host in hosts]
    return vol.Schema(
        {
            vol.Optional(CONF_SELECTED_HOSTS, default=selected): _multi_select(hosts),
            vol.Optional(CONF_HOST_INCLUDE, default=include_default): _text_selector(),
            vol.Optional(
                CONF_HOST_EXCLUDE, default=defaults.get(CONF_HOST_EXCLUDE, "")
            ): _text_selector(),
        }
    )


def _service_schema(services: list[str], defaults: dict[str, Any]) -> vol.Schema:
    selected = defaults.get(CONF_SELECTED_SERVICES)
    include_default = defaults.get(CONF_SERVICE_INCLUDE, "") or defaults.get(
        CONF_SERVICE_FILTER, ""
    )
    if selected is None:
        include = split_terms(include_default)
        selected = [
            service for service in services if include and match_any(service, include)
        ]
        if selected:
            include_default = ""
    selected = [service for service in selected if service in services]
    return vol.Schema(
        {
            vol.Optional(CONF_SELECTED_SERVICES, default=selected): _multi_select(
                services
            ),
            vol.Optional(
                CONF_SERVICE_INCLUDE,
                default=include_default,
            ): _text_selector(),
            vol.Optional(
                CONF_SERVICE_EXCLUDE,
                default=defaults.get(CONF_SERVICE_EXCLUDE, ""),
            ): _text_selector(),
        }
    )


def _service_value(service: dict[str, Any], key: str):
    value = service.get(key)
    extensions = service.get("extensions")
    if value is None and isinstance(extensions, dict):
        value = extensions.get(key)
    return value


async def _async_discover(
    config: dict[str, Any],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Validate credentials and return Checkmk hosts and their services."""
    protocol = config.get(CONF_PROTOCOL, "https")
    host = config[CONF_HOST]
    port = config.get(CONF_PORT, 443 if protocol == "https" else 80)
    site = config[CONF_SITE]
    base_url = f"{protocol}://{host}:{port}/{site}/check_mk/api/1.0"
    headers = {
        "Authorization": (f"Bearer {config[CONF_USERNAME]} {config[CONF_PASSWORD]}"),
        "Accept": "application/json",
    }
    ssl_context = config.get(CONF_VERIFY_SSL, False) if protocol == "https" else False
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(
            f"{base_url}/domain-types/host_config/collections/all",
            headers=headers,
            timeout=15,
        ) as response:
            if response.status in {401, 403}:
                raise PermissionError
            response.raise_for_status()
            host_payload = await response.json()

        async with session.post(
            f"{base_url}/domain-types/service/collections/all",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "sites": [site],
                "columns": ["host_name", "description"],
            },
            timeout=15,
        ) as response:
            if response.status in {401, 403}:
                raise PermissionError
            response.raise_for_status()
            service_payload = await response.json()

    hosts = sorted(
        {
            item.get("id") or item.get("name") or item.get("title")
            for item in host_payload.get("value", [])
            if item.get("id") or item.get("name") or item.get("title")
        },
        key=str.casefold,
    )
    services = sorted(
        {
            (_service_value(item, "host_name"), _service_value(item, "description"))
            for item in service_payload.get("value", [])
            if _service_value(item, "host_name") and _service_value(item, "description")
        },
        key=lambda item: (item[0].casefold(), item[1].casefold()),
    )
    if not hosts:
        raise ValueError("No hosts returned by Checkmk")
    return hosts, services


class _DiscoveryFlowMixin:
    """Shared three-step discovery flow for setup and options."""

    _connection_data: dict[str, Any]
    _defaults: dict[str, Any]
    _hosts: list[str]
    _host_services: list[tuple[str, str]]
    _host_filters: dict[str, Any]

    async def _async_connection_step(self, step_id: str, user_input=None):
        errors = {}
        if user_input is not None:
            self._defaults = {**self._defaults, **user_input}
            try:
                self._hosts, self._host_services = await _async_discover(user_input)
            except PermissionError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except (ValueError, TypeError):
                errors["base"] = "invalid_response"
            except Exception:  # pragma: no cover - defensive HA boundary
                _LOGGER.exception("Unexpected Checkmk discovery error")
                errors["base"] = "unknown"
            else:
                self._connection_data = dict(user_input)
                return await self.async_step_hosts()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_connection_schema(self._defaults),
            errors=errors,
        )

    async def async_step_hosts(self, user_input=None):
        errors = {}
        if user_input is not None:
            invalid = invalid_regex_patterns(
                split_terms(user_input.get(CONF_HOST_INCLUDE, ""))
                + split_terms(user_input.get(CONF_HOST_EXCLUDE, ""))
            )
            if invalid:
                errors["base"] = "invalid_regex"
            else:
                self._host_filters = dict(user_input)
                return await self.async_step_services()
        return self.async_show_form(
            step_id="hosts",
            data_schema=_host_schema(self._hosts, self._defaults),
            errors=errors,
        )

    async def async_step_services(self, user_input=None):
        errors = {}
        selected_hosts = set(self._host_filters.get(CONF_SELECTED_HOSTS, []))
        include = split_terms(self._host_filters.get(CONF_HOST_INCLUDE, ""))
        exclude = split_terms(self._host_filters.get(CONF_HOST_EXCLUDE, ""))
        allowed_hosts = {
            host
            for host in self._hosts
            if selection_allows(host, selected_hosts, include, exclude)
        }
        available_services = sorted(
            {service for host, service in self._host_services if host in allowed_hosts},
            key=str.casefold,
        )
        if user_input is not None:
            invalid = invalid_regex_patterns(
                split_terms(user_input.get(CONF_SERVICE_INCLUDE, ""))
                + split_terms(user_input.get(CONF_SERVICE_EXCLUDE, ""))
            )
            if invalid:
                errors["base"] = "invalid_regex"
            else:
                data = {
                    **self._connection_data,
                    **self._host_filters,
                    **user_input,
                }
                data.pop(CONF_SERVICE_FILTER, None)
                return self._async_finish(data)
        return self.async_show_form(
            step_id="services",
            data_schema=_service_schema(available_services, self._defaults),
            errors=errors,
        )


class CheckmkConfigFlow(_DiscoveryFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Checkmk and discover selectable hosts and services."""

    VERSION = 1

    def __init__(self):
        super().__init__()
        self._defaults = {}

    async def async_step_user(self, user_input=None):
        return await self._async_connection_step("user", user_input)

    @staticmethod
    def async_get_options_flow(config_entry):
        """Expose the Configure button for an existing config entry."""
        return CheckmkOptionsFlowHandler(config_entry)

    def _async_finish(self, data):
        return self.async_create_entry(title=data[CONF_HOST], data=data)


class CheckmkOptionsFlowHandler(_DiscoveryFlowMixin, config_entries.OptionsFlow):
    """Refresh discovery and edit host/service selections."""

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry
        self._defaults = dict(config_entry.options or config_entry.data)

    async def async_step_init(self, user_input=None):
        return await self._async_connection_step("init", user_input)

    def _async_finish(self, data):
        return self.async_create_entry(title="", data=data)
