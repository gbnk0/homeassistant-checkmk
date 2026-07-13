"""Entity classes for Checkmk."""
import logging
import aiohttp
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .utils import metric_device_class

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


class CheckmkServiceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, host_name, service_name):
        super().__init__(coordinator)
        self._host_name = host_name
        self._service_name = service_name
        self._attr_name = f"Checkmk {host_name} {service_name}"

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
        service = self.coordinator.data.get((self._host_name, self._service_name))
        return _map_state(service.get("state"), SERVICE_STATE_MAP) if service else None

    @property
    def available(self):
        return super().available and (
            self._host_name, self._service_name
        ) in self.coordinator.data


class CheckmkMetricSensor(CoordinatorEntity, SensorEntity):
    """Numeric Home Assistant sensor backed by one Checkmk metric."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, host_name, service_name, metric):
        super().__init__(coordinator)
        self._host_name = host_name
        self._service_name = service_name
        self._metric_name = metric["name"]
        self._attr_name = (
            f"Checkmk {host_name} {service_name} {self._metric_name}"
        )
        self._attr_unique_id = (
            f"checkmk_{host_name}_{service_name}_{self._metric_name}"
        )
        self._attr_native_unit_of_measurement = metric["unit"]
        self._attr_device_class = metric_device_class(metric["unit"])

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._host_name)},
            "manufacturer": "Checkmk",
            "name": f"Checkmk Host {self._host_name}",
            "model": "Checkmk Host",
        }

    @property
    def native_value(self):
        metric = self._current_metric()
        return metric["value"] if metric else None

    @property
    def available(self):
        return super().available and self._current_metric() is not None

    @property
    def extra_state_attributes(self):
        metric = self._current_metric()
        if metric is None:
            return None
        return {
            key: metric[key]
            for key in ("warning", "critical", "minimum", "maximum")
            if metric[key] is not None
        }

    def _current_metric(self):
        service = self.coordinator.data.get((self._host_name, self._service_name))
        if not service:
            return None
        return service["metrics"].get(self._metric_name)


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
