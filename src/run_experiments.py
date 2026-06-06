# =============================================================
# run_experiments.py - NetProbe full experiment automation
#
# Runs the complete rubric-aligned experiment set:
#   1. Packet size impact: 256, 512, 1024, 4096 bytes
#   2. Timeout impact: 0.5, 1.0, 2.0, 5.0 seconds
#   3. Loss impact: 0%, 5%, 15%, 30%
#   4. File size impact: 10KB, 100KB, 1MB, 10MB
# plus SAW-vs-GBN and UDP-vs-TCP bonus comparisons.
# =============================================================

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib
import importlib
import json
import os
import socket
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LOG_DIR, RESULTS_DIR, N_REPEATS
from network_sim import ExperimentRunner, generate_test_files
from analysis import (
    plot_completion_vs_timeout,
    plot_filesize_impact,
    plot_loss_impact,
    plot_saw_vs_gbn,
    plot_throughput_vs_packet_size,
    plot_udp_vs_tcp,
)


CONSOLE_LOG = os.path.join(LOG_DIR, "experiment_console.log")


def clean_logs():
    """Remove old CSV logs and the previous experiment console log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    for fname in os.listdir(LOG_DIR):
        if fname.endswith(".csv") or fname == os.path.basename(CONSOLE_LOG):
            os.remove(os.path.join(LOG_DIR, fname))
    print("[EXPERIMENT] Old logs cleared.")


def _allocate_udp_port() -> int:
    """Ask the OS for a currently-free UDP port and put it in config.PORT."""
    import config as cfg

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind((cfg.HOST, 0))
    port = probe.getsockname()[1]
    probe.close()
    cfg.PORT = port
    return port


def _start_server(save_filename: str, gbn: bool = False) -> threading.Thread:
    """Start SAW or GBN server on a fresh port."""
    _allocate_udp_port()
    if gbn:
        import server_gbn
        importlib.reload(server_gbn)
        target = server_gbn.run_server_gbn
    else:
        import server
        importlib.reload(server)
        target = server.run_server

    thread = threading.Thread(
        target=target,
        kwargs={"save_filename": save_filename},
        daemon=True,
    )
    thread.start()
    time.sleep(0.25)
    return thread


def _is_successful_transfer(stats: dict) -> bool:
    return bool(
        stats
        and stats.get("success", True)
        and stats.get("file_size", 0) > 0
        and stats.get("ack_count", 0) == stats.get("total_packets", 0)
        and not stats.get("failed_packets")
        and stats.get("fin_acked", False)
    )


def _append_console_header(label: str):
    with open(CONSOLE_LOG, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"{datetime.now().isoformat(timespec='seconds')} | {label}\n")
        f.write("=" * 72 + "\n")


def _run_quiet(label: str, func):
    """Keep the terminal readable while preserving detailed per-packet output."""
    _append_console_header(label)
    with open(CONSOLE_LOG, "a", encoding="utf-8") as f:
        with contextlib.redirect_stdout(f):
            return func()


def _patch_runner_with_server(runner: ExperimentRunner):
    """Wrap ExperimentRunner transfers so each run gets its own server."""
    original_run_transfer = runner._run_transfer

    def patched_run_transfer(label, **config_overrides):
        save_name = f"exp_{label}.bin"

        def do_transfer():
            import config as cfg

            for key, value in config_overrides.items():
                setattr(cfg, key, value)
            if config_overrides.get("LOSS_RATE", 0) > 0:
                cfg.LOSS_SIMULATION = True
            elif "LOSS_RATE" in config_overrides:
                cfg.LOSS_SIMULATION = False

            server_thread = _start_server(save_name)
            try:
                result = original_run_transfer(label, **config_overrides)
            finally:
                server_thread.join(timeout=120)
                time.sleep(0.15)
            if not _is_successful_transfer(result):
                raise RuntimeError(f"{label} did not complete cleanly: {result}")
            return result

        try:
            print(f"[EXPERIMENT] Running {label} {config_overrides}")
            return _run_quiet(label, do_transfer)
        except Exception as exc:
            print(f"[EXPERIMENT] FAILED {label}: {exc}")
            return {
                "label": label,
                "success": False,
                "error": str(exc),
                **config_overrides,
            }

    runner._run_transfer = patched_run_transfer


def _require_complete_results(name: str, results: list, expected_count: int):
    ok = [r for r in results if r.get("success", True) and r.get("file_size", 0) > 0]
    if len(ok) != expected_count:
        raise RuntimeError(
            f"{name} produced {len(ok)}/{expected_count} valid points. "
            "See data/logs/experiment_console.log and results/graphs/all_experiment_metrics.json."
        )
    return ok


def _error_bars(results: list, mapping: dict) -> dict:
    return {
        output_key: [r.get(input_key, 0.0) for r in results]
        for output_key, input_key in mapping.items()
    }


def _clean_for_json(obj):
    if isinstance(obj, dict):
        return {
            key: _clean_for_json(value)
            for key, value in obj.items()
            if key not in ("rtt_list",)
        }
    if isinstance(obj, list):
        return [_clean_for_json(item) for item in obj]
    if isinstance(obj, bytes):
        return obj.hex()
    return obj


def _run_saw_once(filepath: str, label: str) -> dict:
    import client

    def do_transfer():
        server_thread = _start_server(f"{label}_{os.path.basename(filepath)}")
        importlib.reload(client)
        stats = client.send_file(filepath)
        server_thread.join(timeout=120)
        if not _is_successful_transfer(stats):
            raise RuntimeError(f"{label} SAW transfer failed: {stats}")
        stats["file_size_kb"] = os.path.getsize(filepath) / 1024
        stats["throughput_kbps"] = stats.get("throughput_bps", 0) / 1000
        stats["goodput_kbps"] = stats.get("goodput_bps", 0) / 1000
        return stats

    return _run_quiet(label, do_transfer)


def _run_gbn_once(filepath: str, label: str) -> dict:
    import client_gbn

    def do_transfer():
        server_thread = _start_server(f"{label}_{os.path.basename(filepath)}", gbn=True)
        importlib.reload(client_gbn)
        stats = client_gbn.send_file_gbn(filepath)
        server_thread.join(timeout=120)
        if not (
            stats
            and stats.get("file_size", 0) > 0
            and stats.get("ack_count", 0) == stats.get("total_packets", 0)
            and not stats.get("failed_packets")
            and stats.get("fin_acked", False)
        ):
            raise RuntimeError(f"{label} GBN transfer failed: {stats}")
        return stats

    return _run_quiet(label, do_transfer)


def run_all_experiments():
    print("\n" + "=" * 64)
    print("    NetProbe - Full Rubric Experiment Runner")
    print("=" * 64)

    print("\n[1/7] Preparing test files...")
    file_10kb, file_100kb, file_1mb, file_10mb = generate_test_files()

    print("\n[2/7] Cleaning logs...")
    clean_logs()

    print("\n[3/7] Running four required scenarios...")
    print(f"[EXPERIMENT] Repeats per data point: {N_REPEATS}")

    runner = ExperimentRunner(file_10kb, n_repeats=N_REPEATS)
    _patch_runner_with_server(runner)

    s1_results = runner.scenario1_packet_size(sizes=(256, 512, 1024, 4096))
    s1_results = _require_complete_results("Scenario 1", s1_results, 4)

    s2_results = runner.scenario2_timeout(timeouts=(0.5, 1.0, 2.0, 5.0))
    s2_results = _require_complete_results("Scenario 2", s2_results, 4)

    s3_results = runner.scenario3_loss(loss_rates=(0.0, 0.05, 0.15, 0.30))
    s3_results = _require_complete_results("Scenario 3", s3_results, 4)

    s4_results = runner.scenario4_filesize([file_10kb, file_100kb, file_1mb, file_10mb])
    s4_results = _require_complete_results("Scenario 4", s4_results, 4)

    print("\n[4/7] Running SAW vs GBN bonus comparison...")
    saw_results = []
    gbn_results = []
    for fpath in (file_10kb, file_100kb):
        base = os.path.splitext(os.path.basename(fpath))[0]
        print(f"[EXPERIMENT] Bonus SAW/GBN: {base}")
        saw_results.append(_run_saw_once(fpath, f"saw_{base}"))
        gbn_results.append(_run_gbn_once(fpath, f"gbn_{base}"))

    print("\n[5/7] Running UDP Reliable vs TCP bonus comparison...")
    from tcp_transfer import tcp_transfer_test

    udp_results = saw_results
    tcp_results = []
    for fpath in (file_10kb, file_100kb):
        base = os.path.splitext(os.path.basename(fpath))[0]
        print(f"[EXPERIMENT] Bonus TCP: {base}")
        tcp_stats = _run_quiet(f"tcp_{base}", lambda p=fpath: tcp_transfer_test(p))
        if not tcp_stats or tcp_stats.get("file_size", 0) <= 0:
            raise RuntimeError(f"TCP comparison failed for {fpath}: {tcp_stats}")
        tcp_stats["file_size_kb"] = os.path.getsize(fpath) / 1024
        tcp_results.append(tcp_stats)

    print("\n[6/7] Generating graphs...")
    s1_errors = _error_bars(s1_results, {
        "throughput_std": "throughput_kbps_std",
        "goodput_std": "goodput_kbps_std",
    })
    s2_errors = _error_bars(s2_results, {
        "elapsed_std": "elapsed_sec_std",
        "retry_std": "retry_count_std",
    })
    s3_errors = _error_bars(s3_results, {
        "goodput_std": "goodput_kbps_std",
        "retry_rate_std": "retry_rate_pct_std",
    })
    s4_errors = _error_bars(s4_results, {
        "throughput_std": "throughput_kbps_std",
        "goodput_std": "goodput_kbps_std",
    })

    plot_throughput_vs_packet_size(s1_results, error_bars=s1_errors)
    plot_completion_vs_timeout(s2_results, error_bars=s2_errors)
    plot_loss_impact(s3_results, error_bars=s3_errors)
    plot_filesize_impact(s4_results, error_bars=s4_errors)
    plot_saw_vs_gbn(saw_results, gbn_results)
    plot_udp_vs_tcp(udp_results, tcp_results)

    print("\n[7/7] Saving metrics...")
    all_metrics = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_repeats": N_REPEATS,
            "required_scenarios_complete": True,
            "console_log": CONSOLE_LOG,
        },
        "scenario1_packet_size": s1_results,
        "scenario2_timeout": s2_results,
        "scenario3_loss": s3_results,
        "scenario4_filesize": s4_results,
        "saw_vs_gbn": {"saw": saw_results, "gbn": gbn_results},
        "udp_vs_tcp": {"udp": udp_results, "tcp": tcp_results},
    }

    metrics_path = os.path.join(RESULTS_DIR, "all_experiment_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(_clean_for_json(all_metrics), f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 64)
    print("    EXPERIMENTS COMPLETE")
    print("=" * 64)
    print(f"  Scenario 1 points : {len(s1_results)}")
    print(f"  Scenario 2 points : {len(s2_results)}")
    print(f"  Scenario 3 points : {len(s3_results)}")
    print(f"  Scenario 4 points : {len(s4_results)}")
    print(f"  Graphs            : {RESULTS_DIR}")
    print(f"  Metrics           : {metrics_path}")
    print(f"  Detailed log      : {CONSOLE_LOG}")
    print("=" * 64)


if __name__ == "__main__":
    run_all_experiments()
