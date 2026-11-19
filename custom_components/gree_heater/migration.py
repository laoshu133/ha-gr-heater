"""Migrate configuration from the previous integration domain."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

LEGACY_DOMAIN = "gr_heater"


async def async_migrate_legacy_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> ConfigEntry | None:
    """Move the previous device and entities while keeping their registry IDs."""
    if entry.unique_id is None:
        return None
    entries = hass.config_entries
    legacy = entries.async_entry_for_domain_unique_id(LEGACY_DOMAIN, entry.unique_id)
    if legacy is None:
        return None
    if legacy.state.recoverable and not await entries.async_unload(legacy.entry_id):
        raise ConfigEntryNotReady("Could not unload the previous Gree heater entry")

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, legacy.entry_id):
        registry.async_update_entity_platform(
            entity.entity_id, DOMAIN, new_config_entry_id=entry.entry_id
        )

    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, legacy.entry_id):
        identifiers = {
            (DOMAIN if domain == LEGACY_DOMAIN else domain, identity)
            for domain, identity in device.identifiers
        }
        devices.async_update_device(
            device.id,
            new_config_entry_id=entry.entry_id,
            new_identifiers=identifiers,
        )

    return legacy
