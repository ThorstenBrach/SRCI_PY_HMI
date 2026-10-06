"""System variables of the RC (Read/WriteSystemVariable): the standardized parameter list of the
specification (SIMATIC Robot Library manual, chapter 7.3) and the conversion of the 4-byte values.

Every (sub-)parameter is transferred in 4 bytes, its type is a DataType ID (manual table 6-72).
The bytes are interpreted little endian - the way a PLC copies them into its variables.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

BOOL, BYTE, WORD, DWORD, SINT, USINT, INT, UINT, DINT, UDINT, REAL, CHAR, CHARS = range(1, 14)
TYPE_NAMES = {BOOL: "BOOL", BYTE: "BYTE", WORD: "WORD", DWORD: "DWORD", SINT: "SINT", USINT: "USINT",
              INT: "INT", UINT: "UINT", DINT: "DINT", UDINT: "UDINT", REAL: "REAL", CHAR: "CHAR",
              CHARS: "CHAR[4]"}  # fmt: skip
_FORMATS = {BOOL: "<?", BYTE: "<B", WORD: "<H", DWORD: "<I", SINT: "<b", USINT: "<B", INT: "<h",
            UINT: "<H", DINT: "<i", UDINT: "<I", REAL: "<f"}  # fmt: skip


@dataclass
class Value:
    """One (sub-)parameter as transferred."""

    sub: int  # SubParameterID
    data_type: int  # DataType ID
    raw: bytes  # 4 bytes

    def decode(self) -> float | int | bool | str:
        if self.data_type in (CHAR, CHARS):
            return self.raw[: 1 if self.data_type == CHAR else 4].rstrip(b"\0").decode("latin-1")
        fmt = _FORMATS.get(self.data_type)
        if fmt is None:
            return self.raw.hex(" ")
        value: float | int | bool = struct.unpack_from(fmt, self.raw.ljust(4, b"\0"))[0]
        return round(value, 6) if isinstance(value, float) else value

    @classmethod
    def encode(cls, sub: int, data_type: int, value: object) -> Value:
        if data_type in (CHAR, CHARS):
            raw = str(value).encode("latin-1")[: 1 if data_type == CHAR else 4]
        elif data_type == REAL:
            raw = struct.pack("<f", float(str(value).replace(",", ".")))
        elif data_type == BOOL:
            raw = struct.pack("<?", str(value).strip().lower() in ("1", "true", "wahr", "on", "ein"))
        elif data_type in _FORMATS:
            raw = struct.pack(_FORMATS[data_type], int(str(value), 0))
        else:
            raise ValueError(f"unknown data type {data_type}")
        return cls(sub, data_type, raw.ljust(4, b"\0"))


@dataclass(frozen=True)
class Parameter:
    """A parameter of the standardized list."""

    id: int
    de: str
    en: str
    subs: tuple[str, ...]  # names of the sub-parameters 1..n
    data_type: int
    unit: str = ""
    writable: bool = False

    def name(self, lang: str) -> str:
        return self.de if lang == "de" else self.en

    @property
    def text(self) -> bool:
        """The value is a text spread over the sub-parameters (4 characters each)."""
        return self.data_type == CHARS


def _symbols(n: int) -> tuple[str, ...]:
    return tuple(f"{4 * i}..{4 * i + 3}" for i in range(n))


_AXES = ("J1", "J2", "J3", "J4", "J5", "J6", "E1", "E2", "E3", "E4", "E5", "E6")
_POSE = ("X", "Y", "Z", "Rx", "Ry", "Rz", "E1", "E2", "E3", "E4", "E5", "E6", "Tool", "Frame")
_IP = ("1", "2", "3", "4", "5 (IPv6)", "6 (IPv6)")

# manual 7.3, table 7-7 (the positions 16..18 have more sub-parameters with other types - only the
# REAL values are listed)
PARAMETERS: tuple[Parameter, ...] = (
    Parameter(1, "Seriennummer der RC", "Serial number of the RC", _symbols(4), CHARS),
    Parameter(2, "Hersteller der RC", "Manufacturer of the RC", _symbols(5), CHARS),
    Parameter(3, "Name der RC (anwenderdefiniert)", "User defined name of the RC", _symbols(5), CHARS,
              writable=True),
    Parameter(4, "Firmware-Version", "Firmware version", _symbols(3), CHARS),
    Parameter(5, "IP-Adresse PROFINET-Port", "IP address PROFINET port", _IP, UINT),
    Parameter(6, "IP-Adresse TCP/IP-Port", "IP address TCP/IP port", _IP, UINT),
    Parameter(7, "Betriebsstunden", "Operating hours", ("h",), UDINT, "h"),
    Parameter(8, "Positionsanpassung Achsen", "Position adjustment of the axes", _AXES, REAL, "°", True),
    Parameter(9, "Korrekturposition Achsen", "Correction position of the axes", _AXES, REAL, "mm", True),
    Parameter(10, "Welt- zu Basiskoordinatensystem", "World to base frame", _POSE[:6], REAL, "mm / °"),
    Parameter(11, "Zuletzt aktiver Frame", "Last active frame", ("No.",), USINT),
    Parameter(12, "Zuletzt aktives Werkzeug", "Last active tool", ("No.",), USINT),
    Parameter(13, "Zuletzt aktive Last", "Last active load", ("No.",), USINT),
    Parameter(14, "TCP-Istgeschwindigkeit", "Actual TCP velocity", ("%",), USINT, "%"),
    Parameter(15, "Achs-Istgeschwindigkeit", "Actual joint velocity", _AXES, USINT, "%"),
    Parameter(16, "Ziel des letzten Fahrbefehls", "Target of the last motion", _POSE[:12], REAL, "mm / °"),
    Parameter(17, "Ziel des aktuellen Fahrbefehls", "Target of the current motion", _POSE[:12], REAL, "mm / °"),
    Parameter(18, "Position beim Verlassen der Bahn", "Position when leaving the path", _POSE[:12], REAL,
              "mm / °"),
    Parameter(19, "Armlängen", "Arm lengths", _AXES, REAL, "mm"),
    Parameter(20, "Motorstrom", "Motor current", _AXES, REAL, "mA"),
    Parameter(21, "Zustimmtaster", "Enabling switch", ("",), CHAR),
    Parameter(22, "Antriebsmoment", "Drive torque", _AXES, INT),
    Parameter(23, "Kraftsensor", "Force sensor", ("Fx", "Fy", "Fz", "Mx", "My", "Mz"), REAL),
    Parameter(24, "Bremsen offen", "Brakes open", _AXES[:6], BOOL),
    Parameter(25, "Name des RC-Systems", "Name of the RC system", _symbols(5), CHARS),
    Parameter(26, "Name der RC", "Name of the RC", _symbols(5), CHARS),
    Parameter(27, "DelayTime", "DelayTime", ("ms",), UINT, "ms", True),
    Parameter(28, "MonitoringTime", "MonitoringTime", ("ms",), UINT, "ms", True),
    Parameter(29, "Bedienpanel verbunden", "Panel connected", ("",), BOOL),
    Parameter(30, "In Überschleifzone warten", "Wait at blending zone", ("",), BOOL, writable=True),
    Parameter(31, "Punkte für Überschleifen", "Points for blending", ("",), USINT, writable=True),
    Parameter(32, "LifeSign-Timeout", "LifeSign timeout", ("ms",), UINT, "ms", True),
    Parameter(33, "Letzte Bahnposition (kartesisch)", "Last path position (Cartesian)", _POSE[:12], REAL,
              "mm / °"),
    Parameter(34, "Letzte Bahnposition (Achsen)", "Last path position (joints)", _AXES, REAL, "°"),
)  # fmt: skip
BY_ID = {p.id: p for p in PARAMETERS}


def text_of(values: list[Value]) -> str:
    """A text parameter: the characters of all sub-parameters."""
    return b"".join(v.raw for v in values).split(b"\0", 1)[0].decode("latin-1").strip()
