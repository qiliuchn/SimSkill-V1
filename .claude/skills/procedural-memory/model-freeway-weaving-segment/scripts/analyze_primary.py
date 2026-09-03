#!/usr/bin/env python3
"""PRIMARY analysis: W (weave, shared aux lane) vs C (severed control, no shared
aux lane). Finding-2/3 logic reused from attempt-1 analyze.py (verified correct),
re-parameterised for the W/C geometry. Also cross-checks insertion/completion
against the route-file definition so every headline count is file-derived."""
import xml.etree.ElementTree as ET
from collections import defaultdict

BASE = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-28_20-44-20/attempts/attempt-2"

# weave/merge/diverge spans in global x (edges start x=1000)
W_WEAVE = (1000.0, 1331.0)          # W: single 331 m weave edge
C_MERGE = (1000.0, 1200.0)          # C: on-ramp accel/merge segment
C_DIVERGE = (2900.0, 3100.0)        # C: off-ramp decel/diverge segment, 1900 m later
BAND_LO, BAND_HI = 1000.0, 1350.0   # common short "weave band" at the merge
BIN = 50.0
WARMUP = 600.0
END = 3600.0

# ---------------------------------------------------------- finding 1
def edges_touched_by_ramps(net):
    t = ET.parse(net).getroot()
    on_targets, off_sources = set(), set()
    for c in t.findall("connection"):
        f, to = c.get("from"), c.get("to")
        if f is None or f.startswith(":"):
            continue
        if "onramp" in f:
            on_targets.add(to)
        if "offramp" in to:
            off_sources.add(f)
    return on_targets, off_sources

print("========== FINDING 1: shared vs. disjoint auxiliary lane ==========")
for tag in ("W", "C"):
    net = f"{BASE}/scenario{tag}/{tag}.net.xml"
    on_t, off_s = edges_touched_by_ramps(net)
    shared = on_t & off_s
    verdict = ("SHARED aux lane -> weaving possible" if shared
               else "DISJOINT (no shared lane) -> no weaving possible")
    print(f"  {tag}: on-ramp feeds {sorted(on_t)}; off-ramp drains {sorted(off_s)}; "
          f"shared={sorted(shared) or 'NONE'}  => {verdict}")

# also confirm the actual shared LANE ids at the connection level for W, and that
# C shares neither an edge nor a lane between the two ramp movements
def shared_lanes(net):
    t = ET.parse(net).getroot()
    on_lanes, off_lanes = set(), set()
    for c in t.findall("connection"):
        f, to = c.get("from"), c.get("to")
        if f is None or f.startswith(":"):
            continue
        if "onramp" in f:
            on_lanes.add(f"{to}_{c.get('toLane')}")
        if "offramp" in to:
            off_lanes.add(f"{f}_{c.get('fromLane')}")
    return on_lanes, off_lanes

for tag in ("W", "C"):
    net = f"{BASE}/scenario{tag}/{tag}.net.xml"
    onl, offl = shared_lanes(net)
    print(f"    {tag}: on-ramp delivers into lane(s) {sorted(onl)}; off-ramp is fed "
          f"from lane(s) {sorted(offl)}; shared lane(s)={sorted(onl & offl) or 'NONE'}")
print()

# ---------------------------------------------------------- finding 2
def bin_lane_changes(lc):
    root = ET.parse(lc).getroot()
    per_bin = defaultdict(int)
    total = 0
    band = 0
    for ch in root.findall("change"):
        x = float(ch.get("x"))
        b = int(x // BIN) * int(BIN)
        per_bin[b] += 1
        total += 1
        if BAND_LO <= x < BAND_HI:
            band += 1
    return per_bin, total, band

print("========== FINDING 2: lane-change spatial concentration (per 50 m) ==========")
res2 = {}
for tag in ("W", "C"):
    lc = f"{BASE}/scenario{tag}/{tag}_lanechange.xml"
    pb, total, band = bin_lane_changes(lc)
    res2[tag] = (pb, total, band)

# W weave-edge density
pbW = res2["W"][0]
lo, hi = W_WEAVE
w_on_weave = sum(n for b, n in pbW.items() if lo <= b < hi)
w_dens = 100.0 * w_on_weave / (hi - lo)
print(f"  W: total changes={res2['W'][1]}; on 331 m weave edge [{lo:.0f}-{hi:.0f}] = "
      f"{w_on_weave} -> {w_dens:.1f}/100 m; within band [{BAND_LO:.0f},{BAND_HI:.0f}) = "
      f"{res2['W'][2]} ({100*res2['W'][2]/res2['W'][1]:.1f}% of all)")

# C: split into merge zone, mid, diverge zone
pbC = res2["C"][0]
c_merge = sum(n for b, n in pbC.items() if C_MERGE[0] <= b < C_MERGE[1])
c_div   = sum(n for b, n in pbC.items() if C_DIVERGE[0] <= b < C_DIVERGE[1])
c_mid   = sum(n for b, n in pbC.items() if C_MERGE[1] <= b < C_DIVERGE[0])
c_dens_band = 100.0 * c_merge / (BAND_HI - BAND_LO)
print(f"  C: total changes={res2['C'][1]}; merge zone [1000-1200]={c_merge}, "
      f"mid [1200-2900]={c_mid}, diverge zone [2900-3100]={c_div}; within band "
      f"[{BAND_LO:.0f},{BAND_HI:.0f}) = {res2['C'][2]} "
      f"({100*res2['C'][2]/res2['C'][1]:.1f}% of all)")
print(f"     -> C's changes split into TWO zones 1900 m apart; no single weave band.")

# per-50m histogram, key regions
def show(tag, lo, hi, label):
    pb = res2[tag][0]
    print(f"    {tag} {label} [{lo:.0f}-{hi:.0f} m]:")
    for b in range(int(lo), int(hi), int(BIN)):
        n = pb.get(b, 0)
        print(f"      {b:>5d}-{b+int(BIN):<5d}: {n:>4d} {'#'*min(n,60)}")

print("\n  --- per-50m bins ---")
show("W", 950, 1400, "weave (merge x=1000, diverge x=1331)")
show("C", 950, 1250, "merge (on-ramp x=1000)")
show("C", 2850, 3150, "diverge (off-ramp x=3100)")

# concentration metric
for tag in ("W", "C"):
    pb = res2[tag][0]
    peak = max(pb, key=pb.get)
    print(f"  {tag} peak 50 m bin: x={peak}-{peak+int(BIN)} m = {pb[peak]} changes")
print(f"  W weave-band density {w_dens:.1f}/100m vs C merge-band density "
      f"{c_dens_band:.1f}/100m  -> ratio {w_dens/max(c_dens_band,1e-9):.1f}x")
print()

# ---------------------------------------------------------- finding 3
def e1_station(e1, det_ids):
    root = ET.parse(e1).getroot()
    nveh = 0.0
    inv = 0.0
    for iv in root.findall("interval"):
        if iv.get("id") not in det_ids:
            continue
        beg = float(iv.get("begin"))
        if beg < WARMUP:
            continue
        n = float(iv.get("nVehContrib"))
        spd = float(iv.get("harmonicMeanSpeed"))
        nveh += n
        if n > 0 and spd > 0:
            inv += n / spd
    flow = nveh / ((END - WARMUP) / 3600.0)
    vspace = (nveh / inv) if inv > 0 else float("nan")
    return flow, vspace, nveh

print("========== FINDING 3: downstream E1 throughput & speed ==========")
down = {"W": ["W_down_0", "W_down_1", "W_down_2"],
        "C": ["C_down_0", "C_down_1", "C_down_2"]}
up = {"W": ["W_up_0", "W_up_1", "W_up_2"],
      "C": ["C_up_0", "C_up_1", "C_up_2"]}
out = {}
for tag in ("W", "C"):
    e1 = f"{BASE}/scenario{tag}/{tag}_e1.xml"
    f_d, v_d, n_d = e1_station(e1, down[tag])
    f_u, v_u, _ = e1_station(e1, up[tag])
    out[tag] = (f_d, v_d, f_u, v_u)
    print(f"  {tag} downstream 3-lane mainline: flow={f_d:.0f} veh/h, "
          f"space-mean speed={v_d*3.6:.1f} km/h (n={n_d:.0f}) | upstream: "
          f"flow={f_u:.0f} veh/h, speed={v_u*3.6:.1f} km/h")

fW, vW, _, uvW = out["W"]; fC, vC, _, uvC = out["C"]
print("\n  --- weaving penalty (W weave vs C severed control, identical volumes) ---")
print(f"    downstream throughput: W={fW:.0f} vs C={fC:.0f} veh/h -> "
      f"{fW-fC:+.0f} veh/h ({100*(fW-fC)/fC:+.1f}%)")
print(f"    downstream speed:      W={vW*3.6:.1f} vs C={vC*3.6:.1f} km/h -> "
      f"{(vW-vC)*3.6:+.1f} km/h ({100*(vW-vC)/vC:+.1f}%)")
print(f"    upstream mainline speed: W={uvW*3.6:.1f} vs C={uvC*3.6:.1f} km/h "
      f"(weave back-pressure onto the approach)")
print()

# ---------------------------------------------------------- insertion cross-check
def count_defined(rou):
    """expected vehicles = sum over flows of vehsPerHour * (end-begin)/3600."""
    root = ET.parse(rou).getroot()
    tot = 0.0
    for fl in root.findall("flow"):
        vph = float(fl.get("vehsPerHour"))
        dur = (float(fl.get("end")) - float(fl.get("begin"))) / 3600.0
        tot += vph * dur
    return tot

def count_completed(tripinfo):
    root = ET.parse(tripinfo).getroot()
    trips = root.findall("tripinfo")
    vaporized = sum(1 for t in trips if (t.get("vaporized") or "") not in ("", None))
    return len(trips), vaporized

import re
def parse_stats(stats_log):
    """Pull Loaded/Inserted/Running/Waiting and DepartDelay from the preserved
    sumo stdout so every insertion claim is file-derived, not asserted."""
    txt = open(stats_log).read()
    def grab(pat, default=None):
        m = re.search(pat, txt)
        return m.group(1) if m else default
    loaded = grab(r"Inserted:\s*\d+\s*\(Loaded:\s*(\d+)\)")
    inserted = grab(r"Inserted:\s*(\d+)")
    if loaded is None:  # no un-inserted -> "Inserted: N" with no (Loaded:)
        loaded = inserted
    return {
        "loaded": loaded,
        "inserted": inserted,
        "waiting": grab(r"Waiting:\s*(\d+)"),
        "departdelay": grab(r"DepartDelay:\s*([\d.]+)"),
        "teleports": grab(r"Teleports:\s*(\d+)", "0"),
        "collisions": grab(r"Collisions:\s*(\d+)", "0"),
    }

print("========== INSERTION / COMPLETION CROSS-CHECK (file-derived) ==========")
for tag in ("W", "C"):
    exp = count_defined(f"{BASE}/scenario{tag}/{tag}.rou.xml")
    comp, vap = count_completed(f"{BASE}/scenario{tag}/{tag}_tripinfo.xml")
    s = parse_stats(f"{BASE}/scenario{tag}/{tag}_stats.log")
    uninserted = int(s["loaded"]) - int(s["inserted"])
    print(f"  {tag}: flows define {exp:.0f} veh -> Loaded={s['loaded']}, "
          f"Inserted={s['inserted']} (un-inserted at sim end={uninserted}, "
          f"Waiting-queue={s['waiting']}); mean DepartDelay={s['departdelay']} s; "
          f"tripinfo completed={comp}, vaporized/teleported={vap}; "
          f"Teleports={s['teleports']}, Collisions={s['collisions']} "
          f"[source: {tag}_stats.log + {tag}_tripinfo.xml]")
