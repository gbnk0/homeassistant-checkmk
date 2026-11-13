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
    CONF_METRIC_EXCLUDE,
    CONF_METRIC_INCLUDE,
    CONF_SELECTED_HOSTS,
    CONF_SELECTED_METRICS,
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
    metric_key,
    parse_perf_data,
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


def _multi_select(options: list[str], labels: dict[str, str] | None = None):
    labels = labels or {}
    return selector(
        {
            "select": {
                "options": [
                    {"value": option, "label": labels.get(option, option)}
                    for option in options
                ],
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


def _metric_schema(metrics: list[str], defaults: dict[str, Any]) -> vol.Schema:
    selected = defaults.get(CONF_SELECTED_METRICS, [])
    selected = [metric for metric in selected if metric in metrics]
    labels = {metric: metric.replace("::", " — ", 1) for metric in metrics}
    return vol.Schema(
        {
            vol.Optional(CONF_SELECTED_METRICS, default=selected): _multi_select(
                metrics, labels
            ),
            vol.Optional(
                CONF_METRIC_INCLUDE,
                default=defaults.get(CONF_METRIC_INCLUDE, ""),
            ): _text_selector(),
            vol.Optional(
                CONF_METRIC_EXCLUDE,
                default=defaults.get(CONF_METRIC_EXCLUDE, ""),
            ): _text_selector(),
        }
    )


def _service_value(service: dict[str, Any], key: str):
    value = service.get(key)
    extensions = service.get("extensions")
    if value is None and isinstance(extensions, dict):
        value = extensions.get(key)
    return value


class NoHostsError(ValueError):
    """No hosts are visible to the automation user."""


def _collection(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    """Validate the collection envelope without logging server data."""
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("value"), list)
        or any(not isinstance(item, dict) for item in payload["value"])
    ):
        raise ValueError(f"{endpoint}: expected an object with a value array of objects")
    return payload["value"]


def _host_names(payload: Any, endpoint: str) -> list[str]:
    names = set()
    for item in _collection(payload, endpoint):
        # Keep the existing identifier precedence; monitoring also exposes name
        # inside extensions. Titles remain a compatibility fallback.
        extensions = item.get("extensions")
        name = item.get("id") or item.get("name")
        if not name and isinstance(extensions, dict):
            name = extensions.get("name")
        name = name or item.get("title")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{endpoint}: host entry has no valid host identifier")
        names.add(name)
    return sorted(names, key=str.casefold)


async def _response_payload(response, endpoint: str):
    """Report safe endpoint diagnostics, never response bodies or credentials."""
    _LOGGER.debug("Checkmk %s returned HTTP %s", endpoint, response.status)
    if response.status in {401, 403}:
        _LOGGER.warning("Checkmk %s denied access (HTTP %s)", endpoint, response.status)
        raise PermissionError
    if response.status >= 400:
        _LOGGER.warning("Checkmk %s failed (HTTP %s)", endpoint, response.status)
    response.raise_for_status()
    try:
        return await response.json()
    except (ValueError, aiohttp.ContentTypeError) as err:
        raise ValueError(f"{endpoint}: expected a JSON response") from err


async def _async_discover(
    config: dict[str, Any],
) -> tuple[list[str], list[tuple[str, str, tuple[str, ...]]]]:
    """Validate credentials and return hosts, services, and metric names."""
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
        config_endpoint = "/domain-types/host_config/collections/all"
        monitoring_endpoint = "/domain-types/host/collections/all"
        async with session.get(
            f"{base_url}{config_endpoint}", headers=headers, timeout=15
        ) as response:
            # Setup visibility is not required for a monitoring-only account.
            if response.status == 403:
                _LOGGER.debug("Checkmk host_config denied access; trying monitoring hosts")
                hosts = []
            else:
                hosts = _host_names(
                    await _response_payload(response, config_endpoint), config_endpoint
                )
        if not hosts:
            _LOGGER.debug("No configured hosts visible; trying Checkmk monitoring hosts")
            async with session.get(
                f"{base_url}{monitoring_endpoint}", headers=headers, timeout=15
            ) as response:
                hosts = _host_names(
                    await _response_payload(response, monitoring_endpoint),
                    monitoring_endpoint,
                )
        if not hosts:
            raise NoHostsError

        async with session.post(
            f"{base_url}/domain-types/service/collections/all",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "sites": [site],
                "columns": ["host_name", "description", "perf_data"],
            },
            timeout=15,
        ) as response:
            service_payload = await _response_payload(
                response, "/domain-types/service/collections/all"
            )

    service_items = _collection(service_payload, "/domain-types/service/collections/all")
    for item in service_items:
        for key in ("host_name", "description", "perf_data"):
            value = _service_value(item, key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"/domain-types/service/collections/all: invalid {key} field")
    services = sorted(
        {
            (
                _service_value(item, "host_name"),
                _service_value(item, "description"),
                tuple(
                    metric["name"]
                    for metric in parse_perf_data(
                        _service_value(item, "perf_data") or "",
                        _service_value(item, "description"),
                    )
                ),
            )
            for item in service_items
            if _service_value(item, "host_name") and _service_value(item, "description")
        },
        key=lambda item: (item[0].casefold(), item[1].casefold()),
    )
    _LOGGER.debug("Checkmk discovery found %s hosts and %s services", len(hosts), len(services))
    return hosts, services


class _DiscoveryFlowMixin:
    """Shared discovery assistant for setup and options."""

    _connection_data: dict[str, Any]
    _defaults: dict[str, Any]
    _hosts: list[str]
    _host_services: list[tuple[str, str, tuple[str, ...]]]
    _host_filters: dict[str, Any]
    _service_filters: dict[str, Any]

    async def _async_connection_step(self, step_id: str, user_input=None):
        errors = {}
        if user_input is not None:
            self._defaults = {**self._defaults, **user_input}
            try:
                self._hosts, self._host_services = await _async_discover(user_input)
            except NoHostsError:
                _LOGGER.warning(
                    "Checkmk returned no visible hosts from configured and monitoring "
                    "host collections; check the site, monitoring status and user visibility"
                )
                errors["base"] = "no_hosts"
            except PermissionError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.warning("Checkmk discovery request failed (%s)", type(err).__name__)
                errors["base"] = "cannot_connect"
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Invalid Checkmk discovery response: %s", err)
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
            {
                service
                for host, service, _metrics in self._host_services
                if host in allowed_hosts
            },
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
                self._service_filters = dict(user_input)
                return await self.async_step_metrics()
        return self.async_show_form(
            step_id="services",
            data_schema=_service_schema(available_services, self._defaults),
            errors=errors,
        )

    async def async_step_metrics(self, user_input=None):
        errors = {}
        selected_hosts = set(self._host_filters.get(CONF_SELECTED_HOSTS, []))
        host_include = split_terms(self._host_filters.get(CONF_HOST_INCLUDE, ""))
        host_exclude = split_terms(self._host_filters.get(CONF_HOST_EXCLUDE, ""))
        selected_services = set(self._service_filters.get(CONF_SELECTED_SERVICES, []))
        service_include = split_terms(
            self._service_filters.get(CONF_SERVICE_INCLUDE, "")
        )
        service_exclude = split_terms(
            self._service_filters.get(CONF_SERVICE_EXCLUDE, "")
        )
        available_metrics = sorted(
            {
                metric_key(service, metric)
                for host, service, metrics in self._host_services
                if selection_allows(host, selected_hosts, host_include, host_exclude)
                and selection_allows(
                    service,
                    selected_services,
                    service_include,
                    service_exclude,
                )
                for metric in metrics
            },
            key=str.casefold,
        )
        if user_input is not None:
            invalid = invalid_regex_patterns(
                split_terms(user_input.get(CONF_METRIC_INCLUDE, ""))
                + split_terms(user_input.get(CONF_METRIC_EXCLUDE, ""))
            )
            if invalid:
                errors["base"] = "invalid_regex"
            else:
                data = {
                    **self._connection_data,
                    **self._host_filters,
                    **self._service_filters,
                    **user_input,
                }
                data.pop(CONF_SERVICE_FILTER, None)
                return self._async_finish(data)
        return self.async_show_form(
            step_id="metrics",
            data_schema=_metric_schema(available_metrics, self._defaults),
            errors=errors,
        )


class CheckmkConfigFlow(_DiscoveryFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Checkmk with selectable hosts, services, and metrics."""

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
    """Refresh discovery and edit host, service, and metric selections."""

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry
        self._defaults = dict(config_entry.options or config_entry.data)

    async def async_step_init(self, user_input=None):
        return await self._async_connection_step("init", user_input)

    def _async_finish(self, data):
        return self.async_create_entry(title="", data=data)
