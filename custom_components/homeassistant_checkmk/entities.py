"""Entity classes for Checkmk."""
import logging
import aiohttp
from homeassistant.helpers.entity import Entity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_STATE_MAP = {
    0: "OK",
    1: "WARN",
    2: "CRIT",
    3: "UNKNOWN",
}

HOST_STATE_MAP = {
    0: "UP",
    1: "DOWN",
    2: "UNREACH",
    3: "UNKNOWN",
}


def _map_state(state, state_map):
    if isinstance(state, str) and state.isdigit():
        state = int(state)
    if isinstance(state, int):
        return state_map.get(state, "UNKNOWN")
    return state if state is not None else "unknown"


class CheckmkServiceSensor(Entity):
    def __init__(self, host, site, user, secret, host_name, service_name, verify_ssl=False, protocol="https", port=443):
        self._protocol = protocol
        self._port = port
        self._host = host
        self._site = site
        self._user = user
        self._secret = secret
        self._host_name = host_name
        self._service_name = service_name
        self._state = None
        self._attr_name = f"Checkmk {host_name} {service_name}"
        self._available = False
        self._verify_ssl = verify_ssl
        self._ssl_context = False if (protocol != "https" or not verify_ssl) else True

    @property
    def name(self):
        return self._attr_name

    @property
    def unique_id(self):
        return f"checkmk_{self._host_name}_{self._service_name}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host_name)},
            "manufacturer": "Checkmk",
            "name": f"Checkmk Host {self._host_name}",
            "model": "Checkmk Host",
        }

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        url = f"{self._protocol}://{self._host}:{self._port}/{self._site}/check_mk/api/1.0/domain-types/service/collections/all"
        headers = {"Authorization": f"Bearer {self._user} {self._secret}", "Content-Type": "application/json"}
        body = {
            "sites": [self._site],
            "columns": ["host_name", "description", "state"],
            "query": {
                "op": "and",
                "expr": [
                    {"op": "=", "left": "host_name", "right": self._host_name},
                    {"op": "=", "left": "description", "right": self._service_name}
                ]
            }
        }
        try:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, headers=headers, json=body, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        services = data.get("value", [])
                        if services:
                            service = services[0]
                            extensions = service.get("extensions") if isinstance(service, dict) else None
                            state = service.get("state") if isinstance(service, dict) else None
                            if isinstance(extensions, dict):
                                state = state if state is not None else extensions.get("state")
                            self._state = _map_state(state, SERVICE_STATE_MAP)
                            self._available = True
                        else:
                            self._state = None
                            self._available = False
                            _LOGGER.error(f"No status for service {self._service_name} on host {self._host_name}")
                    else:
                        self._state = None
                        self._available = False
                        _LOGGER.error(f"Checkmk service status API error: {resp.status}")
        except Exception as e:
            self._state = None
            self._available = False
            _LOGGER.error(f"Checkmk service status connection error: {e}")


class CheckmkHostSensor(Entity):
    @property
    def unique_id(self):
        return f"checkmk_{self._host_name}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host_name)},
            "manufacturer": "Checkmk",
            "name": f"Checkmk Host {self._host_name}",
            "model": "Checkmk Host",
        }

    def __init__(self, host, site, user, secret, host_name, verify_ssl=False, protocol="https", port=443):
        self._protocol = protocol
        self._port = port
        self._ssl_context = False if (protocol != "https" or not verify_ssl) else True
        self._host = host
        self._site = site
        self._user = user
        self._secret = secret
        self._host_name = host_name
        self._state = None
        self._attr_name = f"Checkmk Host {host_name}"
        self._available = False
        self._verify_ssl = verify_ssl

    @property
    def name(self):
        return self._attr_name

    @property
    def state(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self):
        url = f"{self._protocol}://{self._host}:{self._port}/{self._site}/check_mk/api/1.0/domain-types/host/collections/all"
        headers = {"Authorization": f"Bearer {self._user} {self._secret}", "Content-Type": "application/json"}
        body = {
            "query": {
                "op": "=",
                "left": "name",
                "right": self._host_name
            }
        }
        try:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, headers=headers, json=body, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _LOGGER.debug(f"Checkmk host status API response: {data}")
                        hosts = data.get("value", [])
                        if hosts:
                            status = hosts[0].get("state")
                            self._state = _map_state(status, HOST_STATE_MAP)
                            self._available = True
                        else:
                            self._state = None
                            self._available = False
                            _LOGGER.error(f"No status for host {self._host_name}, API response: {data}")
                    else:
                        self._state = None
                        self._available = False
                        error_text = await resp.text()
                        _LOGGER.error(f"Checkmk host status API error: {resp.status}, body={error_text}")
        except Exception as e:
            self._state = None
            self._available = False
            _LOGGER.error(f"Checkmk host status connection error: {e}")
