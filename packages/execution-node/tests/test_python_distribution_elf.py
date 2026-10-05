"""Static synthetic ELF regressions; no interpreter or ELF tooling is executed."""

import struct
from pathlib import Path

import pytest
from boberagent_execution_node.preparation.python_distribution import (
    _elf,
    _LoadSegment,
    _read_file_backed_vaddr_range,
)

NEEDED = ("libpthread.so.0", "libdl.so.2", "libutil.so.1", "libm.so.6", "librt.so.1", "libc.so.6")
BASE = 0x3FF000
SECOND_OFFSET = 0x5000  # Deliberately not adjacent to the first segment's file bytes.
SECOND_SIZE = 0x20D70
STRING_ADDRESS = 0x3FF5D8
STRING_SIZE = 0xA51A


def split_elf() -> bytearray:
    """Observed EXEC/address layout class, without the real 30 MB interpreter."""
    data = bytearray(SECOND_OFFSET + SECOND_SIZE)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", data, 16, 2, 62)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 4)
    for index, segment in enumerate(
        (
            (1, 4, 0, BASE, 0, 0x1000, 0x1000, 0x1000),
            (1, 5, SECOND_OFFSET, 0x400000, 0, SECOND_SIZE, SECOND_SIZE, 0x1000),
            (2, 4, 0x388, BASE + 0x388, 0, 0x250, 0x250, 8),
            (3, 4, 0x1C070, 0x41B070, 0, 28, 28, 1),
        )
    ):
        struct.pack_into("<IIQQQQQQ", data, 64 + index * 56, *segment)
    data[0x1C070 : 0x1C070 + 28] = b"/lib64/ld-linux-x86-64.so.2\0".ljust(28, b"\0")
    strings = bytearray(STRING_SIZE)
    cursor = 0xA20  # The first dependency name itself crosses the virtual boundary.
    dynamic = [(5, STRING_ADDRESS), (10, STRING_SIZE)]
    for name in NEEDED:
        encoded = name.encode() + b"\0"
        strings[cursor : cursor + len(encoded)] = encoded
        dynamic.append((1, cursor))
        cursor += len(encoded)
    dynamic.append((15, cursor))
    strings[cursor : cursor + 15] = b"$ORIGIN/../lib\0"
    first_size = 0x400000 - STRING_ADDRESS
    data[0x5D8:0x1000] = strings[:first_size]
    data[SECOND_OFFSET : SECOND_OFFSET + len(strings) - first_size] = strings[first_size:]
    for index, entry in enumerate(dynamic):
        struct.pack_into("<qQ", data, 0x388 + index * 16, *entry)
    return data


def test_static_string_table_crosses_file_backed_loads() -> None:
    assert _elf(bytes(split_elf()), origin=Path("/runtime/bin"), boundary=Path("/runtime")) == (
        NEEDED,
        "/lib64/ld-linux-x86-64.so.2",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (3, 0x400001),  # Virtual gap.
        (5, 1),  # Remaining bytes are only BSS (memsz remains large).
        (2, SECOND_OFFSET + SECOND_SIZE + 1),  # Offset outside the file.
        (6, 1),  # Malformed filesz > memsz.
        (3, 2**64 - 1),  # Virtual range overflow.
    ],
)
def test_invalid_second_load_is_rejected(field: int, value: int) -> None:
    data = split_elf()
    segment = list(struct.unpack_from("<IIQQQQQQ", data, 120))
    segment[field] = value
    struct.pack_into("<IIQQQQQQ", data, 120, *segment)
    with pytest.raises(ValueError):
        _elf(bytes(data))


def test_truncated_second_load_is_rejected() -> None:
    with pytest.raises(ValueError, match="bounds"):
        _elf(bytes(split_elf()[:-1]))


def test_zero_fill_cannot_bridge_file_backed_mappings() -> None:
    data = split_elf()
    struct.pack_into("<Q", data, 64 + 40, 0x2000)  # First LOAD memsz, not filesz.
    struct.pack_into("<Q", data, 120 + 16, 0x401000)
    with pytest.raises(ValueError, match="gap"):
        _elf(bytes(data))


def test_range_reader_handles_three_independent_offsets_and_unsorted_headers() -> None:
    loads = (_LoadSegment(6, 100, 2), _LoadSegment(0, 102, 2), _LoadSegment(4, 104, 2))
    assert _read_file_backed_vaddr_range(b"cdXXefab", loads, 100, 6) == b"abcdef"
    assert _read_file_backed_vaddr_range(b"cdXXefab", tuple(reversed(loads)), 100, 6) == b"abcdef"


@pytest.mark.parametrize(
    "loads",
    [
        (),
        (_LoadSegment(0, 0, 1),) * 129,
        (_LoadSegment(-1, 0, 1),),
        (_LoadSegment(0, -1, 1),),
        (_LoadSegment(0, 0, -1),),
        (_LoadSegment(2**64 - 1, 0, 1),),
        (_LoadSegment(0, 2**64 - 1, 1),),
        (_LoadSegment(1, 0, 1),),
    ],
)
def test_range_reader_rejects_malformed_or_unbounded_segments(
    loads: tuple[_LoadSegment, ...],
) -> None:
    with pytest.raises(ValueError):
        _read_file_backed_vaddr_range(b"x", loads, 0, 1)


@pytest.mark.parametrize("identical", [False, True])
def test_overlapping_loads_must_resolve_identically(identical: bool) -> None:
    data = split_elf()
    # Add a short overlapping mapping starting inside the requested range. The
    # reader must notice it even when the original segment covers the entire chunk.
    struct.pack_into("<HH", data, 54, 56, 5)
    payload = bytes(data[SECOND_OFFSET + 20 : SECOND_OFFSET + 40])
    data[0x3000:0x3014] = payload if identical else b"X" * 20
    struct.pack_into("<IIQQQQQQ", data, 288, 1, 4, 0x3000, 0x400014, 0, 20, 20, 1)
    if identical:
        assert _elf(bytes(data))[0] == NEEDED
    else:
        with pytest.raises(ValueError, match="ambiguous"):
            _elf(bytes(data))


@pytest.mark.parametrize(
    ("address", "size"),
    [
        (STRING_ADDRESS, 4 * 1024**2 + 1),
        (STRING_ADDRESS, 0),
        (2**64 - 1, 10),
        (0, STRING_SIZE),
    ],
)
def test_invalid_string_table_range_is_rejected(address: int, size: int) -> None:
    data = split_elf()
    struct.pack_into("<qQ", data, 0x388, 5, address)
    struct.pack_into("<qQ", data, 0x398, 10, size)
    with pytest.raises(ValueError):
        _elf(bytes(data))


@pytest.mark.parametrize("tag", [5, 10])
def test_missing_or_conflicting_string_table_metadata_is_rejected(tag: int) -> None:
    data = split_elf()
    offset = 0x388 if tag == 5 else 0x398
    struct.pack_into("<qQ", data, offset, 0, 0)
    with pytest.raises(ValueError, match="string table"):
        _elf(bytes(data))
    data = split_elf()
    struct.pack_into("<qQ", data, 0x388 + 9 * 16, tag, 1)
    with pytest.raises(ValueError, match="string table"):
        _elf(bytes(data))


def test_split_table_preserves_normalized_origin_escape_rejection() -> None:
    with pytest.raises(ValueError, match="search path escape"):
        _elf(bytes(split_elf()), origin=Path("/runtime"), boundary=Path("/runtime"))
