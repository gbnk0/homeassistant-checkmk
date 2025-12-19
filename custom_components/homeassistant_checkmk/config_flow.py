"""Config flow for Checkmk integration"""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.selector import selector
from .const import (
    DOMAIN,
    CONF_VERIFY_SSL,
    CONF_SERVICE_FILTER,
    CONF_SERVICE_INCLUDE,
    CONF_SERVICE_EXCLUDE,
    CONF_HOST_INCLUDE,
    CONF_HOST_EXCLUDE,
)

class CheckmkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Ici, on pourrait tester la connexion avant de créer l'entrée
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)
        text_selector = selector({"text": {"multiline": True}})
        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required("site"): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional("protocol", default="https"): vol.In(["http", "https"]),
            vol.Optional("port", default=443): int,
            vol.Optional(CONF_VERIFY_SSL, default=False): bool,
            vol.Optional(CONF_HOST_INCLUDE, default=""): text_selector,
            vol.Optional(CONF_HOST_EXCLUDE, default=""): text_selector,
            vol.Optional(CONF_SERVICE_INCLUDE, default=""): text_selector,
            vol.Optional(CONF_SERVICE_EXCLUDE, default=""): text_selector,
            vol.Optional(CONF_SERVICE_FILTER, default=""): text_selector,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    def _options_schema(data):
        text_selector = selector({"text": {"multiline": True}})
        return vol.Schema({
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required("site", default=data.get("site", "")): str,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Optional("protocol", default=data.get("protocol", "https")): vol.In(["http", "https"]),
            vol.Optional("port", default=data.get("port", 443)): int,
            vol.Optional(CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, False)): bool,
            vol.Optional(CONF_HOST_INCLUDE, default=data.get(CONF_HOST_INCLUDE, "")): text_selector,
            vol.Optional(CONF_HOST_EXCLUDE, default=data.get(CONF_HOST_EXCLUDE, "")): text_selector,
            vol.Optional(CONF_SERVICE_INCLUDE, default=data.get(CONF_SERVICE_INCLUDE, "")): text_selector,
            vol.Optional(CONF_SERVICE_EXCLUDE, default=data.get(CONF_SERVICE_EXCLUDE, "")): text_selector,
            vol.Optional(CONF_SERVICE_FILTER, default=data.get(CONF_SERVICE_FILTER, "")): text_selector,
        })

class CheckmkOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        return await self.async_step_options(user_input)

    async def async_step_options(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = self._config_entry.options or self._config_entry.data
        return self.async_show_form(
            step_id="options",
            data_schema=CheckmkConfigFlow._options_schema(defaults),
            errors=errors,
        )
