"""TESTBED A rig -- isolated signalised approach, permanently spilled-back queue.

Method reused verbatim from `measure-saturation-flow-and-validate-webster-method`:
  * only the four THROUGH movements ever get green or demand (no turning confounds);
  * --step-length 0.1 (1 s cannot resolve ~1.5-2 s saturation headways);
  * departSpeed="max" (departSpeed=0 caps insertion at ~1500 veh/h/lane);
  * rear-bumper (state="leave") crossing convention for headways;
  * a laneAreaDetector clipped with an explicit endPos == the lane's COMPILED
    length (an oversized one silently measures the upstream lane);
  * the window-free green-duration regression N_d(g) = (s/3600)(g - l1 + e)
    is the PRIMARY saturation-flow estimator; its R^2 doubles as proof the
    standing queue never ran out at any tested green duration.
  * every run gets its own directory -- detector `file` paths resolve relative
    to the ADDITIONAL file's own directory, so shared dirs silently collide.
"""
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

from common import (WORK, NETS, SIG_SPEED, YELLOW, ALLRED, STEP, G_EW,
                    SIG_TEND, SIG_WARMUP, SIG_DEMAND, vtype_xml, run_sumo)
import demand

SIG_NET = os.path.join(NETS, "cross.net.xml")
SIG_LANE_LEN = 292.80          # verified from the compiled net (build_networks.py)
APPROACHES = ["N", "S", "E", "W"]
ROUTES = {"N": "in_N out_S", "S": "in_S out_N", "E": "in_E out_W", "W": "in_W out_E"}

def _link_map(net):
    """Derive the tlLogic link-index map from the COMPILED net -- never hardcode
    it.  (Hardcoding a map copied from a differently-built cross network silently
    gave green to the wrong movements and left 3 of 4 approaches at 0 discharge.)"""
    root = ET.parse(net).getroot()
    m = {}
    for c in root.findall("connection"):
        li = c.get("linkIndex")
        if li is not None:
            m[(c.get("from"), c.get("to"))] = int(li)
    return m, max(m.values()) + 1


LINKS, N_LINKS = _link_map(SIG_NET)
NS_THROUGH = (LINKS[("in_N", "out_S")], LINKS[("in_S", "out_N")])
EW_THROUGH = (LINKS[("in_E", "out_W")], LINKS[("in_W", "out_E")])


def _state(idx, ch):
    s = ["r"] * N_LINKS
    for i in idx:
        s[i] = ch
    return "".join(s)


def tls_xml(g_ns):
    return ('<additional>\n'
            '  <tlLogic id="C" type="static" programID="pce" offset="0">\n'
            '    <phase duration="%g" state="%s"/>\n'
            '    <phase duration="%g" state="%s"/>\n'
            '    <phase duration="%g" state="%s"/>\n'
            '    <phase duration="%g" state="%s"/>\n'
            '  </tlLogic>\n</additional>\n'
            % (g_ns, _state(NS_THROUGH, "G"), YELLOW, _state(NS_THROUGH, "y"),
               G_EW, _state(EW_THROUGH, "G"), YELLOW, _state(EW_THROUGH, "y")))


def prepare(outdir, g_ns, p, seed, hv_attrs, car_attrs):
    os.makedirs(outdir, exist_ok=True)
    rou = os.path.join(outdir, "sig.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write(vtype_xml("car", car_attrs, SIG_SPEED))
        f.write(vtype_xml("hv", hv_attrs, SIG_SPEED))
        for rid, edges in ROUTES.items():
            f.write('  <route id="r_%s" edges="%s"/>\n' % (rid, edges))
    ntot, nhv = demand.write_signal_routes(rou, APPROACHES, SIG_DEMAND, SIG_TEND,
                                           p, seed, "car", "hv")
    with open(rou, "a") as f:
        f.write('</routes>\n')

    add = os.path.join(outdir, "det.add.xml")
    C = g_ns + YELLOW + G_EW + YELLOW
    with open(add, "w") as f:
        f.write('<additional>\n')
        f.write('  <instantInductionLoop id="inst_N" lane="in_N_0" pos="-0.1" '
                'friendlyPos="true" file="instant_N.xml"/>\n')
        f.write('  <instantInductionLoop id="inst_S" lane="in_S_0" pos="-0.1" '
                'friendlyPos="true" file="instant_S.xml"/>\n')
        # endPos clipped to the COMPILED lane length; an oversized detector would
        # silently continue onto the upstream lane and corrupt queue verification
        for a in ("N", "S"):
            f.write('  <laneAreaDetector id="e2_%s" lane="in_%s_0" pos="0" endPos="%.2f" '
                    'friendlyPos="true" period="%g" file="e2_%s.xml"/>\n'
                    % (a, a, SIG_LANE_LEN, C, a))
        f.write('</additional>\n')
    tls = os.path.join(outdir, "tls.add.xml")
    with open(tls, "w") as f:
        f.write(tls_xml(g_ns))
    return rou, add, tls, ntot, nhv


def run(outdir, g_ns, p, seed, hv_attrs, car_attrs):
    rou, add, tls, ntot, nhv = prepare(outdir, g_ns, p, seed, hv_attrs, car_attrs)
    args = ["-n", SIG_NET, "-r", "sig.rou.xml", "-a", "det.add.xml,tls.add.xml",
            "--begin", "0", "--end", str(SIG_TEND), "--step-length", str(STEP),
            "--seed", str(seed), "--time-to-teleport", "-1",
            "--no-step-log", "true", "--xml-validation", "never",
            "--duration-log.statistics", "true",
            "--statistic-output", "stats.xml", "--collision.action", "warn"]
    out, err = run_sumo(args, "sig g=%g p=%g s=%d" % (g_ns, p, seed), cwd=outdir)
    with open(os.path.join(outdir, "sumo.stderr.txt"), "w") as f:
        f.write(err)
    return dict(n_generated=ntot, n_hv_generated=nhv)


# ------------------------------------------------------------------ parsing --
def parse_instant(path):
    """-> sorted list of (t_leave, 'c'|'t') rear-bumper stop-line crossings."""
    ev = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave":
            # NB: `id` is the DETECTOR id; the vehicle is in `vehID`.
            vid = el.get("vehID") or ""
            ev.append((float(el.get("time")), vid.rsplit("_", 1)[-1],
                       el.get("type"), float(el.get("length", 0)),
                       float(el.get("speed", 0))))
            el.clear()
    ev.sort()
    return ev


def parse_queue(path, warmup):
    vals = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            if float(el.get("begin")) >= warmup:
                vals.append(float(el.get("maxVehicleNumber")))
            el.clear()
    return (min(vals), sum(vals) / len(vals), len(vals)) if vals else (None, None, 0)


def parse_stats(path):
    r = ET.parse(path).getroot()
    d = {}
    for tag in ("vehicles", "teleports", "safety", "vehicleTripStatistics"):
        el = r.find(tag)
        if el is not None:
            d[tag] = dict(el.attrib)
    return d


def cycles(g_ns, t_end, warmup):
    C = g_ns + YELLOW + G_EW + YELLOW
    return [i * C for i in range(int(t_end // C) + 1)
            if warmup <= i * C < t_end - C], C


def analyse_run(outdir, g_ns, approaches=("N", "S"), t_end=SIG_TEND,
                warmup=SIG_WARMUP):
    """Per-cycle discharge counts + per-vehicle rear-bumper headways, pooled over
    the two NS approaches (identical geometry, identical phase)."""
    onsets, C = cycles(g_ns, t_end, warmup)
    span = g_ns + YELLOW + ALLRED
    counts, exts, hlist = [], [], []
    qmins, qmeans, qn = [], [], 0
    for app in approaches:
        ev = parse_instant(os.path.join(outdir, "instant_%s.xml" % app))
        for t0 in onsets:
            win = [e for e in ev if t0 <= e[0] < t0 + span]
            counts.append(len(win))
            if win:
                exts.append(max(0.0, win[-1][0] - (t0 + g_ns)))
            prev = t0
            for n, e in enumerate(win, start=1):
                # (queue position, rear-bumper headway, class of the FOLLOWING
                #  vehicle -- the headway of vehicle n is attributed to n itself,
                #  since it is n's own length/acceleration that produces it)
                hlist.append((n, e[0] - prev, e[1], e[4]))
                prev = e[0]
        a, b, c = parse_queue(os.path.join(outdir, "e2_%s.xml" % app), warmup)
        if a is not None:
            qmins.append(a)
            qmeans.append(b)
            qn += c
    return dict(green=g_ns, cycle=C, n_cycles=len(onsets),
                n_approach_cycles=len(counts),
                veh_per_cycle=sum(counts) / len(counts) if counts else 0.0,
                counts_min=min(counts) if counts else 0,
                counts_max=max(counts) if counts else 0,
                ext_into_yellow=sum(exts) / len(exts) if exts else 0.0,
                queue_min=min(qmins) if qmins else None,
                queue_mean=sum(qmeans) / len(qmeans) if qmeans else None,
                queue_intervals=qn,
                headways=hlist,
                hv_share_discharged=(sum(1 for _, _, c, _ in hlist if c == "t") /
                                     len(hlist)) if hlist else 0.0)
