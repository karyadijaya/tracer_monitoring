
import paramiko
import re
import time
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

# ================= KONFIGURASI =================
MK_IP = "10.71.129.150"  # Ganti: IP LAN (ETH1) SRT Encoder
MK_USER = "mfeng"        # Ganti: Username SSH Encoder
MK_PASS = "2u4y&C"     # Ganti: Password SSH Encoder

TARGET_IPS = [
    "202.147.251.4",
    "202.147.251.5",
    "69.46.153.111"
]
# ===============================================

# Menambahkan indikator status "Tracing..." atau "Idle"
metrics_data = {
    ip: {
        "nodes": [], 
        "last_update": "-",
        "is_reached": 0,
        "status": "Idle" 
    } for ip in TARGET_IPS
}

def execute_trace(ssh_client, ip):
    try:
        command = f"tracepath -n -m 20 {ip}"
        stdin, stdout, stderr = ssh_client.exec_command(command, get_pty=True)
        
        # 1. RESET DATA SAAT TRACE BARU DIMULAI
        metrics_data[ip]["status"] = "Tracing..."
        metrics_data[ip]["is_reached"] = 0
        current_pmtu = 1500
        
        metrics_data[ip]["nodes"] = [{
            "hop": 0, "ip": MK_IP, "type": "source", "latency": 0, "pmtu": current_pmtu, "status": "ok"
        }]
        
        # 2. MEMBACA TERMINAL SECARA REAL-TIME (BARIS DEMI BARIS)
        for line in iter(stdout.readline, ""):
            if not line:
                break
                
            line = line.strip()
            
            pmtu_match = re.search(r'pmtu\s+(\d+)', line.lower())
            if pmtu_match:
                current_pmtu = int(pmtu_match.group(1))
                
            match_hop = re.search(r'\b(\d+)\??:\s+(.*)', line)
            if match_hop:
                hop_num = int(match_hop.group(1))
                remainder = match_hop.group(2).strip()
                
                if 'localhost' in remainder.lower() and 'pmtu' in remainder.lower():
                    continue
                    
                if 'no reply' in remainder.lower():
                    node_ip = "no reply"
                    latency = None
                    status = "drop"
                    node_type = "unknown"
                else:
                    parts = remainder.split()
                    node_ip = parts[0]
                    latency = None
                    for p in parts:
                        if 'ms' in p.lower():
                            try:
                                latency = float(p.lower().replace('ms', ''))
                            except:
                                pass
                    status = "ok"
                    node_type = "router"
                    
                    if 'reached' in remainder.lower() or node_ip == ip:
                        node_type = "destination"
                        metrics_data[ip]["is_reached"] = 1

                # Update data secara instan ke memori agar dibaca Frontend
                existing_hop = next((item for item in metrics_data[ip]["nodes"] if item["hop"] == hop_num), None)
                if existing_hop:
                    existing_hop.update({"ip": node_ip, "latency": latency, "status": status, "pmtu": current_pmtu, "type": node_type})
                else:
                    metrics_data[ip]["nodes"].append({
                        "hop": hop_num, "ip": node_ip, "type": node_type, "latency": latency, "pmtu": current_pmtu, "status": status
                    })
                    
        # 3. TRACE SELESAI
        metrics_data[ip]["status"] = "Idle"
        metrics_data[ip]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ip}] Selesai dilacak.")
        
    except Exception as e:
        print(f"[{ip}] Error trace: {e}")
        metrics_data[ip]["status"] = "Error"

def run_remote_trace_worker():
    while True:
        try:
            print(f"\nMencoba koneksi SSH ke Encoder {MK_IP}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(MK_IP, username=MK_USER, password=MK_PASS, timeout=10)
            print("Koneksi SSH Berhasil. Memulai pelacakan rute (Paralel)...\n")
            
            threads = []
            for ip in TARGET_IPS:
                t = threading.Thread(target=execute_trace, args=(ssh, ip))
                t.start()
                threads.append(t)
            
            for t in threads:
                t.join()
                
            ssh.close()
        except Exception as e:
            print(f"Error Koneksi SSH: {e}")
        
        print("\nMenunggu 8 detik...\n")
        time.sleep(8)

# ================= KODE HTML DASHBOARD =================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tracepath Network Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>

    <style>
        body { font-family: 'Inter', sans-serif; background-color: #f3f4f6; }
        #network-topology { width: 100%; height: 100%; border-radius: 0.5rem; background-color: #ffffff; }
        .tooltip { position: absolute; text-align: left; padding: 8px; font: 12px sans-serif; background: rgba(0, 0, 0, 0.8); color: white; border-radius: 4px; pointer-events: none; opacity: 0; transition: opacity 0.2s; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 50; }
        .bar:hover, .dot:hover { opacity: 0.8; cursor: pointer; }
        .chart-container svg { width: 100%; height: 100%; }
        select.target-dropdown { background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3E%3Cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3E%3C/svg%3E"); background-position: right .5rem center; background-repeat: no-repeat; background-size: 1.5em 1.5em; padding-right: 2.5rem; appearance: none; }
    </style>
</head>
<body class="text-gray-800">
    <nav class="bg-indigo-600 shadow-md">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16">
                <div class="flex items-center">
                    <i class="fa-solid fa-route text-white text-2xl mr-3"></i>
                    <span class="font-bold text-xl text-white tracking-tight">Tracepath Analytics</span>
                </div>
                <div class="flex items-center">
                    <span class="text-indigo-100 text-sm bg-indigo-700 px-3 py-1 rounded-full"><i class="fa-solid fa-circle text-green-400 text-xs mr-2 animate-pulse"></i>Live Streaming</span>
                </div>
            </div>
        </div>
    </nav>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div class="mb-6 flex flex-col md:flex-row justify-between items-start md:items-center">
            <div>
                <div class="flex items-center gap-3">
                    <h1 class="text-2xl font-bold text-gray-900">Target:</h1>
                    <select id="target-selector" onchange="changeTarget()" class="target-dropdown bg-white border border-gray-300 text-indigo-600 text-xl font-bold rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 py-1 pl-3 pr-10 shadow-sm cursor-pointer"></select>
                </div>
                <p class="text-sm text-gray-500 mt-2">Last scanned: <span id="scan-time" class="font-mono bg-gray-100 px-2 py-1 rounded">Fetching...</span></p>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-6 flex items-center">
                <div class="p-3 rounded-full bg-blue-100 text-blue-600 mr-4"><i class="fa-solid fa-diagram-project fa-fw text-xl"></i></div>
                <div><p class="text-sm font-medium text-gray-500 mb-1">Total Hops</p><p class="text-2xl font-bold text-gray-900" id="stat-hops">--</p></div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-6 flex items-center">
                <div class="p-3 rounded-full bg-orange-100 text-orange-600 mr-4"><i class="fa-solid fa-stopwatch fa-fw text-xl"></i></div>
                <div><p class="text-sm font-medium text-gray-500 mb-1">Avg Latency</p><p class="text-2xl font-bold text-gray-900"><span id="stat-latency">--</span> <span class="text-sm font-normal text-gray-500">ms</span></p></div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-6 flex items-center">
                <div class="p-3 rounded-full bg-purple-100 text-purple-600 mr-4"><i class="fa-solid fa-truck-fast fa-fw text-xl"></i></div>
                <div><p class="text-sm font-medium text-gray-500 mb-1">Minimum PMTU</p><p class="text-2xl font-bold text-gray-900"><span id="stat-mtu">--</span> <span class="text-sm font-normal text-gray-500">bytes</span></p></div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-6 flex items-center">
                <div class="p-3 rounded-full bg-gray-100 text-gray-600 mr-4 transition-colors duration-300" id="status-icon-bg"><i class="fa-solid fa-circle-notch fa-fw text-xl" id="status-icon"></i></div>
                <div><p class="text-sm font-medium text-gray-500 mb-1">Target Status</p><p class="text-xl font-bold text-gray-600 transition-colors duration-300" id="stat-status">Checking...</p></div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-2 bg-white rounded-lg shadow-sm border border-gray-100 p-1 flex flex-col h-[500px]">
                <div class="px-5 py-4 border-b border-gray-100 flex justify-between items-center">
                    <h2 class="text-lg font-semibold text-gray-800"><i class="fa-solid fa-network-wired text-indigo-500 mr-2"></i>Network Path Topology</h2>
                </div>
                <div class="flex-grow p-2"><div id="network-topology"></div></div>
            </div>

            <div class="lg:col-span-1 flex flex-col gap-6">
                <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-1 h-[238px] flex flex-col">
                    <div class="px-4 py-3 border-b border-gray-100"><h2 class="text-sm font-semibold text-gray-800"><i class="fa-solid fa-chart-line text-orange-500 mr-2"></i>Latency per Hop (ms)</h2></div>
                    <div class="flex-grow p-2 relative chart-container" id="latency-chart"></div>
                </div>
                <div class="bg-white rounded-lg shadow-sm border border-gray-100 p-1 h-[238px] flex flex-col">
                    <div class="px-4 py-3 border-b border-gray-100"><h2 class="text-sm font-semibold text-gray-800"><i class="fa-solid fa-chart-bar text-purple-500 mr-2"></i>Path MTU Drop-off</h2></div>
                    <div class="flex-grow p-2 relative chart-container" id="mtu-chart"></div>
                </div>
            </div>
        </div>

        <div class="mt-8 bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden">
             <div class="px-5 py-4 border-b border-gray-100"><h2 class="text-lg font-semibold text-gray-800">Raw Tracepath Data</h2></div>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Hop</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP / Hostname</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency (ms)</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">PMTU</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200" id="raw-data-table"></tbody>
                </table>
            </div>
        </div>
    </main>

    <div id="d3-tooltip" class="tooltip"></div>

    <script>
        let dbTracepathData = {};
        let currentTarget = '';
        let visNetworkInstance = null; // Menyimpan state topologi agar tidak mereset posisi

        document.addEventListener('DOMContentLoaded', () => {
            fetchTraceData();
            // Polling dipercepat jadi 2 detik untuk efek REAL-TIME
            setInterval(fetchTraceData, 2000); 
        });

        async function fetchTraceData() {
            try {
                const response = await fetch('/api/data');
                dbTracepathData = await response.json();
                
                const selector = document.getElementById('target-selector');
                if (selector.options.length === 0) {
                    for (const ip in dbTracepathData) {
                        const opt = document.createElement('option');
                        opt.value = ip; opt.textContent = ip;
                        selector.appendChild(opt);
                    }
                    currentTarget = selector.value;
                }
                
                renderDashboard();
                if(dbTracepathData[currentTarget].last_update !== "-") {
                    document.getElementById('scan-time').textContent = dbTracepathData[currentTarget].last_update;
                }
            } catch (error) {
                console.error("Failed to fetch data", error);
            }
        }

        function changeTarget() {
            currentTarget = document.getElementById('target-selector').value;
            renderDashboard();
        }

        function renderDashboard() {
            if(!dbTracepathData[currentTarget] || dbTracepathData[currentTarget].nodes.length === 0) return;
            const data = dbTracepathData[currentTarget].nodes;
            const isReached = dbTracepathData[currentTarget].is_reached === 1;
            const backendStatus = dbTracepathData[currentTarget].status;
            
            updateSummaryCards(data, isReached, backendStatus);
            drawNetworkTopology(data);
            drawLatencyChart(data);
            drawMtuChart(data);
            populateTable(data);
        }

        function updateSummaryCards(data, isReached, backendStatus) {
            const hopsCount = data[data.length-1].hop;
            const validLatencies = data.filter(d => d.hop > 0 && d.latency !== null).map(d => d.latency);
            const avgLatency = validLatencies.length > 0 ? (validLatencies.reduce((a, b) => a + b, 0) / validLatencies.length) : 0;
            const minMtu = Math.min(...data.map(d => d.pmtu));
            
            document.getElementById('stat-hops').textContent = hopsCount;
            document.getElementById('stat-latency').textContent = avgLatency > 0 ? avgLatency.toFixed(2) : '--';
            document.getElementById('stat-mtu').textContent = minMtu;
            
            const statusEl = document.getElementById('stat-status');
            const statusIconBg = document.getElementById('status-icon-bg');
            const statusIcon = document.getElementById('status-icon');

            // Deteksi jika Backend sedang melacak (Real-Time Loading)
            if (backendStatus === 'Tracing...') {
                statusEl.textContent = 'Tracing...';
                statusEl.className = 'text-xl font-bold text-blue-600';
                statusIconBg.className = 'p-3 rounded-full bg-blue-100 text-blue-600 mr-4';
                statusIcon.className = 'fa-solid fa-circle-notch fa-spin fa-fw text-xl'; // Icon berputar
            } 
            else if (isReached) {
                statusEl.textContent = 'Reached';
                statusEl.className = 'text-xl font-bold text-green-600';
                statusIconBg.className = 'p-3 rounded-full bg-green-100 text-green-600 mr-4';
                statusIcon.className = 'fa-solid fa-check fa-fw text-xl';
            } 
            else {
                statusEl.textContent = 'Unreachable (RTO)';
                statusEl.className = 'text-xl font-bold text-red-600';
                statusIconBg.className = 'p-3 rounded-full bg-red-100 text-red-600 mr-4';
                statusIcon.className = 'fa-solid fa-xmark fa-fw text-xl';
            }
        }

        function drawNetworkTopology(data) {
            const container = document.getElementById('network-topology');
            const nodes = data.map((d) => {
                let iconCode = '\uf233'; let color = '#4F46E5';
                if (d.type === 'source') { iconCode = '\uf108'; color = '#10B981'; } 
                else if (d.type === 'destination') { iconCode = '\uf0ac'; color = '#10B981'; } 
                else if (d.status === 'drop') { iconCode = '\uf071'; color = '#EF4444'; } 
                else if (d.type === 'router') { iconCode = '\uf233'; color = '#6366F1'; }

                return {
                    id: d.hop, label: `Hop ${d.hop}\\n${d.ip}`,
                    title: `Latency: ${d.latency !== null ? d.latency : 'Timeout'} ms<br>PMTU: ${d.pmtu}`,
                    shape: 'icon', font: { size: 12, multi: true },
                    icon: { face: '"Font Awesome 6 Free"', code: iconCode, size: 40, color: color, weight: 900 }
                };
            });

            const edges = [];
            for (let i = 0; i < data.length - 1; i++) {
                let edgeColor = '#9CA3AF'; let dashes = false;
                if (data[i+1].status === 'drop' || data[i].status === 'drop') { edgeColor = '#EF4444'; dashes = true; }
                edges.push({
                    from: data[i].hop, to: data[i+1].hop, arrows: 'to', dashes: dashes, color: { color: edgeColor },
                    label: data[i+1].pmtu < data[i].pmtu ? `MTU↓ ${data[i+1].pmtu}` : '',
                    font: { align: 'top', color: '#8B5CF6', size: 10, background: 'rgba(255,255,255,0.7)' }
                });
            }

            const graphData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };

            // Hanya UPDATE data jika Network sudah ada (Mencegah Zoom ter-reset saat hop baru muncul)
            if (!visNetworkInstance) {
                visNetworkInstance = new vis.Network(container, graphData, {
                    layout: { hierarchical: { direction: 'LR', sortMethod: 'directed', nodeSpacing: 150, levelSeparation: 150 } },
                    interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true }, physics: false
                });
            } else {
                visNetworkInstance.setData(graphData);
            }
        }

        // Animasi Chart dimatikan agar saat data masuk per detik, pergerakannya instan & tidak kedap-kedip
        function drawLatencyChart(data) {
            const container = d3.select("#latency-chart"); container.selectAll("*").remove();
            const rect = container.node().getBoundingClientRect();
            const margin = {top: 10, right: 20, bottom: 30, left: 40}, width = rect.width - margin.left - margin.right, height = rect.height - margin.top - margin.bottom;
            const svg = container.append("svg").attr("viewBox", `0 0 ${width + margin.left + margin.right} ${height + margin.top + margin.bottom}`).append("g").attr("transform", `translate(${margin.left},${margin.top})`);
            const tooltip = d3.select("#d3-tooltip");
            const lineData = data.filter(d => d.latency !== null);
            if(lineData.length === 0) return;

            const x = d3.scaleLinear().domain(d3.extent(lineData, d => d.hop)).range([0, width]);
            const y = d3.scaleLinear().domain([0, d3.max(lineData, d => d.latency) * 1.2]).range([height, 0]);

            svg.append("g").attr("transform", `translate(0,${height})`).call(d3.axisBottom(x).ticks(lineData.length).tickFormat(d => `H${d}`)).attr("color", "#9CA3AF");
            svg.append("g").call(d3.axisLeft(y).ticks(5)).attr("color", "#9CA3AF");

            svg.append("path").data([lineData]).attr("fill", "none").attr("stroke", "#F97316").attr("stroke-width", 2)
               .attr("d", d3.line().x(d => x(d.hop)).y(d => y(d.latency)).curve(d3.curveMonotoneX));

            svg.selectAll(".dot").data(lineData).enter().append("circle").attr("cx", d => x(d.hop)).attr("cy", d => y(d.latency))
               .attr("r", 4).attr("fill", "#F97316").attr("stroke", "#fff").attr("stroke-width", 1.5)
               .on("mouseover", function(event, d) { d3.select(this).attr("r", 6); tooltip.style("opacity", .9).html(`Hop: ${d.hop}<br/>IP: ${d.ip}<br/>Latency: <b>${d.latency} ms</b>`).style("left", (event.pageX + 10) + "px").style("top", (event.pageY - 28) + "px"); })
               .on("mouseout", function() { d3.select(this).attr("r", 4); tooltip.style("opacity", 0); });
        }

        function drawMtuChart(data) {
            const container = d3.select("#mtu-chart"); container.selectAll("*").remove();
            const rect = container.node().getBoundingClientRect();
            const margin = {top: 10, right: 10, bottom: 30, left: 40}, width = rect.width - margin.left - margin.right, height = rect.height - margin.top - margin.bottom;
            const svg = container.append("svg").attr("viewBox", `0 0 ${width + margin.left + margin.right} ${height + margin.top + margin.bottom}`).append("g").attr("transform", `translate(${margin.left},${margin.top})`);
            const tooltip = d3.select("#d3-tooltip");

            const x = d3.scaleBand().domain(data.map(d => `H${d.hop}`)).range([0, width]).padding(0.2);
            const minMtu = d3.min(data, d => d.pmtu);
            const y = d3.scaleLinear().domain([Math.max(0, minMtu - 50), 1520]).range([height, 0]);

            svg.append("g").attr("transform", `translate(0,${height})`).call(d3.axisBottom(x)).attr("color", "#9CA3AF");
            svg.append("g").call(d3.axisLeft(y).ticks(4)).attr("color", "#9CA3AF");

            svg.selectAll(".bar").data(data).enter().append("rect").attr("x", d => x(`H${d.hop}`)).attr("width", x.bandwidth()).attr("y", d => y(d.pmtu)).attr("height", d => height - y(d.pmtu))
               .attr("fill", d => d.pmtu < 1500 ? "#EF4444" : "#8B5CF6").attr("rx", 2)
               .on("mouseover", function(event, d) { d3.select(this).attr("fill", "#6D28D9"); tooltip.style("opacity", .9).html(`Hop: ${d.hop}<br/>IP: ${d.ip}<br/>PMTU: <b>${d.pmtu} bytes</b>`).style("left", (event.pageX + 10) + "px").style("top", (event.pageY - 28) + "px"); })
               .on("mouseout", function(event, d) { d3.select(this).attr("fill", d.pmtu < 1500 ? "#EF4444" : "#8B5CF6"); tooltip.style("opacity", 0); });
        }

        function populateTable(data) {
            const tbody = document.getElementById('raw-data-table'); tbody.innerHTML = '';
            data.forEach((row, i) => {
                let statusBadge = row.status === 'drop' ? `<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800">Dropped</span>` : `<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">OK</span>`;
                let mtuDisplay = row.pmtu;
                if(i > 0 && data[i-1].pmtu > row.pmtu) mtuDisplay = `<span class="text-red-500 font-bold"><i class="fa-solid fa-arrow-down text-xs mr-1"></i>${row.pmtu}</span>`;
                tbody.innerHTML += `<tr><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.hop}</td><td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${row.ip}</td><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.latency !== null ? row.latency.toFixed(3) : '-'}</td><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${mtuDisplay}</td><td class="px-6 py-4 whitespace-nowrap">${statusBadge}</td></tr>`;
            });
        }
    </script>
</body>
</html>
"""

# ================= WEB SERVER =================
class ExporterAndDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/data':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(metrics_data).encode('utf-8'))
            
        elif self.path == '/metrics':
            self.send_response(200)
            self.send_header("Content-type", "text/plain; version=0.0.4")
            self.end_headers()
            response = ""
            for ip, data in metrics_data.items():
                if data["nodes"]:
                    hops = data["nodes"][-1]["hop"]
                    response += f'encoder_trace_hops{{target_ip="{ip}"}} {hops}\n'
                    response += f'encoder_trace_reachable{{target_ip="{ip}"}} {data["is_reached"]}\n'
            self.wfile.write(response.encode('utf-8'))
            
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    PORT = 5000
    threading.Thread(target=run_remote_trace_worker, daemon=True).start()
    server = HTTPServer(('0.0.0.0', PORT), ExporterAndDashboardHandler)
    print(f"=== Backend & Dashboard Berjalan di Port {PORT} ===")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMematikan sistem...")
        server.server_close()
