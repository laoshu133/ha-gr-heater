"""Synchronize water heater state and verify writes."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, NAME, POLL_INTERVAL
from .protocol import GreeClient, GreeError, HeaterState, discover

_LOGGER = logging.getLogger(__name__)

type HeaterConfigEntry = ConfigEntry[HeaterCoordinator]


class HeaterCoordinator(DataUpdateCoordinator[HeaterState]):
    """Poll the heater, recovering the V1 session and address when needed."""

    def __init__(self, hass: HomeAssistant, entry: HeaterConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=NAME, update_interval=POLL_INTERVAL
        )
        self.client = GreeClient(entry.data[CONF_HOST], entry.data[CONF_MAC])
        self.firmware = entry.data.get("firmware")
        self.metadata: dict[str, str] = {}
        self._io_lock = asyncio.Lock()

    async def async_load_metadata(self) -> None:
        """Read optional model information from the reachable endpoint."""
        try:
            self.metadata = await self.client.metadata()
        except GreeError:
            pass

    @property
    def device_info(self) -> DeviceInfo:
        """Share one device registry entry across the heater and its controls."""
        mac = self.client.mac
        return DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)},
            name=NAME,
            manufacturer="Gree",
            model="Air-to-water heater",
            model_id=self.metadata.get("mid"),
            sw_version=self.firmware,
        )

    async def _async_update_data(self) -> HeaterState:
        async with self._io_lock:
            try:
                return await self.client.read()
            except GreeError as err:
                try:
                    for device in await discover():
                        if device.mac != self.client.mac or device.host == self.client.host:
                            continue
                        client = GreeClient(device.host, device.mac)
                        state = await client.read()
                        self.client = client
                        return state
                except GreeError:
                    pass
                raise UpdateFailed(str(err)) from err

    @staticmethod
    def invalid_temperature(minimum: float, maximum: float) -> ServiceValidationError:
        """Use the integration's shared target temperature validation message."""
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_temperature",
            translation_placeholders={"min_temp": str(minimum), "max_temp": str(maximum)},
        )

    async def async_set_target_temperature(self, temperature: int) -> None:
        """Write an integer Celsius setpoint and wait for the device to report it."""
        async with self._io_lock:
            values = {"SetTemInt": temperature}
            if self.data.target_decimal is not None:
                values["SetTemDec"] = 0
            await self._async_write(values, confirmation_delays=(0.25, 0.75))

    async def async_write(self, values: dict[str, int]) -> None:
        """Write power or mode with immediate readback."""
        async with self._io_lock:
            await self._async_write(values)

    async def _async_write(
        self, values: dict[str, int], *, confirmation_delays: tuple[float, ...] = ()
    ) -> None:
        try:
            state = await self.client.write(values)
            for delay in confirmation_delays:
                if self._matches(state, values):
                    break
                # Some devices report the previous target briefly. Re-read without
                # sending another command or publishing the old target to the bridge.
                await asyncio.sleep(delay)
                state = await self.client.read()
        except GreeError as err:
            self.async_set_update_error(UpdateFailed(str(err)))
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unconfirmed"
            ) from err

        self.async_set_updated_data(state)
        if not self._matches(state, values):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unconfirmed"
            )

    @staticmethod
    def _matches(state: HeaterState, values: dict[str, int]) -> bool:
        reported = {
            "Pow": state.power,
            "Wmod": state.mode,
            "SetTemInt": state.target_integer,
            "SetTemDec": state.target_decimal,
        }
        return all(reported[field] == value for field, value in values.items())
