/* ============================================================
   app.js — Unified MTR Network Monitor Dashboard
   ============================================================ */

const POLL_INTERVAL_MS = 3000;
let allData = {};
let targetList = [];
let metricsHistory = {};
const MAX_HISTORY_POINTS = 20;
let hiddenTargets = new Set();

// ── COLOR PALETTE FOR TARGETS ──
const TARGET_COLORS = ['#4F8EF7', '#F59E0B', '#10B981', '#E879F9', '#F43F5E', '#06B6D4'];

function getColor(index) {
    return TARGET_COLORS[index % TARGET_COLORS.length];
}

// ── CLOCK ──
function updateClock() {
    const el = document.getElementById('navbar-time');
    if (el) el.textContent = new Date().toLocaleTimeString('en-GB');
}
setInterval(updateClock, 1000);
updateClock();

// ── FETCH DATA ──
async function fetchTargets() {
    try {
        const res = await fetch('/api/targets');
        const data = await res.json();
        targetList = data.targets || [];
        renderTargetList();
    } catch (e) {
        console.warn('Failed to fetch targets:', e);
    }
}

let currentMinutes = 30;

async function fetchAndRender() {
    try {
        const res = await fetch('/api/latest');
        allData = await res.json();
        
        const ips = Object.keys(allData);
        if (!ips.length) return;
        
        drawUnifiedTopology(ips);
        drawHopsChart(ips);
        populateSummaryTable(ips);
    } catch (e) {
        console.warn('[MTR] Fetch error:', e);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch(`/api/history?minutes=${currentMinutes}`);
        metricsHistory = await res.json();
        const ips = Object.keys(allData);
        if (!ips.length) return;
        
        ips.forEach(ip => {
            if (metricsHistory[ip]) {
                metricsHistory[ip].forEach(d => {
                    d.time = new Date(d.time);
                });
            }
        });

        drawLossChart(ips);
        drawLatencyChart(ips);
        drawStdevChart(ips);
    } catch (e) {
        console.warn('[MTR History] Fetch error:', e);
    }
}

window.onTimeRangeChange = function() {
    const sel = document.getElementById('time-range');
    currentMinutes = parseInt(sel.value, 10) || 30;
    fetchHistory();
};

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const pill = document.getElementById('influx-status');
        if (pill) {
            if (data.influxdb === 'ok') {
                pill.className = 'status-pill influx-ok';
                pill.querySelector('.status-text').textContent = 'InfluxDB ✓';
            } else {
                pill.className = 'status-pill influx-err';
                pill.querySelector('.status-text').textContent = 'InfluxDB ✗';
            }
        }
    } catch (_) {}
}

// ── TARGET MANAGEMENT ──
function getTargetName(ip) {
    const t = targetList.find(x => x.ip === ip);
    if (t && t.name) return t.name;
    return ip;
}

function renderTargetList() {
    const container = document.getElementById('target-list');
    container.innerHTML = '';
    targetList.forEach((t, idx) => {
        const color = getColor(idx);
        const displayName = t.name ? `${t.name} (${t.ip})` : t.ip;
        container.insertAdjacentHTML('beforeend', `
            <div class="target-chip" style="border-color:${color}">
                <span class="status-dot" style="background:${color}"></span>
                ${displayName}
                <button class="btn-danger-sm" onclick="removeTarget('${t.ip}')" title="Remove" style="margin-left:4px">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `);
    });
}

window.addTarget = async function addTarget() {
    const inputIp = document.getElementById('new-target-ip');
    const inputName = document.getElementById('new-target-name');
    const ip = inputIp.value.trim();
    const name = inputName ? inputName.value.trim() : '';
    
    if (!ip) return;
    try {
        const res = await fetch('/api/targets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip_address: ip, description: name })
        });
        if (res.ok) {
            inputIp.value = '';
            if (inputName) inputName.value = '';
            fetchTargets();
        } else {
            alert('Failed to add target');
        }
    } catch (e) {
        alert('Error adding target');
    }
};

window.removeTarget = async function removeTarget(ip) {
    if (!confirm(`Hapus target ${ip}?`)) return;
    try {
        const res = await fetch(`/api/targets/${ip}`, { method: 'DELETE' });
        if (res.ok) {
            fetchTargets();
        } else {
            alert('Failed to remove target');
        }
    } catch (e) {
        alert('Error removing target');
    }
};

// Unified dashboard logic is now split between fetchAndRender (live) and fetchHistory (time series)

// ── TOPOLOGY (Tree Structure) ──
function drawUnifiedTopology(ips) {
    const wrap = document.getElementById('network-topology');
    d3.select(wrap).selectAll('*').remove();
    
    // Build a simple tree by merging hops with the same IP and Hop number
    const root = { id: 'localhost', hop: 0, children: [], ip: 'localhost' };
    const nodeMap = { '0_localhost': root };

    ips.forEach((targetIp, targetIdx) => {
        const hops = allData[targetIp]?.hops || [];
        let parentId = '0_localhost';
        
        hops.forEach(h => {
            const nodeId = `${h.hop}_${h.ip}`;
            if (!nodeMap[nodeId]) {
                const newNode = {
                    id: nodeId,
                    hop: h.hop,
                    ip: h.ip,
                    loss_pct: h.loss_pct,
                    avg: h.avg,
                    best: h.best,
                    worst: h.worst,
                    stdev: h.stdev,
                    is_target: h.ip === targetIp,
                    targets: [targetIdx],
                    children: []
                };
                nodeMap[nodeId] = newNode;
                nodeMap[parentId].children.push(newNode);
            } else {
                if (!nodeMap[nodeId].targets.includes(targetIdx)) {
                    nodeMap[nodeId].targets.push(targetIdx);
                }
            }
            parentId = nodeId;
        });
    });

    const rect = wrap.getBoundingClientRect();
    const W = rect.width || 800;
    const H = rect.height || 460;
    const margin = { top: 40, right: 120, bottom: 40, left: 120 };

    const svg = d3.select(wrap).append('svg')
        .attr('width', W).attr('height', H)
        .call(d3.zoom().on("zoom", (e) => svg.select("g").attr("transform", e.transform)))
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const treeLayout = d3.tree().size([H - margin.top - margin.bottom, W - margin.left - margin.right]);
    const hierarchy = d3.hierarchy(root);
    const treeData = treeLayout(hierarchy);

    const nodes = treeData.descendants();
    const links = treeData.links();

    // Links
    svg.selectAll('.link')
        .data(links)
        .enter().append('path')
        .attr('class', 'link')
        .attr('fill', 'none')
        .attr('stroke', d => d.target.data.loss_pct > 10 ? '#EF4444' : d.target.data.loss_pct > 0 ? '#F59E0B' : '#10B981')
        .attr('stroke-width', 2)
        .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x));

    // Nodes
    const node = svg.selectAll('.node')
        .data(nodes)
        .enter().append('g')
        .attr('class', 'node')
        .attr('transform', d => `translate(${d.y},${d.x})`);

    node.append('circle')
        .attr('r', d => d.data.is_target ? 12 : 8)
        .attr('fill', d => d.data.ip === 'no reply' ? '#F3F4F6' : '#FFFFFF')
        .attr('stroke', d => {
            if (d.data.is_target) return getColor(d.data.targets[0]);
            if (d.data.loss_pct > 10) return '#EF4444';
            if (d.data.loss_pct > 0) return '#F59E0B';
            return '#10B981';
        })
        .attr('stroke-width', 2.5);

    node.append('text')
        .attr('dy', -14)
        .attr('text-anchor', 'middle')
        .attr('font-size', '10px')
        .attr('font-weight', '500')
        .attr('fill', '#374151')
        .text(d => {
            if (d.data.ip === 'localhost') return 'Source';
            if (d.data.is_target) return getTargetName(d.data.ip);
            return d.data.ip !== 'no reply' ? `Hop ${d.data.hop}` : `Hop ${d.data.hop} (Timeout)`;
        });

    // Tooltip implementation
    const tooltip = document.getElementById('d3-tooltip');
    node.on('mouseover', (event, d) => {
            if (d.data.ip === 'localhost') return;
            tooltip.style.opacity = '1';
            const color = (d.data.loss_pct > 10) ? '#EF4444' : (d.data.loss_pct > 0) ? '#F59E0B' : '#10B981';
            tooltip.innerHTML = `
                <b>Hop ${d.data.hop}</b><br>
                Host/IP: ${d.data.ip}<br>
                Loss: <b style="color:${color}">${d.data.loss_pct}%</b><br>
                Avg: ${d.data.avg} ms &nbsp; Best: ${d.data.best || d.data.avg} ms<br>
                Worst: ${d.data.worst || d.data.avg} ms &nbsp; StDev: ${d.data.stdev || 0}
            `;
            tooltip.style.left = (event.clientX + 12) + 'px';
            tooltip.style.top  = (event.clientY - 10) + 'px';
        })
        .on('mousemove', event => {
            tooltip.style.left = (event.clientX + 12) + 'px';
            tooltip.style.top  = (event.clientY - 10) + 'px';
        })
        .on('mouseout', () => { document.getElementById('d3-tooltip').style.opacity = '0'; });
}

// ── CHARTS (D3 Multi-Bar/Line) ──
function getChartBase(containerId, marginOverride = null) {
    const wrap = document.getElementById(containerId);
    d3.select(wrap).selectAll('*').remove();
    const rect = wrap.getBoundingClientRect();
    const m = marginOverride || { top: 15, right: 15, bottom: 45, left: 40 };
    const width = rect.width - m.left - m.right;
    const height = rect.height - m.top - m.bottom;
    
    const svg = d3.select(wrap).append('svg')
        .attr('viewBox', `0 0 ${width + m.left + m.right} ${height + m.top + m.bottom}`)
        .append('g').attr('transform', `translate(${m.left},${m.top})`);
        
    return { svg, width, height };
}

function drawChartLegend(svg, width, height, ips) {
    const legendG = svg.append('g')
        .attr('transform', `translate(0, ${height + 32})`);
    
    let xOffset = 0;
    ips.forEach((ip, i) => {
        const color = getColor(i);
        const name = getTargetName(ip);
        const isHidden = hiddenTargets.has(ip);
        
        const g = legendG.append('g')
            .attr('transform', `translate(${xOffset}, 0)`)
            .style('cursor', 'pointer')
            .style('opacity', isHidden ? 0.4 : 1)
            .on('click', () => {
                if (isHidden) hiddenTargets.delete(ip);
                else hiddenTargets.add(ip);
                
                const allIps = Object.keys(allData);
                drawHopsChart(allIps);
                drawLossChart(allIps);
                drawLatencyChart(allIps);
                drawStdevChart(allIps);
            });
            
        g.append('rect').attr('width', 10).attr('height', 10).attr('rx', 2).attr('fill', color);
        const text = g.append('text').attr('x', 14).attr('y', 9).attr('font-size', '10px').attr('font-weight', '500').attr('fill', '#374151').text(name);
        
        try {
            xOffset += text.node().getComputedTextLength() + 25;
        } catch(e) {
            xOffset += (name.length * 6) + 25;
        }
    });
}

function drawHopsChart(ips) {
    const { svg, width, height } = getChartBase('hops-chart', { top: 20, right: 20, bottom: 45, left: 10 });
    const data = ips.map((ip, i) => {
        const hops = allData[ip].hops || [];
        return { ip, hops: hops.length, color: getColor(i) };
    });

    const activeData = data.filter(d => !hiddenTargets.has(d.ip));

    const innerHeight = Math.min(height, Math.max(1, activeData.length) * 55);
    const y = d3.scaleBand().domain(activeData.map(d => d.ip)).range([0, innerHeight]).padding(0.4);
    const x = d3.scaleLinear().domain([0, d3.max(activeData, d => d.hops) || 10]).range([0, width]);
    
    // Draw subtle Y-axis line without labels
    svg.append('g').call(d3.axisLeft(y).tickSize(0).tickFormat('')).select('.domain').attr('stroke', 'rgba(255,255,255,0.04)');

    const bars = svg.selectAll('.bar').data(activeData).enter().append('g');
    
    // IP label above the bar
    bars.append('text')
        .attr('y', d => y(d.ip) - 4)
        .attr('x', 0)
        .attr('fill', '#374151')
        .attr('font-size', '10px')
        .attr('font-family', 'JetBrains Mono, monospace')
        .text(d => getTargetName(d.ip));

    // The bar
    bars.append('rect')
        .attr('y', d => y(d.ip)).attr('height', y.bandwidth())
        .attr('x', 0).attr('width', d => x(d.hops))
        .attr('fill', d => d.color).attr('rx', 3)
        .on('mouseover', (event, d) => {
            const tooltip = document.getElementById('d3-tooltip');
            tooltip.style.opacity = '1';
            tooltip.innerHTML = `<b>Target: ${getTargetName(d.ip)}</b><br>Total Hops: ${d.hops}`;
            tooltip.style.left = (event.clientX + 12) + 'px';
            tooltip.style.top  = (event.clientY - 10) + 'px';
        })
        .on('mousemove', event => {
            const tooltip = document.getElementById('d3-tooltip');
            tooltip.style.left = (event.clientX + 12) + 'px';
            tooltip.style.top  = (event.clientY - 10) + 'px';
        })
        .on('mouseout', () => { document.getElementById('d3-tooltip').style.opacity = '0'; });
        
    // The value on the right
    bars.append('text')
        .attr('y', d => y(d.ip) + y.bandwidth() / 2)
        .attr('x', d => x(d.hops) + 5)
        .attr('dy', '0.35em')
        .attr('fill', '#374151')
        .attr('font-weight', '600')
        .attr('font-size', '16px')
        .text(d => d.hops);
        
    drawChartLegend(svg, width, height, ips);
}

function drawLossChart(ips) {
    const { svg, width, height } = getChartBase('loss-chart');
    
    let allTimes = [];
    ips.forEach(ip => {
        if (hiddenTargets.has(ip)) return;
        if (metricsHistory[ip]) {
            metricsHistory[ip].forEach(d => allTimes.push(d.time));
        }
    });
    
    if (allTimes.length === 0) {
        drawChartLegend(svg, width, height, ips);
        return;
    }
    
    // Ensure the X domain spans at least 10 seconds if history is very new
    let minTime = d3.min(allTimes);
    let maxTime = d3.max(allTimes);
    if (maxTime - minTime < 10000) {
        minTime = new Date(maxTime.getTime() - 10000);
    }

    const x = d3.scaleTime().domain([minTime, maxTime]).range([0, width]);
    const y = d3.scaleLinear().domain([0, 100]).range([height, 0]);

    svg.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat("%H:%M:%S")))
        .selectAll('text').attr('fill', '#6B7280');
        
    svg.append('g').call(d3.axisLeft(y).ticks(5)).selectAll('text').attr('fill', '#6B7280');

    const line = d3.line()
        .x(d => x(d.time))
        .y(d => y(d.loss))
        .curve(d3.curveMonotoneX);

    ips.forEach((ip, i) => {
        if (hiddenTargets.has(ip)) return;
        const data = metricsHistory[ip] || [];
        const color = getColor(i);
        
        svg.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', color)
            .attr('stroke-width', 2)
            .attr('d', line);

        svg.selectAll(`.dot-${i}`)
            .data(data).enter().append('circle')
            .attr('class', `dot-${i}`)
            .attr('cx', d => x(d.time))
            .attr('cy', d => y(d.loss))
            .attr('r', 4)
            .attr('fill', color)
            .attr('stroke', '#FFFFFF')
            .attr('stroke-width', 1.5)
            .on('mouseover', (event, d) => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.opacity = '1';
                tooltip.innerHTML = `<b>${ip}</b><br>${d3.timeFormat("%H:%M:%S")(d.time)}<br>Loss: <b>${d.loss}%</b>`;
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mousemove', event => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mouseout', () => { document.getElementById('d3-tooltip').style.opacity = '0'; });
    });
    
    drawChartLegend(svg, width, height, ips);
}

function drawLatencyChart(ips) {
    const { svg, width, height } = getChartBase('latency-worst-chart');
    
    let allTimes = [];
    let allValues = [];
    ips.forEach(ip => {
        if (hiddenTargets.has(ip)) return;
        if (metricsHistory[ip]) {
            metricsHistory[ip].forEach(d => {
                allTimes.push(d.time);
                allValues.push(d.worst);
            });
        }
    });
    
    if (allTimes.length === 0) {
        drawChartLegend(svg, width, height, ips);
        return;
    }
    
    let minTime = d3.min(allTimes);
    let maxTime = d3.max(allTimes);
    if (maxTime - minTime < 10000) {
        minTime = new Date(maxTime.getTime() - 10000);
    }

    const x = d3.scaleTime().domain([minTime, maxTime]).range([0, width]);
    const y = d3.scaleLinear().domain([0, (d3.max(allValues) * 1.2) || 100]).range([height, 0]);

    svg.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat("%H:%M:%S")))
        .selectAll('text').attr('fill', '#6B7280');
        
    svg.append('g').call(d3.axisLeft(y).ticks(5)).selectAll('text').attr('fill', '#6B7280');

    const line = d3.line()
        .x(d => x(d.time))
        .y(d => y(d.worst))
        .curve(d3.curveMonotoneX);

    ips.forEach((ip, i) => {
        if (hiddenTargets.has(ip)) return;
        const data = metricsHistory[ip] || [];
        const color = getColor(i);
        
        svg.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', color)
            .attr('stroke-width', 2)
            .attr('d', line);

        svg.selectAll(`.dot-lat-${i}`)
            .data(data).enter().append('circle')
            .attr('class', `dot-lat-${i}`)
            .attr('cx', d => x(d.time))
            .attr('cy', d => y(d.worst))
            .attr('r', 4)
            .attr('fill', color)
            .attr('stroke', '#FFFFFF')
            .attr('stroke-width', 1.5)
            .on('mouseover', (event, d) => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.opacity = '1';
                tooltip.innerHTML = `<b>${ip}</b><br>${d3.timeFormat("%H:%M:%S")(d.time)}<br>Worst: <b>${d.worst} ms</b>`;
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mousemove', event => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mouseout', () => { document.getElementById('d3-tooltip').style.opacity = '0'; });
    });
    
    drawChartLegend(svg, width, height, ips);
}

function drawStdevChart(ips) {
    const { svg, width, height } = getChartBase('stdev-chart');
    
    let allTimes = [];
    let allValues = [];
    ips.forEach(ip => {
        if (hiddenTargets.has(ip)) return;
        if (metricsHistory[ip]) {
            metricsHistory[ip].forEach(d => {
                allTimes.push(d.time);
                allValues.push(d.stdev);
            });
        }
    });
    
    if (allTimes.length === 0) {
        drawChartLegend(svg, width, height, ips);
        return;
    }
    
    let minTime = d3.min(allTimes);
    let maxTime = d3.max(allTimes);
    if (maxTime - minTime < 10000) {
        minTime = new Date(maxTime.getTime() - 10000);
    }

    const x = d3.scaleTime().domain([minTime, maxTime]).range([0, width]);
    const y = d3.scaleLinear().domain([0, (d3.max(allValues) * 1.2) || 10]).range([height, 0]);

    svg.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat("%H:%M:%S")))
        .selectAll('text').attr('fill', '#6B7280');
        
    svg.append('g').call(d3.axisLeft(y).ticks(5)).selectAll('text').attr('fill', '#6B7280');

    const line = d3.line()
        .x(d => x(d.time))
        .y(d => y(d.stdev))
        .curve(d3.curveMonotoneX);

    ips.forEach((ip, i) => {
        if (hiddenTargets.has(ip)) return;
        const data = metricsHistory[ip] || [];
        const color = getColor(i);
        
        svg.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', color)
            .attr('stroke-width', 2)
            .attr('d', line);

        svg.selectAll(`.dot-std-${i}`)
            .data(data).enter().append('circle')
            .attr('class', `dot-std-${i}`)
            .attr('cx', d => x(d.time))
            .attr('cy', d => y(d.stdev))
            .attr('r', 4)
            .attr('fill', color)
            .attr('stroke', '#FFFFFF')
            .attr('stroke-width', 1.5)
            .on('mouseover', (event, d) => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.opacity = '1';
                tooltip.innerHTML = `<b>${ip}</b><br>${d3.timeFormat("%H:%M:%S")(d.time)}<br>StDev: <b>${d.stdev}</b>`;
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mousemove', event => {
                const tooltip = document.getElementById('d3-tooltip');
                tooltip.style.left = (event.clientX + 12) + 'px';
                tooltip.style.top  = (event.clientY - 10) + 'px';
            })
            .on('mouseout', () => { document.getElementById('d3-tooltip').style.opacity = '0'; });
    });
    
    drawChartLegend(svg, width, height, ips);
}

// ── SUMMARY TABLE ──
function populateSummaryTable(ips) {
    const tbody = document.getElementById('summary-tbody');
    tbody.innerHTML = '';
    
    ips.forEach((ip, idx) => {
        const d = allData[ip];
        const hops = d.hops || [];
        const numHops = hops.length;
        const validHops = hops.filter(h => h.avg > 0 && h.ip !== 'no reply');
        const avgRtt = validHops.length ? (validHops.reduce((s, h) => s + h.avg, 0) / validHops.length).toFixed(2) : '--';
        const endLoss = numHops ? hops[numHops-1].loss_pct : 0;
        const worst = numHops ? Math.max(...hops.map(h => h.worst)).toFixed(2) : '--';
        const stdev = numHops ? hops[numHops-1].stdev : '--';
        
        let statusBadge = '<span class="badge idle">Idle</span>';
        if (d.status === 'Scanning') statusBadge = '<span class="badge scanning"><i class="fa-solid fa-circle-notch spin"></i> Scanning</span>';
        else if (d.is_reached) statusBadge = '<span class="badge reached"><i class="fa-solid fa-check"></i> Reached</span>';
        else if (numHops > 0) statusBadge = '<span class="badge unreachable"><i class="fa-solid fa-xmark"></i> Unreachable</span>';

        const color = getColor(idx);
        
        tbody.insertAdjacentHTML('beforeend', `
            <tr>
                <td><span class="status-dot" style="background:${color}; display:inline-block; margin-right:6px"></span>${ip}</td>
                <td>${statusBadge}</td>
                <td>${numHops}</td>
                <td>${avgRtt} ms</td>
                <td>${worst} ms</td>
                <td>${stdev}</td>
                <td class="${endLoss > 10 ? 'loss-high' : endLoss > 0 ? 'loss-warn' : 'loss-ok'}">${endLoss}%</td>
                <td>
                    <button class="btn-danger-sm" onclick="removeTarget('${ip}')">Delete</button>
                </td>
            </tr>
        `);
    });
}

// ── INIT ──
(async () => {
    await fetchTargets();
    await Promise.all([fetchAndRender(), fetchStatus(), fetchHistory()]);
    setInterval(fetchAndRender, POLL_INTERVAL_MS);
    setInterval(fetchHistory, 10_000);
    setInterval(fetchStatus, 30_000);
})();
