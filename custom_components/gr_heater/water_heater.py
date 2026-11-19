"""Expose temperature and power as a Home Assistant water heater."""

from math import isfinite

from homeassistant.components.water_heater import WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_TEMP, MIN_TEMP
from .coordinator import HeaterConfigEntry, HeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeaterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the entity for this heater."""
    async_add_entities([GreeWaterHeater(entry)])


class GreeWaterHeater(CoordinatorEntity[HeaterCoordinator], WaterHeaterEntity):
    """Gree water heater with local control."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, entry: HeaterConfigEntry) -> None:
        super().__init__(entry.runtime_data)
        self._attr_unique_id = self.coordinator.client.mac
        self._attr_device_info = self.coordinator.device_info

    @property
    def native_current_temperature(self) -> float:
        return self.coordinator.data.current_temperature

    @property
    def native_target_temperature(self) -> float:
        return self.coordinator.data.target_temperature

    @property
    def current_operation(self) -> str:
        return STATE_ON if self.coordinator.data.power else STATE_OFF

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        data = self.coordinator.data
        return {
            key: value
            for key, value in (
                ("gree_work_state", data.work_state),
                ("gree_mode", data.mode),
                ("water_level_percent", data.water_level),
            )
            if value is not None
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Set a whole Celsius degree and confirm the reported target."""
        temperature = kwargs[ATTR_TEMPERATURE]
        if not isfinite(temperature) or not (
            MIN_TEMP <= temperature <= MAX_TEMP
            and int(temperature) == temperature
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_temperature"
            )
        values = {"SetTemInt": int(temperature)}
        if self.coordinator.data.target_decimal is not None:
            values["SetTemDec"] = 0
        await self.coordinator.async_write(values)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_write({"Pow": 1})

    async def async_turn_off(self) -> None:
        await self.coordinator.async_write({"Pow": 0})
