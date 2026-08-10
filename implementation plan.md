# NOC Implementation Plan
**Dynamic MTR Traceroute Monitoring System**

Dokumen ini menguraikan arsitektur dan langkah implementasi teknis untuk membangun sistem monitoring jaringan berbasis **MTR (My Traceroute)**. Sistem ini dirancang secara dinamis, memungkinkan penambahan atau penghapusan IP tujuan tanpa menghentikan layanan. Menjalankan *backend* Python ini pada *server* yang tangguh dengan sistem operasi seperti Ubuntu 24.04 (misalnya pada mesin PowerEdge R620) akan memastikan eksekusi MTR paralel berjalan dengan sangat stabil dan optimal[cite: 1].

---

## 1. Arsitektur Sistem

*   **Data Collector (Backend):** Python mengeksekusi `mtr -j` secara paralel menggunakan *multi-threading* atau *asyncio*[cite: 1]. IP target dibaca secara dinamis (misalnya dari tabel database lokal SQLite atau endpoint API)[cite: 1].
*   **Time-Series Database:** InfluxDB bertugas menyimpan metrik performa (Loss, Avg, Worst, StDev) per *hop* dan per destinasi[cite: 1].
*   **Data Provider (API):** Python (FastAPI/Flask) membaca data dari InfluxDB dan menyajikannya dalam format JSON untuk *frontend*[cite: 1].
*   **Dashboard (Frontend):** Antarmuka web kustom menggunakan Tailwind CSS, Vis.js (Topology), dan Chart.js/D3.js (Grafik) untuk memvisualisasikan data dari API[cite: 1].

---

## 2. Manajemen Target Dinamis

Agar IP destinasi bersifat dinamis (bisa ditambah/dihapus kapan saja tanpa *restart script*), kita akan menggunakan pendekatan **Dynamic Watcher**[cite: 1]. Python akan menyimpan daftar IP dalam *database* lokal (SQLite) atau InfluxDB[cite: 1]. Setiap kali siklus *scanning* dimulai (misal tiap 10 detik), Python melakukan *query* IP target aktif terlebih dahulu[cite: 1].

---

## 3. Desain Skema Database (InfluxDB)

Format data JSON yang dihasilkan oleh `mtr -j` menyediakan parameter lengkap (Loss%, Snt, Last, Avg, Best, Wrst, StDev)[cite: 1]. Struktur *bucket* dan *measurement* pada InfluxDB akan didesain sebagai berikut[cite: 1]:

| Measurement | Tags (Indeks Pencarian) | Fields (Nilai Metrik) |
| :--- | :--- | :--- |
| `mtr_hop_stats` | `target_ip`, `hop_number`, `hop_ip` | `loss_pct`, `avg_rtt`, `worst_rtt`, `stdev_rtt` |
| `mtr_end_to_end` | `target_ip` | `total_hops`, `end_loss_pct`, `end_avg_rtt` |

---

## 4. Implementasi Backend (Python)

Backend akan menggunakan modul `subprocess` untuk memanggil *binary* MTR bawaan Ubuntu[cite: 1]. Proses eksekusi akan dibuat paralel agar tidak ada waktu tunggu (*blocking*) jika ada IP yang RTO[cite: 1].

```python
# Contoh snippet eksekusi MTR & Parsing ke JSON
import subprocess
import json

def run_mtr(ip_address):
    # -r: Report, -j: JSON output, -c 5: Kirim 5 ping per hop
    result = subprocess.run(
        ['mtr', '-r', '-j', '-c', '5', ip_address],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        mtr_data = json.loads(result.stdout)
        # Parse data dan Push ke InfluxDB
        return mtr_data['report']




token influxdb:jWgl3qjk0d18jZYjVx1bTqVluKyhYeqiU42vbFuLLfF4Uc8eVag-vkST0Awssdrisf_qkC7GNxqdCL5lOIyv1A==
bucket : traceroute_db
ORG : NOCSC
