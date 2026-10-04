"""System variables of the RC (Read/WriteSystemVariable, manual 7.3): raw 4-byte values."""

from __future__ import annotations

import struct
from dataclasses import dataclass

# DataType IDs (manual table 6-72) -> struct format (little endian, like the memory copy in the PLC)
FORMATS = {1: "<?", 2: "<B", 3: "<H", 4: "<I", 5: "<b", 6: "<B", 7: "<h", 8: "<H", 9: "<i", 10: "<I",
           11: "<f", 12: "<c"}  # fmt: skip
CHAR_ARRAY = 13


@dataclass
class Value:
    sub: int  # SubParameterID
    data_type: int  # DataType ID
    raw: bytes  # 4 bytes as transferred

    def decode(self) -> object:
        if self.data_type == CHAR_ARRAY:
            return self.raw.rstrip(b"\0").decode("latin-1")
        fmt = FORMATS.get(self.data_type)
        if fmt is None:
            return self.raw.hex(" ")
        return struct.unpack_from(fmt, self.raw.ljust(4, b"\0"))[0]
