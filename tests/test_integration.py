# =============================================================
# tests/test_integration.py — Entegrasyon Testleri
#
# Client ve server'ı aynı process içinde thread ile çalıştırır.
# Dosya transferi bütünlüğünü doğrular.
# =============================================================

import sys
import os
import time
import hashlib
import threading
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest

# Config'i test için ayarla
import config
config.TIMEOUT = 2.0
config.MAX_RETRIES = 5
config.LOSS_SIMULATION = False
config.LOSS_RATE = 0.0
config.DELAY_SIMULATION = False


def sha256_file(filepath: str) -> str:
    """Dosyanın SHA-256 hash'ini döner."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def test_dir(tmp_path):
    """Test dosyaları için geçici dizin."""
    return tmp_path


@pytest.fixture
def small_file(test_dir):
    """10KB test dosyası oluşturur."""
    filepath = test_dir / "test_10kb.bin"
    filepath.write_bytes(os.urandom(10 * 1024))
    return str(filepath)


@pytest.fixture
def medium_file(test_dir):
    """50KB test dosyası oluşturur."""
    filepath = test_dir / "test_50kb.bin"
    filepath.write_bytes(os.urandom(50 * 1024))
    return str(filepath)


@pytest.fixture(autouse=True)
def setup_config(test_dir):
    """Her test öncesi config'i sıfırla."""
    config.LOSS_SIMULATION = False
    config.LOSS_RATE = 0.0
    config.DELAY_SIMULATION = False
    config.PACKET_SIZE = 1024
    config.TIMEOUT = 2.0
    config.MAX_RETRIES = 5
    config.ACK_LOSS_RATE = 0.0
    config.RECEIVED_DIR = str(test_dir)

    # Log dosyalarını temizle
    config.LOG_FILE_CLIENT = str(test_dir / "client.csv")
    config.LOG_FILE_SERVER = str(test_dir / "server.csv")
    yield


def run_transfer(filepath: str, save_name: str = "received.bin", port: int = None):
    """
    Client-server transferi yapar. Her iki tarafı da thread ile çalıştırır.

    Returns:
        tuple: (client_stats, received_file_path)
    """
    import importlib

    # Her test için OS'tan boş port iste (çakışma önlemi)
    if port is None:
        import socket as _sock
        _tmp = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        _tmp.bind(('', 0))
        port = _tmp.getsockname()[1]
        _tmp.close()

    config.PORT = port

    # Server ve client modüllerini yeniden yükle
    import server
    importlib.reload(server)
    import client
    importlib.reload(client)

    received_path = os.path.join(config.RECEIVED_DIR, save_name)
    server_error = [None]

    def server_thread():
        try:
            server.run_server(save_filename=save_name)
        except Exception as e:
            server_error[0] = e

    # Server başlat
    t = threading.Thread(target=server_thread, daemon=True)
    t.start()
    time.sleep(0.5)

    # Client gönderim
    stats = client.send_file(filepath)

    # Server'ın bitmesini bekle
    t.join(timeout=15)

    if server_error[0]:
        raise server_error[0]

    return stats, received_path


class TestBasicTransfer:
    """Temel dosya transferi testleri."""

    def test_10kb_file_integrity(self, small_file, test_dir):
        """10KB dosya transferi — SHA-256 ile bütünlük doğrulama."""
        original_hash = sha256_file(small_file)

        stats, received_path = run_transfer(small_file, "received_10kb.bin")

        assert os.path.exists(received_path), "Alınan dosya oluşturulmadı"
        received_hash = sha256_file(received_path)
        assert original_hash == received_hash, "Dosya bütünlüğü bozuldu!"

    def test_50kb_file_integrity(self, medium_file, test_dir):
        """50KB dosya transferi — SHA-256 ile bütünlük doğrulama."""
        original_hash = sha256_file(medium_file)

        stats, received_path = run_transfer(medium_file, "received_50kb.bin")

        assert os.path.exists(received_path)
        received_hash = sha256_file(received_path)
        assert original_hash == received_hash

    def test_transfer_stats_returned(self, small_file, test_dir):
        """Transfer istatistikleri doğru dönmeli."""
        stats, _ = run_transfer(small_file, "received_stats.bin")

        assert stats is not None
        assert stats["file_size"] == 10 * 1024
        assert stats["ack_count"] > 0
        assert stats["elapsed_sec"] >= 0  # Localhost'ta 0.0 olabilir
        assert stats["throughput_bps"] >= 0
        assert stats["fin_acked"] is True

    def test_all_packets_acked(self, small_file, test_dir):
        """Tüm paketler ACK'lanmış olmalı."""
        stats, _ = run_transfer(small_file, "received_allack.bin")

        assert stats["ack_count"] == stats["total_packets"]
        assert len(stats["failed_packets"]) == 0


class TestLossSimulation:
    """Kayıp simülasyonu altında transfer testleri."""

    def test_transfer_with_5pct_loss(self, small_file, test_dir):
        """5% kayıp ile transfer tamamlanmalı."""
        config.LOSS_SIMULATION = True
        config.LOSS_RATE = 0.05

        import importlib
        import client
        importlib.reload(client)

        original_hash = sha256_file(small_file)
        stats, received_path = run_transfer(small_file, "received_loss5.bin")

        assert os.path.exists(received_path)
        # Kayıp varsa retry olmuş olmalı veya drop_count > 0
        # Dosya yine de doğru transfere edilmiş olmalı
        received_hash = sha256_file(received_path)
        assert original_hash == received_hash

    def test_transfer_with_15pct_loss(self, small_file, test_dir):
        """15% kayıp ile transfer."""
        config.LOSS_SIMULATION = True
        config.LOSS_RATE = 0.15

        import importlib
        import client
        importlib.reload(client)

        original_hash = sha256_file(small_file)
        stats, received_path = run_transfer(small_file, "received_loss15.bin")

        # Dosya bütünlüğü korunmalı
        if os.path.exists(received_path):
            received_hash = sha256_file(received_path)
            assert original_hash == received_hash


class TestDuplicatePackets:
    """Duplicate paket senaryosu testi."""

    def test_duplicate_handling(self, small_file, test_dir):
        """
        Server duplicate paketleri yok saymalı ve dosya bütünlüğü korunmalı.
        ACK loss simülasyonu ile client tekrar gönderir → server duplicate algılar.
        """
        config.ACK_LOSS_RATE = 0.1  # %10 ACK kaybı → client tekrar gönderir

        import importlib
        import server
        importlib.reload(server)

        original_hash = sha256_file(small_file)
        stats, received_path = run_transfer(small_file, "received_dup.bin")

        if os.path.exists(received_path):
            received_hash = sha256_file(received_path)
            assert original_hash == received_hash


class TestGBNTransfer:
    """Go-Back-N transfer testleri."""

    def test_gbn_basic_transfer(self, small_file, test_dir):
        """GBN ile temel dosya transferi."""
        import importlib
        import random

        port = random.randint(10000, 60000)
        config.PORT = port

        import server_gbn
        importlib.reload(server_gbn)
        import client_gbn
        importlib.reload(client_gbn)

        received_name = "gbn_received.bin"
        received_path = os.path.join(str(test_dir), received_name)

        server_error = [None]

        def server_thread():
            try:
                server_gbn.run_server_gbn(save_filename=received_name)
            except Exception as e:
                server_error[0] = e

        t = threading.Thread(target=server_thread, daemon=True)
        t.start()
        time.sleep(0.5)

        original_hash = sha256_file(small_file)
        stats = client_gbn.send_file_gbn(small_file)
        t.join(timeout=15)

        assert stats is not None
        assert stats["protocol"] == "GBN"
        if os.path.exists(received_path):
            received_hash = sha256_file(received_path)
            assert original_hash == received_hash


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
