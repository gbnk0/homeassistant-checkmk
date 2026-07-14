"""Initialize the Checkmk integration."""


async def async_setup_entry(hass, entry):
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def _async_update_listener(hass, entry):
    """Reload the integration after options are saved."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_forward_entry_unload(entry, "sensor")
