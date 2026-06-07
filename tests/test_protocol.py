# =============================================================
# tests/test_protocol.py — Protocol modülü unit testleri
# =============================================================

import sys
import os

# src/ dizinini path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from protocol import (
    compute_checksum, verify_checksum,
    create_data_packet, parse_data_packet,
    create_ack_packet, parse_ack_packet,
    create_fin_packet, parse_fin_packet,
    identify_packet, compute_file_checksum,
    DATA_HEADER_SIZE, ACK_SIZE, FIN_SIZE
)
from config import PACKET_TYPE_DATA, PACKET_TYPE_ACK, PACKET_TYPE_FIN


class TestChecksum:
    """Checksum hesaplama ve doğrulama testleri."""

    def test_compute_checksum_returns_32_bytes(self):
        data = b"hello world"
        result = compute_checksum(data)
        assert len(result) == 32

    def test_verify_checksum_valid(self):
        data = b"test data for checksum"
        cs = compute_checksum(data)
        assert verify_checksum(data, cs) is True

    def test_verify_checksum_invalid(self):
        data = b"test data"
        wrong_cs = b"\x00" * 32
        assert verify_checksum(data, wrong_cs) is False

    def test_checksum_deterministic(self):
        data = b"same input always same output"
        assert compute_checksum(data) == compute_checksum(data)

    def test_checksum_different_for_different_data(self):
        assert compute_checksum(b"a") != compute_checksum(b"b")


class TestDataPacket:
    """DATA paket oluşturma ve parse testleri."""

    def test_create_parse_roundtrip(self):
        payload = b"Hello, NetProbe!"
        seq_num = 5
        total_packets = 10

        packet = create_data_packet(seq_num, total_packets, payload)
        parsed = parse_data_packet(packet)

        assert parsed is not None
        assert parsed["seq_num"] == seq_num
        assert parsed["total_packets"] == total_packets
        assert parsed["payload"] == payload
        assert parsed["valid"] is True
        assert parsed["packet_type"] == PACKET_TYPE_DATA

    def test_empty_payload(self):
        """Boş payload ile paket oluşturma."""
        packet = create_data_packet(0, 1, b"")
        parsed = parse_data_packet(packet)

        assert parsed is not None
        assert parsed["payload"] == b""
        assert parsed["payload_length"] == 0
        assert parsed["valid"] is True

    def test_max_size_payload(self):
        """Maksimum boyut payload testi."""
        payload = os.urandom(4096)  # 4KB payload
        packet = create_data_packet(0, 1, payload)
        parsed = parse_data_packet(packet)

        assert parsed is not None
        assert parsed["payload"] == payload
        assert parsed["valid"] is True

    def test_corrupted_data(self):
        """Bozuk veri — checksum hatası tespiti."""
        payload = b"original data"
        packet = create_data_packet(0, 1, payload)

        # Payload'ın bir byte'ını boz
        corrupted = bytearray(packet)
        corrupted[-1] ^= 0xFF  # Son byte'ı flip et
        corrupted = bytes(corrupted)

        parsed = parse_data_packet(corrupted)
        # Parse edilebilir ama valid = False olmalı
        if parsed is not None:
            assert parsed["valid"] is False

    def test_too_short_data(self):
        """Çok kısa veri — parse başarısız."""
        result = parse_data_packet(b"\x01\x00")
        assert result is None

    def test_wrong_packet_type(self):
        """Yanlış paket tipi — parse başarısız."""
        packet = create_ack_packet(0)
        result = parse_data_packet(packet)
        assert result is None

    def test_sequence_numbers(self):
        """Farklı sequence number'lar."""
        for seq in [0, 1, 100, 65535, 2**20]:
            packet = create_data_packet(seq, seq + 1, b"data")
            parsed = parse_data_packet(packet)
            assert parsed["seq_num"] == seq
            assert parsed["total_packets"] == seq + 1


class TestACKPacket:
    """ACK paket testleri."""

    def test_create_parse_roundtrip(self):
        ack_num = 42
        packet = create_ack_packet(ack_num)
        parsed = parse_ack_packet(packet)

        assert parsed is not None
        assert parsed["ack_num"] == ack_num
        assert parsed["packet_type"] == PACKET_TYPE_ACK

    def test_ack_packet_size(self):
        packet = create_ack_packet(0)
        assert len(packet) == ACK_SIZE

    def test_various_ack_numbers(self):
        for num in [0, 1, 9999, 2**20]:
            packet = create_ack_packet(num)
            parsed = parse_ack_packet(packet)
            assert parsed["ack_num"] == num

    def test_too_short_ack(self):
        result = parse_ack_packet(b"\x02")
        assert result is None

    def test_wrong_type_for_ack(self):
        """DATA paketi ACK olarak parse edilemez."""
        packet = create_data_packet(0, 1, b"data")
        result = parse_ack_packet(packet)
        assert result is None


class TestFINPacket:
    """FIN paket testleri."""

    def test_create_parse_roundtrip(self):
        file_hash = compute_checksum(b"file content")
        packet = create_fin_packet(file_hash)
        parsed = parse_fin_packet(packet)

        assert parsed is not None
        assert parsed["file_checksum"] == file_hash
        assert parsed["packet_type"] == PACKET_TYPE_FIN

    def test_fin_packet_size(self):
        packet = create_fin_packet(b"\x00" * 32)
        assert len(packet) == FIN_SIZE

    def test_too_short_fin(self):
        result = parse_fin_packet(b"\x03")
        assert result is None

    def test_wrong_type_for_fin(self):
        packet = create_ack_packet(0)
        result = parse_fin_packet(packet)
        assert result is None


class TestIdentifyPacket:
    """identify_packet fonksiyonu testleri."""

    def test_identify_data(self):
        packet = create_data_packet(0, 1, b"test")
        assert identify_packet(packet) == "DATA"

    def test_identify_ack(self):
        packet = create_ack_packet(0)
        assert identify_packet(packet) == "ACK"

    def test_identify_fin(self):
        packet = create_fin_packet(b"\x00" * 32)
        assert identify_packet(packet) == "FIN"

    def test_identify_empty(self):
        assert identify_packet(b"") == "UNKNOWN"

    def test_identify_unknown_type(self):
        assert identify_packet(b"\xFF\x00\x00") == "UNKNOWN"


class TestFileChecksum:
    """compute_file_checksum testi."""

    def test_file_checksum(self, tmp_path):
        """Geçici dosya ile checksum doğrulama."""
        content = b"test file content for checksum"
        filepath = tmp_path / "test.bin"
        filepath.write_bytes(content)

        result = compute_file_checksum(str(filepath))
        expected = compute_checksum(content)
        assert result == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
