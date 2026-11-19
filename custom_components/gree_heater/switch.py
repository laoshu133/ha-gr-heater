"""Expose the heater's power as a standalone switch."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HeaterConfigEntry, HeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeaterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the heater's power switch."""
    async_add_entities([GreeHeaterPowerSwitch(entry.runtime_data)])


class GreeHeaterPowerSwitch(CoordinatorEntity[HeaterCoordinator], SwitchEntity):
    """Switch the device power via Pow and show the confirmed status."""

    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(self, coordinator: HeaterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.mac}_power"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.power)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_write({"Pow": 1})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_write({"Pow": 0})
