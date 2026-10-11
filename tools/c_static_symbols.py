"""Bounded strong-definition inspection of LLVM Wasm linking-version-2 objects."""
from __future__ import annotations

from tools.application_dependency_store import DependencyError

MAX_SYMBOLS = 65536
MAX_SYMBOL_BYTES = 1024 * 1024
MAX_NAME_BYTES = 4096


class Reader:
    def __init__(self, data: bytes):
        self.data, self.offset, self.name_bytes = data, 0, 0

    def byte(self) -> int:
        if self.offset >= len(self.data):
            raise DependencyError("c-wasm-symbol-table-malformed")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def unsigned(self) -> int:
        value = 0
        for shift in range(0, 35, 7):
            byte = self.byte()
            value |= (byte & 0x7f) << shift
            if not byte & 0x80:
                if value <= 0xffffffff:
                    return value
                break
        raise DependencyError("c-wasm-symbol-table-malformed")

    def name(self) -> str:
        length = self.unsigned()
        self.name_bytes += length
        if not 0 < length <= MAX_NAME_BYTES or self.name_bytes > MAX_SYMBOL_BYTES:
            raise DependencyError("c-wasm-symbol-table-limit")
        end = self.offset + length
        if end > len(self.data):
            raise DependencyError("c-wasm-symbol-table-malformed")
        try:
            value = self.data[self.offset:end].decode("utf-8", "strict")
        except UnicodeError:
            raise DependencyError("c-wasm-symbol-table-malformed") from None
        if "\0" in value:
            raise DependencyError("c-wasm-symbol-table-malformed")
        self.offset = end
        return value


def strong_symbols(linking: bytes) -> list[str]:
    """Inspect symbols, including unused archive members; final linking still validates code."""
    section = Reader(linking)
    symbols, found = set(), False
    while section.offset < len(linking):
        kind, length = section.byte(), section.unsigned()
        end = section.offset + length
        if end > len(linking):
            raise DependencyError("c-wasm-symbol-table-malformed")
        if kind == 8:  # WASM_SYMBOL_TABLE, after the already verified linking version.
            if found:
                raise DependencyError("c-wasm-symbol-table-malformed")
            found = True
            table = Reader(linking[section.offset:end])
            count = table.unsigned()
            if count > MAX_SYMBOLS:
                raise DependencyError("c-wasm-symbol-table-limit")
            for _index in range(count):
                symbol_kind, flags = table.byte(), table.unsigned()
                binding, undefined = flags & 3, bool(flags & 0x10)
                if symbol_kind > 5 or flags & ~0x3f7:
                    raise DependencyError("c-wasm-symbol-profile-unsupported")
                if flags & 0x100:
                    raise DependencyError("c-wasm-object-requires-unqualified-runtime-profile")
                name = None
                if symbol_kind in (0, 2, 4, 5):
                    if binding == 3 or (binding == 2 and undefined):
                        raise DependencyError("c-wasm-symbol-table-malformed")
                    table.unsigned()  # function/global/event/table index
                    if not undefined or flags & 0x40:
                        name = table.name()
                elif symbol_kind == 1:
                    if undefined and binding in (2, 3):
                        raise DependencyError("c-wasm-symbol-table-malformed")
                    name = table.name()
                    if not undefined:
                        if binding == 3:
                            table.unsigned()  # common data size
                            if table.byte() > 31:
                                raise DependencyError("c-wasm-symbol-profile-unsupported")
                        else:
                            for _field in range(3):  # segment, offset, size
                                table.unsigned()
                else:
                    table.unsigned()  # section index; never an external definition
                if name is not None and binding == 0 and not undefined:
                    if name in symbols:
                        raise DependencyError("c-static-archive-duplicate-strong-symbol")
                    symbols.add(name)
            if table.offset != len(table.data):
                raise DependencyError("c-wasm-symbol-table-malformed")
        section.offset = end
    return sorted(symbols)
