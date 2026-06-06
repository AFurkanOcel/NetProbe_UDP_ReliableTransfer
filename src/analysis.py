# =============================================================
# analysis.py — NetProbe Performans Analizi & Grafik Üretimi
#
# Görev:
#   1. transfer_log_client.csv + transfer_log_server.csv oku, merge et
#   2. Metrikleri hesapla: throughput, goodput, loss rate,
#      retransmission rate, avg RTT, completion time
#   3. Deney grafikleri üret (matplotlib):
#      - Throughput vs Paket Boyutu
#      - Completion Time vs Timeout Değeri
#      - Retransmission Rate vs Kayıp Oranı
#      - Goodput vs Dosya Boyutu
#      - Stop-and-Wait vs GBN karşılaştırma
#      - UDP vs TCP karşılaştırma
# =============================================================

import os
import sys
import csv
import math
import json
from datetime import datetime

try:
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend — dosyaya kaydetmek için
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np
    HAS_PANDAS = True
    HAS_PYPLOT = True
except ImportError as _imp_err:
    HAS_PANDAS = False
    HAS_PYPLOT = False
    print(f"[UYARI] pandas, matplotlib veya numpy eksik: {_imp_err}")
    print("  'pip install pandas matplotlib numpy' çalıştırın.")

from config import LOG_FILE_CLIENT, LOG_FILE_SERVER, LOG_FILE, RESULTS_DIR


# ==============================================================
# 1. Log Dosyasını Oku (Client + Server merge)
# ==============================================================

def load_log(log_file: str = None) -> "pd.DataFrame":
    """
    CSV log dosyalarını pandas DataFrame'e yükler.
    Client ve Server loglarını birleştirir.

    Args:
        log_file: Opsiyonel tek log dosyası yolu. None ise client+server merge edilir.

    Returns:
        DataFrame: Birleştirilmiş log kayıtları

    Raises:
        ImportError: pandas kurulu değilse
        FileNotFoundError: Hiçbir log dosyası bulunamazsa
        ValueError: Log dosyaları boş veya bozuksa
    """
    if not HAS_PANDAS:
        raise ImportError("pandas kurulu değil.")

    frames = []

    def _safe_read_csv(path):
        """CSV'yi güvenli şekilde oku; boş veya bozuk dosyayı atla."""
        try:
            if os.path.getsize(path) == 0:
                return None
            df = pd.read_csv(path)
            if df.empty or "timestamp" not in df.columns:
                return None
            return df
        except (pd.errors.EmptyDataError, pd.errors.ParserError, KeyError):
            return None

    if log_file and os.path.exists(log_file):
        result = _safe_read_csv(log_file)
        if result is not None:
            frames.append(result)
    else:
        # Client ve server loglarını oku ve merge et
        if os.path.exists(LOG_FILE_CLIENT):
            result = _safe_read_csv(LOG_FILE_CLIENT)
            if result is not None:
                frames.append(result)
        if os.path.exists(LOG_FILE_SERVER):
            result = _safe_read_csv(LOG_FILE_SERVER)
            if result is not None:
                frames.append(result)
        # Eski tek dosya formatını da destekle (fallback)
        if not frames and os.path.exists(LOG_FILE):
            result = _safe_read_csv(LOG_FILE)
            if result is not None:
                frames.append(result)

    if not frames:
        raise FileNotFoundError(
            f"Log dosyası bulunamadı veya boş. Beklenen: {LOG_FILE_CLIENT} veya {LOG_FILE_SERVER}"
        )

    df = pd.concat(frames, ignore_index=True)

    # Timestamp sütunu kontrolü
    if "timestamp" not in df.columns:
        raise ValueError("Log dosyasında 'timestamp' sütunu bulunamadı.")

    # Sayısal olmayan timestamp'leri temizle
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if df.empty:
        raise ValueError("Log dosyasında geçerli kayıt bulunamadı.")

    df = df.sort_values("timestamp").reset_index(drop=True)

    # event_type'tan [CLIENT]/[SERVER] etiketi temizle
    if "event_type" in df.columns:
        df["event_clean"] = df["event_type"].str.replace(r"\[(CLIENT|SERVER)\] ", "", regex=True)
    else:
        df["event_clean"] = ""

    return df


# ==============================================================
# 2. Metrikleri Hesapla
# ==============================================================

def compute_metrics(df: "pd.DataFrame", file_size: int, elapsed_sec: float,
                     packet_size: int) -> dict:
    """
    DataFrame'den tüm performans metriklerini hesaplar.

    Args:
        df          : Log DataFrame'i
        file_size   : Dosya boyutu (byte)
        elapsed_sec : Toplam aktarım süresi (saniye)
        packet_size : Kullanılan paket boyutu (byte)

    Returns:
        dict: Hesaplanmış metrikler
    """
    # Olay sayıları
    sent_count    = len(df[df["event_clean"] == "SENT"])
    ack_count     = len(df[df["event_clean"] == "ACK_RECEIVED"])
    timeout_count = len(df[df["event_clean"] == "TIMEOUT"])
    retry_count   = len(df[df["event_clean"] == "RETRANSMIT"])
    fail_count    = len(df[df["event_clean"] == "FAILED"])

    # RTT (ms) — ACK_RECEIVED satırlarında elapsed_ms var
    rtt_rows = df[(df["event_clean"] == "ACK_RECEIVED") & (df["elapsed_ms"] > 0)]["elapsed_ms"]
    avg_rtt  = rtt_rows.mean() if not rtt_rows.empty else 0.0
    max_rtt  = rtt_rows.max()  if not rtt_rows.empty else 0.0

    # Throughput: toplam gönderilen byte / süre
    total_sent_bytes = sent_count * packet_size
    throughput_bps   = (total_sent_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0

    # Goodput: sadece başarılı payload (ack_count × packet_size) ama en fazla file_size
    good_bytes   = min(ack_count * packet_size, file_size)
    goodput_bps  = (good_bytes * 8) / elapsed_sec if elapsed_sec > 0 else 0

    # Packet loss rate
    loss_rate = (timeout_count / sent_count * 100) if sent_count > 0 else 0.0

    # Retransmission rate
    retry_rate = (retry_count / sent_count * 100) if sent_count > 0 else 0.0

    return {
        "file_size_kb"       : file_size / 1024,
        "packet_size_b"      : packet_size,
        "elapsed_sec"        : elapsed_sec,
        "sent_count"         : sent_count,
        "ack_count"          : ack_count,
        "timeout_count"      : timeout_count,
        "retry_count"        : retry_count,
        "fail_count"         : fail_count,
        "throughput_kbps"    : throughput_bps / 1000,
        "goodput_kbps"       : goodput_bps / 1000,
        "loss_rate_pct"      : loss_rate,
        "retry_rate_pct"     : retry_rate,
        "avg_rtt_ms"         : avg_rtt,
        "max_rtt_ms"         : max_rtt,
    }


def print_metrics(m: dict):
    """Metrikleri ekrana güzel biçimde yazar."""
    print("\n" + "=" * 55)
    print("         PERFORMANS METRİKLERİ ÖZET")
    print("=" * 55)
    print(f"  Dosya boyutu       : {m['file_size_kb']:.1f} KB")
    print(f"  Paket boyutu       : {m['packet_size_b']} B")
    print(f"  Aktarım süresi     : {m['elapsed_sec']:.3f}s")
    print(f"  Throughput         : {m['throughput_kbps']:.1f} kbps")
    print(f"  Goodput            : {m['goodput_kbps']:.1f} kbps")
    print(f"  Packet Loss Rate   : {m['loss_rate_pct']:.1f}%")
    print(f"  Retransmission Rate: {m['retry_rate_pct']:.1f}%")
    print(f"  Ortalama RTT       : {m['avg_rtt_ms']:.1f}ms")
    print(f"  Max RTT            : {m['max_rtt_ms']:.1f}ms")
    print(f"  Başarısız paket    : {m['fail_count']}")
    print("=" * 55)


# ==============================================================
# 3. Grafik Üretimi
# ==============================================================

def _style():
    """Matplotlib stil ayarları."""
    plt.rcParams.update({
        "figure.facecolor": "#1a1a2e",
        "axes.facecolor"  : "#16213e",
        "axes.edgecolor"  : "#e94560",
        "axes.labelcolor" : "#eaeaea",
        "xtick.color"     : "#eaeaea",
        "ytick.color"     : "#eaeaea",
        "text.color"      : "#eaeaea",
        "grid.color"      : "#2a2a4a",
        "grid.linestyle"  : "--",
        "legend.facecolor": "#16213e",
        "legend.edgecolor": "#e94560",
        "font.size"       : 11,
    })


def plot_throughput_vs_packet_size(results: list, save: bool = True, error_bars: dict = None):
    """
    Senaryo 1: Throughput ve Goodput vs Paket Boyutu grafiği.

    Args:
        results    : Her eleman {'packet_size_b', 'throughput_kbps', 'goodput_kbps'} içeren dict
        save       : True ise dosyaya kaydet
        error_bars : {'throughput_std': [...], 'goodput_std': [...]} opsiyonel
    """
    if not HAS_PYPLOT:
        return
    _style()
    sizes      = [r["packet_size_b"]   for r in results]
    throughput = [r["throughput_kbps"] for r in results]
    goodput    = [r["goodput_kbps"]    for r in results]

    fig, ax = plt.subplots(figsize=(9, 5))

    if error_bars and "throughput_std" in error_bars:
        ax.errorbar(sizes, throughput, yerr=error_bars["throughput_std"],
                    fmt="o-", color="#e94560", linewidth=2, markersize=7,
                    capsize=4, label="Throughput")
        ax.errorbar(sizes, goodput, yerr=error_bars["goodput_std"],
                    fmt="s--", color="#0f3460", linewidth=2, markersize=7,
                    capsize=4, label="Goodput", markerfacecolor="#e94560")
    else:
        ax.plot(sizes, throughput, "o-", color="#e94560", linewidth=2, markersize=7, label="Throughput")
        ax.plot(sizes, goodput, "s--", color="#0f3460", linewidth=2, markersize=7, label="Goodput",
                markerfacecolor="#e94560")

    ax.set_xlabel("Paket Boyutu (byte)")
    ax.set_ylabel("Bant Genişliği (kbps)")
    ax.set_title("Senaryo 1: Throughput & Goodput vs Paket Boyutu")
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "s1_throughput_vs_packetsize.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def plot_completion_vs_timeout(results: list, save: bool = True, error_bars: dict = None):
    """
    Senaryo 2: Completion Time & Retransmission vs Timeout Değeri.
    """
    if not HAS_PYPLOT:
        return
    _style()
    timeouts   = [r["timeout_sec"]     for r in results]
    completion = [r["elapsed_sec"]     for r in results]
    retries    = [r["retry_count"]     for r in results]

    fig, ax1 = plt.subplots(figsize=(9, 5))
    color1 = "#e94560"
    ax1.set_xlabel("Timeout Değeri (saniye)")
    ax1.set_ylabel("Tamamlanma Süresi (s)", color=color1)

    if error_bars and "elapsed_std" in error_bars:
        ax1.errorbar(timeouts, completion, yerr=error_bars["elapsed_std"],
                     fmt="o-", color=color1, linewidth=2, markersize=7, capsize=4)
    else:
        ax1.plot(timeouts, completion, "o-", color=color1, linewidth=2, markersize=7)
    ax1.tick_params(axis="y", labelcolor=color1)

    ax2 = ax1.twinx()
    color2 = "#00b4d8"
    ax2.set_ylabel("Retransmission Sayısı", color=color2)

    if error_bars and "retry_std" in error_bars:
        ax2.errorbar(timeouts, retries, yerr=error_bars["retry_std"],
                     fmt="s--", color=color2, linewidth=2, markersize=7, capsize=4)
    else:
        ax2.plot(timeouts, retries, "s--", color=color2, linewidth=2, markersize=7)
    ax2.tick_params(axis="y", labelcolor=color2)

    ax1.set_title("Senaryo 2: Completion Time & Retransmission vs Timeout")
    fig.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "s2_completion_vs_timeout.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def plot_loss_impact(results: list, save: bool = True, error_bars: dict = None):
    """
    Senaryo 3: Goodput & Retransmission Rate vs Kayıp Oranı.
    """
    if not HAS_PYPLOT:
        return
    _style()
    loss_rates  = [r["loss_rate_configured_pct"] for r in results]
    goodputs    = [r["goodput_kbps"]             for r in results]
    retry_rates = [r["retry_rate_pct"]           for r in results]

    fig, ax1 = plt.subplots(figsize=(9, 5))
    color1 = "#06d6a0"
    ax1.set_xlabel("Yapay Kayıp Oranı (%)")
    ax1.set_ylabel("Goodput (kbps)", color=color1)

    if error_bars and "goodput_std" in error_bars:
        ax1.errorbar(loss_rates, goodputs, yerr=error_bars["goodput_std"],
                     fmt="o-", color=color1, linewidth=2, markersize=7, capsize=4)
    else:
        ax1.plot(loss_rates, goodputs, "o-", color=color1, linewidth=2, markersize=7)
    ax1.tick_params(axis="y", labelcolor=color1)

    ax2 = ax1.twinx()
    color2 = "#ef233c"
    ax2.set_ylabel("Retransmission Rate (%)", color=color2)

    if error_bars and "retry_rate_std" in error_bars:
        ax2.errorbar(loss_rates, retry_rates, yerr=error_bars["retry_rate_std"],
                     fmt="D--", color=color2, linewidth=2, markersize=7, capsize=4)
    else:
        ax2.plot(loss_rates, retry_rates, "D--", color=color2, linewidth=2, markersize=7)
    ax2.tick_params(axis="y", labelcolor=color2)

    ax1.set_title("Senaryo 3: Goodput & Retransmission Rate vs Kayıp Oranı")
    fig.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "s3_loss_impact.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def plot_filesize_impact(results: list, save: bool = True, error_bars: dict = None):
    """
    Senaryo 4: Throughput & Goodput vs Dosya Boyutu.
    """
    if not HAS_PYPLOT:
        return
    _style()
    sizes      = [r["file_size_kb"]    for r in results]
    throughput = [r["throughput_kbps"] for r in results]
    goodput    = [r["goodput_kbps"]    for r in results]

    fig, ax = plt.subplots(figsize=(9, 5))

    if error_bars and "throughput_std" in error_bars:
        ax.errorbar(sizes, throughput, yerr=error_bars["throughput_std"],
                    fmt="o-", color="#f72585", linewidth=2, markersize=7,
                    capsize=4, label="Throughput")
        ax.errorbar(sizes, goodput, yerr=error_bars["goodput_std"],
                    fmt="s--", color="#4cc9f0", linewidth=2, markersize=7,
                    capsize=4, label="Goodput")
    else:
        ax.plot(sizes, throughput, "o-", color="#f72585", linewidth=2, markersize=7, label="Throughput")
        ax.plot(sizes, goodput, "s--", color="#4cc9f0", linewidth=2, markersize=7, label="Goodput")

    ax.set_xlabel("Dosya Boyutu (KB)")
    ax.set_ylabel("Bant Genişliği (kbps)")
    ax.set_xscale("log")
    ax.set_title("Senaryo 4: Throughput & Goodput vs Dosya Boyutu")
    ax.legend()
    ax.grid(True, which="both")
    plt.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "s4_filesize_impact.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def plot_saw_vs_gbn(saw_results: list, gbn_results: list, save: bool = True):
    """
    Stop-and-Wait vs Go-Back-N karşılaştırma grafiği.

    Args:
        saw_results : SAW sonuçları (her biri {'file_size_kb', 'throughput_kbps', 'elapsed_sec'})
        gbn_results : GBN sonuçları
    """
    if not HAS_PYPLOT:
        return
    _style()

    sizes_saw = [r["file_size_kb"] for r in saw_results]
    tp_saw    = [r["throughput_kbps"] for r in saw_results]
    sizes_gbn = [r["file_size_kb"] for r in gbn_results]
    tp_gbn    = [r["throughput_kbps"] for r in gbn_results]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(sizes_saw, tp_saw, "o-", color="#e94560", linewidth=2, markersize=7, label="Stop-and-Wait")
    ax.plot(sizes_gbn, tp_gbn, "s--", color="#06d6a0", linewidth=2, markersize=7, label="Go-Back-N")
    ax.set_xlabel("Dosya Boyutu (KB)")
    ax.set_ylabel("Throughput (kbps)")
    ax.set_xscale("log")
    ax.set_title("Stop-and-Wait vs Go-Back-N Karşılaştırması")
    ax.legend()
    ax.grid(True, which="both")
    plt.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "saw_vs_gbn_comparison.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def plot_udp_vs_tcp(udp_results: list, tcp_results: list, save: bool = True):
    """
    UDP-Reliable vs TCP karşılaştırma grafiği.

    Args:
        udp_results : UDP sonuçları (her biri {'file_size_kb', 'throughput_kbps', 'elapsed_sec'})
        tcp_results : TCP sonuçları
    """
    if not HAS_PYPLOT:
        return
    _style()

    sizes_udp = [r["file_size_kb"] for r in udp_results]
    tp_udp    = [r["throughput_kbps"] for r in udp_results]
    sizes_tcp = [r["file_size_kb"] for r in tcp_results]
    tp_tcp    = [r["throughput_kbps"] for r in tcp_results]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Throughput karşılaştırma
    ax1.plot(sizes_udp, tp_udp, "o-", color="#e94560", linewidth=2, markersize=7, label="UDP Reliable")
    ax1.plot(sizes_tcp, tp_tcp, "s--", color="#4cc9f0", linewidth=2, markersize=7, label="TCP")
    ax1.set_xlabel("Dosya Boyutu (KB)")
    ax1.set_ylabel("Throughput (kbps)")
    ax1.set_xscale("log")
    ax1.set_title("Throughput: UDP Reliable vs TCP")
    ax1.legend()
    ax1.grid(True, which="both")

    # Completion time karşılaştırma
    time_udp = [r["elapsed_sec"] for r in udp_results]
    time_tcp = [r["elapsed_sec"] for r in tcp_results]
    ax2.plot(sizes_udp, time_udp, "o-", color="#e94560", linewidth=2, markersize=7, label="UDP Reliable")
    ax2.plot(sizes_tcp, time_tcp, "s--", color="#4cc9f0", linewidth=2, markersize=7, label="TCP")
    ax2.set_xlabel("Dosya Boyutu (KB)")
    ax2.set_ylabel("Tamamlanma Süresi (s)")
    ax2.set_xscale("log")
    ax2.set_title("Completion Time: UDP Reliable vs TCP")
    ax2.legend()
    ax2.grid(True, which="both")

    plt.tight_layout()
    if save:
        path = os.path.join(RESULTS_DIR, "udp_vs_tcp_comparison.png")
        plt.savefig(path, dpi=150)
        print(f"[ANALİZ] Grafik kaydedildi: {path}")
    plt.close()


def save_metrics_json(metrics: dict, label: str = "experiment"):
    """Metrikleri JSON olarak kaydeder (rapor için)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"metrics_{label}_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[ANALİZ] Metrikler kaydedildi: {path}")
    return path


# ==============================================================
# 4. Standalone Analiz
# ==============================================================

def run_all_analysis():
    """
    Mevcut log dosyalarını yükler, metrikleri hesaplar ve grafik üretir.
    Deneylerden bağımsız olarak çalışabilir.
    """
    print("[ANALİZ] Log dosyaları yükleniyor...")
    try:
        df = load_log()
        print(f"[ANALİZ] {len(df)} kayıt yüklendi.")
        print(df["event_type"].value_counts().to_string())

        # Transfer bilgilerini logdan çıkar
        transfer_notes = df[df["event_clean"] == "TRANSFER_COMPLETE"]["notes"]
        if not transfer_notes.empty:
            note = transfer_notes.iloc[-1]
            # Parse: "elapsed=X.XXXs bytes=YYYY sent=ZZ retries=WW"
            parts = str(note).split()
            elapsed_sec = float(parts[0].split("=")[1].rstrip("s")) if len(parts) > 0 else 1.0
            file_size = int(parts[1].split("=")[1]) if len(parts) > 1 else 0

            from config import PACKET_SIZE
            metrics = compute_metrics(df, file_size, elapsed_sec, PACKET_SIZE)
            print_metrics(metrics)
            save_metrics_json(metrics, "standalone")
        else:
            print("[ANALİZ] Transfer tamamlanma kaydı bulunamadı.")

    except FileNotFoundError as e:
        print(f"[HATA] {e}")
        print("Önce bir transfer yapın: python client.py <dosya>")
    except Exception as e:
        print(f"[HATA] Analiz sırasında hata: {e}")


# ==============================================================
# Ana Giriş
# ==============================================================
if __name__ == "__main__":
    run_all_analysis()
