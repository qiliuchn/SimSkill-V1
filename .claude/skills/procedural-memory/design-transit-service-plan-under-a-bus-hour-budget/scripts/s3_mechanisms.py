"""Stage 3 -- MANDATORY mechanism verification, established empirically.

(a) does duarouter's intermodal router apply any transfer penalty / minimum
    connection buffer of its own?
(b) how do a person's stages appear in tripinfo/personinfo, and can access walk,
    wait, in-vehicle, transfer walk and transfer wait each be extracted?
(c) is the router genuinely schedule-aware -- does raising a line's frequency
    change route CHOICE, or only realized wait?
(d) how do travellers who never complete, or who are left at a stop at horizon
    end, appear?  plus the teleport-artifact check.
"""
import os, sys, json, math, subprocess
import xml.etree.ElementTree as ET
import tspcore as T
from tspcore import WORK, ensure, run, DUAROUTER

MECH = ensure(os.path.join(WORK, "mech"))
CORR = ["A2B2", "B2C2", "C2D2", "D2E2", "E2F2"]


def net():
    return T.Net(os.path.join(WORK, "base.net.xml"))


def write_stops(N, path, ids):
    with open(path, "w") as f:
        f.write("<additional>\n")
        for sid, edge, end in ids:
            ln = N.edge_len[edge]
            sp, ep = (max(5.0, ln - 45.0), max(20.0, ln - 25.0)) if end == "hi" else (15.0, 35.0)
            f.write(f'    <busStop id="{sid}" lane="{N.drive_lane[edge]}" '
                    f'startPos="{sp:.1f}" endPos="{ep:.1f}" friendlyPos="true">\n'
                    f'        <access lane="{N.ped_lane[edge]}" pos="{(sp+ep)/2:.1f}" '
                    f'friendlyPos="true"/>\n    </busStop>\n')
        f.write("</additional>\n")


def veh(vid, line, dep, edges, stops):
    s = [f'    <vehicle id="{vid}" type="bus" line="{line}" depart="{dep:.1f}" departPos="0">',
         f'        <route edges="{" ".join(edges)}"/>']
    for sid, until in stops:
        s.append(f'        <stop busStop="{sid}" duration="10" until="{until:.1f}"/>')
    s.append("    </vehicle>")
    return "\n".join(s)


def route(tag, N, add, vehicles, persons, extra=None):
    d = ensure(os.path.join(MECH, tag))
    pv = os.path.join(d, "pt.rou.xml")
    with open(pv, "w") as f:
        f.write("<routes>\n" + T.BUS_VTYPE + "\n".join(vehicles) + "\n</routes>\n")
    pf = os.path.join(d, "per.trips.xml")
    with open(pf, "w") as f:
        f.write('<routes>\n    <vType id="ped" vClass="pedestrian"/>\n'
                + "\n".join(persons) + "\n</routes>\n")
    out = os.path.join(d, "routed.rou.xml")
    cmd = [DUAROUTER, "-n", N.file, "--additional-files", add, "-r", f"{pv},{pf}",
           "-o", out, "--ignore-errors", "--no-step-log",
           "--persontrip.walkfactor", "0.9"]
    if extra: cmd += extra
    run(cmd)
    return out


def chosen(routed):
    """map person id -> list of 'intended' vehicles ridden (empty = walked)."""
    res = {}
    r = ET.parse(routed).getroot()
    for p in r.findall("person"):
        res[p.get("id")] = [c.get("intended") for c in p if c.tag == "ride"]
    return res


# ---------------------------------------------------------------- (a) -------
def test_transfer_penalty(N):
    """DIR (one seat, in-vehicle T_dir) vs X1+X2 (two seats, combined 400 s,
    transfer at the IDENTICAL busStop so the transfer walk is zero).
    Sweep T_dir and locate the switch point."""
    add = os.path.join(MECH, "a.add.xml")
    stops = [("SA", "A2B2", "lo"), ("S1", "A2B2", "hi"), ("S2", "B2C2", "hi"),
             ("S5", "E2F2", "hi")]
    write_stops(N, add, stops)
    board_t, t1, t2 = 300.0, 200.0, 200.0

    def picks_transfer(Tdir, w):
        vehs = [
            veh("DIR.0", "DIR", 0, CORR, [("SA", board_t), ("S5", board_t + Tdir)]),
            veh("X1.0", "X1", 0, ["A2B2", "B2C2"], [("SA", board_t), ("S2", board_t + t1)]),
            veh("X2.0", "X2", 0, ["B2C2", "C2D2", "D2E2", "E2F2"],
                [("S2", board_t + t1 + w), ("S5", board_t + t1 + w + t2)]),
        ]
        per = ['    <person id="q" depart="60.00" type="ped">'
               '<personTrip from="A2B2" to="E2F2" modes="public" departPos="25" '
               'arrivalPos="760"/></person>']
        ch = chosen(route("a", N, add, vehs, per))["q"]
        return bool(ch) and ch[0] != "DIR.0", ch

    rows = []
    for w in (-120.0, -60.0, 0.0, 30.0, 120.0, 300.0):   # transfer wait at the hub
        # deterministic coarse-then-fine scan (a bisection is unsafe here: the
        # relation is monotone in theory but a stale concurrent writer once
        # corrupted the probe, so scan explicitly)
        sw = None
        okhi, chhi = picks_transfer(1400, w)
        if okhi:
            prev = 100
            for Tdir in range(100, 1401, 20):
                ok, _ = picks_transfer(Tdir, w)
                if ok:
                    for t in range(prev, Tdir + 1):
                        ok2, _ = picks_transfer(t, w)
                        if ok2:
                            sw = t; break
                    break
                prev = Tdir
        Txfer = t1 + w + t2
        rows.append(dict(transfer_wait=w, T_xfer_total=Txfer, switch_T_dir=sw,
                         implied_penalty_s=(sw - Txfer) if sw else None,
                         two_seat_plan_accepted=bool(okhi), plan_at_Tdir_1400=chhi))
        print(f"  transfer wait {w:6.0f}s : two-seat plan costs {Txfer:.0f}s; "
              f"router drops the one-seat ride at T_dir = {sw} s "
              f"-> implied extra transfer penalty = "
              f"{(sw - Txfer) if sw else 'n/a'} s ; two-seat plan usable: {okhi}")

    # variant: transfer requires a real WALK between two DIFFERENT stops
    add2 = os.path.join(MECH, "a2.add.xml")
    write_stops(N, add2, [("SA", "A2B2", "lo"), ("S2", "B2C2", "hi"),
                          ("S2b", "C2D2", "lo"), ("S5", "E2F2", "hi")])
    walk_rows = []
    for w in (120.0, 240.0):
        sw = None
        for Tdir in range(100, 1401, 5):
            vehs = [veh("DIR.0", "DIR", 0, CORR, [("SA", board_t), ("S5", board_t + Tdir)]),
                    veh("X1.0", "X1", 0, ["A2B2", "B2C2"],
                        [("SA", board_t), ("S2", board_t + t1)]),
                    veh("X2.0", "X2", 0, ["C2D2", "D2E2", "E2F2"],
                        [("S2b", board_t + t1 + w), ("S5", board_t + t1 + w + t2)])]
            per = ['    <person id="q" depart="60.00" type="ped">'
                   '<personTrip from="A2B2" to="E2F2" modes="public" departPos="25" '
                   'arrivalPos="760"/></person>']
            ch = chosen(route("a2", N, add2, vehs, per))["q"]
            if ch and ch[0] != "DIR.0":
                sw = Tdir; break
        walk_rows.append(dict(hub_gap=w, switch_T_dir=sw,
                              nominal_two_seat=t1 + w + t2))
        print(f"  cross-junction transfer, hub gap {w:.0f}s: switch at T_dir = {sw} s "
              f"(nominal two-seat {t1+w+t2:.0f}s -> gap {sw and sw-(t1+w+t2)} s is the "
              f"transfer WALK time the router charges)")
    return dict(same_stop=rows, cross_junction_walk=walk_rows)


# ---------------------------------------------------------------- (c) -------
def test_schedule_awareness(N):
    add = os.path.join(MECH, "c.add.xml")
    write_stops(N, add, [("SA", "A2B2", "lo"), ("S5", "E2F2", "hi")])
    out = {}
    # c1: does the router trade WAIT against IN-VEHICLE, or minimise in-vehicle?
    #     P: departs 200, in-vehicle 600 -> arrives 800   (long ride, leaves soon)
    #     Q: departs 700, in-vehicle 150 -> arrives 850   (short ride, leaves late)
    c1 = []
    for swap in (False, True):
        pd, pv_, qd, qv = (200, 600, 700, 150) if not swap else (200, 600, 500, 150)
        vehs = [veh("P.0", "P", 0, CORR, [("SA", pd), ("S5", pd + pv_)]),
                veh("Q.0", "Q", 0, CORR, [("SA", qd), ("S5", qd + qv)])]
        per = ['    <person id="q" depart="30.00" type="ped">'
               '<personTrip from="A2B2" to="E2F2" modes="public" departPos="25" '
               'arrivalPos="760"/></person>']
        ch = chosen(route("c1", N, add, vehs, per))["q"]
        c1.append(dict(P_arrival=pd + pv_, Q_arrival=qd + qv, chose=ch))
        print(f"  c1: P arrives {pd+pv_}, Q arrives {qd+qv} -> router chose {ch}")
    out["c1_arrival_time_minimisation"] = c1

    # c2: does raising a line's FREQUENCY change route choice?
    #     SLOWFREQ: in-vehicle 520 s, headway h  (varied)
    #     FASTRARE: in-vehicle 330 s, headway 900 s, fixed phase
    c2 = []
    for h in (120, 180, 300, 600, 900):
        vehs = []
        k = 0
        while k * h < 3600:
            d = k * h
            vehs.append(veh(f"SF.{k}", "SF", d, CORR, [("SA", d + 30), ("S5", d + 30 + 520)]))
            k += 1
        k = 0
        while k * 900 < 3600:
            d = k * 900 + 60
            vehs.append(veh(f"FR.{k}", "FR", d, CORR, [("SA", d + 30), ("S5", d + 30 + 330)]))
            k += 1
        per = []
        for i in range(240):
            dep = 100 + i * 12.0
            per.append(f'    <person id="q{i}" depart="{dep:.1f}" type="ped">'
                       f'<personTrip from="A2B2" to="E2F2" modes="public" departPos="25" '
                       f'arrivalPos="760"/></person>')
        ch = chosen(route(f"c2_{h}", N, add, vehs, per))
        sf = sum(1 for v in ch.values() if v and v[0].startswith("SF"))
        fr = sum(1 for v in ch.values() if v and v[0].startswith("FR"))
        walk = sum(1 for v in ch.values() if not v)
        c2.append(dict(headway_SF=h, chose_SF=sf, chose_FR=fr, walked=walk,
                       share_SF=sf / max(1, sf + fr)))
        print(f"  c2: SF headway {h:4d}s (in-veh 520s) vs FR headway 900s (in-veh 330s)"
              f"  -> {sf:3d} chose SF, {fr:3d} chose FR, {walk} walked "
              f"(SF share {sf/max(1,sf+fr):.3f})")
    out["c2_frequency_changes_route_choice"] = c2
    return out


# ---------------------------------------------------------------- (b)(d) ----
def test_personinfo_and_censoring(tripinfo, summary, log):
    pis = T.parse_personinfos(tripinfo)
    comp = [p for p in pis if p["complete"]]
    err = [abs(p["total"] - p["reported_duration"]) for p in comp]
    tel = T.teleports_from_summary(summary)
    d = dict(n_persons=len(pis), n_complete=len(comp),
             n_incomplete=len(pis) - len(comp),
             n_stranded_at_stop=sum(1 for p in pis if p["stranded"]),
             n_walk_only=sum(1 for p in pis if p["mode"] == "walk"),
             reconciliation_max_abs_error_s=max(err) if err else None,
             reconciliation_mismatches=sum(1 for e in err if e > 0.6),
             teleports_summary_last_step=tel,
             teleports_log_lines=T.teleport_count(log))
    return d, pis


def main():
    N = net()
    res = {}
    print("(a) transfer penalty / minimum connection buffer in duarouter")
    res["a_transfer_penalty"] = test_transfer_penalty(N)
    print("(c) schedule awareness")
    res["c_schedule_awareness"] = test_schedule_awareness(N)

    print("(b)+(d) personinfo stage semantics and censoring, on the real scenario")
    run_dir = os.path.join(WORK, "smoke", "cov2", "runOP")
    log = open(os.path.join(run_dir, "sumo.log")).read()
    d, pis = test_personinfo_and_censoring(
        os.path.join(run_dir, "tripinfo.xml"),
        os.path.join(run_dir, "summary.xml"), log)
    res["bd_personinfo_and_censoring"] = d
    for k, v in d.items():
        print(f"   {k}: {v}")

    with open(os.path.join(WORK, "mechanism_verification.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("\nwritten", os.path.join(WORK, "mechanism_verification.json"))


if __name__ == "__main__":
    main()
