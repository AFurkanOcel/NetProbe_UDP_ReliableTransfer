# =============================================================
# dashboard.py — NetProbe Gerçek Zamanlı Terminal Dashboard
#
# Transfer sırasında terminalde canlı izleme:
#   - İlerleme çubuğu
#   - Anlık throughput
#   - Paket sayacı
#   - Retry sayacı
#
# Windows uyumlu: ANSI escape desteğini otomatik algılar.
# =============================================================

import sys
import os
import time


def _enable_ansi_windows():
    """Windows'ta ANSI escape sequence desteğini etkinleştirir."""
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(-11)
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


# ANSI desteği var mı kontrol et
_ANSI_SUPPORTED = _enable_ansi_windows()


class Dashboard:
    """
    Terminal tabanlı canlı transfer izleme paneli.
    client.py ile --dashboard flag'i üzerinden entegre çalışır.
    Windows ve Unix terminallerinde çalışır.
    """

    def __init__(self, bar_width: int = 40):
        """
        Args:
            bar_width : İlerleme çubuğu genişliği (karakter)
        """
        self.bar_width = bar_width
        self.filename = ""
        self.file_size = 0
        self.total_packets = 0
        self.start_time = 0
        self.last_update_time = 0
        self._started = False

    def start(self, filename: str, file_size: int, total_packets: int):
        """Transfer başlangıcında çağrılır."""
        self.filename = filename
        self.file_size = file_size
        self.total_packets = total_packets
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self._started = True

        self._clear_screen()
        self._draw_header()

    def update(self, seq_num: int, rtt_ms: float, retries: int, sent: int):
        """
        Her başarılı ACK'ta çağrılır.

        Args:
            seq_num : Onaylanan paket numarası
            rtt_ms  : Bu paketin RTT'si
            retries : Toplam retry sayısı
            sent    : Toplam gönderim sayısı
        """
        if not self._started:
            return

        now = time.time()
        elapsed = now - self.start_time
        progress = (seq_num + 1) / self.total_packets if self.total_packets > 0 else 0
        transferred_bytes = min((seq_num + 1) * 1024, self.file_size)

        # Anlık throughput
        instant_throughput = (transferred_bytes * 8) / elapsed if elapsed > 0 else 0

        # İlerleme çubuğu
        filled = int(self.bar_width * progress)
        bar = "#" * filled + "-" * (self.bar_width - filled)

        # Satırları hazırla
        line1 = f"  [{bar}] {progress*100:5.1f}%"
        line2 = (f"  Paket: {seq_num + 1}/{self.total_packets} | "
                 f"Gonderim: {sent} | Retry: {retries}")
        line3 = (f"  Throughput: {instant_throughput/1000:.1f} kbps | "
                 f"RTT: {rtt_ms:.1f}ms | Sure: {elapsed:.1f}s")

        if _ANSI_SUPPORTED:
            # ANSI: cursor'u 3 satır yukarı taşı ve üzerine yaz
            sys.stdout.write("\033[3A")
            sys.stdout.write(f"\033[K{line1}\n")
            sys.stdout.write(f"\033[K{line2}\n")
            sys.stdout.write(f"\033[K{line3}")
        else:
            # Fallback: \r ile tek satır güncelle (Windows cmd.exe)
            compact = (f"\r  [{bar}] {progress*100:.0f}% | "
                       f"Pkt:{seq_num+1}/{self.total_packets} | "
                       f"Retry:{retries} | "
                       f"{instant_throughput/1000:.0f}kbps | "
                       f"RTT:{rtt_ms:.0f}ms")
            sys.stdout.write(compact)

        sys.stdout.flush()

    def finish(self, stats: dict):
        """Transfer tamamlandığında çağrılır."""
        if not self._started:
            return

        elapsed = stats.get("elapsed_sec", 0)
        throughput = stats.get("throughput_bps", 0)
        goodput = stats.get("goodput_bps", 0)

        print("\n\n")
        print("  " + "=" * 50)
        print("   TRANSFER TAMAMLANDI")
        print("  " + "=" * 50)
        print(f"   Dosya      : {self.filename}")
        print(f"   Boyut      : {self.file_size} byte")
        print(f"   Sure       : {elapsed:.3f}s")
        print(f"   Throughput : {throughput/1000:.1f} kbps")
        print(f"   Goodput    : {goodput/1000:.1f} kbps")
        print(f"   ACK        : {stats.get('ack_count', 0)}/{self.total_packets}")
        print(f"   Retry      : {stats.get('retry_count', 0)}")
        print(f"   Drop       : {stats.get('drop_count', 0)}")
        print("  " + "=" * 50)
        sys.stdout.flush()

    def _clear_screen(self):
        """Terminal ekranını temizle."""
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')

    def _draw_header(self):
        """Dashboard başlığını çiz."""
        print("  " + "=" * 50)
        print("   NetProbe — Canli Transfer Izleme")
        print("  " + "=" * 50)
        print(f"   Dosya: {self.filename} ({self.file_size} byte)")
        print(f"   Paket sayisi: {self.total_packets}")
        print("  " + "-" * 50)
        # İlerleme çubuğu için boş satırlar
        bar = "-" * self.bar_width
        print(f"  [{bar}]   0.0%")
        print(f"  Paket: 0/{self.total_packets} | Gonderim: 0 | Retry: 0")
        print(f"  Throughput: 0.0 kbps | RTT: 0.0ms | Sure: 0.0s")
        sys.stdout.flush()
