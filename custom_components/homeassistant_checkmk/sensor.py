"""Sensor entity for Checkmk with config entry support"""

import logging
from datetime import timedelta
import aiohttp
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import (
    DOMAIN,
    CONF_VERIFY_SSL,
    CONF_SERVICE_FILTER,
    CONF_SERVICE_INCLUDE,
    CONF_SERVICE_EXCLUDE,
    CONF_HOST_INCLUDE,
    CONF_HOST_EXCLUDE,
    CONF_SELECTED_HOSTS,
    CONF_SELECTED_SERVICES,
)
from .entities import CheckmkHostSensor, CheckmkMetricSensor, CheckmkServiceSensor
from .utils import match_any, parse_perf_data, selection_allows, split_terms

_LOGGER = logging.getLogger(__name__)


def _service_value(service, key):
    if not isinstance(service, dict):
        return None
    value = service.get(key)
    extensions = service.get("extensions")
    if value is None and isinstance(extensions, dict):
        value = extensions.get(key)
    return value


class CheckmkServiceCoordinator(DataUpdateCoordinator):
    """Fetch all Checkmk service states and metrics in one API request."""

    def __init__(self, hass, config_entry, url, headers, site, ssl_context):
        super().__init__(
            hass,
            _LOGGER,
            name="Checkmk services",
            config_entry=config_entry,
            update_interval=timedelta(seconds=60),
            always_update=False,
        )
        self._url = url
        self._headers = headers
        self._site = site
        self._ssl_context = ssl_context

    async def _async_update_data(self):
        body = {
            "sites": [self._site],
            "columns": ["host_name", "description", "state", "perf_data"],
        }
        try:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    self._url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json=body,
                    timeout=15,
                ) as response:
                    if response.status != 200:
                        raise UpdateFailed(
                            f"Checkmk services API returned {response.status}: "
                            f"{await response.text()}"
                        )
                    payload = await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Unable to update Checkmk services: {err}") from err

        result = {}
        for service in payload.get("value", []):
            host_name = _service_value(service, "host_name")
            description = _service_value(service, "description")
            if host_name and description:
                metrics = parse_perf_data(
                    _service_value(service, "perf_data") or "", description
                )
                result[(host_name, description)] = {
                    "state": _service_value(service, "state"),
                    "metrics": {metric["name"]: metric for metric in metrics},
                }
        return result


async def async_setup_entry(hass, entry, async_add_entities):
    config = entry.options if entry.options else entry.data
    host = config[CONF_HOST]
    site = config["site"]
    user = config[CONF_USERNAME]
    secret = config[CONF_PASSWORD]
    protocol = config.get("protocol", "https")
    port = config.get("port", 443 if protocol == "https" else 80)
    raw_filter = config.get(CONF_SERVICE_FILTER, "")
    filter_terms = split_terms(raw_filter)
    service_include = config.get(CONF_SERVICE_INCLUDE, "")
    service_exclude = config.get(CONF_SERVICE_EXCLUDE, "")
    host_include = config.get(CONF_HOST_INCLUDE, "")
    host_exclude = config.get(CONF_HOST_EXCLUDE, "")
    selected_hosts = set(config.get(CONF_SELECTED_HOSTS, []))
    selected_services = set(config.get(CONF_SELECTED_SERVICES, []))
    service_include_terms = split_terms(service_include)
    service_exclude_terms = split_terms(service_exclude)
    host_include_terms = split_terms(host_include)
    host_exclude_terms = split_terms(host_exclude)
    url = f"{protocol}://{host}:{port}/{site}/check_mk/api/1.0/domain-types/host_config/collections/all"
    headers = {"Authorization": f"Bearer {user} {secret}", "Accept": "application/json"}
    # Option pour ignorer le certificat SSL (doit aussi prendre en compte entry.options)
    verify_ssl = config.get(CONF_VERIFY_SSL, False) if protocol == "https" else False
    # Pour aiohttp, ssl=False désactive la vérification, sinon ssl=True active la vérification
    ssl_context = False if not verify_ssl else True
    entities = []
    host_names = set()
    device_registry = None
    try:
        from homeassistant.helpers import device_registry as dr

        device_registry = dr.async_get(hass)
        _LOGGER.debug(f"Device registry loaded: {device_registry}")
    except Exception as dr_err:
        _LOGGER.error(f"Device registry error: {dr_err}")

    def _host_allowed(host_name):
        return selection_allows(
            host_name, selected_hosts, host_include_terms, host_exclude_terms
        )

    def _service_allowed(service_name):
        if not service_name:
            return False
        if filter_terms and not match_any(service_name, filter_terms):
            return False
        return selection_allows(
            service_name,
            selected_services,
            service_include_terms,
            service_exclude_terms,
        )

    def _add_host_entity(host_name):
        if not _host_allowed(host_name) or host_name in host_names:
            return
        host_names.add(host_name)
        if device_registry is not None:
            try:
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, host_name)},
                    manufacturer="Checkmk",
                    name=f"Checkmk Host {host_name}",
                    model="Checkmk Host",
                    sw_version=None,
                )
            except Exception as dr_err:
                _LOGGER.error(f"Device registry error for host {host_name}: {dr_err}")
        entities.append(
            CheckmkHostSensor(
                host, site, user, secret, host_name, verify_ssl, protocol, port
            )
        )

    try:
        _LOGGER.debug(f"Connecting to Checkmk API: {url} with SSL {ssl_context}")
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                _LOGGER.debug(f"Checkmk API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    _LOGGER.debug(f"Checkmk API response data: {data}")
                    hosts = data.get("value", [])
                    if (
                        not filter_terms
                        and not service_include_terms
                        and not service_exclude_terms
                    ):
                        for host_obj in hosts:
                            host_name = (
                                host_obj.get("id")
                                or host_obj.get("name")
                                or host_obj.get("title")
                            )
                            if not host_name:
                                _LOGGER.error(
                                    f"Host entry missing id/name/title: {host_obj}"
                                )
                                continue
                            _add_host_entity(host_name)
                else:
                    _LOGGER.error(f"Checkmk hosts API error: {resp.status}")
    except Exception as e:
        _LOGGER.error(f"Checkmk hosts connection error: {e}")

    service_url = f"{protocol}://{host}:{port}/{site}/check_mk/api/1.0/domain-types/service/collections/all"
    coordinator = CheckmkServiceCoordinator(
        hass, entry, service_url, headers, site, ssl_context
    )
    await coordinator.async_config_entry_first_refresh()
    for (service_host, service_name), service in coordinator.data.items():
        if not _service_allowed(service_name) or not _host_allowed(service_host):
            continue
        _add_host_entity(service_host)
        entities.append(CheckmkServiceSensor(coordinator, service_host, service_name))
        entities.extend(
            CheckmkMetricSensor(coordinator, service_host, service_name, metric)
            for metric in service["metrics"].values()
        )
    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.error("No hosts found for Checkmk integration.")
