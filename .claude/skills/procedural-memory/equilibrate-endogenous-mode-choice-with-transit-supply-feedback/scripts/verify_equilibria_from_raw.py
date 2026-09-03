"""INDEPENDENT re-verification of every headline number, reading ONLY the raw SUMO
input/output files copied into outputs/raw/ -- no reliance on the result CSVs except
to compare against them at the end.

For each of the four equilibrium cells it recomputes, from scratch:
  (ii)  the realised headway, from the <stop busStop="S_O" until="..."> times in the
        emitted demand.rou.xml, and checks it against the stated operator rule
        H = clamp(K / Q_transit, H_MIN, H_MAX)   (or the frozen H_FIXED in the control)
  (iii) the inter-modal cost gap, from tripinfo.xml
  (iv)  the direction of the capacity-expansion effect
"""
import csv
import os
import sys
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(OUT, "raw")
sys.path.insert(0, HERE)
import dt_scenario as S  # noqa: E402

CELLS = ["base_fbON", "expanded_fbON", "base_fbOFF", "expanded_fbOFF"]
ok_all = True


def rep(name, ok, detail):
    global ok_all
    ok_all = ok_all and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


res = {}
for cell in CELLS:
    d = os.path.join(RAW, f"equilibrium_{cell}")
    dem = ET.parse(os.path.join(d, "demand.rou.xml")).getroot()

    n_car = n_pax = 0
    departures = []
    for el in dem:
        if el.tag == "vehicle" and el.get("type") == "car":
            n_car += 1
        elif el.tag == "person":
            n_pax += 1
        elif el.tag == "vehicle" and el.get("type") == "bus":
            for st in el.findall("stop"):
                if st.get("busStop") == "S_O":
                    departures.append(float(st.get("until")))
    departures.sort()
    gaps = [departures[i + 1] - departures[i] for i in range(len(departures) - 1)]
    H_obs = gaps[0] if gaps else float("nan")
    H_spread = (max(gaps) - min(gaps)) if gaps else 0.0

    feedback = cell.endswith("fbON")
    H_rule = S.headway_rule(n_pax, feedback=feedback,
                            **({} if feedback else {"h_fixed": S.H_FIXED}))
    rep(f"(ii) {cell} headway from emitted timetable",
        abs(H_obs - H_rule) < 0.02 and H_spread < 0.02,   # 0.02s = the demand
        # file's own "%.2f" write precision; anything larger would be a real deviation
        f"{len(departures)} scheduled departures, inter-departure {H_obs:.3f}s "
        f"(spread {H_spread:.1e}s) vs rule K/Q = {S.K_BUDGET:.0f}/{n_pax} -> {H_rule:.3f}s"
        if feedback else
        f"{len(departures)} departures, inter-departure {H_obs:.3f}s frozen at "
        f"H_FIXED={S.H_FIXED:.0f}s regardless of Q={n_pax}")

    ti = ET.parse(os.path.join(d, "tripinfo.xml")).getroot()
    car, tr, wait, ivt = [], [], [], []
    for t in ti.findall("tripinfo"):
        if t.get("vType") == "car":
            car.append(float(t.get("duration")) + float(t.get("departDelay")))
    for pi in ti.findall("personinfo"):
        rides = pi.findall("ride")
        if rides:
            w = float(rides[0].get("waitingTime")); v = float(rides[0].get("duration"))
            tr.append(w + v); wait.append(w); ivt.append(v)

    mc = sum(car) / len(car)
    mt = sum(tr) / len(tr)
    gap = mc - mt
    res[cell] = dict(n_car=n_car, n_pax=n_pax, H=H_obs, car=mc, tr=mt, gap=gap,
                     wait=sum(wait) / len(wait), ivt=sum(ivt) / len(ivt),
                     mean=(sum(car) + sum(tr)) / (len(car) + len(tr)))

    rep(f"(iii) {cell} inter-modal gap near zero",
        abs(gap) <= 25.0,
        f"n_car={n_car} ({len(car)} arrived), n_transit={n_pax} ({len(tr)} rode)  "
        f"C_car={mc:.1f}s  C_transit={mt:.1f}s  gap={gap:+.1f}s")
    rep(f"      {cell} everyone completed", len(car) == n_car and len(tr) == n_pax,
        f"cars {len(car)}/{n_car}, transit riders {len(tr)}/{n_pax}")

print()
for arm, a, b in (("Mohring feedback ON", "base_fbON", "expanded_fbON"),
                  ("feedback OFF control", "base_fbOFF", "expanded_fbOFF")):
    ca, cb = res[a]["mean"], res[b]["mean"]
    print(f"(iv) {arm:22s}: mean cost/traveller {ca:7.1f}s -> {cb:7.1f}s "
          f"({100*(cb-ca)/ca:+6.1f}%)   car share "
          f"{res[a]['n_car']/(res[a]['n_car']+res[a]['n_pax']):.3f} -> "
          f"{res[b]['n_car']/(res[b]['n_car']+res[b]['n_pax']):.3f}   "
          f"headway {res[a]['H']:.0f}s -> {res[b]['H']:.0f}s")
rep("(iv) expansion RAISES cost when the feedback is on",
    res["expanded_fbON"]["mean"] > res["base_fbON"]["mean"],
    f"{res['base_fbON']['mean']:.1f}s -> {res['expanded_fbON']['mean']:.1f}s")
rep("(iv) expansion does NOT raise cost when the feedback is off",
    res["expanded_fbOFF"]["mean"] <= res["base_fbOFF"]["mean"] + 5.0,
    f"{res['base_fbOFF']['mean']:.1f}s -> {res['expanded_fbOFF']['mean']:.1f}s")

# cross-check against the recorded CSV
with open(os.path.join(OUT, "results", "equilibria.csv")) as f:
    rows = {r["cell"]: r for r in csv.DictReader(f)}
print()
for c in CELLS:
    r = rows[c]
    d1 = abs(float(r["car_cost"]) - res[c]["car"])
    d2 = abs(float(r["transit_cost"]) - res[c]["tr"])
    rep(f"CSV vs raw {c}", d1 < 60 and d2 < 60,
        f"car {float(r['car_cost']):.1f} (CSV, 3-rep mean) vs {res[c]['car']:.1f} (raw seed 1), "
        f"transit {float(r['transit_cost']):.1f} vs {res[c]['tr']:.1f}")

print("\nALL RAW-FILE CHECKS PASSED" if ok_all else "\nSOME RAW-FILE CHECKS FAILED")
sys.exit(0 if ok_all else 1)
