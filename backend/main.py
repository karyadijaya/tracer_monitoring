"""
main.py
=======
FastAPI server — menyajikan dashboard HTML dan REST API.
Collector MTR berjalan sebagai background asyncio task.
"""

import asyncio
import os
import urllib.request
import urllib.error
import csv
import json
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.collector import cache, start_all_collectors, update_target_watcher
from backend.config import INFLUX_URL, INFLUX_ORG, INFLUX_BUCKET, INFLUX_TOKEN
from backend.database import get_db, TargetIP

# ─── Inisialisasi App ─────────────────────────────────────────────────────────
app = FastAPI(title="MTR Traceroute Monitor", version="1.0.0")

# Serve static files (CSS, JS)
STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Lifecycle: start collector saat app start ───────────────────────────────
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_all_collectors())
    print("[Server] MTR collectors started.")


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve halaman utama dashboard."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/api/latest")
async def api_latest():
    """
    Kembalikan snapshot data MTR terbaru dari semua target.
    Format: { "target_ip": { hops, status, last_update, is_reached }, ... }
    """
    result = {}
    for ip, data in cache.items():
        hops_list = []
        for hop_num in sorted(data["hops"].keys()):
            h = data["hops"][hop_num]
            hops_list.append({
                "hop":      hop_num,
                "ip":       h.get("ip",       "???"),
                "avg":      round(h.get("avg",      0.0), 3),
                "best":     round(h.get("best",     0.0), 3),
                "worst":    round(h.get("worst",    0.0), 3),
                "last":     round(h.get("last",     0.0), 3),
                "stdev":    round(h.get("stdev",    0.0), 3),
                "loss_pct": round(h.get("loss_pct", 0.0), 1),
            })
        result[ip] = {
            "hops":        hops_list,
            "status":      data["status"],
            "last_update": data["last_update"],
            "is_reached":  data["is_reached"],
        }
    return JSONResponse(content=result)

class TargetCreate(BaseModel):
    ip_address: str
    description: str = ""

@app.get("/api/targets")
async def api_targets(db: Session = Depends(get_db)):
    """Kembalikan daftar IP target dari database beserta namanya."""
    targets = db.query(TargetIP).filter(TargetIP.is_active == True).all()
    result = [{"ip": t.ip_address, "name": t.description} for t in targets]
    return JSONResponse(content={"targets": result})

@app.post("/api/targets")
async def add_target(target: TargetCreate, db: Session = Depends(get_db)):
    """Tambahkan IP target baru."""
    existing = db.query(TargetIP).filter(TargetIP.ip_address == target.ip_address).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.description = target.description
            db.commit()
            update_target_watcher(db)
            return {"status": "ok", "message": "Target reactivated"}
        raise HTTPException(status_code=400, detail="IP already exists")
    
    new_target = TargetIP(ip_address=target.ip_address, description=target.description)
    db.add(new_target)
    db.commit()
    update_target_watcher(db)
    return {"status": "ok", "message": "Target added"}

@app.delete("/api/targets/{ip}")
async def remove_target(ip: str, db: Session = Depends(get_db)):
    """Hapus IP target (soft delete)."""
    target = db.query(TargetIP).filter(TargetIP.ip_address == ip).first()
    if not target:
        raise HTTPException(status_code=404, detail="IP not found")
    
    target.is_active = False
    db.commit()
    update_target_watcher(db)
    return {"status": "ok", "message": "Target removed"}
def _fetch_influx_csv(req):
    with urllib.request.urlopen(req, timeout=10) as response:
        lines = response.read().decode('utf-8').splitlines()
        # Remove empty lines and InfluxDB annotations (#datatype, #group, #default)
        return [line for line in lines if line.strip() and not line.startswith('#')]

@app.get("/api/history")
async def api_history(minutes: int = 30):
    """Ambil riwayat data metrik dari InfluxDB berdasarkan menit."""
    try:
        if minutes <= 30:
            every = "10s"
        elif minutes <= 60:
            every = "30s"
        elif minutes <= 360:
            every = "2m"
        elif minutes <= 720:
            every = "5m"
        else:
            every = "10m"

        query = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r._measurement == "mtr_summary")
          |> filter(fn: (r) => r._field == "end_loss_pct" or r._field == "end_worst_rtt" or r._field == "end_stdev_rtt")
          |> aggregateWindow(every: {every}, fn: mean, createEmpty: false)
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        
        req = urllib.request.Request(
            f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}",
            data=json.dumps({"query": query}).encode('utf-8'),
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/csv",
                "User-Agent": "influxdb-client-python/1.36.0"
            },
            method="POST"
        )
        
        lines = await asyncio.to_thread(_fetch_influx_csv, req)
        
        result = {}
        reader = csv.DictReader(lines)
        for row in reader:
            if not row or '_time' not in row:
                continue
            target_ip = row.get("target_ip")
            if not target_ip:
                continue
            if target_ip not in result:
                result[target_ip] = []
                
            loss = float(row.get("end_loss_pct") or 0)
            worst = float(row.get("end_worst_rtt") or 0)
            stdev = float(row.get("end_stdev_rtt") or 0)
            
            result[target_ip].append({
                "time": row["_time"],
                "loss": round(loss, 1),
                "worst": round(worst, 2),
                "stdev": round(stdev, 2)
            })
            
        return JSONResponse(content=result)
    except urllib.error.HTTPError as he:
        try:
            err_body = he.read().decode('utf-8')
        except Exception:
            err_body = str(he)
        print(f"[History API] HTTP Error {he.code}: {err_body}")
        return JSONResponse(content={"error": f"InfluxDB HTTP {he.code}", "details": err_body}, status_code=500)
    except urllib.error.URLError as ue:
        print(f"[History API] URL Error (Cannot connect to InfluxDB): {ue}")
        return JSONResponse(content={"error": "Cannot connect to InfluxDB", "details": str(ue.reason)}, status_code=500)
    except Exception as e:
        print(f"[History API] Error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/status")
async def api_status():
    """Health check: status koneksi InfluxDB dan status per-target."""
    # Cek InfluxDB
    influx_ok = False
    try:
        req = urllib.request.Request(f"{INFLUX_URL}/ping", method="GET", headers={"User-Agent": "influxdb-client-python/1.36.0"})
        with urllib.request.urlopen(req, timeout=3) as res:
            influx_ok = res.status in (200, 204)
    except Exception:
        influx_ok = False

    db = next(get_db())
    active_targets = db.query(TargetIP).filter(TargetIP.is_active == True).all()
    targets_status = {
        t.ip_address: cache.get(t.ip_address, {}).get("status", "Unknown") for t in active_targets
    }

    return JSONResponse(content={
        "influxdb": "ok" if influx_ok else "error",
        "influxdb_url": INFLUX_URL,
        "targets": targets_status,
    })


@app.get("/metrics")
async def prometheus_metrics():
    """Endpoint Prometheus-format untuk scraping external."""
    from fastapi.responses import PlainTextResponse
    lines = []
    for ip, data in cache.items():
        safe_ip = ip.replace(".", "_")
        hops = data["hops"]
        if hops:
            max_hop = max(hops.keys())
            last_hop = hops[max_hop]
            lines.append(f'mtr_total_hops{{target_ip="{ip}"}} {max_hop}')
            lines.append(f'mtr_reachable{{target_ip="{ip}"}} {1 if data["is_reached"] else 0}')
            lines.append(f'mtr_end_loss_pct{{target_ip="{ip}"}} {last_hop.get("loss_pct", 0.0):.2f}')
            lines.append(f'mtr_end_avg_rtt{{target_ip="{ip}"}} {last_hop.get("avg", 0.0):.3f}')
    return PlainTextResponse("\n".join(lines) + "\n")
