#!/usr/bin/env python3
"""Static protocol-vector tests for the embedded Oregon Scientific V2.1 decoder."""

BIT_MASK = (0x10, 0x20, 0x40, 0x80, 0x01, 0x02, 0x04, 0x08)


def nibble(frame: bytes, index: int) -> int:
    value = frame[index // 2]
    return value >> 4 if index % 2 == 0 else value & 0x0F


def checksum_ok(frame: bytes, position: int) -> bool:
    calculated = sum(nibble(frame, i) for i in range(1, position)) & 0xFF
    received = (nibble(frame, position + 1) << 4) | nibble(frame, position)
    return calculated == received


def logical_bits(frame: bytes):
    for value in frame:
        for mask in BIT_MASK:
            yield 1 if value & mask else 0


def physical_intervals(frame: bytes):
    physical = [index & 1 for index in range(32)]
    for bit in logical_bits(frame):
        physical.extend((1 - bit, bit))
    intervals = []
    for previous, current in zip(physical, physical[1:]):
        intervals.extend(("S", "S") if previous == current else ("L",))
    return intervals


def decode_intervals(intervals, expected_bytes: int) -> bytes:
    preamble_longs = 0
    decoding = False
    short_pending = False
    last_physical = 1
    pair_first = None
    decoded = []
    for kind in intervals:
        if not decoding:
            if kind == "L":
                preamble_longs += 1
                continue
            if kind == "S" and preamble_longs >= 24:
                decoding = True
            else:
                preamble_longs = 0
                continue
        if kind == "L":
            assert not short_pending
            last_physical ^= 1
            bit = last_physical
        else:
            if not short_pending:
                short_pending = True
                continue
            short_pending = False
            bit = last_physical
        if pair_first is None:
            pair_first = bit
            continue
        assert pair_first != bit
        pair_first = None
        decoded.append(bit)
        if len(decoded) == expected_bytes * 8:
            break
    assert len(decoded) == expected_bytes * 8
    result = bytearray(expected_bytes)
    for index, bit in enumerate(decoded):
        if bit:
            result[index // 8] |= BIT_MASK[index % 8]
    return bytes(result)


def temperature(frame: bytes) -> float:
    value = nibble(frame, 11) * 10 + nibble(frame, 10) + nibble(frame, 9) / 10
    return -value if nibble(frame, 12) == 8 else value


def main() -> None:
    vectors = (
        (bytes.fromhex("AEC4015F07300D30"), 13, 3.7, None),
        (bytes.fromhex("A1D20485C480882835"), 16, -8.4, 28),
    )
    for frame, checksum_position, expected_temp, expected_humidity in vectors:
        assert checksum_ok(frame, checksum_position)
        assert decode_intervals(physical_intervals(frame), len(frame)) == frame
        assert temperature(frame) == expected_temp
        if expected_humidity is not None:
            assert nibble(frame, 14) * 10 + nibble(frame, 13) == expected_humidity
        corrupted = bytearray(frame)
        corrupted[5] ^= 0x10
        assert not checksum_ok(corrupted, checksum_position)
    print("Oregon V2.1 vectors: 2 valid, 2 corrupt rejected, Manchester round-trip OK")


if __name__ == "__main__":
    main()
