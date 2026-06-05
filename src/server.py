# =============================================================
# server.py — NetProbe UDP Sunucusu
#
# Görev:
#   1. UDP soketi aç, porta bağlan (bind)
#   2. Client'tan DATA paketlerini al
#   3. Her paket için:
#      - Checksum doğrula
#      - Sequence number kontrolü yap
#      - Duplicate gelirse sadece ACK gönder, dosyaya yazma
#      - Geçerliyse payload'u belleğe yaz, ACK gönder
#   4. FIN paketi gelince:
#      - Dosyayı birleştir ve diske yaz
#      - Tüm dosyanın SHA-256 hash'ini doğrula
#   5. Log kaydı tut
# =============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import socket
import os
import time
import random

# src/ içindeyiz, config ve protocol doğrudan import edilebilir
from config import (
    HOST, PORT, PACKET_SIZE, RECEIVED_DIR,
    PACKET_TYPE_DATA, PACKET_TYPE_ACK, PACKET_TYPE_FIN,
    ACK_LOSS_RATE
)
from protocol import (
    parse_data_packet, parse_fin_packet,
    create_ack_packet,
    compute_checksum, verify_checksum,
    DATA_HEADER_SIZE, identify_packet
)
from logger import TransferLogger


def run_server(save_filename: str = "received_file", ack_loss_rate: float = None):
    """
    UDP sunucusunu başlatır. Tek bir dosya transferi bekler.

    Args:
        save_filename : Alınan dosyanın kaydedileceği isim (uzantısız)
        ack_loss_rate : ACK kayıp oranı (None ise config'den alınır)
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

    print(f"[SERVER] {HOST}:{PORT} dinleniyor...")

    # ---- Alım Durumu ----
    received_chunks = {}     # seq_num → payload (dict)
    received_seqs   = set()  # Zaten alınan seq numaraları (duplicate tespiti)
    total_packets   = None   # İlk paketten öğrenilecek
    client_addr     = None
    transfer_started = False
    start_time      = None

    try:
        while True:
            try:
                raw, addr = sock.recvfrom(PACKET_SIZE + DATA_HEADER_SIZE + 100)
            except socket.timeout:
                print("[SERVER] Bağlantı zaman aşımına uğradı.")
                break

            # İlk paketten client adresini kaydet
            if client_addr is None:
                client_addr = addr

            ptype = identify_packet(raw)

            # ============================================================
            # DATA Paketi İşle
            # ============================================================
            if ptype == "DATA":
                parsed = parse_data_packet(raw)
                if parsed is None:
                    print("[SERVER] Parse hatası — paket yok sayıldı.")
                    continue

                seq_num       = parsed["seq_num"]
                total_packets = parsed["total_packets"]
                payload       = parsed["payload"]
                valid         = parsed["valid"]

                if not transfer_started:
                    transfer_started = True
                    start_time = time.time()
                    print(f"[SERVER] Transfer başladı. Beklenen toplam paket: {total_packets}")

                # Checksum bozuk mu?
                if not valid:
                    print(f"[SERVER] Paket #{seq_num} checksum hatası! Yok sayıldı.")
                    # ACK göndermiyoruz → client timeout'a düşecek ve yeniden gönderecek
                    continue

                # Duplicate mu?
                if seq_num in received_seqs:
                    logger.log_duplicate(seq_num)
                    print(f"[SERVER] Duplicate paket #{seq_num} — ACK tekrar gönderildi.")
                    sock.sendto(create_ack_packet(seq_num), client_addr)
                    continue

                # Yeni ve geçerli paket → kaydet
                received_seqs.add(seq_num)
                received_chunks[seq_num] = payload
                logger.log_data_received(seq_num)

                # ACK loss simülasyonu
                if _ack_loss_rate > 0 and random.random() < _ack_loss_rate:
                    print(f"[SERVER] ★ ACK #{seq_num} simüle kayıp (düşürüldü)")
                    continue

                # ACK gönder
                ack = create_ack_packet(seq_num)
                sock.sendto(ack, client_addr)
                print(f"[SERVER] Paket #{seq_num}/{total_packets - 1} alındı | ACK gönderildi")

            # ============================================================
            # FIN Paketi → Aktarım Sonu
            # ============================================================
            elif ptype == "FIN":
                fin = parse_fin_packet(raw)
                if fin is None:
                    print("[SERVER] FIN parse hatası.")
                    continue

                expected_file_checksum = fin["file_checksum"]
                print(f"\n[SERVER] FIN paketi alındı. Dosya birleştiriliyor...")

                # --- Dosyayı Birleştir ---
                if total_packets is None:
                    print("[SERVER] HATA: Hiç paket alınmadı!")
                    break

                # Eksik paket var mı?
                missing = [i for i in range(total_packets) if i not in received_seqs]
                if missing:
                    print(f"[SERVER] UYARI: Eksik paketler: {missing}")

                # Sıralı birleştir
                file_data = b"".join(
                    received_chunks.get(i, b"") for i in range(total_packets)
                )

                # Dosya bütünlüğü kontrolü
                actual_hash = compute_checksum(file_data)
                if actual_hash == expected_file_checksum:
                    logger.log_integrity_ok()
                    print("[SERVER] Dosya bütünlüğü doğrulandı (SHA-256 eşleşti).")
                else:
                    logger.log_integrity_fail()
                    print("[SERVER] UYARI: Dosya checksum uyuşmazlığı!")

                # Dosyayı kaydet
                out_path = os.path.join(RECEIVED_DIR, save_filename)
                with open(out_path, "wb") as f:
                    f.write(file_data)

                elapsed = time.time() - start_time if start_time else 0
                print(f"[SERVER] Dosya kaydedildi: {out_path}")
                print(f"[SERVER] Toplam süre: {elapsed:.3f}s | {len(file_data)} byte")

                logger.log_transfer_complete(
                    elapsed_sec=elapsed,
                    total_bytes=len(file_data),
                    sent_count=len(received_seqs),
                    retry_count=0
                )

                # FIN'e ACK gönder (client'in bitmesini sağlar)
                sock.sendto(create_ack_packet(9999), client_addr)
                break

            else:
                print(f"[SERVER] Bilinmeyen paket tipi: {ptype}")

    except KeyboardInterrupt:
        print("\n[SERVER] Durduruldu (Ctrl+C).")
    finally:
        sock.close()
        print("[SERVER] Soket kapatıldı.")


# ============================================================
# Ana Giriş
# ============================================================
if __name__ == "__main__":
    # Kullanım: python server.py [save_filename]
    fname = sys.argv[1] if len(sys.argv) > 1 else "received_file.bin"
    run_server(save_filename=fname)
