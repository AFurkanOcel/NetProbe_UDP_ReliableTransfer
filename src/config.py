# =============================================================
# config.py — NetProbe Proje Konfigürasyonu
# Tüm parametreler burada. Deney sırasında sadece burası değişir.
# =============================================================

import os

# ----- Ağ Ayarları -----
HOST = "127.0.0.1"       # Sunucu IP'si
PORT = 5005              # Sunucu portu

# ----- Paket Ayarları -----
PACKET_SIZE = 1024       # Her paketin veri kısmı (byte). Deneyde değiştir: 256, 512, 1024, 4096

# ----- Güvenilir Aktarım Ayarları -----
TIMEOUT = 2.0            # ACK bekleme süresi (saniye). Deneyde değiştir: 0.5, 1.0, 2.0, 5.0
MAX_RETRIES = 5          # Bir paket için maksimum yeniden gönderim (ZORUNLU: 5)

# ----- Sliding Window (Go-Back-N) Ayarları -----
WINDOW_SIZE = 4          # GBN pencere boyutu
PROTOCOL_MODE = "SAW"    # "SAW" = Stop-and-Wait, "GBN" = Go-Back-N

# ----- Ağ Simülasyonu -----
LOSS_SIMULATION = False  # True yapınca yapay paket kaybı aktif olur
LOSS_RATE = 0.0          # 0.0 = kayıp yok | 0.05 = %5 | 0.15 = %15 | 0.30 = %30
DELAY_SIMULATION = False # True yapınca yapay gecikme eklenir
DELAY_MIN_MS = 0         # Minimum gecikme (ms)
DELAY_MAX_MS = 50        # Maksimum gecikme (ms)

# ----- Gelişmiş Ağ Simülasyonu -----
ACK_LOSS_RATE = 0.0      # ACK paketlerinin kaybolma olasılığı (0.0-1.0)
BURST_LENGTH = 1         # Burst loss: ardışık kaç paket düşürülecek
JITTER_MS = 0.0          # Jitter: gecikme standart sapması (ms, normal dağılım)

# ----- Çoklu Deneme -----
N_REPEATS = 3            # Her senaryo kaç kez tekrarlanacak

# ----- Dosya Yolları -----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
TEST_FILES_DIR = os.path.join(BASE_DIR, "data", "test_files")
RESULTS_DIR = os.path.join(BASE_DIR, "results", "graphs")
LOG_FILE = os.path.join(LOG_DIR, "transfer_log.csv")  # Deprecated: eski format fallback
LOG_FILE_CLIENT = os.path.join(LOG_DIR, "transfer_log_client.csv")
LOG_FILE_SERVER = os.path.join(LOG_DIR, "transfer_log_server.csv")
RECEIVED_DIR = os.path.join(BASE_DIR, "data", "received")

# Klasörleri oluştur (yoksa)
for d in [LOG_DIR, TEST_FILES_DIR, RESULTS_DIR, RECEIVED_DIR]:
    os.makedirs(d, exist_ok=True)

# ----- Protokol Sabitleri -----
PACKET_TYPE_DATA = 0x01  # Veri paketi
PACKET_TYPE_ACK  = 0x02  # ACK paketi
PACKET_TYPE_FIN  = 0x03  # Aktarım sonu sinyali
