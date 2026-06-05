# =============================================================
# network_sim.py — NetProbe Ağ Koşulları Simülatörü
#
# Görev:
#   Gerçek bir ağda oluşabilecek paket kayıpları ve gecikmeleri
#   yazılım katmanında simüle eder. Deney senaryolarını
#   config.py parametrelerini değiştirerek kolayca çalıştırmaya
#   yarar bir yardımcı modüldür.
#
# Özellikler:
#   - Basit paket kaybı (uniform random)
#   - Burst loss (ardışık N paket düşürme)
#   - Jitter (değişken gecikme, normal dağılım)
#   - ACK loss simülasyonu (server tarafı)
#   - Çoklu deneme (N_REPEATS) desteği
# =============================================================

import random
import time
import os
import sys
import statistics


class NetworkSimulator:
    """
    Yapay paket kaybı ve gecikme simülatörü.

    Attributes:
        loss_rate    : 0.0–1.0 arası kayıp olasılığı
        delay_min_ms : Minimum gecikme (ms)
        delay_max_ms : Maksimum gecikme (ms)
        burst_length : Ardışık düşürülecek paket sayısı
        jitter_ms    : Gecikme standart sapması (ms)
        enabled      : False ise hiçbir şey yapmaz (pass-through)
    """

    def __init__(self, loss_rate: float = 0.0,
                 delay_min_ms: float = 0.0,
                 delay_max_ms: float = 0.0,
                 burst_length: int = 1,
                 jitter_ms: float = 0.0,
                 enabled: bool = True):
        """
        Args:
            loss_rate    : Paket düşürme olasılığı. 0.05 = %5 kayıp.
            delay_min_ms : En az bu kadar ms gecikme eklenir.
            delay_max_ms : En fazla bu kadar ms gecikme eklenir.
            burst_length : Burst loss: ilk kayıp sonrası ardışık kaç paket düşürülür.
            jitter_ms    : Gecikme standart sapması (normal dağılım, ms).
            enabled      : False yapılırsa simülatör devre dışı.
        """
        self.loss_rate    = max(0.0, min(1.0, loss_rate))
        self.delay_min_ms = max(0.0, delay_min_ms)
        self.delay_max_ms = max(delay_min_ms, delay_max_ms)
        self.burst_length = max(1, burst_length)
        self.jitter_ms    = max(0.0, jitter_ms)
        self.enabled      = enabled

        # Burst state
        self._burst_remaining = 0

        # İstatistik sayaçları
        self.total_packets = 0
        self.dropped       = 0
        self.delayed       = 0
        self.total_delay_ms = 0.0

    def should_send(self) -> bool:
        """
        Paketi gönder ya da düşür kararı verir.

        Returns:
            True  → paketi gönder (normal akış)
            False → paketi düşür (simüle kayıp)
        """
        self.total_packets += 1
        if not self.enabled or self.loss_rate == 0.0:
            return True

        # Burst devam ediyor mu?
        if self._burst_remaining > 0:
            self._burst_remaining -= 1
            self.dropped += 1
            return False

        # Normal kayıp kontrolü
        if random.random() < self.loss_rate:
            self.dropped += 1
            # Burst başlat
            if self.burst_length > 1:
                self._burst_remaining = self.burst_length - 1
            return False
        return True

    def apply_delay(self) -> float:
        """
        Yapay ağ gecikmesi uygular.
        Jitter_ms > 0 ise normal dağılımla değişken gecikme ekler.

        Returns:
            float: Eklenen gecikme miktarı (ms)
        """
        if not self.enabled or (self.delay_max_ms == 0.0 and self.jitter_ms == 0.0):
            return 0.0

        # Temel gecikme
        base_delay_ms = random.uniform(self.delay_min_ms, self.delay_max_ms)

        # Jitter ekle (normal dağılım)
        jitter = 0.0
        if self.jitter_ms > 0:
            jitter = random.gauss(0, self.jitter_ms)

        delay_ms = max(0.0, base_delay_ms + jitter)
        time.sleep(delay_ms / 1000.0)
        self.delayed += 1
        self.total_delay_ms += delay_ms
        return delay_ms

    def stats(self) -> dict:
        """Simülatör istatistiklerini döner."""
        avg_delay = (self.total_delay_ms / self.delayed) if self.delayed > 0 else 0.0
        actual_loss = (self.dropped / self.total_packets * 100) if self.total_packets > 0 else 0.0
        return {
            "total_packets"      : self.total_packets,
            "dropped"            : self.dropped,
            "actual_loss_pct"    : actual_loss,
            "configured_loss_pct": self.loss_rate * 100,
            "delayed"            : self.delayed,
            "avg_delay_ms"       : avg_delay,
            "burst_length"       : self.burst_length,
            "jitter_ms"          : self.jitter_ms,
        }

    def print_stats(self):
        s = self.stats()
        print("\n[SİMÜLATÖR] İstatistikler:")
        print(f"  Toplam paket     : {s['total_packets']}")
        print(f"  Düşürülen paket  : {s['dropped']} ({s['actual_loss_pct']:.1f}%)")
        print(f"  Yapay gecikme    : {s['delayed']} paket | Ort: {s['avg_delay_ms']:.1f}ms")
        print(f"  Burst uzunluğu   : {s['burst_length']}")
        print(f"  Jitter (std)     : {s['jitter_ms']:.1f}ms")


# ==============================================================
# Deney Yöneticisi — Otomatik Senaryo Çalıştırıcı
# ==============================================================

class ExperimentRunner:
    """
    4 deney senaryosunu otomatik olarak çalıştırır.
    config.py parametrelerini geçici olarak değiştirir,
    transfer gerçekleştirir, sonuçları toplar.
    N_REPEATS kez tekrar desteği ile ortalama ve standart sapma hesaplar.
    """

    def __init__(self, test_file: str, n_repeats: int = None):
        """
        Args:
            test_file  : Deneyde kullanılacak dosyanın yolu
            n_repeats  : Her senaryo kaç kez tekrarlanacak (None ise config'den)
        """
        self.test_file = test_file
        if n_repeats is None:
            from config import N_REPEATS
            self.n_repeats = N_REPEATS
        else:
            self.n_repeats = n_repeats
        self.results = []

    def _run_transfer(self, label: str, **config_overrides) -> dict:
        """
        Verilen config ile bir transfer çalıştırır.
        """
        import config as cfg
        import importlib

        # Config'i geçici olarak değiştir
        originals = {}
        for key, val in config_overrides.items():
            originals[key] = getattr(cfg, key, None)
            setattr(cfg, key, val)
            if key == "LOSS_RATE" and val > 0:
                cfg.LOSS_SIMULATION = True
            elif key == "LOSS_RATE" and val == 0:
                cfg.LOSS_SIMULATION = False

        print(f"\n{'='*55}")
        print(f"  DENEY: {label}")
        for k, v in config_overrides.items():
            print(f"    {k} = {v}")
        print(f"{'='*55}")

        # Transferi çalıştır
        import client as cli
        importlib.reload(cli)
        stats = cli.send_file(self.test_file)
        stats["label"] = label
        stats.update(config_overrides)
        self.results.append(stats)

        # Config'i geri al
        for key, val in originals.items():
            setattr(cfg, key, val)
        cfg.LOSS_SIMULATION = False

        return stats

    def _run_with_repeats(self, label: str, **config_overrides) -> dict:
        """
        Aynı deneyi N_REPEATS kez çalıştırır.
        Ortalama ve standart sapma hesaplar.
        Throughput/goodput: her run'dan gelen değerlerin aritmetik ortalaması.
        """
        all_runs = []
        for i in range(self.n_repeats):
            run_label = f"{label}_r{i+1}"
            stats = self._run_transfer(run_label, **config_overrides)
            all_runs.append(stats)

        # Basarili run'lari filtrele. Basarisiz denemeler sifir metrik olarak
        # ortalamaya katilmaz; JSON'da failed_runs olarak saklanir.
        valid_runs = [
            r for r in all_runs
            if r
            and r.get("file_size")
            and r.get("success", True)
            and not r.get("failed_packets")
        ]
        failed_runs = [r for r in all_runs if r not in valid_runs]
        if not valid_runs:
            return {
                "label": label,
                "success": False,
                "run_count": len(all_runs),
                "valid_run_count": 0,
                "failed_runs": failed_runs,
                **config_overrides,
            }

        # Ortalama ve std hesapla
        avg_result = {}
        numeric_keys = ["elapsed_sec", "throughput_bps", "goodput_bps",
                        "loss_rate_pct", "retry_rate_pct", "avg_rtt_ms",
                        "sent_count", "ack_count", "timeout_count", "retry_count"]

        for key in numeric_keys:
            values = [r.get(key, 0) for r in valid_runs
                      if r.get(key) is not None and isinstance(r.get(key), (int, float))]
            if values:
                avg_result[key] = statistics.mean(values)
                avg_result[f"{key}_std"] = statistics.stdev(values) if len(values) > 1 else 0.0
            else:
                avg_result[key] = 0
                avg_result[f"{key}_std"] = 0

        # Diğer alanlar ilk geçerli run'dan al
        avg_result["label"] = label
        avg_result["success"] = True
        avg_result["run_count"] = len(all_runs)
        avg_result["valid_run_count"] = len(valid_runs)
        avg_result["failed_runs"] = failed_runs
        avg_result["file_size"] = valid_runs[0].get("file_size", 0)
        avg_result["total_packets"] = valid_runs[0].get("total_packets", 0)
        avg_result.update(config_overrides)

        # Türetilmiş metrikler (kbps cinsinden — grafiklerde kullanılır)
        file_size = avg_result.get("file_size", 0)
        avg_result["file_size_kb"] = file_size / 1024

        # throughput/goodput kbps: bps ortalamasından türet
        avg_result["throughput_kbps"] = avg_result.get("throughput_bps", 0) / 1000
        avg_result["goodput_kbps"] = avg_result.get("goodput_bps", 0) / 1000
        avg_result["throughput_kbps_std"] = avg_result.get("throughput_bps_std", 0) / 1000
        avg_result["goodput_kbps_std"] = avg_result.get("goodput_bps_std", 0) / 1000

        # Ek: elapsed_sec_std ve retry_count_std grafiklerde kullanılıyor
        avg_result["elapsed_std"] = avg_result.get("elapsed_sec_std", 0)
        avg_result["retry_std"] = avg_result.get("retry_count_std", 0)

        return avg_result

    def scenario1_packet_size(self, sizes=(256, 512, 1024, 4096)):
        """Senaryo 1: Farklı paket boyutları."""
        print("\n\n SENARYO 1: Paket Boyutunun Etkisi")
        s1_results = []
        for size in sizes:
            r = self._run_with_repeats(f"S1_pkt{size}", PACKET_SIZE=size, LOSS_RATE=0.0, TIMEOUT=2.0)
            r["packet_size_b"] = size
            s1_results.append(r)
        return s1_results

    def scenario2_timeout(self, timeouts=(0.5, 1.0, 2.0, 5.0)):
        """Senaryo 2: Farklı timeout değerleri (%5 kayıp ile)."""
        print("\n\n SENARYO 2: Timeout Değerinin Etkisi")
        s2_results = []
        for t in timeouts:
            r = self._run_with_repeats(f"S2_to{t}", TIMEOUT=t, LOSS_RATE=0.05, PACKET_SIZE=1024)
            r["timeout_sec"] = t
            s2_results.append(r)
        return s2_results

    def scenario3_loss(self, loss_rates=(0.0, 0.05, 0.15, 0.30)):
        """Senaryo 3: Farklı kayıp oranları."""
        print("\n\n SENARYO 3: Kayıp Oranının Etkisi")
        s3_results = []
        for lr in loss_rates:
            r = self._run_with_repeats(f"S3_loss{int(lr*100)}pct", LOSS_RATE=lr, PACKET_SIZE=1024, TIMEOUT=2.0)
            r["loss_rate_configured_pct"] = lr * 100
            s3_results.append(r)
        return s3_results

    def scenario4_filesize(self, filepaths: list):
        """
        Senaryo 4: Farklı dosya boyutları.

        Args:
            filepaths : Farklı boyutlarda dosyaların yolları
        """
        print("\n\n SENARYO 4: Dosya Boyutunun Etkisi")
        s4_results = []
        for fp in filepaths:
            size_kb = os.path.getsize(fp) / 1024
            self.test_file = fp
            r = self._run_with_repeats(f"S4_{size_kb:.0f}KB", PACKET_SIZE=1024, TIMEOUT=2.0, LOSS_RATE=0.0)
            r["file_size_kb"] = size_kb
            s4_results.append(r)
        self.test_file = filepaths[0]
        return s4_results


# ==============================================================
# Test Dosyası Üreteci
# ==============================================================

def generate_test_files(test_dir: str = None):
    """
    Deney için farklı boyutlarda test dosyaları oluşturur.

    Oluşturulan dosyalar:
        test_10KB.bin   — 10 KB
        test_100KB.bin  — 100 KB
        test_1MB.bin    — 1 MB
        test_10MB.bin   — 10 MB
    """
    if test_dir is None:
        from config import TEST_FILES_DIR
        test_dir = TEST_FILES_DIR

    os.makedirs(test_dir, exist_ok=True)
    sizes = [
        ("test_10KB.bin",  10   * 1024),
        ("test_100KB.bin", 100  * 1024),
        ("test_1MB.bin",   1024 * 1024),
        ("test_10MB.bin",  10 * 1024 * 1024),
    ]
    created = []
    for fname, size in sizes:
        path = os.path.join(test_dir, fname)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(os.urandom(size))
            print(f"[TEST] Oluşturuldu: {fname} ({size//1024} KB)")
        else:
            print(f"[TEST] Zaten mevcut: {fname}")
        created.append(path)
    return created


# ==============================================================
# Ana Giriş
# ==============================================================
if __name__ == "__main__":
    print("Test dosyaları oluşturuluyor...")
    files = generate_test_files()
    print(f"\n{len(files)} dosya hazır.")
    for f in files:
        print(f"  {f} ({os.path.getsize(f)//1024} KB)")
