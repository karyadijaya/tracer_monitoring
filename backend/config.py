import os
from pathlib import Path

# ================= KONFIGURASI TERPUSAT =================

# Parse .env if it exists (Dependency-free approach)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# MTR Settings
MTR_MAX_HOPS = 30       # Maksimum hop (-m)
# Catatan: interval & cycles dikontrol di collector.py
#   -c 5  : 5 probes per hop
#   -i 0.3: interval 0.3 detik → ~1.5 detik per full scan

# InfluxDB (Loaded from .env)
INFLUX_URL    = os.environ.get("INFLUX_URL", "")
INFLUX_TOKEN  = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG    = os.environ.get("INFLUX_ORG", "")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "")

# Rolling window: simpan maksimum N sampel latency per hop
MAX_SAMPLES = 200

# Flush ke InfluxDB setiap N siklus scan (1 siklus ≈ 1.5 detik)
# N=4 → flush setiap ~6 detik
INFLUX_FLUSH_INTERVAL = 4

# Dummy untuk backward compat (tidak dipakai di collector baru)
MTR_INTERVAL = "0.3"
