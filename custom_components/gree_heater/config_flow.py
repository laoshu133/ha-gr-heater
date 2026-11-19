"""Configure a heater from local discovery or an IPv4 address."""

from ipaddress import IPv4Address

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import DOMAIN, NAME
from .protocol import Device, GreeClient, GreeError, discover


class HeaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Gree V1 water heater."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Choose LAN discovery or manual entry."""
        return self.async_show_menu(step_id="user", menu_options=["scan", "manual"])

    async def async_step_scan(self, user_input: dict | None = None) -> ConfigFlowResult:
        """List unconfigured heaters advertising a known device name."""
        errors = {}
        if user_input is None:
            configured = {entry.unique_id for entry in self._async_current_entries()}
            try:
                devices = await discover()
            except GreeError:
                return self.async_abort(reason="scan_failed")
            self._devices = {
                device.mac: device for device in devices if device.mac not in configured
            }
            if not self._devices:
                return self.async_abort(reason="no_devices")
        else:
            device = self._devices.get(user_input["device"])
            if device is not None:
                try:
                    return await self._finish(device, reconfigure=False)
                except GreeError:
                    errors["base"] = "cannot_connect"

        options = [
            SelectOptionDict(value=device.mac, label=f"{device.name} ({device.host})")
            for device in self._devices.values()
        ]
        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Validate an IPv4 address and verify heater status."""
        return await self._host_form("manual", user_input)

    async def async_step_import(self, user_input: dict) -> ConfigFlowResult:
        """Validate a heater imported from configuration.yaml."""
        try:
            return await self._connect(user_input[CONF_HOST], reconfigure=False)
        except ValueError:
            return self.async_abort(reason="invalid_host")
        except GreeError:
            return self.async_abort(reason="cannot_connect")

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Update an existing device's address."""
        return await self._host_form("reconfigure", user_input)

    async def _host_form(
        self, step_id: str, user_input: dict | None
    ) -> ConfigFlowResult:
        reconfigure = step_id == "reconfigure"
        errors = {}
        if user_input is not None:
            try:
                return await self._connect(user_input[CONF_HOST], reconfigure=reconfigure)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            except GreeError:
                errors["base"] = "cannot_connect"

        field = vol.Required(CONF_HOST)
        if reconfigure:
            field = vol.Required(
                CONF_HOST, default=self._get_reconfigure_entry().data[CONF_HOST]
            )
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema({field: str}), errors=errors
        )

    async def _connect(self, address: str, *, reconfigure: bool) -> ConfigFlowResult:
        host = str(IPv4Address(address.strip()))
        devices = await discover(host=host)
        if not devices:
            raise GreeError("No Gree device replied at this address")
        return await self._finish(devices[0], reconfigure=reconfigure)

    async def _finish(self, device: Device, *, reconfigure: bool) -> ConfigFlowResult:
        if reconfigure:
            await self.async_set_unique_id(device.mac, raise_on_progress=False)
            self._abort_if_unique_id_mismatch()
        else:
            await self.async_set_unique_id(device.mac)
            self._abort_if_unique_id_configured()

        client = GreeClient(device.host, device.mac)
        await client.read()
        data = {CONF_HOST: device.host, CONF_MAC: device.mac}
        if device.firmware:
            data["firmware"] = device.firmware
        if reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=NAME, data=data)
