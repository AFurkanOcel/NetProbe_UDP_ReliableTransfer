# =============================================================
# tcp_transfer.py — TCP Karşılaştırma Modülü
#
# Aynı dosyayı TCP ile gönderir ve alır.
# UDP-reliable ile karşılaştırma yapabilmek için aynı metrikleri ölçer.
# =============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import socket
import os
import time
import hashlib
import threading

from config import HOST, RECEIVED_DIR


TCP_PORT = 5010  # TCP için farklı port


def tcp_send_file(filepath: str, host: str = HOST, port: int = TCP_PORT) -> dict:
    """
    TCP ile dosya gönderir.

    Args:
        filepath : Gönderilecek dosya
        host     : Hedef IP
        port     : Hedef port

    Returns:
        dict : Transfer istatistikleri
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    with open(filepath, "rb") as f:
        file_data = f.read()

    file_size = len(file_data)
    filename = os.path.basename(filepath)

    print(f"\n[TCP-CLIENT] Dosya: {filename} ({file_size} byte)")
    print(f"[TCP-CLIENT] Sunucu: {host}:{port}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))

    start_time = time.time()

    # Önce dosya boyutunu gönder (8 byte big-endian)
    sock.sendall(file_size.to_bytes(8, 'big'))

    # Dosya verisini gönder
    total_sent = 0
    chunk_size = 4096
    while total_sent < file_size:
        end = min(total_sent + chunk_size, file_size)
        sent = sock.send(file_data[total_sent:end])
        total_sent += sent

    # Sunucudan onay bekle (server SHA-256 gönderiyor)
    response = sock.recv(32)
    end_time = time.time()
    sock.close()

    expected_hash = hashlib.sha256(file_data).digest()
    integrity_ok = response == expected_hash
    if integrity_ok:
        print("[TCP-CLIENT] Dosya bütünlüğü doğrulandı (SHA-256 eşleşti).")
    else:
        print("[TCP-CLIENT] UYARI: Dosya checksum uyuşmazlığı!")

    elapsed_sec = end_time - start_time
    throughput_bps = (file_size * 8) / elapsed_sec if elapsed_sec > 0 else 0
    goodput_bps = throughput_bps  # TCP'de kayıp yok, throughput = goodput

    stats = {
        "filename"       : filename,
        "file_size"      : file_size,
        "file_size_kb"   : file_size / 1024,
        "elapsed_sec"    : elapsed_sec,
        "throughput_bps" : throughput_bps,
        "goodput_bps"    : goodput_bps,
        "throughput_kbps": throughput_bps / 1000,
        "goodput_kbps"   : goodput_bps / 1000,
        "protocol"       : "TCP",
        "integrity_ok"   : integrity_ok,
    }

    print(f"[TCP-CLIENT] Transfer tamamlandı: {elapsed_sec:.3f}s | "
          f"Throughput: {throughput_bps/1000:.1f} kbps")

    return stats


def tcp_receive_file(save_filename: str = "tcp_received.bin",
                     host: str = HOST, port: int = TCP_PORT) -> dict:
    """
    TCP ile dosya alır.

    Args:
        save_filename : Kaydedilecek dosya adı
        host          : Dinlenecek IP
        port          : Dinlenecek port

    Returns:
        dict : Alım istatistikleri
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen(1)
    server_sock.settimeout(30.0)

    print(f"[TCP-SERVER] {host}:{port} dinleniyor...")

    conn = None
    try:
        conn, addr = server_sock.accept()
        print(f"[TCP-SERVER] Bağlantı: {addr}")

        start_time = time.time()

        # Dosya boyutunu al
        size_data = b""
        while len(size_data) < 8:
            chunk = conn.recv(8 - len(size_data))
            if not chunk:
                break
            size_data += chunk
        file_size = int.from_bytes(size_data, 'big')

        # Dosya verisini al
        received_data = b""
        while len(received_data) < file_size:
            chunk = conn.recv(min(4096, file_size - len(received_data)))
            if not chunk:
                break
            received_data += chunk

        end_time = time.time()

        # Onay gönder
        file_hash = hashlib.sha256(received_data).digest()
        conn.sendall(file_hash)

        # Dosyayı kaydet
        out_path = os.path.join(RECEIVED_DIR, save_filename)
        with open(out_path, "wb") as f:
            f.write(received_data)

        elapsed_sec = end_time - start_time
        print(f"[TCP-SERVER] Dosya alındı: {out_path} ({len(received_data)} byte, {elapsed_sec:.3f}s)")

        return {
            "file_size": len(received_data),
            "elapsed_sec": elapsed_sec,
            "save_path": out_path,
        }

    except socket.timeout:
        print("[TCP-SERVER] Bağlantı zaman aşımına uğradı.")
        return {}
    except Exception as e:
        print(f"[TCP-SERVER] Hata: {e}")
        return {}
    finally:
        if conn:
            conn.close()
        server_sock.close()


def _free_tcp_port(host: str = HOST) -> int:
    """Return an OS-assigned free TCP port for local experiment runs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def tcp_transfer_test(filepath: str, port: int = None) -> dict:
    """
    TCP client ve server'ı aynı process içinde thread ile çalıştırır.
    Bir dosya transfer eder ve istatistikleri döner.

    Args:
        filepath : Gönderilecek dosya

    Returns:
        dict : Client tarafı istatistikleri
    """
    filename = os.path.basename(filepath)
    save_name = f"tcp_{filename}"

    server_result = {}
    _port = port if port is not None else _free_tcp_port()

    def server_thread():
        nonlocal server_result
        server_result = tcp_receive_file(save_filename=save_name, port=_port)

    # Server'ı thread olarak başlat
    t = threading.Thread(target=server_thread, daemon=True)
    t.start()
    time.sleep(0.3)  # Server'ın hazır olmasını bekle

    # Client gönderim
    client_stats = tcp_send_file(filepath, port=_port)

    t.join(timeout=10)
    return client_stats


# ============================================================
# Ana Giriş
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python tcp_transfer.py <dosya_yolu>")
        print("  TCP client ve server'ı aynı anda çalıştırır.")
        sys.exit(1)

    stats = tcp_transfer_test(sys.argv[1])
    print(f"\nSonuç: {stats}")
