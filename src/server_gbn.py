# =============================================================
# server_gbn.py — NetProbe Go-Back-N Uyumlu Sunucu
#
# GBN protokolü ile çalışır:
#   - Sıralı paket bekleme (expected_seq)
#   - Cumulative ACK gönderimi: ACK(n) = n dahil tüm öncekiler alındı
#   - Sıra dışı paketler yok sayılır, son geçerli ACK tekrar gönderilir
# =============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import socket
import os
import time
import random

from config import (
    HOST, PORT, PACKET_SIZE, RECEIVED_DIR,
    PACKET_TYPE_DATA, PACKET_TYPE_FIN,
    ACK_LOSS_RATE
)
from protocol import (
    parse_data_packet, parse_fin_packet,
    create_ack_packet,
    compute_checksum, identify_packet,
    DATA_HEADER_SIZE
)
from logger import TransferLogger


def run_server_gbn(save_filename: str = "received_file_gbn", ack_loss_rate: float = None):
    """
    Go-Back-N uyumlu UDP sunucusu.
    Cumulative ACK gönderir — sadece sıralı alınan paketleri onaylar.

    Args:
        save_filename : Alınan dosyanın kaydedileceği isim
        ack_loss_rate : ACK kayıp oranı simülasyonu
    """
    logger = TransferLogger(role="SERVER")
    _ack_loss_rate = ack_loss_rate if ack_loss_rate is not None else ACK_LOSS_RATE

    # ---- Soket Kurulumu (retry ile) ----
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for _attempt in range(5):
        try:
            sock.bind((HOST, PORT))
            break
        except OSError:
            if _attempt < 4:
                time.sleep(1)
            else:
                raise
    sock.settimeout(30.0)

    print(f"[GBN-SERVER] {HOST}:{PORT} dinleniyor (Go-Back-N modu)...")

    # ---- Alım Durumu ----
    received_chunks = {}
    expected_seq = 0       # Sıradaki beklenen paket
    total_packets = None
    client_addr = None
    transfer_started = False
    start_time = None
    last_ack_sent = -1     # Son gönderilen cumulative ACK

    try:
        while True:
            try:
                raw, addr = sock.recvfrom(PACKET_SIZE + DATA_HEADER_SIZE + 100)
            except socket.timeout:
                print("[GBN-SERVER] Bağlantı zaman aşımına uğradı.")
                break

            if client_addr is None:
                client_addr = addr

            ptype = identify_packet(raw)

            # ============================================================
            # DATA Paketi
            # ============================================================
            if ptype == "DATA":
                parsed = parse_data_packet(raw)
                if parsed is None:
                    continue

                seq_num       = parsed["seq_num"]
                total_packets = parsed["total_packets"]
                payload       = parsed["payload"]
                valid         = parsed["valid"]

                if not transfer_started:
                    transfer_started = True
                    start_time = time.time()
                    print(f"[GBN-SERVER] Transfer başladı. Beklenen toplam paket: {total_packets}")

                if not valid:
                    print(f"[GBN-SERVER] Paket #{seq_num} checksum hatası!")
                    continue

                # GBN: sadece sıradaki beklenen paketi kabul et
                if seq_num == expected_seq:
                    received_chunks[seq_num] = payload
                    logger.log_data_received(seq_num)
                    expected_seq += 1
                    last_ack_sent = seq_num

                    # ACK loss simülasyonu
                    if _ack_loss_rate > 0 and random.random() < _ack_loss_rate:
                        print(f"[GBN-SERVER] ★ ACK #{seq_num} simüle kayıp")
                        continue

                    # Cumulative ACK gönder
                    ack = create_ack_packet(seq_num)
                    sock.sendto(ack, client_addr)
                    print(f"[GBN-SERVER] Paket #{seq_num}/{total_packets-1} alındı | "
                          f"Cumulative ACK #{seq_num} gönderildi")
                else:
                    # Sıra dışı paket — son geçerli ACK'ı tekrar gönder
                    if last_ack_sent >= 0:
                        sock.sendto(create_ack_packet(last_ack_sent), client_addr)
                    print(f"[GBN-SERVER] Sıra dışı paket #{seq_num} (beklenen: {expected_seq}) — "
                          f"ACK #{last_ack_sent} tekrar gönderildi")

            # ============================================================
            # FIN Paketi
            # ============================================================
            elif ptype == "FIN":
                fin = parse_fin_packet(raw)
                if fin is None:
                    continue

                expected_file_checksum = fin["file_checksum"]
                print(f"\n[GBN-SERVER] FIN paketi alındı. Dosya birleştiriliyor...")

                if total_packets is None:
                    print("[GBN-SERVER] HATA: Hiç paket alınmadı!")
                    break

                # Eksik paket kontrolü
                missing = [i for i in range(total_packets) if i not in received_chunks]
                if missing:
                    print(f"[GBN-SERVER] UYARI: Eksik paketler: {missing}")

                # Sıralı birleştir
                file_data = b"".join(
                    received_chunks.get(i, b"") for i in range(total_packets)
                )

                # Bütünlük kontrolü
                actual_hash = compute_checksum(file_data)
                if actual_hash == expected_file_checksum:
                    logger.log_integrity_ok()
                    print("[GBN-SERVER] Dosya bütünlüğü doğrulandı (SHA-256 eşleşti).")
                else:
                    logger.log_integrity_fail()
                    print("[GBN-SERVER] UYARI: Dosya checksum uyuşmazlığı!")

                # Dosyayı kaydet
                out_path = os.path.join(RECEIVED_DIR, save_filename)
                with open(out_path, "wb") as f:
                    f.write(file_data)

                elapsed = time.time() - start_time if start_time else 0
                print(f"[GBN-SERVER] Dosya kaydedildi: {out_path}")
                print(f"[GBN-SERVER] Toplam süre: {elapsed:.3f}s | {len(file_data)} byte")

                logger.log_transfer_complete(
                    elapsed_sec=elapsed,
                    total_bytes=len(file_data),
                    sent_count=expected_seq,
                    retry_count=0
                )

                # FIN ACK
                sock.sendto(create_ack_packet(9999), client_addr)
                break

    except KeyboardInterrupt:
        print("\n[GBN-SERVER] Durduruldu (Ctrl+C).")
    finally:
        sock.close()
        print("[GBN-SERVER] Soket kapatıldı.")


# ============================================================
# Ana Giriş
# ============================================================
if __name__ == "__main__":
    fname = sys.argv[1] if len(sys.argv) > 1 else "received_file_gbn.bin"
    run_server_gbn(save_filename=fname)
