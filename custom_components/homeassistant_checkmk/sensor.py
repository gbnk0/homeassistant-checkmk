"""Sensor entity for Checkmk with config entry support"""
import logging
import aiohttp
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from .const import (
    DOMAIN,
    CONF_VERIFY_SSL,
    CONF_SERVICE_FILTER,
    CONF_SERVICE_INCLUDE,
    CONF_SERVICE_EXCLUDE,
    CONF_HOST_INCLUDE,
    CONF_HOST_EXCLUDE,
)
from .entities import CheckmkHostSensor, CheckmkServiceSensor
from .utils import match_any, split_terms

_LOGGER = logging.getLogger(__name__)

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
    service_include_terms = split_terms(service_include)
    service_exclude_terms = split_terms(service_exclude)
    host_include_terms = split_terms(host_include)
    host_exclude_terms = split_terms(host_exclude)
    url = f"{protocol}://{host}:{port}/{site}/check_mk/api/1.0/domain-types/host_config/collections/all"
    headers = {
        "Authorization": f"Bearer {user} {secret}",
        "Accept": "application/json"
    }
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
        if not host_name:
            return False
        if host_include_terms and not match_any(host_name, host_include_terms):
            return False
        if host_exclude_terms and match_any(host_name, host_exclude_terms):
            return False
        return True

    def _service_allowed(service_name):
        if not service_name:
            return False
        if filter_terms and not match_any(service_name, filter_terms):
            return False
        if service_include_terms and not match_any(service_name, service_include_terms):
            return False
        if service_exclude_terms and match_any(service_name, service_exclude_terms):
            return False
        return True

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
        entities.append(CheckmkHostSensor(host, site, user, secret, host_name, verify_ssl, protocol, port))
    try:
        _LOGGER.debug(f"Connecting to Checkmk API: {url} with headers {headers} and SSL {ssl_context}")
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                _LOGGER.debug(f"Checkmk API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    _LOGGER.debug(f"Checkmk API response data: {data}")
                    hosts = data.get("value", [])
                    if not filter_terms and not service_include_terms and not service_exclude_terms:
                        for host_obj in hosts:
                            host_name = host_obj.get("id") or host_obj.get("name") or host_obj.get("title")
                            if not host_name:
                                _LOGGER.error(f"Host entry missing id/name/title: {host_obj}")
                                continue
                            _add_host_entity(host_name)
                else:
                    _LOGGER.error(f"Checkmk hosts API error: {resp.status}")
            service_url = f"{protocol}://{host}:{port}/{site}/check_mk/api/1.0/domain-types/service/collections/all"
            service_body = {
                "sites": [site],
                "columns": ["host_name", "description", "state"]
            }
            try:
                _LOGGER.debug(f"POST {service_url} body: {service_body}")
                async with session.post(service_url, headers={**headers, "Content-Type": "application/json"}, json=service_body, timeout=15) as service_resp:
                    if service_resp.status == 200:
                        service_data = await service_resp.json()
                        _LOGGER.debug(f"Checkmk services API response: {service_data}")
                        services = service_data.get("value", [])
                        for service in services:
                            extensions = service.get("extensions") if isinstance(service, dict) else None
                            service_host = service.get("host_name") if isinstance(service, dict) else None
                            service_name = service.get("description") if isinstance(service, dict) else None
                            if isinstance(extensions, dict):
                                service_host = service_host or extensions.get("host_name")
                                service_name = service_name or extensions.get("description")
                            if not service_host or not service_name:
                                _LOGGER.error(f"Service entry missing host_name/description: {service}")
                                continue
                            if not _service_allowed(service_name):
                                continue
                            if not _host_allowed(service_host):
                                continue
                            _add_host_entity(service_host)
                            entities.append(CheckmkServiceSensor(host, site, user, secret, service_host, service_name, verify_ssl, protocol, port))
                    else:
                        try:
                            error_text = await service_resp.text()
                        except Exception:
                            error_text = "(no body)"
                        _LOGGER.error(f"Checkmk services API error: {service_resp.status} body={error_text}")
            except Exception as se:
                _LOGGER.error(f"Checkmk services connection error: {se}")
    except Exception as e:
        _LOGGER.error(f"Checkmk hosts connection error: {e}")
    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.error("No hosts found for Checkmk integration.")
