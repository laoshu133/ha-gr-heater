# Gree Air-to-Water Heater for Home Assistant

A local Home Assistant integration for Gree air-to-water heat pump water heaters that speak the Gree V1 UDP protocol. It uses UDP port 7000 and requires Home Assistant 2026.11.2 or newer.

## Installation

1. In HACS, open **Custom repositories**, add `https://github.com/laoshu133/ha-gr-heater` as an **Integration**, and download **Gree Air-to-Water Heater**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Gree Air-to-Water Heater**. Select **Discover on the local network**, or **Enter an IP address** to connect directly by IPv4.

For manual installation, copy `custom_components/gr_heater` into Home Assistant’s `custom_components` directory, then restart and follow the same setup flow. Setups are deduplicated by device MAC. If the address changes, the integration can rediscover the heater by MAC on the local network. Use **Reconfigure** on the integration entry to save a different address.

For unattended setup, add the following top-level section to `configuration.yaml` and restart. Replace the example address with the heater’s IPv4 address. After import, the device appears under **Devices & services** and the YAML section can be removed.

```yaml
gr_heater:
  host: 192.0.2.10
```

## Controls and readings

- A `water_heater` entity reports the current and target water temperatures and the power state. It supports the `water_heater.set_temperature`, `water_heater.turn_on`, and `water_heater.turn_off` actions. Targets are whole degrees Celsius between 40 and 80, based on the public heat-pump field reference. A unit may impose a narrower range.
- Home Assistant polls every 30 seconds. After a write, it reads device status and reports an error if it cannot confirm the requested value.
- When supplied by the device, `gree_work_state` and `gree_mode` show the raw `Wstate` and `Wmod` codes. `water_level_percent` shows the decoded tank level. Operating-mode changes are unavailable.
- Discovery lists devices advertising names that start with `GR-Heater`. Manual setup accepts a device when its V1 status contains the water-heater fields. Broadcast discovery requires local broadcast reachability. Manual entry requires direct UDP reachability.

## Compatibility

The initial target is a Gree V1.2.1 Wi-Fi module advertising discovery ID `9100` and reporting status model ID `901d`. These IDs identify protocol metadata. The appliance’s nameplate model and other device variants are unverified.

## Development

Run the config flow, entity and simulated UDP device tests against the same Home Assistant image used by CI.

```sh
docker run --rm --network none --entrypoint python \
  --volume "$PWD:/project:ro" --workdir /project \
  ghcr.io/home-assistant/home-assistant:2026.11.2 \
  -m unittest discover -s tests -v
```

## Protocol references and license

This MIT-licensed implementation uses the public Gree V1 wire format documented by [greeclimate](https://github.com/cmroche/greeclimate) (GPL-3.0). Heater field names and temperature encodings were cross-checked against [Gree Cloud 1.7.6](https://github.com/davo22/homeassistant-gree-cloud/tree/1.7.6) (MIT).
