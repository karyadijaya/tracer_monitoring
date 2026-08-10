# TRACEROUTE MONITOR (NOC Dashboard)

Sistem monitoring jaringan *real-time* berbasis MTR (My Traceroute) yang dirancang khusus untuk operasional NOC. Menyediakan visualisasi jalur jaringan (Hop Topology), tingkat packet loss, latency, dan histori performa jaringan yang terintegrasi dengan InfluxDB.

---

## 🚀 Persyaratan Sistem (Prerequisites)

Sebelum melakukan deployment ke server produksi, pastikan server Anda telah memenuhi persyaratan berikut:

1. **OS Linux** (direkomendasikan Ubuntu/Debian)
2. **Python 3.10+** (direkomendasikan 3.12)
3. **MTR (My Traceroute)**: Paket `mtr` dengan dukungan output JSON (`mtr-tiny` atau `mtr`) wajib terinstal.
4. **InfluxDB v2**: Digunakan untuk menyimpan data *time-series* dari histori kualitas jaringan.

---

## 🛠 Instalasi dan Deployment

### 1. Kloning Repositori
Clone project dari repositori GitHub Anda dan masuk ke direktorinya:
```bash
git clone https://github.com/karyadijaya/tracer_monitoring.git
cd tracer_monitoring
```

### 2. Instalasi Dependensi Sistem (MTR)
Pastikan `mtr` sudah terinstal di server Anda:
```bash
sudo apt update
sudo apt install mtr-tiny -y
```
*(Opsional)*: Berikan *capabilities* agar script Python dapat mengeksekusi `mtr` tanpa harus menggunakan `sudo` (biasanya sudah dikonfigurasi otomatis saat instalasi `mtr-tiny`):
```bash
sudo setcap cap_net_raw=ep /usr/bin/mtr-packet
```

### 3. Setup Virtual Environment (Python)
Buat *virtual environment* untuk mengisolasi instalasi *library* Python:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Instalasi Dependencies Python
Instal seluruh modul yang dibutuhkan. Buat file `requirements.txt` terlebih dahulu jika belum ada, atau jalankan perintah instalasi manual berikut:
```bash
pip install fastapi uvicorn sqlalchemy
```

### 5. Konfigurasi InfluxDB
Sistem membutuhkan *bucket* InfluxDB untuk berjalan dengan normal. Buka file konfigurasi di `backend/config.py` dan pastikan nilainya sesuai dengan server InfluxDB Anda:
```python
INFLUX_URL    = "http://influxsc.nocdm.qzz.io"
INFLUX_TOKEN  = "<TOKEN_INFLUXDB_ANDA>"
INFLUX_ORG    = "NOCSC"
INFLUX_BUCKET = "traceroute_db"
```
*Pastikan bucket `traceroute_db` sudah terbuat di dalam InfluxDB.*

---

## ▶️ Menjalankan Aplikasi

Aplikasi ini menggabungkan FastAPI sebagai API Server dan juga *Background Worker* secara *asynchronous* yang melakukan _polling_ MTR.

### Menjalankan untuk Testing / Development
Anda dapat menjalankannya dengan *Uvicorn*:
```bash
venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 9000
```
Buka browser dan akses ke `http://<IP_SERVER_ANDA>:9000/`.

### Menjalankan di Production (Background Service)
Untuk lingkungan produksi, sangat disarankan menggunakan `systemd` agar aplikasi terus berjalan di *background* dan otomatis menyala ketika server *reboot*.

1. Buat file service baru:
   ```bash
   sudo nano /etc/systemd/system/tracermonitor.service
   ```
2. Isikan konfigurasi berikut *(sesuaikan `/path/to/tracer_monitoring` dengan lokasi folder sebenarnya)*:
   ```ini
   [Unit]
   Description=Traceroute Monitor FastAPI Service
   After=network.target

   [Service]
   User=noc-scm
   WorkingDirectory=/var/project/tracer_monitoring
   ExecStart=/var/project/tracer_monitoring/venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 9000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   *(Catatan: `User=root` mungkin diperlukan jika `mtr` menuntut privilege ICMP socket di server Anda)*
3. Aktifkan dan jalankan service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable tracermonitor
   sudo systemctl start tracermonitor
   ```
4. Cek statusnya dengan:
   ```bash
   sudo systemctl status tracermonitor
   ```

---

## 🏗 Struktur Direktori Utama
* `backend/` : Berisi logika Python (FastAPI, integrasi Database SQLite, InfluxDB, dan `collector.py` untuk eksekusi MTR).
* `static/` : Berisi *frontend* UI (HTML, CSS murni, dan `app.js` menggunakan D3.js untuk render grafik).
* `targets.db` : Database SQLite lokal untuk menyimpan daftar IP target yang dimonitor.
