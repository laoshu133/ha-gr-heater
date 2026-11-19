"""Expose the verified Gree heater operating modes."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MODES, MODE_PROFILE
from .coordinator import HeaterConfigEntry, HeaterCoordinator

_MODE_NAMES = {code: name for name, code in MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeaterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add mode control for the verified protocol profile."""
    coordinator = entry.runtime_data
    if coordinator.metadata.get("mid") == MODE_PROFILE and coordinator.data.mode is not None:
        async_add_entities([GreeHeaterMode(coordinator)])


class GreeHeaterMode(CoordinatorEntity[HeaterCoordinator], SelectEntity):
    """Select the operating mode through the local Wmod property."""

    _attr_has_entity_name = True
    _attr_translation_key = "operating_mode"
    _attr_options = list(MODES)

    def __init__(self, coordinator: HeaterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.mac}_operating_mode"
        self._attr_device_info = coordinator.device_info

    @property
    def current_option(self) -> str | None:
        return _MODE_NAMES.get(self.coordinator.data.mode)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data.mode is not None
            and bool(self.coordinator.data.power)
        )

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write({"Wmod": MODES[option]})
