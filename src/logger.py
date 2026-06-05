# =============================================================
# logger.py — NetProbe Olay Kayıt Sistemi
#
# Her transfer olayını CSV formatında kaydeder.
# Client ve Server ayrı dosyalara yazar (race condition önlemi).
# Sütunlar: timestamp | event_type | seq_num | retry_count | elapsed_ms | notes
#
# event_type değerleri:
#   SENT            - Paket gönderildi
#   ACK_RECEIVED    - ACK alındı
#   DATA_RECEIVED   - Veri paketi alındı (server)
#   TIMEOUT         - Paket için timeout oluştu
#   RETRANSMIT      - Yeniden gönderim yapıldı
#   FAILED          - Maks deneme aşıldı, paket başarısız
#   DUPLICATE       - Sunucu duplicate paket aldı, yok sayıldı
#   TRANSFER_START  - Aktarım başladı
#   TRANSFER_COMPLETE - Aktarım tamamlandı
#   INTEGRITY_OK    - Dosya bütünlüğü doğrulandı
#   INTEGRITY_FAIL  - Dosya bütünlüğü doğrulanamadı
# =============================================================

import csv
import os
import time
from config import LOG_FILE_CLIENT, LOG_FILE_SERVER


class TransferLogger:
    """
    Aktarım olaylarını CSV'ye kaydeder.
    Her TransferLogger örneği bir transfer oturumuna karşılık gelir.
    Client ve Server ayrı dosyalara yazar.
    """

    CSV_COLUMNS = [
        "timestamp",      # Unix timestamp (float) — hassas zamanlama için
        "event_type",     # Olayın türü (SENT, ACK_RECEIVED, TIMEOUT vb.)
        "seq_num",        # Paket sıra numarası (-1 ise genel olay)
        "retry_count",    # Kaçıncı deneme (0 = ilk gönderim)
        "elapsed_ms",     # Bu olay için geçen süre (ms), -1 ise bilinmiyor
        "notes"           # Ek bilgi (hata mesajı, dosya adı vb.)
    ]

    def __init__(self, log_file: str = None, role: str = "CLIENT"):
        """
        Args:
            log_file : Log dosyasının yolu (None ise role'a göre otomatik belirlenir)
            role     : "CLIENT" veya "SERVER"
        """
        self.role = role
        if log_file is not None:
            self.log_file = log_file
        elif role == "SERVER":
            self.log_file = LOG_FILE_SERVER
        else:
            self.log_file = LOG_FILE_CLIENT
        self.start_time = time.time()
        self._ensure_header()

    def _ensure_header(self):
        """Log dosyası yoksa oluştur ve başlık ekle."""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        write_header = not os.path.exists(self.log_file)
        # Dosya boşsa da başlık yaz
        if not write_header:
            write_header = os.path.getsize(self.log_file) == 0
        if write_header:
            with open(self.log_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
                writer.writeheader()

    def _write(self, event_type: str, seq_num: int = -1,
                retry_count: int = 0, elapsed_ms: float = -1.0, notes: str = ""):
        """CSV'ye tek satır yazar."""
        row = {
            "timestamp"  : time.time(),
            "event_type" : f"[{self.role}] {event_type}",
            "seq_num"    : seq_num,
            "retry_count": retry_count,
            "elapsed_ms" : round(elapsed_ms, 3),
            "notes"      : notes
        }
        with open(self.log_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
            writer.writerow(row)

    # ---- Kullanışlı Log Metodları ----

    def log_transfer_start(self, filename: str, file_size: int, total_packets: int):
        notes = f"file={filename} size={file_size}B packets={total_packets}"
        self._write("TRANSFER_START", notes=notes)

    def log_sent(self, seq_num: int, retry_count: int = 0):
        self._write("SENT", seq_num=seq_num, retry_count=retry_count)

    def log_ack_received(self, seq_num: int, elapsed_ms: float):
        self._write("ACK_RECEIVED", seq_num=seq_num, elapsed_ms=elapsed_ms)

    def log_data_received(self, seq_num: int):
        """Server tarafında veri paketi alındığında çağrılır."""
        self._write("DATA_RECEIVED", seq_num=seq_num)

    def log_timeout(self, seq_num: int, retry_count: int):
        self._write("TIMEOUT", seq_num=seq_num, retry_count=retry_count)

    def log_retransmit(self, seq_num: int, retry_count: int):
        self._write("RETRANSMIT", seq_num=seq_num, retry_count=retry_count)

    def log_failed(self, seq_num: int, notes: str = ""):
        msg = f"Max retries ({notes}) aşıldı" if notes else "Max retries aşıldı"
        self._write("FAILED", seq_num=seq_num, notes=msg)

    def log_duplicate(self, seq_num: int):
        self._write("DUPLICATE", seq_num=seq_num, notes="Duplicate paket alındı, yok sayıldı")

    def log_transfer_complete(self, elapsed_sec: float, total_bytes: int,
                               sent_count: int, retry_count: int):
        notes = (
            f"elapsed={elapsed_sec:.3f}s "
            f"bytes={total_bytes} "
            f"sent={sent_count} "
            f"retries={retry_count}"
        )
        self._write("TRANSFER_COMPLETE", elapsed_ms=elapsed_sec * 1000, notes=notes)

    def log_integrity_ok(self):
        self._write("INTEGRITY_OK", notes="Dosya SHA-256 checksum doğrulandı")

    def log_integrity_fail(self):
        self._write("INTEGRITY_FAIL", notes="UYARI: Dosya checksum uyuşmazlığı!")
