"""
collector.py
============
Menjalankan MTR --report --json secara paralel untuk semua target.
Menggunakan mode report JSON (lebih reliable tanpa TTY di subprocess).
Data di-update setiap siklus scan (~1-2 detik) ke in-memory cache,
lalu di-flush ke InfluxDB setiap INFLUX_FLUSH_INTERVAL siklus.

Command: mtr --report --json --no-dns -c 5 -i 0.3 <ip>
  -r / --report  : satu kali scan lalu keluar (bukan interactive)
  --json         : output JSON terstruktur
  -c 5           : 5 probes per hop
  -i 0.3         : interval 0.3 detik antar probe → total ~1.5 detik/scan
"""

import asyncio
import json
import math
import subprocess
import time
from datetime import datetime, timezone

import urllib.request
import urllib.error

from backend.config import (
    MTR_MAX_HOPS,
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    MAX_SAMPLES, INFLUX_FLUSH_INTERVAL,
)
from backend.database import get_db, TargetIP

# ─── In-memory cache (dibaca oleh FastAPI) ────────────────────────────────────
# cache[target_ip] = {
#   "hops": {
#       1: { "ip", "avg", "best", "worst", "last", "stdev", "loss_pct",
#            "snt", "samples": [ms,...] }
#   },
#   "status": "Scanning" | "Active" | "Error" | "Idle",
#   "last_update": "YYYY-MM-DD HH:MM:SS",
#   "is_reached": bool,
# }
cache: dict = {}
_active_tasks: dict[str, asyncio.Task] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _parse_mtr_json(mtr_output: str, target_ip: str) -> dict | None:
    """
    Parse output JSON dari `mtr --report --json`.
    Return dict hop_num → hop_data, atau None jika gagal.
    """
    try:
        data  = json.loads(mtr_output)
        hubs  = data["report"]["hubs"]
        result: dict[int, dict] = {}

        for hub in hubs:
            hop_num  = hub["count"]               # 1-indexed
            host     = hub.get("host", "???")
            loss_pct = float(hub.get("Loss%", 0.0))
            snt      = int(hub.get("Snt", 0))
            last_ms  = float(hub.get("Last", 0.0))
            avg_ms   = float(hub.get("Avg",  0.0))
            best_ms  = float(hub.get("Best", 0.0))
            wrst_ms  = float(hub.get("Wrst", 0.0))
            stdev    = float(hub.get("StDev", 0.0))

            # Akumulasi samples untuk rolling history
            prev     = cache[target_ip]["hops"].get(hop_num, {})
            samples  = list(prev.get("samples", []))
            if last_ms > 0:
                samples.append(last_ms)
            if len(samples) > MAX_SAMPLES:
                samples = samples[-MAX_SAMPLES:]

            result[hop_num] = {
                "ip":       host,
                "loss_pct": round(loss_pct, 1),
                "snt":      snt,
                "last":     round(last_ms, 3),
                "avg":      round(avg_ms,  3),
                "best":     round(best_ms, 3),
                "worst":    round(wrst_ms, 3),
                "stdev":    round(stdev,   3),
                "samples":  samples,
            }

        return result
    except Exception as e:
        print(f"[Parser] JSON parse error for {target_ip}: {e}")
        return None


def _flush_to_influx(target_ip: str, hops: dict) -> None:
    """Tulis semua hop + summary ke InfluxDB."""
    try:
        lines = []
        now_ns = int(time.time() * 1_000_000_000)
        for hop_num, h in hops.items():
            hop_ip_raw = str(h.get("ip", "???"))
            hop_ip = hop_ip_raw.split()[0].replace(",", "_").replace("=", "_")
            loss = float(h.get("loss_pct", 0.0) or 0.0)
            avg = float(h.get("avg", 0.0) or 0.0)
            best = float(h.get("best", 0.0) or 0.0)
            worst = float(h.get("worst", 0.0) or 0.0)
            last = float(h.get("last", 0.0) or 0.0)
            stdev = float(h.get("stdev", 0.0) or 0.0)
            lines.append(f"mtr_hop_stats,target_ip={target_ip},hop_number={hop_num},hop_ip={hop_ip} loss_pct={loss},avg_rtt={avg},best_rtt={best},worst_rtt={worst},last_rtt={last},stdev_rtt={stdev} {now_ns}")

        if hops:
            max_hop  = max(hops.keys())
            last_hop = hops[max_hop]
            max_worst = max([h.get("worst", 0.0) for h in hops.values()])
            is_reached_str = 't' if cache[target_ip]["is_reached"] else 'f'
            
            end_loss = float(last_hop.get("loss_pct", 0.0) or 0.0)
            end_avg = float(last_hop.get("avg", 0.0) or 0.0)
            end_stdev = float(last_hop.get("stdev", 0.0) or 0.0)
            max_worst = float(max_worst or 0.0)
            
            lines.append(f"mtr_summary,target_ip={target_ip} total_hops={int(max_hop)}i,is_reached={is_reached_str},end_loss_pct={end_loss},end_avg_rtt={end_avg},end_worst_rtt={max_worst},end_stdev_rtt={end_stdev} {now_ns}")

        if not lines:
            return
            
        data = "\\n".join(lines).encode('utf-8')
        req = urllib.request.Request(
            f"{INFLUX_URL}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}&precision=ns",
            data=data,
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}", 
                "Content-Type": "text/plain; charset=utf-8",
                "User-Agent": "influxdb-client-python/1.36.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            pass
    except urllib.error.HTTPError as he:
        err_body = he.read().decode('utf-8', errors='ignore')
        print(f"[InfluxDB] Write error → {target_ip}: HTTP Error {he.code}: {err_body}")
    except Exception as e:
        print(f"[InfluxDB] Write error → {target_ip}: {e}")


# ─── Core collector ───────────────────────────────────────────────────────────
async def run_mtr_loop(target_ip: str) -> None:
    """
    Loop tanpa henti: jalankan `mtr --report --json -c 5 -i 0.3` lalu parse hasilnya.
    Setiap siklus ~1.5 detik → near real-time.
    """
    cycle = 0
    while True:
        cache[target_ip]["status"] = "Scanning"
        try:
            # Jalankan di thread pool agar tidak blocking event loop
            loop   = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                _run_mtr_blocking,
                target_ip,
            )

            if output:
                hops = _parse_mtr_json(output, target_ip)
                if hops:
                    # Cek apakah target tercapai
                    last_hop_data = hops.get(max(hops.keys()), {})
                    is_reached    = last_hop_data.get("ip", "") == target_ip or \
                                    last_hop_data.get("loss_pct", 100) < 100

                    cache[target_ip]["hops"]        = hops
                    cache[target_ip]["is_reached"]  = is_reached
                    cache[target_ip]["status"]      = "Active"
                    cache[target_ip]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[MTR] {target_ip}: {len(hops)} hops, reached={is_reached}")

                    # Flush ke InfluxDB setiap N siklus
                    cycle += 1
                    if cycle >= INFLUX_FLUSH_INTERVAL:
                        cycle = 0
                        loop.run_in_executor(None, _flush_to_influx, target_ip, dict(hops))
                else:
                    cache[target_ip]["status"] = "Error"
            else:
                cache[target_ip]["status"] = "Error"
                print(f"[MTR] {target_ip}: Empty output, retry...")

        except Exception as e:
            cache[target_ip]["status"] = "Error"
            print(f"[MTR] {target_ip}: Exception: {e}")

        # Jeda singkat sebelum siklus berikutnya
        await asyncio.sleep(0.5)


def _run_mtr_blocking(target_ip: str) -> str | None:
    """
    Jalankan MTR synchronously (dipanggil dari thread pool).
    mtr --report --json --no-dns -c 5 -i 0.3 <ip>
    Setiap call ~1.5 detik.
    """
    try:
        result = subprocess.run(
            [
                "mtr",
                "--report",        # mode report: satu scan lalu keluar
                "--json",          # output JSON
                "-b",              # show both IP and hostname if possible (but JSON might only output host)
                "-m", str(MTR_MAX_HOPS),
                "-c", "3",         # 3 probe per hop
                "-i", "1.0",       # minimum interval untuk non-root (1.0 detik)
                target_ip,
            ],
            capture_output=True,
            text=True,
            timeout=30,            # timeout jika target sangat lambat
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        else:
            if result.stderr:
                print(f"[MTR stderr] {target_ip}: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"[MTR] Timeout for {target_ip}")
        return None
    except Exception as e:
        print(f"[MTR] Run error for {target_ip}: {e}")
        return None


async def start_all_collectors() -> None:
    """Jalankan MTR loop untuk semua target aktif saat startup."""
    db = next(get_db())
    update_target_watcher(db)

def update_target_watcher(db) -> None:
    """Sync target IPs dari DB ke running tasks dan cache."""
    active_targets = db.query(TargetIP).filter(TargetIP.is_active == True).all()
    active_ips = {t.ip_address for t in active_targets}

    # Hapus target yang tidak aktif lagi
    for ip in list(_active_tasks.keys()):
        if ip not in active_ips:
            print(f"[MTR Watcher] Stopping MTR for removed target {ip}")
            _active_tasks[ip].cancel()
            del _active_tasks[ip]
            if ip in cache:
                del cache[ip]

    # Tambah target baru
    for ip in active_ips:
        if ip not in _active_tasks:
            print(f"[MTR Watcher] Starting MTR for new target {ip}")
            cache[ip] = {"hops": {}, "status": "Idle", "last_update": "-", "is_reached": False}
            task = asyncio.create_task(run_mtr_loop(ip))
            _active_tasks[ip] = task

