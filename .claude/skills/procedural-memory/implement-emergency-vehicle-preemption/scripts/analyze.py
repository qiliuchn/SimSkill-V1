"""Findings 3 (cross-street cost) and 4 (rescue lane from FCD)."""
import xml.etree.ElementTree as ET
import os, math

BASE = os.path.join(os.path.dirname(__file__), "..", "runs")
CROSS = {"top0A0","bottom0A0","top1B0","bottom1B0",
         "top2C0","bottom2C0","top3D0","bottom3D0"}
ARTERIAL = ["left0A0","A0B0","B0C0","C0D0","D0right0"]

# ---------- Finding 3: cross-street delay cost (edgeData) ----------
def cross_delay(cfg):
    r = ET.parse(os.path.join(BASE, cfg, "edgedata.out.xml")).getroot()
    tot_wait = tot_loss = veh = 0.0
    for interval in r.findall("interval"):
        for e in interval.findall("edge"):
            if e.get("id") in CROSS:
                n = float(e.get("entered") or 0)
                # waitingTime & timeLoss are per-edge aggregates (veh-seconds via *entered when given as mean)
                wt = float(e.get("waitingTime") or 0)
                tl = float(e.get("timeLoss") or 0)
                tot_wait += wt; tot_loss += tl; veh += n
    return tot_wait, tot_loss, veh

print("=== FINDING 3: cross-street (conflicting approaches) delay, whole run ===")
a = cross_delay("a"); c = cross_delay("c")
print(f"  config a: total waitingTime={a[0]:.1f}s  timeLoss={a[1]:.1f}s  veh entered={a[2]:.0f}")
print(f"  config c: total waitingTime={c[0]:.1f}s  timeLoss={c[1]:.1f}s  veh entered={c[2]:.0f}")
print(f"  preemption cost: +{c[0]-a[0]:.1f}s waiting  (+{c[1]-a[1]:.1f}s timeLoss) on cross approaches")

# ---------- Finding 4: rescue lane from FCD ----------
# For each config, over the EV's traversal window, look at background passenger
# vehicles within 60 m AHEAD of the EV on the SAME arterial edge. Rescue-lane
# formation => they vacate the centerline (mean |y-200| rises) and slow (speed drops).
def rescue_metrics(cfg):
    path = os.path.join(BASE, cfg, "fcd.xml")
    lat_gap = []      # |v.y - ev.y| : lateral distance of leaders from EV's path
    spd_ahead = []    # speed of vehicles ahead of EV
    n_ahead = 0
    for _ev, ts in ET.iterparse(path, events=("end",)):
        if ts.tag != "timestep":
            continue
        vs = ts.findall("vehicle")
        ev = next((v for v in vs if v.get("id") == "EV"), None)
        if ev is not None:
            ex = float(ev.get("x")); ey = float(ev.get("y"))
            eedge = (ev.get("lane") or "").rsplit("_", 1)[0]
            if eedge in ARTERIAL:
                for v in vs:
                    if v.get("id") == "EV" or v.get("type") == "ev":
                        continue
                    if (v.get("lane") or "").rsplit("_", 1)[0] != eedge:
                        continue
                    vx = float(v.get("x"))
                    if 0 < vx - ex < 60:   # ahead of EV, same arterial edge
                        lat_gap.append(abs(float(v.get("y")) - ey))
                        spd_ahead.append(float(v.get("speed")))
                        n_ahead += 1
        ts.clear()
    mean_lat = sum(lat_gap)/len(lat_gap) if lat_gap else 0
    max_lat = max(lat_gap) if lat_gap else 0
    mean_spd = sum(spd_ahead)/len(spd_ahead) if spd_ahead else 0
    return mean_lat, max_lat, mean_spd, n_ahead

print("\n=== FINDING 4: rescue lane / yielding, background veh <=60m AHEAD of EV ===")
print("  (lateral gap = |leader.y - EV.y|; rescue lane => leaders move laterally AWAY from EV)")
print("  cfg | mean lateral gap(m) | max lateral gap(m) | mean speed ahead(m/s) | samples")
for cfg in "abc":
    m = rescue_metrics(cfg)
    print(f"   {cfg}  |   {m[0]:.3f}             |   {m[1]:.3f}            |   {m[2]:.2f}                | {m[3]}")
