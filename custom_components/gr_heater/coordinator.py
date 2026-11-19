"""Synchronize water heater state and verify writes."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        self.metadata: dict[str, str] = {}
        self._io_lock = asyncio.Lock()

    async def async_load_metadata(self) -> None:
        """Read optional model information from the reachable endpoint."""
        try:
            self.metadata = await self.client.metadata()
        except GreeError:
            pass

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

    async def async_write(self, values: dict[str, int]) -> None:
        """Update HA from the device's reply and report any unconfirmed command."""
        async with self._io_lock:
            try:
                state = await self.client.write(values)
            except GreeError as err:
                self.async_set_update_error(UpdateFailed(str(err)))
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="unconfirmed"
                ) from err

            self.async_set_updated_data(state)
            if "Pow" in values:
                confirmed = state.power == values["Pow"]
            else:
                confirmed = state.target_integer == values["SetTemInt"] and (
                    "SetTemDec" not in values
                    or state.target_decimal == values["SetTemDec"]
                )
            if not confirmed:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="unconfirmed"
                )
