"""Expose an HVAC action for HomeKit-compatible thermostat bridges."""

from math import floor, isfinite

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MODE_PROFILE, TEMPERATURE_RANGE_901D
from .coordinator import HeaterConfigEntry, HeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: HeaterConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Expose the thermostat for the verified heater profile."""
    coordinator = entry.runtime_data
    if coordinator.metadata.get("mid") == MODE_PROFILE:
        async_add_entities([GreeHeaterThermostat(coordinator)])


class GreeHeaterThermostat(CoordinatorEntity[HeaterCoordinator], ClimateEntity):
    """Represent powered, heating and keeping-warm states separately."""

    _attr_has_entity_name = True
    _attr_translation_key = "thermostat"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp, _attr_max_temp = TEMPERATURE_RANGE_901D
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator: HeaterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.mac}_thermostat"
        self._attr_device_info = coordinator.device_info

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.coordinator.data.power else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        data = self.coordinator.data
        if not data.power:
            return HVACAction.OFF
        if data.work_state == 0:
            return HVACAction.IDLE
        if data.work_state == 1:
            return HVACAction.HEATING
        return None

    @property
    def native_current_temperature(self) -> float:
        return self.coordinator.data.current_temperature

    @property
    def native_target_temperature(self) -> float:
        return self.coordinator.data.target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.async_write({"Pow": int(hvac_mode == HVACMode.HEAT)})

    async def async_set_temperature(self, **kwargs) -> None:
        """Normalize bridge input to the appliance's nearest whole degree."""
        temperature = kwargs[ATTR_TEMPERATURE]
        if not isfinite(temperature) or not self.min_temp <= temperature <= self.max_temp:
            raise self.coordinator.invalid_temperature(self.min_temp, self.max_temp)
        await self.coordinator.async_set_target_temperature(floor(temperature + 0.5))
