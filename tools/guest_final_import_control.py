"""Append one diagnostic import without rewriting any original component byte.

This is a compiler-inspection control, never an execution or signing tool.
The caller must validate both binaries with the pinned wasm-tools validator.
The finite index-space decoder follows wasm-encoder 0.254.2 component
builder/import/export/alias encodings. Unsupported forms refuse the control.
"""
from tools.guest_emitted_code import Budget, COMPONENT, Reader

UNKNOWN = 'diagnostic:unknown/final-import@0.1.0'
MAXIMUM = 64 * 1024 * 1024


def require(value):
    if not value:
        raise ValueError('final-import-control-unsupported-or-out-of-bound')


def leb(value):
    require(type(value) is int and 0 <= value < 2**32)
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def sections(raw):
    require(type(raw) is bytes and raw.startswith(COMPONENT) and len(raw) <= MAXIMUM)
    reader = Reader(raw[8:], Budget())
    output = []
    while reader.at < len(reader.data):
        require(len(output) < 4096)
        kind = reader.byte()
        require(kind <= 11)
        size = reader.count(MAXIMUM)
        output.append((kind, bytes(reader.take(size))))
    return output


def external_name(reader):
    # The selected 0.254 encoding has the ordinary/legacy name discriminator.
    # Extended extern-name options are deliberately outside this control.
    require(reader.byte() in (0, 1))
    return reader.name()


def external_kind(reader):
    kind = reader.byte()
    if kind == 0:
        require(reader.byte() == 0x11)
    else:
        require(kind in (1, 3, 4, 5))
    return kind


def type_reference(reader):
    kind = external_kind(reader)
    if kind == 3:
        bound = reader.byte()
        require(bound in (0, 1))
        if bound == 0:
            reader.leb()
    else:
        reader.leb()
    return kind


def outer_type_count(raw):
    total = 0
    for kind, payload in sections(raw):
        if kind not in (6, 7, 10, 11):
            continue
        reader = Reader(payload, Budget())
        count = reader.count(16384)
        if kind == 7:
            # Nested type declarations do not enter the outer index space.
            # The actual validator, rather than this counter, checks bodies.
            total += count
        else:
            for _ in range(count):
                if kind == 6:
                    sort = reader.byte()
                    if sort == 0:
                        require(reader.byte() in (0, 1, 2, 3, 4, 0x10, 0x11))
                    else:
                        require(sort in (1, 3, 4, 5))
                    target = reader.byte()
                    require(target in (0, 1, 2))
                    reader.leb()
                    if target == 2:
                        reader.leb()
                    else:
                        reader.name()
                    total += sort == 3
                elif kind == 10:
                    external_name(reader)
                    total += type_reference(reader) == 3
                else:
                    external_name(reader)
                    total += external_kind(reader) == 3
                    reader.leb()
                    ascribed = reader.byte()
                    require(ascribed in (0, 1))
                    if ascribed:
                        type_reference(reader)
            reader.done()
        require(total <= 16384)
    return total


def append_unknown(raw, template):
    """Keep the complete original as a byte-exact prefix; append two sections.

    `template` is assembled by the pinned tool from TEMPLATE below. It has no
    core module, initializer, implementation, authority or executable code.
    """
    additions = sections(template)
    require([kind for kind, _ in additions] == [7, 10])
    types, imports = (payload for _, payload in additions)
    reader = Reader(types, Budget())
    require(reader.leb() == 1)
    reader = Reader(imports, Budget())
    require(reader.leb() == 1 and external_name(reader) == UNKNOWN)
    require(external_kind(reader) == 5 and reader.leb() == 0)
    reader.done()
    index = outer_type_count(raw)
    name = UNKNOWN.encode('ascii')
    imports = b'\x01\x00' + leb(len(name)) + name + b'\x05' + leb(index)
    suffix = b'\x07' + leb(len(types)) + types + b'\x0a' + leb(len(imports)) + imports
    require(len(raw) + len(suffix) <= MAXIMUM)
    return raw + suffix


TEMPLATE = '''(component
  (type (instance
    (type (func))
    (export "touch" (func (type 0)))))
  (import "diagnostic:unknown/final-import@0.1.0" (instance (type 0))))
'''
