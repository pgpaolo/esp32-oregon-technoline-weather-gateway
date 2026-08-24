#!/usr/bin/env python3
"""Static protocol-vector tests for the embedded Oregon Scientific V2.1 decoder."""

BIT_MASK = (0x10, 0x20, 0x40, 0x80, 0x01, 0x02, 0x04, 0x08)
NIBBLE_MASK = (0x01, 0x02, 0x04, 0x08)
UVR128_BURST_EDGE_BUFFER = 672


def nibble(frame: bytes, index: int) -> int:
    value = frame[index // 2]
    return value >> 4 if index % 2 == 0 else value & 0x0F


def checksum_ok(frame: bytes, position: int) -> bool:
    calculated = sum(nibble(frame, i) for i in range(1, position)) & 0xFF
    received = (nibble(frame, position + 1) << 4) | nibble(frame, position)
    return calculated == received


def make_frame(nibbles: list[int], checksum_position: int) -> bytes:
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
            if kind == "S" and preamble_longs >= 10:
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


def recover_uvr128_from_intervals(intervals):
    for start in range(len(intervals)):
        for initial in (0, 1):
            last = initial
            have_first = False
            pair_first = 0
            decoded = []
            i = start
            while i < len(intervals) and len(decoded) < 64:
                kind = intervals[i]
                if kind == "L":
                    last ^= 1
                    physical = last
                    i += 1
                elif kind == "S" and i + 1 < len(intervals) and intervals[i + 1] == "S":
                    physical = last
                    i += 2
                else:
                    break
                if not have_first:
                    pair_first = physical
                    have_first = True
                    continue
                if pair_first == physical:
                    break
                have_first = False
                decoded.append(physical)
                if len(decoded) == 4:
                    first_nibble = sum(bit << k for k, bit in enumerate(decoded))
                    if first_nibble != 0xA:
                        break
            if len(decoded) < 64:
                continue
            frame = bytearray(8)
            for index, bit in enumerate(decoded[:64]):
                if bit:
                    frame[index // 8] |= BIT_MASK[index % 8]
            frame = bytes(frame)
            code = ((nibble(frame, 1) << 12) | (nibble(frame, 2) << 8) |
                    (nibble(frame, 3) << 4) | nibble(frame, 4))
            if code == 0xEC70 and checksum_ok(frame, 13):
                return frame
    return None


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
         0x4, 0x3, 0x2, 0x0, 0x6, 0x5, 0x0, 0x0, 0x0], 16)
    wgr968 = make_frame(
        [0xA, 0x3, 0xD, 0x0, 0x0, 0x1, 0x2, 0x3, 0x0,
         0x5, 0x2, 0x2, 0x2, 0x5, 0x2, 0x3, 0x4, 0x3, 0x0, 0x0], 18)
    rgr968 = make_frame(
        [0xA, 0x2, 0xD, 0x1, 0x0, 0x1, 0x2, 0x3, 0x0,
         0x2, 0x1, 0x3, 0x4, 0x3, 0x2, 0x1, 0x0, 0x0, 0x0, 0x0], 17)
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
    for frame, checksum_position in ((thgr968, 16), (wgr968, 18), (rgr968, 17)):
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
    clipped = physical_intervals_from_bits(uvr_bits, preamble_physical_bits=12)
    decoded_uvr128 = decode_intervals_bits(clipped, 64, len(uvr128))
    assert decoded_uvr128 == uvr128
    assert checksum_ok(decoded_uvr128, 13)
    assert nibble(decoded_uvr128, 10) * 10 + nibble(decoded_uvr128, 9) == 12

    # Real UVR128 V2.1 repeats the full message without a pause. Preserve the
    # whole combined burst so the second preamble/payload remains available if
    # the first copy begins clipped. The old 384-edge budget is deliberately
    # shown to be tight for a standards-shaped synthetic message.
    full_double = physical_intervals_from_bits(uvr_bits, preamble_physical_bits=32)
    assert len(full_double) > 384
    assert len(full_double) <= UVR128_BURST_EDGE_BUFFER
    assert recover_uvr128_from_intervals(full_double) == uvr128

    raw = physical_intervals_from_bits(uvr_bits, preamble_physical_bits=16)
    noisy = ["S", "S", "L", "S", "S"] + raw[9:]
    assert recover_uvr128_from_intervals(noisy) == uvr128

    corrupt_uvr_bits = uvr_bits.copy()
    corrupt_uvr_bits[40] ^= 1
    corrupt_uvr128 = decode_intervals_bits(
        physical_intervals_from_bits(corrupt_uvr_bits, preamble_physical_bits=16),
        64, len(uvr128))
    assert not checksum_ok(corrupt_uvr128, 13)
    print("Oregon V2.1 vectors: 6 valid, 6 corrupt rejected, UVR128 no-gap double burst + clipped phase recovery OK")


if __name__ == "__main__":
    main()
