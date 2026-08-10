# ================= KONFIGURASI TERPUSAT =================

# MTR Settings
MTR_MAX_HOPS = 30       # Maksimum hop (-m)
# Catatan: interval & cycles dikontrol di collector.py
#   -c 5  : 5 probes per hop
#   -i 0.3: interval 0.3 detik → ~1.5 detik per full scan

# InfluxDB
INFLUX_URL    = "http://influxsc.nocdm.qzz.io"
INFLUX_TOKEN  = "jWgl3qjk0d18jZYjVx1bTqVluKyhYeqiU42vbFuLLfF4Uc8eVag-vkST0Awssdrisf_qkC7GNxqdCL5lOIyv1A=="
INFLUX_ORG    = "NOCSC"
INFLUX_BUCKET = "traceroute_db"

# Rolling window: simpan maksimum N sampel latency per hop
MAX_SAMPLES = 200

# Flush ke InfluxDB setiap N siklus scan (1 siklus ≈ 1.5 detik)
# N=4 → flush setiap ~6 detik
INFLUX_FLUSH_INTERVAL = 4

# Dummy untuk backward compat (tidak dipakai di collector baru)
MTR_INTERVAL = "0.3"
