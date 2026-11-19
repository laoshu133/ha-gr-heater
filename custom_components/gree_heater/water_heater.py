"""Expose temperature and power as a Home Assistant water heater."""

from math import isfinite

from homeassistant.components.water_heater import WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    MAX_TEMP,
    MIN_TEMP,
    MODES,
    MODE_NAMES,
    MODE_PROFILE,
    TEMPERATURE_RANGE_901D,
)
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
    _attr_translation_key = "heater"
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
        if self.coordinator.metadata.get("mid") == MODE_PROFILE:
            self._attr_min_temp, self._attr_max_temp = TEMPERATURE_RANGE_901D
            if self.coordinator.data.mode is not None:
                self._attr_supported_features |= WaterHeaterEntityFeature.OPERATION_MODE
                self._attr_operation_list = [STATE_OFF, *MODES]

    @property
    def native_current_temperature(self) -> float:
        return self.coordinator.data.current_temperature

    @property
    def native_target_temperature(self) -> float:
        return self.coordinator.data.target_temperature

    @property
    def current_operation(self) -> str:
        data = self.coordinator.data
        if not data.power:
            return STATE_OFF
        if WaterHeaterEntityFeature.OPERATION_MODE in self.supported_features:
            return MODE_NAMES.get(data.mode, STATE_ON)
        return STATE_ON

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Select the mode, powering on when a heating mode is requested."""
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
        else:
            await self.coordinator.async_write({"Pow": 1, "Wmod": MODES[operation_mode]})

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
            self._attr_min_temp <= temperature <= self._attr_max_temp
            and int(temperature) == temperature
        ):
            raise self.coordinator.invalid_temperature(
                self._attr_min_temp, self._attr_max_temp
            )
        await self.coordinator.async_set_target_temperature(int(temperature))

    async def async_turn_on(self) -> None:
        await self.coordinator.async_write({"Pow": 1})

    async def async_turn_off(self) -> None:
        await self.coordinator.async_write({"Pow": 0})
