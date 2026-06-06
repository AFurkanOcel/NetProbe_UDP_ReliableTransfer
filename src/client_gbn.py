# =============================================================
# client_gbn.py — NetProbe Go-Back-N (Sliding Window) İstemcisi
#
# Stop-and-Wait yerine pencere tabanlı gönderim:
#   - WINDOW_SIZE kadar paket ACK beklemeden gönderilir
#   - Cumulative ACK: ACK(n) → n dahil tüm öncekiler onaylanmış
#   - Timeout → penceredeki tüm unack paketleri yeniden gönder
# =============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import socket
import os
import time
import math
import threading

from config import (
    HOST, PORT, PACKET_SIZE, TIMEOUT, MAX_RETRIES,
    WINDOW_SIZE, LOSS_SIMULATION, LOSS_RATE,
    DELAY_SIMULATION, DELAY_MIN_MS, DELAY_MAX_MS
)
from protocol import (
    create_data_packet, parse_ack_packet,
    create_fin_packet,
    compute_checksum,
    DATA_HEADER_SIZE
)
from logger import TransferLogger


def send_file_gbn(filepath: str, window_size: int = None) -> dict:
    """
    Go-Back-N sliding window ile dosya gönderir.

    Args:
        filepath    : Gönderilecek dosyanın tam yolu
        window_size : Pencere boyutu (None ise config'den)

    Returns:
        dict : Transfer istatistikleri
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    _window_size = window_size if window_size else WINDOW_SIZE
    logger = TransferLogger(role="CLIENT")

    # ---- Dosyayı Oku & Parçala ----
    with open(filepath, "rb") as f:
        file_data = f.read()

    file_size     = len(file_data)
    filename      = os.path.basename(filepath)
    total_packets = math.ceil(file_size / PACKET_SIZE)

    if total_packets == 0:
        print("[GBN-CLIENT] HATA: Dosya boş!")
        return {}

    file_checksum = compute_checksum(file_data)

    print(f"\n[GBN-CLIENT] Dosya: {filename}")
    print(f"[GBN-CLIENT] Boyut: {file_size} byte | {total_packets} paket | Pencere: {_window_size}")
    print(f"[GBN-CLIENT] Sunucu: {HOST}:{PORT} | Timeout: {TIMEOUT}s")
    print("-" * 60)

    logger.log_transfer_start(filename, file_size, total_packets)

    # ---- Soket Kurulumu ----
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    # ---- Paketleri hazırla ----
    packets = []
    for seq in range(total_packets):
        start_byte = seq * PACKET_SIZE
        end_byte   = min(start_byte + PACKET_SIZE, file_size)
        payload    = file_data[start_byte:end_byte]
        packets.append(create_data_packet(seq, total_packets, payload))

    # ---- GBN State ----
    base = 0           # En eski unACK'ed paket
    next_seq = 0       # Gönderilecek sonraki paket
    sent_count = 0
    ack_count = 0
    timeout_count = 0
    retry_count = 0
    drop_count = 0
    rtt_list = []
    failed_packets = []
    send_times = {}    # seq_num → send_time

    start_time = time.time()

    # Loss simulation helper
    def maybe_drop() -> bool:
        if LOSS_SIMULATION:
            import random
            return random.random() < LOSS_RATE
        return False

    # MAX_RETRIES: base ilerlemeden kaç ardışık timeout olursa transfer fail olsun
    consecutive_timeouts = 0
    max_consecutive_timeouts = MAX_RETRIES * 2  # Pencere bazlı, SAW'a göre daha toleranslı
    transfer_failed = False

    try:
        while base < total_packets:
            # ---- Pencere içindeki paketleri gönder ----
            while next_seq < min(base + _window_size, total_packets):
                if maybe_drop():
                    print(f"[GBN-CLIENT] ★ Paket #{next_seq} simüle kayıp")
                    drop_count += 1
                else:
                    sock.sendto(packets[next_seq], (HOST, PORT))
                    sent_count += 1
                    send_times[next_seq] = time.time()

                logger.log_sent(next_seq)
                next_seq += 1

            # ---- ACK bekle ----
            try:
                raw_ack, _ = sock.recvfrom(64)
                ack_time = time.time()
                ack = parse_ack_packet(raw_ack)

                if ack and ack["ack_num"] >= base:
                    ack_num = ack["ack_num"]
                    # Cumulative ACK: ack_num dahil tüm paketler onaylanmış
                    newly_acked = ack_num - base + 1
                    ack_count += newly_acked
                    consecutive_timeouts = 0  # Reset on progress

                    # RTT hesapla
                    if ack_num in send_times:
                        rtt_ms = (ack_time - send_times[ack_num]) * 1000
                        rtt_list.append(rtt_ms)
                        logger.log_ack_received(ack_num, rtt_ms)

                    print(f"[GBN-CLIENT] ✓ Cumulative ACK #{ack_num} | "
                          f"Base: {base} → {ack_num + 1}")
                    base = ack_num + 1

            except socket.timeout:
                timeout_count += 1
                consecutive_timeouts += 1
                retry_count += (next_seq - base)
                logger.log_timeout(base, consecutive_timeouts)
                print(f"[GBN-CLIENT] ⏱ Timeout! Pencere yeniden gönderiliyor: "
                      f"#{base}-{next_seq-1} (ardışık timeout: {consecutive_timeouts})")

                # MAX_RETRIES kontrolü
                if consecutive_timeouts >= max_consecutive_timeouts:
                    print(f"[GBN-CLIENT] ✗ Max retry aşıldı! ({max_consecutive_timeouts} ardışık timeout)")
                    failed_packets = list(range(base, next_seq))
                    transfer_failed = True
                    break

                # Go-Back-N: penceredeki tüm paketleri yeniden gönder
                for seq in range(base, next_seq):
                    if maybe_drop():
                        drop_count += 1
                        continue
                    sock.sendto(packets[seq], (HOST, PORT))
                    sent_count += 1
                    send_times[seq] = time.time()
                    logger.log_retransmit(seq, consecutive_timeouts)

        fin_acked = False
        if transfer_failed or failed_packets:
            print("\n[GBN-CLIENT] Transfer basarisiz: FIN gonderilmeyecek.")
            logger.log_failed(base, notes="gbn_transfer_aborted")
        else:
            print("\n[GBN-CLIENT] Tum paketler gonderildi. FIN gonderiliyor...")
            fin_packet = create_fin_packet(file_checksum)
            for _ in range(5):
                sock.sendto(fin_packet, (HOST, PORT))
                try:
                    raw, _ = sock.recvfrom(64)
                    ack = parse_ack_packet(raw)
                    if ack and ack["ack_num"] == 9999:
                        fin_acked = True
                        break
                except socket.timeout:
                    pass

    finally:
        sock.close()

    end_time = time.time()
    elapsed_sec = end_time - start_time

    # ---- Metrikler ----
    last_pkt_size = file_size - (total_packets - 1) * PACKET_SIZE if total_packets > 1 else file_size
    if ack_count >= total_packets:
        good_bytes = file_size
    else:
        good_bytes = min(ack_count * PACKET_SIZE, file_size)
    unique_bytes = (total_packets - 1) * PACKET_SIZE + last_pkt_size
    retransmit_overhead = retry_count * PACKET_SIZE
    total_sent_bytes = unique_bytes + retransmit_overhead
    throughput_bps = (total_sent_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0
    goodput_bps = (good_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0
    avg_rtt = sum(rtt_list) / len(rtt_list) if rtt_list else 0
    loss_rate = (timeout_count / sent_count * 100) if sent_count > 0 else 0
    retry_rate = (retry_count / total_packets * 100) if total_packets > 0 else 0

    transfer_success = (
        ack_count >= total_packets
        and not failed_packets
        and not transfer_failed
        and fin_acked
    )

    stats = {
        "filename"       : filename,
        "file_size"      : file_size,
        "file_size_kb"   : file_size / 1024,
        "total_packets"  : total_packets,
        "window_size"    : _window_size,
        "sent_count"     : sent_count,
        "ack_count"      : ack_count,
        "timeout_count"  : timeout_count,
        "retry_count"    : retry_count,
        "drop_count"     : drop_count,
        "failed_packets" : failed_packets,
        "rtt_list"       : rtt_list,
        "elapsed_sec"    : elapsed_sec,
        "throughput_bps" : throughput_bps,
        "goodput_bps"    : goodput_bps,
        "throughput_kbps": throughput_bps / 1000,
        "goodput_kbps"   : goodput_bps / 1000,
        "loss_rate_pct"  : loss_rate,
        "retry_rate_pct" : retry_rate,
        "avg_rtt_ms"     : avg_rtt,
        "fin_acked"      : fin_acked,
        "success"        : transfer_success,
        "protocol"       : "GBN",
    }

    if transfer_success:
        logger.log_transfer_complete(
            elapsed_sec=elapsed_sec,
            total_bytes=file_size,
            sent_count=sent_count,
            retry_count=retry_count
        )

    # ---- Özet ----
    print("\n" + "=" * 60)
    print("        GBN TRANSFER TAMAMLANDI — ÖZET")
    print("=" * 60)
    print(f"  Dosya               : {filename} ({file_size} byte)")
    print(f"  Pencere Boyutu      : {_window_size}")
    print(f"  Toplam Süre         : {elapsed_sec:.3f}s")
    print(f"  Throughput          : {throughput_bps/1000:.1f} kbps")
    print(f"  Goodput             : {goodput_bps/1000:.1f} kbps")
    print(f"  Gönderilen paket    : {sent_count}")
    print(f"  Başarılı ACK        : {ack_count}")
    print(f"  Timeout sayısı      : {timeout_count}")
    print(f"  Retransmission      : {retry_count} ({retry_rate:.1f}%)")
    print(f"  Ortalama RTT        : {avg_rtt:.1f}ms")
    print(f"  FIN onaylandı       : {'Evet' if fin_acked else 'Hayır'}")
    print(f"  Transfer durumu     : {'BASARILI' if transfer_success else 'BASARISIZ'}")
    print("=" * 60)

    return stats


# ============================================================
# Ana Giriş
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python client_gbn.py <dosya_yolu> [window_size]")
        sys.exit(1)
    filepath = sys.argv[1]
    ws = int(sys.argv[2]) if len(sys.argv) > 2 else None
    send_file_gbn(filepath, window_size=ws)
