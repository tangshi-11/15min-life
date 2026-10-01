/* 15分钟生活圈 · 智能体检与规划助手 — 前端逻辑
 * 地图：Leaflet + OSM（无密钥可跑通演示）；坐标：后端返回百度 BD-09，渲染前转 WGS-84。
 * 图表：ECharts 雷达图(分类评分) + 柱状图(设施数量)。
 */
(function () {
  "use strict";

  /* ---------- 坐标转换：BD-09 → GCJ-02 → WGS-84（与后端 coords.py 一致） ---------- */
  var X_PI = Math.PI * 3000 / 180;
  function outOfChina(lng, lat) { return !(lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55); }
  function transformLat(x, y) {
    var ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    ret += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    ret += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    ret += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
    return ret;
  }
  function transformLng(x, y) {
    var ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    ret += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    ret += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    ret += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
    return ret;
  }
  function bd09ToGcj02(lng, lat) {
    var x = lng - 0.0065, y = lat - 0.006;
    var z = Math.sqrt(x * x + y * y) - 0.00002 * Math.sin(y * X_PI);
    var theta = Math.atan2(y, x) - 0.000003 * Math.cos(x * X_PI);
    return [z * Math.cos(theta), z * Math.sin(theta)];
  }
  function gcj02ToBd09(lng, lat) {
    var z = Math.sqrt(lng * lng + lat * lat) + 0.00002 * Math.sin(lat * X_PI);
    var theta = Math.atan2(lat, lng) + 0.000003 * Math.cos(lng * X_PI);
    return [z * Math.cos(theta) + 0.0065, z * Math.sin(theta) + 0.006];
  }
  function gcj02ToWgs84(lng, lat) {
    if (outOfChina(lng, lat)) return [lng, lat];
    var dlat = transformLat(lng - 105, lat - 35);
    var dlng = transformLng(lng - 105, lat - 35);
    var radlat = lat / 180 * Math.PI;
    var magic = Math.sin(radlat); magic = 1 - 0.00669342162296594323 * magic * magic;
    var sqrtmagic = Math.sqrt(magic);
    dlat = (dlat * 180) / ((6378245 * (1 - 0.00669342162296594323)) / (magic * sqrtmagic) * Math.PI);
    dlng = (dlng * 180) / (6378245 / sqrtmagic * Math.cos(radlat) * Math.PI);
    return [lng - dlng, lat - dlat];
  }
  function wgs84ToGcj02(lng, lat) {
    if (outOfChina(lng, lat)) return [lng, lat];
    var dlat = transformLat(lng - 105, lat - 35);
    var dlng = transformLng(lng - 105, lat - 35);
    var radlat = lat / 180 * Math.PI;
    var magic = Math.sin(radlat); magic = 1 - 0.00669342162296594323 * magic * magic;
    var sqrtmagic = Math.sqrt(magic);
    dlat = (dlat * 180) / ((6378245 * (1 - 0.00669342162296594323)) / (magic * sqrtmagic) * Math.PI);
    dlng = (dlng * 180) / (6378245 / sqrtmagic * Math.cos(radlat) * Math.PI);
    return [lng + dlng, lat + dlat];
  }
  function bd09ToWgs84(lng, lat) { var g = bd09ToGcj02(lng, lat); return gcj02ToWgs84(g[0], g[1]); }
  function wgs84ToBd09(lng, lat) { var g = wgs84ToGcj02(lng, lat); return gcj02ToBd09(g[0], g[1]); }

  /* ---------- 常量与状态 ---------- */
  var CAT_COLORS = {
    医疗: "#e11d48", 教育: "#2563eb", 购物: "#f59e0b",
    养老: "#0d9488", 文体: "#16a34a", 餐饮: "#7c3aed", 交通: "#0891b2", 其他: "#64748b"
  };
  var CAT_NAMES = { 医疗: "医疗", 教育: "教育", 购物: "购物", 养老: "养老", 文体: "文体", 餐饮: "餐饮", 交通: "交通" };

  var map = L.map("map").setView([25.0406, 102.7146], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap contributors"
  }).addTo(map);

  var layers = {
    grid: L.layerGroup().addTo(map),
    iso: L.layerGroup().addTo(map),
    blind: L.layerGroup().addTo(map),
    pois: L.layerGroup().addTo(map),
    center: L.layerGroup().addTo(map)
  };

  var centerMarker = null;
  var currentCenter = { lat: 25.0406, lng: 102.7146 }; // BD-09

  function setCenterBd(lat, lng, fly) {
    currentCenter = { lat: lat, lng: lng };
    var w = bd09ToWgs84(lng, lat);
    if (centerMarker) {
      centerMarker.setLatLng([w[1], w[0]]);
    } else {
      centerMarker = L.marker([w[1], w[0]], { draggable: true }).addTo(layers.center);
      centerMarker.bindTooltip("中心点（可拖拽）", { direction: "top" }).openTooltip();
      centerMarker.on("dragend", function (e) {
        var ll = e.target.getLatLng();
        var b = wgs84ToBd09(ll.lng, ll.lat);
        currentCenter = { lat: b[1], lng: b[0] };
        document.getElementById("addressInput").value = "自定义坐标";
      });
    }
    if (fly) map.flyTo([w[1], w[0]], Math.max(map.getZoom(), 15), { duration: 0.8 });
  }

  map.on("click", function (e) {
    var b = wgs84ToBd09(e.latlng.lng, e.latlng.lat);
    setCenterBd(b[1], b[0], false);
    document.getElementById("addressInput").value = "自定义坐标";
  });

  /* ---------- 图表 ---------- */
  var radarChart = null, barChart = null;
  function initCharts() {
    radarChart = echarts.init(document.getElementById("radarChart"));
    barChart = echarts.init(document.getElementById("barChart"));
    window.addEventListener("resize", function () { radarChart && radarChart.resize(); barChart && barChart.resize(); });
  }
  function renderCharts(coverage) {
    var cats = coverage.categories;
    var indicators = cats.map(function (c) { return { name: CAT_NAMES[c] || c, max: 100 }; });
    var scores = cats.map(function (c) { return coverage.scores[c] || 0; });
    radarChart.setOption({
      tooltip: {},
      radar: { indicator: indicators, radius: "60%", splitNumber: 4 },
      series: [{
        type: "radar", data: [{
          value: scores,
          areaStyle: { color: "rgba(37,99,235,.28)" },
          lineStyle: { color: "#2563eb", width: 2 },
          itemStyle: { color: "#1d4ed8" }
        }]
      }]
    }, true);
    var counts = Object.keys(coverage.counts || {}).sort(function (a, b) {
      return (coverage.counts[b] || 0) - (coverage.counts[a] || 0);
    }).map(function (c) {
      return { name: CAT_NAMES[c] || c, value: coverage.counts[c] || 0, color: CAT_COLORS[c] || "#64748b" };
    });
    barChart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 12, top: 16, bottom: 28 },
      xAxis: { type: "category", data: counts.map(function (c) { return c.name; }), axisLabel: { fontSize: 11 } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 11 } },
      series: [{
        type: "bar", barWidth: "55%", data: counts.map(function (c) { return { value: c.value, itemStyle: { color: c.color } }; })
      }]
    }, true);
  }

  /* ---------- 地图图层渲染 ---------- */
  function clearMap() {
    Object.keys(layers).forEach(function (k) { layers[k].clearLayers(); });
    centerMarker = null;
  }

  function renderGrid(grid) {
    var n = grid.n, vals = grid.values, half = grid.half_size_m || 2000;
    var step = 2 * half / (n - 1);
    var s = Math.max(1, Math.ceil(n / 45));
    var lat = currentCenter.lat;
    for (var j = 0; j < n; j += s) {
      for (var i = 0; i < n; i += s) {
        var sum = 0, cnt = 0;
        for (var dj = 0; dj < s && j + dj < n; dj++) {
          for (var di = 0; di < s && i + di < n; di++) {
            sum += vals[(j + dj) * n + (i + di)] || 0; cnt++;
          }
        }
        var m = cnt ? sum / cnt : 0;
        var east0 = -half + i * step, east1 = Math.min(half, east0 + s * step);
        var north1 = half - j * step, north0 = Math.max(-half, north1 - s * step);
        var w = bd09ToWgs84(
          currentCenter.lng + (east0 + east1) / 2 / (111320 * Math.cos(lat * Math.PI / 180)),
          currentCenter.lat + (north0 + north1) / 2 / 110540
        );
        var halfLng = (east1 - east0) / 2 / (111320 * Math.cos(lat * Math.PI / 180));
        var halfLat = (north1 - north0) / 2 / 110540;
        var hue = Math.max(0, Math.min(120, 120 - m * 6));
        var alpha = m <= 15 ? 0.5 : 0.14;
        L.rectangle(
          [[w[1] - halfLat, w[0] - halfLng], [w[1] + halfLat, w[0] + halfLng]],
          { color: "transparent", fillColor: "hsl(" + hue + ",70%,45%)", fillOpacity: alpha, stroke: false, interactive: false }
        ).addTo(layers.grid);
      }
    }
  }

  function renderIso(iso) {
    var poly = iso.polygon || iso.boundary_polygon;
    if (poly && poly.length >= 3) {
      var pts = poly.map(function (p) { var w = bd09ToWgs84(p[0], p[1]); return [w[1], w[0]]; });
      L.polygon(pts, { color: "#1d4ed8", weight: 2.5, fillColor: "#2563eb", fillOpacity: 0.15 }).addTo(layers.iso);
      L.polyline(pts, { color: "#0ea5e9", weight: 1.5, dashArray: "4 6", opacity: 0.8 }).addTo(layers.iso);
    }
  }

  function renderBlind(blind) {
    (blind.polygons || []).forEach(function (poly) {
      if (poly.length < 3) return;
      var pts = poly.map(function (p) { var w = bd09ToWgs84(p[0], p[1]); return [w[1], w[0]]; });
      L.polygon(pts, {
        color: "#dc2626", weight: 2, fillColor: "#ef4444", fillOpacity: 0.35,
        interactive: true
      }).bindTooltip("服务盲区（灰色区域）", { sticky: true }).addTo(layers.blind);
    });
  }

  function renderPois(pois) {
    pois.forEach(function (p) {
      var w = bd09ToWgs84(p.lng, p.lat);
      L.circleMarker([w[1], w[0]], {
        radius: 5, color: "#fff", weight: 1,
        fillColor: CAT_COLORS[p.category] || "#64748b", fillOpacity: 0.9
      }).bindTooltip(p.name + "（" + (CAT_NAMES[p.category] || p.category) + "）", { sticky: true }).addTo(layers.pois);
    });
  }

  function renderLegend() {
    var html = '<div class="lg-title">图例</div>';
    Object.keys(CAT_COLORS).forEach(function (c) {
      if (c === "其他") return;
      html += '<div class="lg-item"><span class="dot" style="background:' + CAT_COLORS[c] + '"></span>' + c + '</div>';
    });
    html += '<div class="lg-line"><span class="sw" style="background:#2563eb"></span>15分钟等时圈</div>';
    html += '<div class="lg-line"><span class="sw" style="background:#ef4444"></span>服务盲区(灰色区域)</div>';
    html += '<div class="lg-item"><span class="dot rect" style="background:hsl(60,70%,45%)"></span>步行热力场(分钟)</div>';
    document.getElementById("legend").innerHTML = html;
  }

  /* ---------- 体检流程 ---------- */
  var inspecting = false;
  function inspect() {
    if (inspecting) return;
    var addr = document.getElementById("addressInput").value.trim();
    var walk = parseInt(document.getElementById("walkSelect").value, 10) || 15;
    var payload = { walk_minutes: walk };
    if (addr && addr !== "自定义坐标") {
      payload.address = addr;
    } else {
      payload.center = { lat: +currentCenter.lat.toFixed(6), lng: +currentCenter.lng.toFixed(6) };
    }
    inspecting = true;
    var btn = document.getElementById("inspectBtn");
    btn.disabled = true;
    document.getElementById("loading").hidden = false;

    fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("HTTP " + r.status)); });
      return r.json();
    }).then(render).catch(function (err) {
      alert("体检失败：" + err.message);
    }).finally(function () {
      inspecting = false;
      btn.disabled = false;
      document.getElementById("loading").hidden = true;
    });
  }

  function render(data) {
    clearMap();
    setCenterBd(data.center.lat, data.center.lng, true);

    if (data.isochrone.grid) renderGrid(data.isochrone.grid);
    renderIso(data.isochrone);
    renderBlind(data.blind_spots);
    renderPois(data.pois || []);
    renderLegend();

    var cov = data.coverage;
    document.getElementById("scoreBox").hidden = false;
    document.getElementById("scoreNum").textContent = cov.overall;
    var blindTxt = cov.blind_summary || "";
    var warn = "";
    if (data.warnings && data.warnings.length) warn = "（部分数据已降级：" + data.warnings.join("；") + "）";
    document.getElementById("blindSummary").textContent = blindTxt + warn;
    var s = data.isochrone.stats || {};
    var inPoly = cov.in_polygon_pois || 0;
    document.getElementById("statLine").textContent =
      "等时圈面积 " + (s.area_km2 || 0) + " km² · 最远可达 " + Math.round(s.max_reach_m || 0) + " m · " +
      "圈内设施 " + inPoly + " 个 · 耗时 " + data.elapsed_ms + " ms";

    document.getElementById("charts").hidden = false;
    if (!radarChart) initCharts();
    renderCharts(cov);
  }

  /* ---------- 初始化 ---------- */
  function boot() {
    document.getElementById("inspectBtn").addEventListener("click", inspect);
    document.getElementById("addressInput").addEventListener("keydown", function (e) { if (e.key === "Enter") inspect(); });
    Array.prototype.forEach.call(document.querySelectorAll(".samples button"), function (b) {
      b.addEventListener("click", function () {
        document.getElementById("addressInput").value = b.getAttribute("data-addr");
        inspect();
      });
    });
    renderLegend();

    fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
      var badge = document.getElementById("modeBadge");
      if (cfg.mode === "live") {
        badge.textContent = "实时数据 · 百度地图 API";
        badge.className = "mode-badge live";
      } else {
        badge.textContent = "演示模式 · Mock 数据（配置 AK 后自动切换实时）";
        badge.className = "mode-badge mock";
      }
    }).catch(function () { /* 忽略 */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
