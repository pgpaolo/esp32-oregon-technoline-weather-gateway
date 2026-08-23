#!/usr/bin/env python3
"""Static protocol-vector tests for the embedded Oregon Scientific V2.1 decoder."""

BIT_MASK = (0x10, 0x20, 0x40, 0x80, 0x01, 0x02, 0x04, 0x08)
NIBBLE_MASK = (0x01, 0x02, 0x04, 0x08)


def nibble(frame: bytes, index: int) -> int:
    value = frame[index // 2]
    return value >> 4 if index % 2 == 0 else value & 0x0F


def checksum_ok(frame: bytes, position: int) -> bool:
    calculated = sum(nibble(frame, i) for i in range(1, position)) & 0xFF
    received = (nibble(frame, position + 1) << 4) | nibble(frame, position)
    return calculated == received


def make_frame(nibbles: list[int], checksum_position: int) -> bytes:
    """Complete an even-sized nibble vector with the protocol checksum."""
    assert checksum_position + 1 < len(nibbles)
    checksum = sum(nibbles[1:checksum_position]) & 0xFF
    nibbles[checksum_position] = checksum & 0x0F
    nibbles[checksum_position + 1] = checksum >> 4
    assert len(nibbles) % 2 == 0
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def logical_bits(frame: bytes):
    for value in frame:
        for mask in BIT_MASK:
            yield 1 if value & mask else 0


def logical_nibble_bits(nibbles):
    for value in nibbles:
        for mask in NIBBLE_MASK:
            yield 1 if value & mask else 0


def physical_intervals_from_bits(bits, preamble_physical_bits=32):
    physical = [index & 1 for index in range(preamble_physical_bits)]
    for bit in bits:
        physical.extend((1 - bit, bit))
    intervals = []
    for previous, current in zip(physical, physical[1:]):
        intervals.extend(("S", "S") if previous == current else ("L",))
    return intervals


def physical_intervals(frame: bytes):
    return physical_intervals_from_bits(logical_bits(frame))


def decode_intervals_bits(intervals, expected_bits: int, stored_bytes: int) -> bytes:
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
            if kind == "S" and preamble_longs >= 15:
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
        if len(decoded) == expected_bits:
            break
    assert len(decoded) == expected_bits
    result = bytearray(stored_bytes)
    for index, bit in enumerate(decoded[:stored_bytes * 8]):
        if bit:
            result[index // 8] |= BIT_MASK[index % 8]
    return bytes(result)


def decode_intervals(intervals, expected_bytes: int) -> bytes:
    return decode_intervals_bits(intervals, expected_bytes * 8, expected_bytes)


def uvr128_double_message() -> tuple[bytes, list[int]]:
    """Build sync+payload, second preamble and immediate duplicate (152 bits)."""
    first_nibbles = [
        0xA, 0xE, 0xC, 0x7, 0x0, 0x1, 0x2, 0x3, 0x0,
        0x2, 0x1, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    ]
    checksum = sum(first_nibbles[1:13]) & 0xFF
    first_nibbles[13] = checksum & 0x0F
    first_nibbles[14] = checksum >> 4
    first_copy = bytes(
        (first_nibbles[i] << 4) | first_nibbles[i + 1]
        for i in range(0, 16, 2)
    )
    first_bits = list(logical_nibble_bits(first_nibbles))
    # Il secondo preambolo OSV2.1 e' composto da 16 bit logici a 1 e non e'
    # separato da una pausa. La seconda copia include nuovamente il sync 0xA.
    decoded_bits = first_bits + [1] * 16 + first_bits
    assert len(decoded_bits) == 152
    assert len(decoded_bits) - 4 == 148
    return first_copy, decoded_bits


def temperature(frame: bytes) -> float:
    value = nibble(frame, 11) * 10 + nibble(frame, 10) + nibble(frame, 9) / 10
    return -value if nibble(frame, 12) == 8 else value


def synthetic_vectors():
    thgr968 = make_frame(
        [0xA, 0x1, 0xD, 0x3, 0x0, 0x2, 0x4, 0x2, 0x0,
         0x4, 0x3, 0x2, 0x0, 0x6, 0x5, 0x0, 0x0, 0x0],
        16,
    )
    wgr968 = make_frame(
        [0xA, 0x3, 0xD, 0x0, 0x0, 0x1, 0x2, 0x3, 0x0,
         0x5, 0x2, 0x2, 0x2, 0x5, 0x2, 0x3, 0x4, 0x3, 0x0, 0x0],
        18,
    )
    rgr968 = make_frame(
        [0xA, 0x2, 0xD, 0x1, 0x0, 0x1, 0x2, 0x3, 0x0,
         0x2, 0x1, 0x3, 0x4, 0x3, 0x2, 0x1, 0x0, 0x0, 0x0, 0x0],
        17,
    )
    return thgr968, wgr968, rgr968


def main() -> None:
    thermo_vectors = (
        (bytes.fromhex("AEC4015F07300D30"), 13, 3.7, None),
        (bytes.fromhex("A1D20485C480882835"), 16, -8.4, 28),
    )
    for frame, checksum_position, expected_temp, expected_humidity in thermo_vectors:
        assert checksum_ok(frame, checksum_position)
        assert decode_intervals(physical_intervals(frame), len(frame)) == frame
        assert temperature(frame) == expected_temp
        if expected_humidity is not None:
            assert nibble(frame, 14) * 10 + nibble(frame, 13) == expected_humidity
        corrupted = bytearray(frame)
        corrupted[5] ^= 0x10
        assert not checksum_ok(corrupted, checksum_position)

    thgr968, wgr968, rgr968 = synthetic_vectors()
    legacy_vectors = ((thgr968, 16), (wgr968, 18), (rgr968, 17))
    for frame, checksum_position in legacy_vectors:
        assert checksum_ok(frame, checksum_position)
        assert decode_intervals(physical_intervals(frame), len(frame)) == frame
        corrupted = bytearray(frame)
        corrupted[4] ^= 0x10
        assert not checksum_ok(corrupted, checksum_position)

    assert temperature(thgr968) == 23.4
    assert nibble(thgr968, 14) * 10 + nibble(thgr968, 13) == 56
    assert nibble(wgr968, 11) * 100 + nibble(wgr968, 10) * 10 + nibble(wgr968, 9) == 225
    assert nibble(wgr968, 13) + (nibble(wgr968, 12) + nibble(wgr968, 14)) / 10 == 5.4
    assert nibble(wgr968, 16) + (nibble(wgr968, 15) + nibble(wgr968, 17)) / 10 == 4.6
    assert (nibble(rgr968, 10) * 100 + nibble(rgr968, 9) * 10 + nibble(rgr968, 11)) / 10 == 12.3
    assert (nibble(rgr968, 16) * 10000 + nibble(rgr968, 15) * 1000 +
            nibble(rgr968, 14) * 100 + nibble(rgr968, 13) * 10 + nibble(rgr968, 12)) / 10 == 123.4
    uvr128, uvr_bits = uvr128_double_message()
    decoded_uvr128 = decode_intervals_bits(
        physical_intervals_from_bits(uvr_bits, preamble_physical_bits=16),
        152,
        len(uvr128),
    )
    assert decoded_uvr128 == uvr128
    assert checksum_ok(decoded_uvr128, 13)
    assert nibble(decoded_uvr128, 10) * 10 + nibble(decoded_uvr128, 9) == 12

    corrupt_uvr_bits = uvr_bits.copy()
    corrupt_uvr_bits[40] ^= 1
    corrupt_uvr128 = decode_intervals_bits(
        physical_intervals_from_bits(corrupt_uvr_bits, preamble_physical_bits=16),
        152,
        len(uvr128),
    )
    assert not checksum_ok(corrupt_uvr128, 13)
    print("Oregon V2.1 vectors: 6 valid, 6 corrupt rejected, UVR128 double-message OK")


if __name__ == "__main__":
    main()
