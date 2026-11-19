"""Home Assistant integration for Gree V1 water heaters."""

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import HeaterConfigEntry, HeaterCoordinator

_PLATFORMS = (Platform.WATER_HEATER, Platform.SWITCH, Platform.SENSOR, Platform.SELECT)
CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_HOST): str})}, extra=vol.ALLOW_EXTRA
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import optional YAML into a regular config entry."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeaterConfigEntry) -> bool:
    """Load the water heater from a config entry."""
    coordinator = HeaterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_load_metadata()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeaterConfigEntry) -> bool:
    """Unload this integration's entities and stop polling."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
