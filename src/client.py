# =============================================================
# client.py — NetProbe UDP İstemcisi
#
# Görev:
#   1. Gönderilecek dosyayı oku
#   2. PACKET_SIZE'a göre parçalara böl
#   3. Stop-and-wait: her paket için:
#      a. Paketi gönder
#      b. ACK bekle (timeout süresince)
#      c. ACK geldi → sonraki pakete geç
#      d. Timeout → yeniden gönder (max MAX_RETRIES kez)
#      e. MAX_RETRIES aşılırsa → FAILED, log'a yaz, kullanıcıya bildir
#   4. Tüm paketler gönderilince FIN paketi gönder
#   5. Metrikleri log'a yaz
# =============================================================

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import socket
import os
import time
import math

from config import (
    HOST, PORT, PACKET_SIZE, TIMEOUT, MAX_RETRIES,
    LOSS_SIMULATION, LOSS_RATE,
    DELAY_SIMULATION, DELAY_MIN_MS, DELAY_MAX_MS
)
from protocol import (
    create_data_packet, parse_ack_packet,
    create_fin_packet,
    compute_file_checksum, compute_checksum,
    DATA_HEADER_SIZE
)
from logger import TransferLogger


def send_file(filepath: str, dashboard=None) -> dict:
    """
    Verilen dosyayı UDP üzerinden güvenilir biçimde sunucuya gönderir.

    Args:
        filepath  : Gönderilecek dosyanın tam yolu
        dashboard : Opsiyonel Dashboard nesnesi (canlı izleme için)

    Returns:
        dict : Transfer istatistikleri (throughput, goodput, vb.)

    Raises:
        FileNotFoundError : Dosya bulunamazsa
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    logger = TransferLogger(role="CLIENT")

    # ---- Dosyayı Oku & Parçala ----
    with open(filepath, "rb") as f:
        file_data = f.read()

    file_size    = len(file_data)
    filename     = os.path.basename(filepath)
    total_packets = math.ceil(file_size / PACKET_SIZE)

    if total_packets == 0:
        print("[CLIENT] HATA: Dosya boş!")
        return {}

    # Tüm dosyanın hash'i (FIN paketinde kullanılacak)
    file_checksum = compute_checksum(file_data)

    print(f"\n[CLIENT] Dosya: {filename}")
    print(f"[CLIENT] Boyut: {file_size} byte | {total_packets} paket | Paket boyutu: {PACKET_SIZE}B")
    print(f"[CLIENT] Sunucu: {HOST}:{PORT} | Timeout: {TIMEOUT}s | Max Retry: {MAX_RETRIES}")
    print("-" * 60)

    logger.log_transfer_start(filename, file_size, total_packets)

    # ---- Soket Kurulumu ----
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    # ---- Transfer İstatistikleri ----
    stats = {
        "filename"       : filename,
        "file_size"      : file_size,
        "total_packets"  : total_packets,
        "sent_count"     : 0,    # Toplam gönderim (retransmission dahil)
        "ack_count"      : 0,    # Başarılı ACK sayısı
        "timeout_count"  : 0,    # Toplam timeout sayısı
        "retry_count"    : 0,    # Toplam retransmission sayısı
        "drop_count"     : 0,    # Simülasyon ile düşürülen paket sayısı
        "failed_packets" : [],   # Başarısız paket numaraları
        "rtt_list"       : [],   # Her ACK için RTT (ms)
        "start_time"     : None,
        "end_time"       : None,
    }

    # ---- Yapay Kayıp/Gecikme için import ----
    if LOSS_SIMULATION or DELAY_SIMULATION:
        import random

    def maybe_drop() -> bool:
        """LOSS_SIMULATION açıksa paketi rastgele düşür."""
        if LOSS_SIMULATION:
            import random
            return random.random() < LOSS_RATE
        return False

    def maybe_delay():
        """DELAY_SIMULATION açıksa yapay gecikme ekle."""
        if DELAY_SIMULATION:
            import random, time as t
            delay = random.uniform(DELAY_MIN_MS, DELAY_MAX_MS) / 1000.0
            t.sleep(delay)

    # ---- Dashboard başlat ----
    if dashboard:
        dashboard.start(filename, file_size, total_packets)

    # ---- Ana Gönderim Döngüsü ----
    stats["start_time"] = time.time()

    try:
        for seq_num in range(total_packets):
            # Payload'u hesapla
            start_byte = seq_num * PACKET_SIZE
            end_byte   = min(start_byte + PACKET_SIZE, file_size)
            payload    = file_data[start_byte:end_byte]

            # DATA paketi oluştur
            packet = create_data_packet(seq_num, total_packets, payload)

            retry = 0
            ack_received = False

            while retry <= MAX_RETRIES:
                # Yapay gecikme simülasyonu
                maybe_delay()

                # Yapay kayıp simülasyonu
                if maybe_drop():
                    print(f"[CLIENT] ★ Paket #{seq_num} simüle kayıp (düşürüldü)")
                    stats["drop_count"] += 1
                    # Göndermedik ama sanki gönderdik gibi timeout bekle
                else:
                    sock.sendto(packet, (HOST, PORT))
                    stats["sent_count"] += 1

                if retry == 0:
                    logger.log_sent(seq_num)
                else:
                    logger.log_retransmit(seq_num, retry)
                    stats["retry_count"] += 1

                # ACK bekle
                send_time = time.time()
                try:
                    raw_ack, _ = sock.recvfrom(64)
                    ack_time   = time.time()
                    rtt_ms     = (ack_time - send_time) * 1000

                    ack = parse_ack_packet(raw_ack)
                    if ack and ack["ack_num"] == seq_num:
                        # Doğru ACK alındı
                        stats["ack_count"] += 1
                        stats["rtt_list"].append(rtt_ms)
                        logger.log_ack_received(seq_num, rtt_ms)
                        ack_received = True
                        print(f"[CLIENT] ✓ Paket #{seq_num}/{total_packets-1} | "
                              f"RTT={rtt_ms:.1f}ms | Deneme={retry+1}")
                        # Dashboard güncelle
                        if dashboard:
                            dashboard.update(
                                seq_num=seq_num,
                                rtt_ms=rtt_ms,
                                retries=stats["retry_count"],
                                sent=stats["sent_count"]
                            )
                        break
                    else:
                        # Yanlış ACK → sayma, tekrar dene
                        print(f"[CLIENT] ⚠ Yanlış ACK: beklenen {seq_num}, gelen {ack}")

                except socket.timeout:
                    stats["timeout_count"] += 1
                    logger.log_timeout(seq_num, retry)
                    print(f"[CLIENT] ⏱ Paket #{seq_num} timeout! (Deneme {retry+1}/{MAX_RETRIES})")
                    retry += 1
                    continue

                # Eğer yanlış ACK gelirse de retry artır
                retry += 1

            # Max retry aşıldı mı?
            if not ack_received:
                stats["failed_packets"].append(seq_num)
                logger.log_failed(seq_num, notes=str(MAX_RETRIES))
                print(f"[CLIENT] ✗ Paket #{seq_num} BAŞARISIZ! ({MAX_RETRIES} deneme tükendi)")

        # ---- FIN Paketi Gönder ----
        fin_acked = False
        if stats["failed_packets"]:
            print("\n[CLIENT] Transfer basarisiz: eksik paket var, FIN gonderilmeyecek.")
            logger.log_failed(-1, notes="transfer_aborted_missing_packets")
        else:
            print("\n[CLIENT] Tum paketler gonderildi. FIN gonderiliyor...")
            fin_packet = create_fin_packet(file_checksum)

        # FIN için ACK al (sunucunun dosyayı kaydettiğini doğrula)
            for _ in range(5):
                sock.sendto(fin_packet, (HOST, PORT))
                try:
                    raw, _ = sock.recvfrom(64)
                    ack = parse_ack_packet(raw)
                    if ack and ack["ack_num"] == 9999:
                        fin_acked = True
                        break
                    # Yanlış ACK geldi (örn. gecikmeli veri ACK'ı) → tekrar dene
                except socket.timeout:
                    continue

        stats["end_time"] = time.time()

    finally:
        sock.close()

    # ---- Özet İstatistikler ----
    elapsed_sec = stats["end_time"] - stats["start_time"]

    # Son paket boyutu (dosya tam bölünmeyebilir)
    last_packet_size = file_size - (total_packets - 1) * PACKET_SIZE if total_packets > 1 else file_size

    # Throughput: gerçek gönderilen toplam byte / süre
    # Her retransmit'te full paket veya son paket gönderilmiş olabilir
    # Basitleştirme: unique paketler PACKET_SIZE, son paket last_packet_size
    # Retransmit'ler dahil toplam = (sent_count - retransmit_of_last) * PACKET_SIZE + ...
    # En doğru yaklaşım: file_size + retransmit_overhead
    unique_bytes = (total_packets - 1) * PACKET_SIZE + last_packet_size  # = file_size
    retransmit_bytes = stats["retry_count"] * PACKET_SIZE  # Retransmit'ler genelde tam paket
    total_sent_bytes = unique_bytes + retransmit_bytes
    throughput_bps = (total_sent_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0

    # Goodput: sadece başarıyla teslim edilen payload / süre
    # ack_count == total_packets ise tam dosya, değilse kısmi
    if stats["ack_count"] >= total_packets:
        good_bytes = file_size
    else:
        # Son paket hariç her ACK = PACKET_SIZE, son paket = last_packet_size
        good_bytes = min(stats["ack_count"] * PACKET_SIZE, file_size)
    goodput_bps = (good_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0

    loss_rate        = (stats["timeout_count"] / stats["sent_count"] * 100) if stats["sent_count"] > 0 else 0
    retry_rate       = (stats["retry_count"] / stats["total_packets"] * 100) if stats["total_packets"] > 0 else 0
    avg_rtt          = sum(stats["rtt_list"]) / len(stats["rtt_list"]) if stats["rtt_list"] else 0

    transfer_success = (
        stats["ack_count"] == total_packets
        and not stats["failed_packets"]
        and fin_acked
    )

    stats.update({
        "elapsed_sec"     : elapsed_sec,
        "throughput_bps"  : throughput_bps,
        "goodput_bps"     : goodput_bps,
        "loss_rate_pct"   : loss_rate,
        "retry_rate_pct"  : retry_rate,
        "avg_rtt_ms"      : avg_rtt,
        "fin_acked"       : fin_acked,
        "success"         : transfer_success,
    })

    if transfer_success:
        logger.log_transfer_complete(
            elapsed_sec=elapsed_sec,
            total_bytes=file_size,
            sent_count=stats["sent_count"],
            retry_count=stats["retry_count"]
        )

    # ---- Dashboard bitir ----
    if dashboard:
        dashboard.finish(stats)

    # ---- Ekrana Özet Yazdır ----
    print("\n" + "=" * 60)
    print("            TRANSFER TAMAMLANDI — ÖZET")
    print("=" * 60)
    print(f"  Dosya               : {filename} ({file_size} byte)")
    print(f"  Toplam Süre         : {elapsed_sec:.3f}s")
    print(f"  Throughput          : {throughput_bps/1000:.1f} kbps")
    print(f"  Goodput             : {goodput_bps/1000:.1f} kbps")
    print(f"  Gönderilen paket    : {stats['sent_count']}")
    print(f"  Başarılı ACK        : {stats['ack_count']}")
    print(f"  Timeout sayısı      : {stats['timeout_count']}")
    print(f"  Retransmission      : {stats['retry_count']} ({retry_rate:.1f}%)")
    print(f"  Drop (simülasyon)   : {stats['drop_count']}")
    print(f"  Ortalama RTT        : {avg_rtt:.1f}ms")
    print(f"  Başarısız paketler  : {stats['failed_packets'] if stats['failed_packets'] else 'Yok'}")
    print(f"  FIN onaylandı       : {'Evet' if fin_acked else 'Hayır'}")
    print(f"  Transfer durumu     : {'BASARILI' if transfer_success else 'BASARISIZ'}")
    print("=" * 60)

    return stats


# ============================================================
# Ana Giriş
# ============================================================
if __name__ == "__main__":
    # Kullanım: python client.py <dosya_yolu> [--dashboard]
    if len(sys.argv) < 2:
        print("Kullanım: python client.py <dosya_yolu> [--dashboard]")
        sys.exit(1)

    use_dashboard = "--dashboard" in sys.argv
    filepath = sys.argv[1]

    if use_dashboard:
        from dashboard import Dashboard
        dash = Dashboard()
        send_file(filepath, dashboard=dash)
    else:
        send_file(filepath)
