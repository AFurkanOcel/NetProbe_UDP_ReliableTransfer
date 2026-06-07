# =============================================================
# tests/test_logger.py — Logger modülü unit testleri
# =============================================================

import sys
import os
import csv
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from logger import TransferLogger


@pytest.fixture
def temp_log_dir(tmp_path):
    """Geçici log dizini oluşturur."""
    return tmp_path


@pytest.fixture
def client_logger(temp_log_dir):
    """Client logger oluşturur."""
    log_file = str(temp_log_dir / "test_client.csv")
    return TransferLogger(log_file=log_file, role="CLIENT")


@pytest.fixture
def server_logger(temp_log_dir):
    """Server logger oluşturur."""
    log_file = str(temp_log_dir / "test_server.csv")
    return TransferLogger(log_file=log_file, role="SERVER")


def read_csv_rows(log_file: str) -> list:
    """CSV dosyasını okur, satırları dict listesi olarak döner."""
    with open(log_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


class TestLoggerCreation:
    """Logger oluşturma ve dosya yönetimi testleri."""

    def test_creates_csv_file(self, client_logger):
        """Logger oluşturulunca CSV dosyası yaratılmalı."""
        assert os.path.exists(client_logger.log_file)

    def test_csv_has_header(self, client_logger):
        """CSV dosyasında doğru başlık olmalı."""
        with open(client_logger.log_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        expected = ["timestamp", "event_type", "seq_num", "retry_count", "elapsed_ms", "notes"]
        assert header == expected

    def test_client_server_separate_files(self, temp_log_dir):
        """Client ve server ayrı dosyalara yazmalı."""
        client_file = str(temp_log_dir / "client.csv")
        server_file = str(temp_log_dir / "server.csv")

        client_log = TransferLogger(log_file=client_file, role="CLIENT")
        server_log = TransferLogger(log_file=server_file, role="SERVER")

        assert client_log.log_file != server_log.log_file
        assert os.path.exists(client_file)
        assert os.path.exists(server_file)

    def test_role_in_event_type(self, client_logger, server_logger):
        """Event type'ta role bilgisi olmalı."""
        client_logger.log_sent(0)
        server_logger.log_data_received(0)

        client_rows = read_csv_rows(client_logger.log_file)
        server_rows = read_csv_rows(server_logger.log_file)

        assert "[CLIENT]" in client_rows[0]["event_type"]
        assert "[SERVER]" in server_rows[0]["event_type"]


class TestLogEvents:
    """Her event type için log yazma ve okuma testleri."""

    def test_log_transfer_start(self, client_logger):
        client_logger.log_transfer_start("test.bin", 1024, 10)
        rows = read_csv_rows(client_logger.log_file)
        assert len(rows) == 1
        assert "TRANSFER_START" in rows[0]["event_type"]
        assert "test.bin" in rows[0]["notes"]
        assert "1024" in rows[0]["notes"]

    def test_log_sent(self, client_logger):
        client_logger.log_sent(5, retry_count=0)
        rows = read_csv_rows(client_logger.log_file)
        assert len(rows) == 1
        assert "SENT" in rows[0]["event_type"]
        assert rows[0]["seq_num"] == "5"

    def test_log_ack_received(self, client_logger):
        client_logger.log_ack_received(3, elapsed_ms=12.5)
        rows = read_csv_rows(client_logger.log_file)
        assert "ACK_RECEIVED" in rows[0]["event_type"]
        assert float(rows[0]["elapsed_ms"]) == 12.5

    def test_log_data_received(self, server_logger):
        server_logger.log_data_received(7)
        rows = read_csv_rows(server_logger.log_file)
        assert "DATA_RECEIVED" in rows[0]["event_type"]
        assert rows[0]["seq_num"] == "7"

    def test_log_timeout(self, client_logger):
        client_logger.log_timeout(2, retry_count=1)
        rows = read_csv_rows(client_logger.log_file)
        assert "TIMEOUT" in rows[0]["event_type"]
        assert rows[0]["retry_count"] == "1"

    def test_log_retransmit(self, client_logger):
        client_logger.log_retransmit(4, retry_count=2)
        rows = read_csv_rows(client_logger.log_file)
        assert "RETRANSMIT" in rows[0]["event_type"]
        assert rows[0]["retry_count"] == "2"

    def test_log_failed(self, client_logger):
        client_logger.log_failed(6, notes="5")
        rows = read_csv_rows(client_logger.log_file)
        assert "FAILED" in rows[0]["event_type"]
        assert "5" in rows[0]["notes"]

    def test_log_duplicate(self, server_logger):
        server_logger.log_duplicate(1)
        rows = read_csv_rows(server_logger.log_file)
        assert "DUPLICATE" in rows[0]["event_type"]
        assert "Duplicate" in rows[0]["notes"]

    def test_log_transfer_complete(self, client_logger):
        client_logger.log_transfer_complete(
            elapsed_sec=2.5, total_bytes=10240,
            sent_count=15, retry_count=3
        )
        rows = read_csv_rows(client_logger.log_file)
        assert "TRANSFER_COMPLETE" in rows[0]["event_type"]
        assert "2.5" in rows[0]["notes"] or "2.500" in rows[0]["notes"]

    def test_log_integrity_ok(self, server_logger):
        server_logger.log_integrity_ok()
        rows = read_csv_rows(server_logger.log_file)
        assert "INTEGRITY_OK" in rows[0]["event_type"]

    def test_log_integrity_fail(self, server_logger):
        server_logger.log_integrity_fail()
        rows = read_csv_rows(server_logger.log_file)
        assert "INTEGRITY_FAIL" in rows[0]["event_type"]


class TestLogMultipleEntries:
    """Birden fazla log kaydı testleri."""

    def test_multiple_entries_appended(self, client_logger):
        """Birden fazla log satırı doğru şekilde eklenmeli."""
        client_logger.log_sent(0)
        client_logger.log_sent(1)
        client_logger.log_sent(2)
        client_logger.log_ack_received(0, 10.0)
        client_logger.log_ack_received(1, 11.0)
        client_logger.log_ack_received(2, 12.0)

        rows = read_csv_rows(client_logger.log_file)
        assert len(rows) == 6

    def test_timestamps_increasing(self, client_logger):
        """Timestamp'ler artan sırada olmalı."""
        client_logger.log_sent(0)
        client_logger.log_sent(1)

        rows = read_csv_rows(client_logger.log_file)
        assert float(rows[1]["timestamp"]) >= float(rows[0]["timestamp"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
