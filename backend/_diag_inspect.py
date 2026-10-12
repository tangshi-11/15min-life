import json, sys, urllib.request, time

body = json.dumps({"center": {"lat": 24.741355, "lng": 102.694037}, "walk_minutes": 15}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/inspect", data=body, headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode())
    print(f"elapsed={time.time()-t0:.1f}s", flush=True)
    iso = data.get("isochrone", {})
    st = iso.get("stats", {})
    print("area_km2=", st.get("area_km2"))
    print("max_reach_m=", st.get("max_reach_m"))
    poly = iso.get("polygon", [])
    print("polygon_pts=", len(poly))
    if poly:
        lats = [p[0] for p in poly]
        lngs = [p[1] for p in poly]
        print("bbox lat", min(lats), max(lats), "lng", min(lngs), max(lngs))
        # 北侧是否收缩（中心点 24.741355，北边界的纬度最高点应远小于湖面 24.755）
        print("max_lat_diff_m=", round((max(lats)-24.741355)*110540, 0))
        # 西侧是否保留（中心点 lng 102.694037，西边界经度最低点）
        print("min_lng_diff_m=", round((102.694037-min(lngs))*111320, 0))
        north = sorted(poly, key=lambda p: -p[1])[:4]
        print("north_pts(lng,lat):", [(round(p[0], 5), round(p[1], 5)) for p in north])
        west = sorted(poly, key=lambda p: p[0])[:4]
        print("west_pts(lng,lat):", [(round(p[0], 5), round(p[1], 5)) for p in west])
except Exception as e:
    print("ERR", repr(e), flush=True)
