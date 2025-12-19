from .config_flow import CheckmkOptionsFlowHandler
def async_get_options_flow(config_entry):
    return CheckmkOptionsFlowHandler(config_entry)
"""Init for Checkmk integration with config flow"""
from .const import DOMAIN

async def async_setup(hass, config):
    return True

async def async_setup_entry(hass, entry):
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_forward_entry_unload(entry, "sensor")
