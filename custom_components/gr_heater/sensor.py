"""Expose water level and raw status codes when the heater reports them."""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HeaterConfigEntry, HeaterCoordinator

SENSORS = (
    SensorEntityDescription(
        key="water_level",
        translation_key="water_level",
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="mode", translation_key="mode", entity_category=EntityCategory.DIAGNOSTIC
    ),
    SensorEntityDescription(
        key="work_state",
        translation_key="work_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeaterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Only create sensors for fields reported by the device."""
    coordinator = entry.runtime_data
    async_add_entities(
        GreeHeaterSensor(coordinator, description)
        for description in SENSORS
        if getattr(coordinator.data, description.key) is not None
    )


class GreeHeaterSensor(CoordinatorEntity[HeaterCoordinator], SensorEntity):
    """Read an optional value from the shared polling result."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: HeaterCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.client.mac}_{description.key}"

    @property
    def native_value(self) -> int | None:
        return getattr(self.coordinator.data, self.entity_description.key)
