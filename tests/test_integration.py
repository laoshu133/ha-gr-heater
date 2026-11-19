"""Exercise config entries and services against a UDP Gree V1 emulator."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from homeassistant.bootstrap import async_from_config_dict
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant import loader
from homeassistant.setup import async_setup_component

from custom_components.gr_heater import protocol
from custom_components.gr_heater.const import DOMAIN

MAC = "020000000001"
HOST = "127.0.0.1"
INITIAL_KEY = b"test-device-key!"
NEXT_KEY = b"fake-new-session"
ENTITY = "water_heater.gree_air_to_water_heater"


class SimulatedHeater(asyncio.DatagramProtocol):
    """Implement only the protocol used by the integration."""

    def __init__(self):
        self.key = INITIAL_KEY
        self.bound = 0
        self.apply_writes = True
        self.drop_ack = False
        self.mismatch = False
        self.commands = []
        self.queries = []
        self.values = {
            "WatTmp": 154,
            "SetTemInt": 55,
            "SetTemDec": 0,
            "Pow": 1,
            "Wstate": 0,
            "Wmod": 1,
            "Watpercent": 200,
            "mid": "fabc",
            "hid": "synthetic-firmware",
        }

    def connection_made(self, transport):
        self.transport = transport

    def _reply(self, data, key, address):
        packet = json.loads(protocol._encode(MAC, data, key, bind=False))
        packet["cid"] = MAC
        packet["tcid"] = "app"
        self.transport.sendto(json.dumps(packet).encode(), address)

    def datagram_received(self, packet, address):
        outer = json.loads(packet)
        if outer == {"t": "scan"}:
            self._reply(
                {"t": "dev", "name": "GR-Heater_Simulator", "ver": "V1.0-test"},
                protocol._BOOTSTRAP,
                address,
            )
            return
        if outer.get("tcid") != MAC:
            return
        binding = outer.get("i") == 1
        key = protocol._BOOTSTRAP if binding else self.key
        try:
            _, data = protocol._decode(packet, key)
        except ValueError:
            return
        match data["t"]:
            case "bind":
                self.bound += 1
                self._reply({"t": "bindok", "key": self.key.decode()}, key, address)
            case "status":
                cols = data["cols"]
                self.queries.append(cols)
                if self.mismatch and len(cols) > 1:
                    values = [self.values[col] for col in cols if col in self.values and col != "Wstate"]
                else:
                    cols = [col for col in cols if col in self.values]
                    values = [self.values[col] for col in cols]
                self._reply({"t": "dat", "cols": cols, "dat": values}, key, address)
            case "cmd":
                values = dict(zip(data["opt"], data["p"], strict=True))
                self.commands.append(values)
                if self.apply_writes:
                    self.values.update(values)
                if not self.drop_ack:
                    self._reply({"t": "res"}, key, address)


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "custom_components").symlink_to(
            Path(__file__).resolve().parents[1] / "custom_components",
            target_is_directory=True,
        )
        loop = asyncio.get_running_loop()
        transport, self.device = await loop.create_datagram_endpoint(
            SimulatedHeater, local_addr=("0.0.0.0", 0)
        )
        self.addCleanup(transport.close)
        for name, value in {
            "PORT": transport.get_extra_info("sockname")[1],
            "REQUEST_TIMEOUT": 0.25,
            "SCAN_TIMEOUT": 0.15,
            "_BROADCAST": "127.255.255.255",
        }.items():
            patcher = patch.object(protocol, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.hass = HomeAssistant(self.tmp.name)
        self.addAsyncCleanup(self.hass.async_stop, force=True)
        loader.async_setup(self.hass)
        self.hass.config.skip_pip = True
        self.assertIs(await async_from_config_dict({}, self.hass), self.hass)
        await self.hass.async_start()

    async def _flow(self):
        flow = self.hass.config_entries.flow
        menu = await flow.async_init(DOMAIN, context={"source": "user"})
        self.assertEqual(menu["type"], FlowResultType.MENU)
        return flow, menu["flow_id"]

    async def _configure(self, step="manual"):
        flow, flow_id = await self._flow()
        form = await flow.async_configure(flow_id, {"next_step_id": step})
        self.assertEqual(form["step_id"], step)
        data = {"host": HOST} if step == "manual" else {"device": MAC}
        result = await flow.async_configure(flow_id, data)
        await self.hass.async_block_till_done()
        return result

    async def _setup_heater(self, step="manual"):
        result = await self._configure(step)
        self.assertEqual(result["type"], FlowResultType.CREATE_ENTRY)
        entry = result["result"]
        self.assertIs(entry.state, ConfigEntryState.LOADED)
        self.assertEqual(entry.unique_id, MAC)
        return entry

    def _state(self):
        state = self.hass.states.get(ENTITY)
        self.assertIsNotNone(state)
        return state

    async def _call(self, service, **data):
        await self.hass.services.async_call(
            "water_heater", service, {"entity_id": ENTITY, **data}, blocking=True
        )

    async def test_discovery_metadata_dedup_and_reconfigure(self):
        entry = await self._setup_heater("scan")
        self.assertIn(["mid"], self.device.queries)
        self.assertIn(["hid"], self.device.queries)
        self.assertEqual(entry.runtime_data.metadata["mid"], "fabc")
        self.assertEqual(self._state().attributes["current_temperature"], 54)
        self.assertEqual(self._state().attributes["gree_mode"], 1)
        self.assertEqual(self._state().attributes["water_level_percent"], 100)

        duplicate = await self._configure()
        self.assertEqual(duplicate["reason"], "already_configured")
        flow = self.hass.config_entries.flow
        form = await flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        result = await flow.async_configure(form["flow_id"], {"host": HOST})
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(len(self.hass.config_entries.async_entries(DOMAIN)), 1)

    async def test_services_and_status_confirmation(self):
        await self._setup_heater()
        await self._call("set_temperature", temperature=56)
        self.assertEqual(self._state().attributes["temperature"], 56)
        self.assertEqual(self.device.commands[-1], {"SetTemInt": 56, "SetTemDec": 0})
        await self._call("turn_off")
        self.assertEqual(self._state().state, "off")
        await self._call("turn_on")
        self.assertEqual(self._state().state, "on")
        self.assertEqual(self.device.commands[-2:], [{"Pow": 0}, {"Pow": 1}])

        with self.assertRaises(ServiceValidationError):
            await self._call("set_temperature", temperature=45.5)
        self.device.apply_writes = False
        with self.assertRaises(HomeAssistantError):
            await self._call("set_temperature", temperature=57)
        self.assertEqual(self._state().attributes["temperature"], 56)
        self.assertEqual(len(self.device.commands), 4)

        self.device.apply_writes = True
        self.device.drop_ack = True
        await self._call("set_temperature", temperature=58)
        self.assertEqual(self._state().attributes["temperature"], 58)
        self.assertEqual(len(self.device.commands), 5)

    async def test_rebind_and_malformed_columns(self):
        entry = await self._setup_heater()
        bound = self.device.bound
        self.device.key = NEXT_KEY
        self.device.values["WatTmp"] = 152
        self.device.values.pop("Wstate")
        self.device.values.pop("SetTemDec")
        self.device.mismatch = True
        await entry.runtime_data.async_refresh()
        self.assertEqual(self.device.bound, bound + 1)
        self.assertEqual(self._state().attributes["current_temperature"], 52)
        self.assertEqual(self._state().attributes["temperature"], 55)
        self.assertNotIn("gree_work_state", self._state().attributes)
        await self._call("set_temperature", temperature=56)
        self.assertEqual(self.device.commands, [{"SetTemInt": 56}])

    async def test_device_becomes_unavailable_and_recovers(self):
        entry = await self._setup_heater()
        self.device.values.pop("Pow")
        await entry.runtime_data.async_refresh()
        self.assertEqual(self._state().state, "unavailable")
        self.device.values["Pow"] = 1
        await entry.runtime_data.async_refresh()
        self.assertEqual(self._state().state, "on")

    async def test_yaml_import_creates_normal_config_entry(self):
        self.assertTrue(
            await async_setup_component(self.hass, DOMAIN, {DOMAIN: {"host": HOST}})
        )
        await self.hass.async_block_till_done()
        entry, = self.hass.config_entries.async_entries(DOMAIN)
        self.assertEqual(entry.source, "import")
        self.assertIs(entry.state, ConfigEntryState.LOADED)
        self.assertEqual((await self._configure())["reason"], "already_configured")
        self.assertEqual(self._state().attributes["temperature"], 55)
