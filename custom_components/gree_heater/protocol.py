"""Local Gree V1 UDP client for air-to-water heaters."""

import asyncio
from base64 import b64decode, b64encode
from collections.abc import Callable
from dataclasses import dataclass
import json
import re
import socket

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PORT = 7000
REQUEST_TIMEOUT = 2.0
SCAN_TIMEOUT = 1.5
_BROADCAST = "255.255.255.255"
# Public Gree V1 bootstrap constant. Bind supplies a separate key for each device.
_BOOTSTRAP = b"a3K8Bx%2r8Y7#xDh"
_REQUIRED = ("WatTmp", "SetTemInt", "Pow")
_STATUS = (*_REQUIRED, "SetTemDec", "Wstate", "Wmod", "Watpercent")
_METADATA = ("mid", "hid")


class GreeError(Exception):
    """A device did not return usable data."""


def _mac(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower().replace(":", "").replace("-", "")
    return normalized if re.fullmatch(r"[0-9a-f]{12}", normalized) else None


def _decode(packet: bytes, key: bytes) -> tuple[dict, dict]:
    outer = json.loads(packet)
    if not isinstance(outer, dict) or outer.get("t") != "pack":
        raise ValueError("Expected a Gree envelope")
    encrypted = outer.get("pack")
    if not isinstance(encrypted, str):
        raise ValueError("Expected an encrypted Gree payload")
    aes = Cipher(algorithms.AES128(key), modes.ECB()).decryptor()
    padded = aes.update(b64decode(encrypted, validate=True)) + aes.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    inner = json.loads(unpadder.update(padded) + unpadder.finalize())
    if not isinstance(inner, dict):
        raise ValueError("Expected a Gree payload object")
    return outer, inner


def _encode(mac: str, payload: dict, key: bytes, *, bind: bool) -> bytes:
    padder = padding.PKCS7(128).padder()
    body = json.dumps({"mac": mac, **payload}, separators=(",", ":")).encode()
    padded = padder.update(body) + padder.finalize()
    aes = Cipher(algorithms.AES128(key), modes.ECB()).encryptor()
    encrypted = b64encode(aes.update(padded) + aes.finalize()).decode("ascii")
    return json.dumps(
        {"t": "pack", "cid": "app", "tcid": mac, "i": int(bind), "uid": 0,
         "pack": encrypted},
        separators=(",", ":"),
    ).encode()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class Device:
    """Identity advertised by the device."""

    host: str
    mac: str
    name: str | None = None
    firmware: str | None = None


@dataclass(frozen=True, slots=True)
class HeaterState:
    """Validated water-heater properties from one poll."""

    current_temperature: int
    target_integer: int
    target_decimal: int | None
    power: int
    work_state: int | None
    mode: int | None
    water_level: int | None

    @property
    def target_temperature(self) -> float:
        """Return the target in Celsius."""
        return self.target_integer + (self.target_decimal or 0) / 10


async def discover(*, host: str | None = None) -> list[Device]:
    """Discover V1 units by broadcast, or identify a unit by unicast."""
    destination = host or _BROADCAST
    devices: dict[str, Device] = {}
    loop = asyncio.get_running_loop()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 0))
            await loop.sock_sendto(sock, b'{"t":"scan"}', (destination, PORT))
            async with asyncio.timeout(SCAN_TIMEOUT):
                while True:
                    packet, address = await loop.sock_recvfrom(sock, 65535)
                    if host is not None and address[0] != host:
                        continue
                    try:
                        outer, data = _decode(packet, _BOOTSTRAP)
                    except ValueError:
                        continue
                    identity = _mac(data.get("mac") or outer.get("cid"))
                    if data.get("t") != "dev" or identity is None:
                        continue
                    name = _text(data.get("name"))
                    if host is None and not (name or "").lower().startswith("gr-heater"):
                        continue
                    devices[identity] = Device(
                        address[0], identity, name, _text(data.get("ver"))
                    )
                    if host is not None:
                        break
    except TimeoutError:
        pass
    except OSError:
        raise GreeError("Could not send or receive Gree discovery") from None
    return list(devices.values())


class GreeClient:
    """Serialize status and commands for a single device."""

    def __init__(self, host: str, mac: str) -> None:
        self.host = host
        self.mac = mac
        self._key: bytes | None = None
        self._lock = asyncio.Lock()

    async def _exchange(
        self, payload: dict, accept: Callable[[dict], bool], *, bind: bool = False
    ) -> dict:
        key = _BOOTSTRAP if bind else self._key
        assert key is not None
        request = _encode(self.mac, payload, key, bind=bind)
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setblocking(False)
                    await loop.sock_connect(sock, (self.host, PORT))
                    await loop.sock_sendall(sock, request)
                    while True:
                        packet = await loop.sock_recv(sock, 65535)
                        try:
                            outer, reply = _decode(packet, key)
                        except ValueError:
                            continue
                        identity = _mac(reply.get("mac") or outer.get("cid"))
                        if identity == self.mac and accept(reply):
                            return reply
        except (TimeoutError, OSError):
            raise GreeError(f"No usable Gree {payload['t']} response") from None

    async def _bind(self) -> None:
        if self._key is not None:
            return
        reply = await self._exchange(
            {"t": "bind", "uid": 0}, lambda data: data.get("t") == "bindok", bind=True
        )
        raw = reply.get("key")
        if not isinstance(raw, str) or len(raw.encode()) != 16:
            raise GreeError("Invalid Gree bind response")
        self._key = raw.encode()

    async def _properties(self, fields: tuple[str, ...]) -> dict | None:
        def accept(reply: dict) -> bool:
            return reply.get("t") == "dat" and isinstance(reply.get("cols"), list)

        reply = await self._exchange({"t": "status", "cols": fields}, accept)
        columns, values = reply["cols"], reply.get("dat")
        if (
            not isinstance(values, list)
            or len(columns) != len(values)
            or any(not isinstance(field, str) or field not in fields for field in columns)
            or len(set(columns)) != len(columns)
        ):
            return None
        return dict(zip(columns, values, strict=True))

    async def _read(self) -> HeaterState:
        await self._bind()
        props = await self._properties(_STATUS)
        # Some firmware omits a value but retains its column. Never guess offsets.
        if props is None:
            props = {}
            for field in _STATUS:
                try:
                    props.update(await self._properties((field,)) or {})
                except GreeError:
                    if field in _REQUIRED:
                        raise
        for field in _REQUIRED:
            if type(props.get(field)) is not int:
                raise GreeError("The device did not report water-heater properties")
        if props["Pow"] not in (0, 1) or not 0 <= props["WatTmp"] <= 200:
            raise GreeError("Invalid Gree water-heater status")

        def optional_int(field: str) -> int | None:
            value = props.get(field)
            return value if type(value) is int else None

        decimal = optional_int("SetTemDec")
        level = optional_int("Watpercent")
        return HeaterState(
            current_temperature=props["WatTmp"] - 100,
            target_integer=props["SetTemInt"],
            target_decimal=decimal if decimal in range(10) else None,
            power=props["Pow"],
            work_state=optional_int("Wstate"),
            mode=optional_int("Wmod"),
            water_level=level - 100 if level in range(100, 201) else None,
        )

    async def read(self) -> HeaterState:
        """Poll status; rebind on the first failure and try again once."""
        async with self._lock:
            for attempt in range(2):
                try:
                    return await self._read()
                except GreeError:
                    self._key = None
                    if attempt:
                        raise
        raise AssertionError("Unreachable")

    async def metadata(self) -> dict[str, str]:
        """Read each optional model hint separately from live values."""
        async with self._lock:
            await self._bind()
            result = {}
            for field in _METADATA:
                try:
                    props = await self._properties((field,))
                except GreeError:
                    continue
                if (value := _text((props or {}).get(field))) is not None:
                    result[field] = value
            return result

    async def write(self, values: dict[str, int]) -> HeaterState:
        """Send one command, then get authoritative status even if its ack was lost."""
        async with self._lock:
            try:
                await self._bind()
                try:
                    await self._exchange(
                        {"t": "cmd", "opt": list(values), "p": list(values.values())},
                        lambda data: data.get("t") == "res",
                    )
                except GreeError:
                    # A timeout cannot tell us whether the command already ran.
                    self._key = None
                return await self._read()
            except GreeError:
                self._key = None
                raise
