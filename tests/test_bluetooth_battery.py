from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'config/plugins'))
from bluetooth_battery import crc16, format_charge, packets, parse_levels, percentage, request


class BluetoothBatteryTests(unittest.TestCase):
    def test_single_left_and_right_levels_are_not_invented(self):
        self.assertEqual(format_charge({'total': 0}), '0%')
        self.assertEqual(format_charge({'left': 80, 'total': 75}), 'Л 80%')
        self.assertEqual(format_charge({'right': 17}, full=True), 'Правый 17%')
        self.assertEqual(format_charge({}), '')
        self.assertIsNone(percentage(255))
        self.assertIsNone(percentage(True))

    def test_component_payloads_and_charging_bit(self):
        self.assertEqual(parse_levels(bytes.fromhex('03 02 E4 03 5F 04 FF')), {'left': 100, 'right': 95})
        self.assertEqual(parse_levels(bytes.fromhex('01 06 37')), {'total': 55})
        self.assertEqual(parse_levels(bytes.fromhex('02 02 40')), {})

    def test_transport_preserves_split_frames_and_rejects_invalid_crc(self):
        self.assertEqual(request(0xC01E, 1).hex(), '5560011ec0000001b11d')
        body = bytes.fromhex('02 02 64 03 5f')
        frame = struct.pack('<BHHHB', 0x55, 0x0160, 0x4007, len(body), 2) + body
        good = frame + crc16(frame).to_bytes(2, 'little')
        buffer = bytearray(b'\x00' + good[:-1])
        self.assertEqual(list(packets(buffer)), [])
        invalid = good[:-1] + bytes([good[-1] ^ 1])
        buffer.extend(good[-1:] + invalid)
        self.assertEqual(list(packets(buffer)), [(0x4007, 2, body)])
        self.assertFalse(buffer)
