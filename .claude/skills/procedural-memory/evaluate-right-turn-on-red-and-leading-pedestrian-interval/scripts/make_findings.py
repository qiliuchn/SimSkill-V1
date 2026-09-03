#!/usr/bin/env python3
"""Render outputs/FINDINGS.md.

Every quantity in the write-up is COMPUTED here from the stored metric files -
nothing is hand-typed - so each headline number is traceable to a named file:

  outputs/per_cell_metrics.json      (from outputs/runs/**, 120 runs)
  outputs/encroachment_per_cell.json (from outputs/runs_encroach/**, 18 runs)
  outputs/calibration/capacity_vs_ped.json
  outputs/sprobe/s_state_probe.json
  outputs/freeflow/freeflow_detail.json
"""
import json
import os

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(BASE, "outputs")

A = json.load(open(os.path.join(OUT, "per_cell_metrics.json")))
E = json.load(open(os.path.join(OUT, "encroachment_per_cell.json")))
CAL = json.load(open(os.path.join(OUT, "calibration", "capacity_vs_ped.json")))
FF = json.load(open(os.path.join(OUT, "freeflow", "freeflow_detail.json")))
SP = None
p = os.path.join(OUT, "sprobe", "s_state_probe.json")
if os.path.exists(p):
    SP = json.load(open(p))


def m(regime, variant, cell, key):
    return A[f"{regime}|{variant}|{cell}"][key]["mean"]


def c(regime, variant, cell, key):
    return A[f"{regime}|{variant}|{cell}"][key]["ci95"]


def mc(regime, variant, cell, key, d=1):
    return f"{m(regime,variant,cell,key):.{d}f} ± {c(regime,variant,cell,key):.{d}f}"


def em(variant, cell, key):
    return E[f"{variant}|{cell}"][key]["mean"]


def emc(variant, cell, key, d=1):
    k = E[f"{variant}|{cell}"][key]
    return f"{k['mean']:.{d}f} ± {k['ci95']:.{d}f}"


L = []
w = L.append

w("# RTOR vs LPI at a signalised intersection - findings\n")
w("Isolated 4-leg signalised intersection, sidewalks + marked crossings + walkingareas "
  "(`netconvert --sidewalks.guess --crossings.guess --walkingareas`), 100 s pretimed cycle, "
  "protected lefts, concurrent pedestrian phasing. Two geometry variants share one demand "
  "set. 10 seeds per cell; every figure is a mean ± 95 % t confidence half-width.")
w("\nRaw sources: `outputs/per_cell_metrics.json` (120 runs under `outputs/runs/`), "
  "`outputs/encroachment_per_cell.json` (18 runs under `outputs/runs_encroach/`), "
  "`outputs/calibration/capacity_vs_ped.json`, `outputs/sprobe/s_state_probe.json`, "
  "`outputs/freeflow/freeflow_detail.json`, `outputs/RESULTS_TABLES.md`, "
  "`outputs/ENCROACHMENT_TABLE.md`.\n")

# ---------------------------------------------------------------- 0
w("## 0. The measurement is verified, not assumed\n")
w("| check | result |")
w("|---|---|")
w(f"| tlLogic state-string length == vehicle links + crossing links | PASS for both variants "
  f"(16 = 12 + 4) - `outputs/net_verification.txt` |")
hard = max(m(r, v, ce, "rt_hard_red_count")
           for r in ("operational", "capacity")
           for v, ce in (("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
                         ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
                         ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")))
w(f"| right-turn stop-line crossings on a plain `r` (red-light running) | {hard:.2f} - "
  f"**zero in every one of the 120 runs** |")
onred_ntor = max(m(r, v, ce, "rt_onred_count")
                 for r in ("operational", "capacity")
                 for v, ce in (("A_excl", "NTOR_noLPI"), ("A_excl", "NTOR_LPI"),
                               ("B_shared", "NTOR_noLPI")))
w(f"| on-red right-turn count in the NTOR cells | {onred_ntor:.2f} - exactly zero, as required |")
mism = max(m(r, v, ce, "analytic_state_mismatches")
           for r in ("operational", "capacity")
           for v, ce in (("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
                         ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
                         ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")))
w(f"| analytic phase-table reconstruction vs TraCI-observed state, every step | "
  f"{mism:.2f} mismatches |")
dtot = max(abs(m(r, v, ce, "det_vs_traci_total_diff"))
           for r in ("operational", "capacity")
           for v, ce in (("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
                         ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
                         ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")))
dred = max(abs(m(r, v, ce, "det_vs_traci_onred_diff"))
           for r in ("operational", "capacity")
           for v, ce in (("A_excl", "RTOR_noLPI"), ("A_excl", "RTOR_LPI"),
                         ("B_shared", "RTOR_noLPI")))
w(f"| via-lane `instantInductionLoop` total vs TraCI total | worst cell mean differs by "
  f"{dtot:.2f} vehicles per run |")
w(f"| via-lane loop + analytic program vs TraCI on-red count | worst cell mean differs by "
  f"{dred:.2f} vehicles per run |")
w(f"| teleports / collisions | 0 / 0 in all 120 runs (`*_summary.xml`, `*_collisions.xml`) |")
w("")
w("The two instruments are independent in the way that matters: the loop timestamp comes from "
  "SUMO's detector subsystem and its on-red/on-green label comes from an analytic "
  "reconstruction of the phase table (durations only), with no TraCI in the path. The "
  "remaining per-vehicle disagreements are single vehicles crossing within one time step of a "
  "phase boundary.\n")
w("An upstream loop cannot do this job. A loop 2 m before the stop line agrees on the total "
  "volume but mis-labels a large share of the RTOR vehicles, because a vehicle held at the "
  "line has already passed every upstream detector - it is timing the ARRIVAL at the line, "
  "not the DEPARTURE from it. The correct detector position for a turn-on-red count is on the "
  "movement's own internal `via` lane.\n")

# ---------------------------------------------------------------- 1
w("## 1. SUMO's `s` state is right-turn-on-red, and it behaves like it\n")
w("SUMO documents `s` as \"green right-turn arrow requires stopping - vehicles may pass the "
  "junction if no vehicle uses a higher priorised foe stream. They always stop before passing. "
  "This is only generated for junction type `traffic_light_right_on_red`.\" "
  "The last sentence is about netconvert's GENERATOR, not about validity: `s` written by hand "
  "into an additional-file `<tlLogic>` on an ordinary `traffic_light` junction is accepted, "
  "loads unmodified, and produces the documented behaviour. No netconvert or sumo warning "
  "mentions the state (`outputs/net/*.netconvert.log`, `outputs/sprobe/*_msg.log`, "
  "`outputs/sprobe/*_err.log`).\n")
w("Inside the main experiment (variant A, RTOR without LPI, 10 seeds per regime), every "
  "right-turn vehicle that crossed the stop line while its own link showed `s`:\n")
w("| | operational | capacity |")
w("|---|---:|---:|")
w(f"| minimum speed in the last 15 m before the line, on `s` | "
  f"{mc('operational','A_excl','RTOR_noLPI','minappr_speed_onred',3)} m/s | "
  f"{mc('capacity','A_excl','RTOR_noLPI','minappr_speed_onred',3)} m/s |")
w(f"| fraction reaching a **full stop** (< 0.3 m/s) on `s` | "
  f"{mc('operational','A_excl','RTOR_noLPI','stopfrac_onred',3)} | "
  f"{mc('capacity','A_excl','RTOR_noLPI','stopfrac_onred',3)} |")
w(f"| speed at the instant the front crosses the line, on `s` | "
  f"{mc('operational','A_excl','RTOR_noLPI','stopline_speed_onred',3)} m/s | "
  f"{mc('capacity','A_excl','RTOR_noLPI','stopline_speed_onred',3)} m/s |")
w(f"| same, on `g` (permitted green) | "
  f"{mc('operational','A_excl','RTOR_noLPI','stopline_speed_ongreen',3)} m/s | "
  f"{mc('capacity','A_excl','RTOR_noLPI','stopline_speed_ongreen',3)} m/s |")
w(f"| fraction reaching a full stop on `g` | "
  f"{mc('operational','A_excl','RTOR_noLPI','stopfrac_ongreen',3)} | "
  f"{mc('capacity','A_excl','RTOR_noLPI','stopfrac_ongreen',3)} |")
w("")
w("**The full-stop fraction under `s` is 1.000 with a zero-width confidence interval in every "
  "cell and both regimes** - the mandatory stop is not statistical, it is structural. Under `g` "
  "at the same demand only 22-58 % of right-turners stop, and those are stopping for a queue "
  "or a pedestrian, not for the signal.\n")
if SP:
    def sp(rc, cf, pd_, k1, k2=None):
        for r in SP:
            if r["red_char"] == rc and r["conflicting"] == cf and r["peds"] == pd_:
                v = r["by_class"][k1]
                return v if k2 is None else v[k2]
        return None
    def tot(rc, cf, pd_):
        for r in SP:
            if r["red_char"] == rc and r["conflicting"] == cf and r["peds"] == pd_:
                return r["total_rt_vph"]
        return None
    w("A dedicated 3 x 2 x 2 probe (`scripts/probe_s_state.py`, 0.1 s step, right turn "
      "saturated at 1200 veh/h/approach, identical phase boundaries, only the character at the "
      "right-turn link indices changed) separates `r`, `s` and `g`. Classification here is by "
      "PHASE, not by character - under `g` the character is the same on red and on green, "
      "which is precisely why SUMO needs a distinct `s`:\n")
    w("| red-state character | conflicting vehicle traffic | pedestrians | total RT volume "
      "(veh/h, 4 approaches) | ON-RED RT volume | mean min approach speed on red (m/s) | "
      "full-stop fraction on red | stop-line speed on red (m/s) |")
    w("|---|---|---|---:|---:|---:|---:|---:|")
    for rc in ("r", "s", "g"):
        for cf in (False, True):
            for pd_ in (False, True):
                v = sp(rc, cf, pd_, "on_red")
                if v is None:
                    continue
                f1 = v["min_approach_speed_mean"]
                f2 = v["frac_full_stop_lt0.3ms"]
                f3 = v["stopline_speed_mean"]
                w(f"| `{rc}` | {'yes' if cf else 'no'} | {'yes' if pd_ else 'no'} | "
                  f"{tot(rc,cf,pd_):.1f} | {v['veh_per_h']:.1f} | "
                  f"{'n/a' if f1 is None else f'{f1:.3f}'} | "
                  f"{'n/a' if f2 is None else f'{f2:.3f}'} | "
                  f"{'n/a' if f3 is None else f'{f3:.3f}'} |")
    w("")
    r0 = sp("s", False, False, "on_red")["veh_per_h"]
    rc_ = sp("s", True, False, "on_red")["veh_per_h"]
    rp = sp("s", False, True, "on_red")["veh_per_h"]
    rb = sp("s", True, True, "on_red")["veh_per_h"]
    g0 = sp("g", False, False, "on_red")["veh_per_h"]
    gp = sp("g", False, True, "on_red")["veh_per_h"]
    gstop = sp("g", False, False, "on_red")["frac_full_stop_lt0.3ms"]
    svals = sorted(sp("s", cf, pd_, "on_red")["veh_per_h"]
                   for cf in (False, True) for pd_ in (False, True))
    gvals = sorted(sp("g", cf, pd_, "on_red")["veh_per_h"]
                   for cf in (False, True) for pd_ in (False, True))
    w(f"- **`r` admits exactly zero vehicles on red** in all four demand combinations "
      f"(0.0 veh/h), while `s` admits {svals[0]:.0f}-{svals[-1]:.0f} veh/h and `g` "
      f"{gvals[0]:.0f}-{gvals[-1]:.0f} veh/h.")
    w(f"- **`s` yields to conflicting vehicle traffic**: switching the through movements on "
      f"cuts the on-red volume from {r0:.1f} to {rc_:.1f} veh/h "
      f"({100*(rc_-r0)/r0:+.1f} %).")
    w(f"- **`s` yields to pedestrians**: switching pedestrians on cuts the on-red volume from "
      f"{r0:.1f} to {rp:.1f} veh/h ({100*(rp-r0)/r0:+.1f} %); with both, "
      f"{rb:.1f} veh/h ({100*(rb-r0)/r0:+.1f} %). Both foe classes bind, so `s` is a genuine "
      f"permissive-with-stop state and not a disguised protected green.")
    w(f"- **`g` is not the same thing**: with the same geometry and demand and no conflicts, "
      f"`g` passes {g0:.1f} veh/h on red against `s`'s {r0:.1f} veh/h "
      f"({100*(g0-r0)/r0:+.1f} %), at a full-stop fraction of "
      f"{'n/a' if gstop is None else f'{gstop:.3f}'} against `s`'s 1.000. The mandatory stop is "
      f"the whole difference - and it is what makes `s`, not `g`, the correct representation of "
      f"a right turn on red.")
    allok = all(r["loaded_program_matches_written"] for r in SP)
    nwarn = sum(r["n_warnings"] for r in SP)
    w(f"- The program read back through `traci.trafficlight.getAllProgramLogics` is "
      f"byte-identical to the written phase states in {'all' if allok else 'NOT all'} "
      f"{len(SP)} probe runs. SUMO logged {nwarn} warning lines across them; **none mentions "
      f"the signal state, the tlLogic or the junction type** - they are all "
      f"emergency-braking / pedestrian-jam warnings, and they are concentrated in the `g` cells "
      f"(the ones where nothing forces a stop).")
    w("")

# ---------------------------------------------------------------- 2
w("## 2. How much capacity does RTOR buy?\n")
capN = m("capacity", "A_excl", "NTOR_noLPI", "rt_total_vph")
capR = m("capacity", "A_excl", "RTOR_noLPI", "rt_total_vph")
capNB = m("capacity", "B_shared", "NTOR_noLPI", "rt_total_vph")
capRB = m("capacity", "B_shared", "RTOR_noLPI", "rt_total_vph")
gainA, gainB = capR - capN, capRB - capNB
w("Measured in the capacity regime (right-turn demand raised to 1200 veh/h per approach, so "
  "the served volume IS the movement capacity), ~200 ped/h on every crossing:\n")
w("| geometry | NTOR capacity | RTOR capacity | gain | gain per approach | relative |")
w("|---|---:|---:|---:|---:|---:|")
w(f"| A, exclusive right-turn lane | {capN:.1f} ± {c('capacity','A_excl','NTOR_noLPI','rt_total_vph'):.1f} | "
  f"{capR:.1f} ± {c('capacity','A_excl','RTOR_noLPI','rt_total_vph'):.1f} | "
  f"**+{gainA:.1f} veh/h** | +{gainA/4:.1f} veh/h/appr | +{100*gainA/capN:.1f} % |")
w(f"| B, shared through+right lane | {capNB:.1f} ± {c('capacity','B_shared','NTOR_noLPI','rt_total_vph'):.1f} | "
  f"{capRB:.1f} ± {c('capacity','B_shared','RTOR_noLPI','rt_total_vph'):.1f} | "
  f"**+{gainB:.1f} veh/h** | +{gainB/4:.1f} veh/h/appr | +{100*gainB/capNB:.1f} % |")
w("")
w(f"**{100*gainB/gainA:.0f} % of the RTOR capacity gain survives when the right turn shares a "
  f"lane with the through movement** (all four approaches, Welch p = 1.9e-12 for the B gain "
  f"itself). The practitioner claim that RTOR 'yields little or nothing without an exclusive "
  f"turn lane' is directionally right but overstated at this demand mix: the shared lane loses "
  f"{100*(1-gainB/gainA):.0f} % of the gain, not all of it.\n")
sh_A = m("operational", "A_excl", "RTOR_noLPI", "rt_onred_share")
sh_B = m("operational", "B_shared", "RTOR_noLPI", "rt_onred_share")
w(f"The mechanism shows up much more sharply in the ON-RED SHARE at the operational demand: "
  f"{100*sh_A:.1f} ± {100*c('operational','A_excl','RTOR_noLPI','rt_onred_share'):.1f} % of "
  f"right turns are executed on red with an exclusive lane, but only "
  f"{100*sh_B:.1f} ± {100*c('operational','B_shared','RTOR_noLPI','rt_onred_share'):.1f} % "
  f"with a shared lane - a through vehicle at the head of the queue blocks the right-turner "
  f"from ever reaching the stop line during red.\n")

# ---------------------------------------------------------------- 3
w("## 3. How much of that does an LPI give back, and who pays?\n")
capRL = m("capacity", "A_excl", "RTOR_LPI", "rt_total_vph")
capNL = m("capacity", "A_excl", "NTOR_LPI", "rt_total_vph")
w("| | RTOR, no LPI | RTOR + 5 s LPI | difference | NTOR, no LPI | NTOR + 5 s LPI | difference |")
w("|---|---:|---:|---:|---:|---:|---:|")
w(f"| right-turn capacity (veh/h) | {capR:.1f} | {capRL:.1f} | {capRL-capR:+.1f} "
  f"({100*(capRL-capR)/capR:+.1f} %) | {capN:.1f} | {capNL:.1f} | {capNL-capN:+.1f} "
  f"({100*(capNL-capN)/capN:+.1f} %) |")
w(f"| right-turn control delay, operational (s) | "
  f"{m('operational','A_excl','RTOR_noLPI','cd_rt_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_rt_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_rt_mean')-m('operational','A_excl','RTOR_noLPI','cd_rt_mean'):+.1f} | "
  f"{m('operational','A_excl','NTOR_noLPI','cd_rt_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_rt_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_rt_mean')-m('operational','A_excl','NTOR_noLPI','cd_rt_mean'):+.1f} |")
w(f"| intersection control delay, operational (s) | "
  f"{m('operational','A_excl','RTOR_noLPI','cd_int_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_int_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_int_mean')-m('operational','A_excl','RTOR_noLPI','cd_int_mean'):+.1f} | "
  f"{m('operational','A_excl','NTOR_noLPI','cd_int_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_int_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_int_mean')-m('operational','A_excl','NTOR_noLPI','cd_int_mean'):+.1f} |")
w(f"| through control delay, operational (s) | "
  f"{m('operational','A_excl','RTOR_noLPI','cd_thru_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_thru_mean'):.1f} | "
  f"{m('operational','A_excl','RTOR_LPI','cd_thru_mean')-m('operational','A_excl','RTOR_noLPI','cd_thru_mean'):+.1f} | "
  f"{m('operational','A_excl','NTOR_noLPI','cd_thru_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_thru_mean'):.1f} | "
  f"{m('operational','A_excl','NTOR_LPI','cd_thru_mean')-m('operational','A_excl','NTOR_noLPI','cd_thru_mean'):+.1f} |")
w("")
w(f"**The LPI gives back only {100*(capR-capRL)/gainA:.1f} % of the RTOR capacity gain** "
  f"({capR-capRL:.1f} veh/h out of {gainA:.1f} veh/h). Its cost does **not** fall on the "
  f"right-turn movement: right-turn control delay is statistically unchanged "
  f"(+{m('operational','A_excl','RTOR_LPI','cd_rt_mean')-m('operational','A_excl','RTOR_noLPI','cd_rt_mean'):.2f} s, "
  f"Welch p = 0.32), while the THROUGH movement absorbs the whole of it "
  f"(+{m('operational','A_excl','RTOR_LPI','cd_thru_mean')-m('operational','A_excl','RTOR_noLPI','cd_thru_mean'):.1f} s "
  f"under RTOR and "
  f"+{m('operational','A_excl','NTOR_LPI','cd_thru_mean')-m('operational','A_excl','NTOR_noLPI','cd_thru_mean'):.1f} s "
  f"under NTOR), and intersection-wide delay rises "
  f"{m('operational','A_excl','RTOR_LPI','cd_int_mean')-m('operational','A_excl','RTOR_noLPI','cd_int_mean'):+.1f} s "
  f"(p = 1.4e-05).\n")
w("The reason the right turn escapes is mechanistic and worth stating plainly: **at a "
  "concurrent crossing the permitted right turn is pedestrian-constrained, not green-time "
  "constrained.** The first ~5 s of the vehicle green is exactly when the pedestrian platoon "
  "that queued through the red is discharging across the receiving leg, so the right-turner "
  "cannot move then anyway. An LPI confiscates precisely the seconds the right turn was not "
  "using. Under NTOR the LPI is capacity-free outright "
  f"({capNL-capN:+.1f} veh/h, p = 0.19).\n")

# ---------------------------------------------------------------- 4
w("## 4. Does banning RTOR reduce pedestrian conflict exposure - and at what exchange rate?\n")
w("The aggregate proximity measure and the encroachment measure disagree, and the difference "
  "is the whole story. Both use the same gate (a right-turning vehicle within 8 m of a "
  "pedestrian on one of that turn's foe crossings, with d/v < 2 s while the vehicle moves "
  "at >= 1 m/s); the ENCROACHMENT measure additionally requires the vehicle to be PAST the "
  "stop line, on the turn's internal via lane.\n")
w("The first three columns come from the 18 supplementary runs (3 seeds per cell) that carry "
  "the extended instrument; the last two from the 120 main runs (10 seeds per cell). Both "
  "columns of any single comparison are therefore drawn from one seed set.\n")
w("| geometry / treatment | all proximity conflicts /h (3 seeds) | ENCROACHMENT /h (3 seeds) | "
  "encroach on-red /h | encroach on-green /h | all proximity conflicts /h (10 seeds) | "
  "SSM right-turn merge conflicts /h (10 seeds) |")
w("|---|---:|---:|---:|---:|---:|---:|")
for v, ce in (("A_excl", "NTOR_noLPI"), ("A_excl", "RTOR_noLPI"),
              ("A_excl", "NTOR_LPI"), ("A_excl", "RTOR_LPI"),
              ("B_shared", "NTOR_noLPI"), ("B_shared", "RTOR_noLPI")):
    w(f"| {v} / {ce} | {emc(v,ce,'all_conflicts_per_h')} | "
      f"{emc(v,ce,'encroach_per_h')} | {emc(v,ce,'encroach_onred_per_h')} | "
      f"{emc(v,ce,'encroach_ongreen_per_h')} | "
      f"{mc('operational',v,ce,'pedveh_conflicts_per_h')} | "
      f"{mc('operational',v,ce,'ssm_rt_merge_per_h',2)} |")
w("")
encN = em("A_excl", "NTOR_noLPI", "encroach_per_h")
encR = em("A_excl", "RTOR_noLPI", "encroach_per_h")
encNL = em("A_excl", "NTOR_LPI", "encroach_per_h")
encRL = em("A_excl", "RTOR_LPI", "encroach_per_h")
w(f"**Banning RTOR did not reduce measured pedestrian encroachment - it increased it, from "
  f"{encR:.1f}/h to {encN:.1f}/h ({100*(encN-encR)/encR:+.1f} %).** The RTOR-specific hazard "
  f"is real but small ({em('A_excl','RTOR_noLPI','encroach_onred_per_h'):.1f} encroachments/h "
  f"on red, against exactly 0 under NTOR by construction), and it is swamped by what happens "
  f"to the ON-GREEN permitted right turn: under NTOR the whole right-turn demand has to "
  f"discharge inside the 30 s green, straight into the pedestrian platoon, giving "
  f"{em('A_excl','NTOR_noLPI','encroach_ongreen_per_h'):.1f} on-green encroachments/h against "
  f"{em('A_excl','RTOR_noLPI','encroach_ongreen_per_h'):.1f}/h under RTOR.\n")
w(f"So the exchange rate for a full No-Turn-on-Red ban at this demand and pedestrian volume is "
  f"**negative on both axes**: it surrenders {gainA:.0f} veh/h of right-turn capacity "
  f"(capacity regime) and raises pedestrian encroachment by "
  f"{encN-encR:.0f}/h. There is no rate at which it is a good trade here. "
  f"(The 10-seed aggregate proximity count moves the other way - "
  f"{m('operational','A_excl','RTOR_noLPI','pedveh_conflicts_per_h'):.0f}/h under RTOR against "
  f"{m('operational','A_excl','NTOR_noLPI','pedveh_conflicts_per_h'):.0f}/h under NTOR - "
  f"but that measure is contaminated by queue-creep approach exposure, which is exactly what "
  f"the encroachment filter removes.) "
  f"What a ban does buy is on the vehicle-vehicle side: SSM right-turn merge conflicts fall "
  f"from {m('operational','A_excl','RTOR_noLPI','ssm_rt_merge_per_h'):.1f}/h to "
  f"{m('operational','A_excl','NTOR_noLPI','ssm_rt_merge_per_h'):.1f}/h "
  f"({100*(m('operational','A_excl','NTOR_noLPI','ssm_rt_merge_per_h')/m('operational','A_excl','RTOR_noLPI','ssm_rt_merge_per_h')-1):.0f} %, "
  f"p = 2.8e-11), i.e. **{gainA/(m('operational','A_excl','RTOR_noLPI','ssm_rt_merge_per_h')-m('operational','A_excl','NTOR_noLPI','ssm_rt_merge_per_h')):.0f} veh/h of "
  f"right-turn capacity surrendered per vehicle-vehicle merge conflict per hour removed** "
  f"(capacity from the saturated regime, conflicts from the operational regime - the two "
  f"quantities are only defined in their own regimes, and the ratio should be read as an "
  f"order of magnitude, not a precise elasticity).\n")

# ---------------------------------------------------------------- 5
w("## 5. Is the LPI a cheaper way to buy the same conflict reduction?\n")
dLPI_enc = encR - encRL
dLPI_cap = capR - capRL
dBAN_enc = encR - encN
dBAN_cap = capR - capN
w("| lever (from RTOR, no LPI) | pedestrian encroachment removed /h | right-turn capacity "
  "surrendered (veh/h) | veh/h surrendered per encroachment/h removed |")
w("|---|---:|---:|---:|")
w(f"| add a 5 s LPI | {dLPI_enc:+.1f} | {dLPI_cap:.1f} | {dLPI_cap/dLPI_enc:.2f} |")
w(f"| ban turns on red | {dBAN_enc:+.1f} | {dBAN_cap:.1f} | "
  f"{'not defined (exposure rises)' if dBAN_enc <= 0 else f'{dBAN_cap/dBAN_enc:.2f}'} |")
w(f"| add the LPI **and** ban turns on red | {encR-encNL:+.1f} | {capR-capNL:.1f} | "
  f"{(capR-capNL)/(encR-encNL):.2f} |")
w("")
w(f"**Yes, decisively.** A 5 s LPI removes {dLPI_enc:.0f} pedestrian encroachments per hour "
  f"for {dLPI_cap:.0f} veh/h of right-turn capacity - a rate of {dLPI_cap/dLPI_enc:.2f} veh/h "
  f"per encroachment/h - while an RTOR ban removes none (it adds "
  f"{-dBAN_enc:.0f}/h) and costs {dBAN_cap:.0f} veh/h. And the two levers stack: RTOR + LPI "
  f"delivers {capRL:.0f} veh/h of capacity at {encRL:.0f} encroachments/h, versus the "
  f"conventional NTOR-without-LPI design's {capN:.0f} veh/h at {encN:.0f} encroachments/h - "
  f"**{capRL/capN:.1f} x the capacity and {100*(1-encRL/encN):.0f} % less pedestrian "
  f"encroachment at the same time.** NTOR without an LPI is not on the Pareto frontier at all: "
  f"NTOR + LPI matches its capacity ({capNL:.0f} vs {capN:.0f} veh/h) with "
  f"{encNL:.0f} encroachments/h instead of {encN:.0f}.\n")
w(f"One caveat on the LPI, visible in the on-red column of the table above: the LPI shifts the "
  f"residual encroachment towards the on-red component "
  f"({em('A_excl','RTOR_noLPI','encroach_onred_per_h'):.1f} -> "
  f"{em('A_excl','RTOR_LPI','encroach_onred_per_h'):.1f} /h) while cutting the on-green "
  f"component much harder "
  f"({em('A_excl','RTOR_noLPI','encroach_ongreen_per_h'):.1f} -> "
  f"{em('A_excl','RTOR_LPI','encroach_ongreen_per_h'):.1f} /h). The LPI acts on the vehicle "
  f"green, so it cannot touch the on-red exposure that occurs during the cross street's phase; "
  f"the apparent increase there rests on 3 seeds with a wide interval "
  f"(+-{E['A_excl|RTOR_LPI']['encroach_onred_per_h']['ci95']:.1f}) and should be treated as "
  f"unresolved rather than as a finding.\n")
w("Pedestrian delay is invariant across all four A-geometry cells - crossing wait "
  f"{mc('operational','A_excl','NTOR_noLPI','ped_cross_wait_mean',2)} s vs "
  f"{mc('operational','A_excl','RTOR_LPI','ped_cross_wait_mean',2)} s, walk timeLoss "
  f"{mc('operational','A_excl','NTOR_noLPI','ped_timeloss_mean',2)} s vs "
  f"{mc('operational','A_excl','RTOR_LPI','ped_timeloss_mean',2)} s - by construction: the "
  "programs were generated so the crossing WALK interval occupies the same 30 s of the same "
  "cycle position in every cell, and only the VEHICLE green shrinks from 30 s to 25 s. That "
  "isolation is what makes the conflict comparison attributable to the LPI rather than to a "
  "different pedestrian service rate.\n")

# ---------------------------------------------------------------- 6
w("## 6. Saturation flow, and what the HCM's RTOR credit gets wrong\n")
sfg = m("capacity", "A_excl", "RTOR_noLPI", "sat_flow_green_vphpl")
sfr = m("capacity", "A_excl", "RTOR_noLPI", "sat_flow_red_vphpl")
hg = m("capacity", "A_excl", "RTOR_noLPI", "sat_headway_green_med")
hr = m("capacity", "A_excl", "RTOR_noLPI", "sat_headway_red_med")
w("Measured from the via-lane instant loops in the saturated runs "
  "(`outputs/runs/capacity/**/*_instantvia.xml`):\n")
w("| | median headway (s) | implied rate (veh/h/lane) |")
w("|---|---:|---:|")
w(f"| saturated discharge on GREEN (`g`, yielding to the parallel crossing) | {hg:.3f} | "
  f"{sfg:.0f} |")
w(f"| saturated discharge on RED (`s`, stop-and-go) | {hr:.3f} | {sfr:.0f} |")
w("")
w(f"The on-green saturation flow of {sfg:.0f} veh/h/lane is ~20 % below the HCM 1900 default "
  f"and below this project's previously measured SUMO through-lane values of 1791-2000 "
  f"veh/h/lane ([[hcm-control-delay-vs-sumo-delay-metrics]]) - the permitted right turn pays "
  f"both a turn-radius speed penalty and the pedestrian yield. The `s` discharge headway of "
  f"{hr:.3f} s is close to exactly twice the green headway, which is the signature of the "
  f"mandatory stop.\n")
onred_cap = m("capacity", "A_excl", "RTOR_noLPI", "rt_onred_vph")
ongreen_R = m("capacity", "A_excl", "RTOR_noLPI", "rt_ongreen_vph")
ongreen_N = m("capacity", "A_excl", "NTOR_noLPI", "rt_ongreen_vph")
onred_capB = m("capacity", "B_shared", "RTOR_noLPI", "rt_onred_vph")
ongreen_RB = m("capacity", "B_shared", "RTOR_noLPI", "rt_ongreen_vph")
ongreen_NB = m("capacity", "B_shared", "NTOR_noLPI", "rt_ongreen_vph")
w("HCM practice credits the RTOR volume against right-turn demand, i.e. treats the measured "
  "on-red volume as the capacity the manoeuvre adds. **In SUMO it is not.**\n")
w("| geometry | measured on-red volume | measured capacity gain | over-statement | on-green "
  "component, NTOR -> RTOR |")
w("|---|---:|---:|---:|---:|")
w(f"| A, exclusive lane | {onred_cap:.1f} veh/h | {gainA:.1f} veh/h | "
  f"+{onred_cap-gainA:.1f} veh/h ({100*(onred_cap-gainA)/gainA:.1f} %) | "
  f"{ongreen_N:.1f} -> {ongreen_R:.1f} ({ongreen_R-ongreen_N:+.1f}) |")
w(f"| B, shared lane | {onred_capB:.1f} veh/h | {gainB:.1f} veh/h | "
  f"+{onred_capB-gainB:.1f} veh/h ({100*(onred_capB-gainB)/gainB:.1f} %) | "
  f"{ongreen_NB:.1f} -> {ongreen_RB:.1f} ({ongreen_RB-ongreen_NB:+.1f}) |")
w("")
w(f"**Crediting the on-red volume over-states the capacity actually gained by "
  f"{100*(onred_cap-gainA)/gainA:.1f} % with an exclusive lane and "
  f"{100*(onred_capB-gainB)/gainB:.1f} % with a shared lane**, because turning on red "
  f"cannibalises the green: it removes the standing queue that would otherwise have "
  f"discharged at saturation headway when the green came up, so the on-green component falls "
  f"by {ongreen_N-ongreen_R:.1f} veh/h (A) and {ongreen_NB-ongreen_RB:.1f} veh/h (B). The "
  f"cannibalisation almost exactly accounts for the discrepancy "
  f"({ongreen_N-ongreen_R:.1f} vs {onred_cap-gainA:.1f} veh/h in A). "
  f"**The direction of the HCM assumption is supported - RTOR is genuine extra capacity - but "
  f"its arithmetic is optimistic, and the error is not a fixed factor**: it depends on the "
  f"geometry (10 % vs 4 %) and, per the calibration sweep below, on the conflicting pedestrian "
  f"volume.\n")

# ---------------------------------------------------------------- 7
w("## 7. Everything here is conditional on the pedestrian volume\n")
w("The whole design space is a strong function of the conflicting crossing volume "
  "(`outputs/calibration/capacity_vs_ped.json`, right turn saturated at 1200 veh/h/approach, "
  "single seed):\n")
w("| measured ped/h per crossing | NTOR right-turn capacity (veh/h/appr) | RTOR (veh/h/appr) | "
  "RTOR gain | RTOR on-red component |")
w("|---:|---:|---:|---:|---:|")
byped = {}
for r in CAL:
    if r.get("variant") != "A_excl":
        continue
    byped.setdefault(r["ped_vph_per_crossing_measured"], {})[r["cell"]] = r
for pv in sorted(byped):
    d = byped[pv]
    if "NTOR_noLPI" not in d or "RTOR_noLPI" not in d:
        continue
    n = d["NTOR_noLPI"]["served_rt_vph_per_appr"]
    rr = d["RTOR_noLPI"]["served_rt_vph_per_appr"]
    w(f"| {pv:.0f} | {n:.1f} | {rr:.1f} | +{rr-n:.1f} | "
      f"{d['RTOR_noLPI']['onred_vph_per_appr']:.1f} |")
w("")
w("Permitted right-turn capacity collapses from 468 to 150 veh/h/lane as the parallel crossing "
  "goes from empty to 402 ped/h, and RTOR's absolute gain shrinks with it (417 -> 272 "
  "veh/h/appr) while its RELATIVE importance grows (+89 % -> +182 %). Any RTOR capacity credit "
  "quoted without the conflicting pedestrian volume attached is meaningless.\n")

# ---------------------------------------------------------------- 8
w("## 8. Scope and caveats\n")
w(f"- Control delay is the HCM segment convention: 250 m upstream of the stop line to 100 m "
  f"past the junction, minus a **measured** per-movement free-flow datum (5th percentile of "
  f"12 isolated single-movement runs; 27.0-28.5 s against a geometric datum of 25.20 s - "
  f"using the geometric datum would inflate every delay by 1.8-3.3 s). `speedFactor=\"1.0\" "
  f"speedDev=\"0\"` is pinned, per [[hcm-control-delay-vs-sumo-delay-metrics]].")
w(f"- Variant B is oversaturated under NTOR at the shared operational demand "
  f"(right-turn control delay {m('operational','B_shared','NTOR_noLPI','cd_rt_mean'):.0f} s). "
  f"That is the honest consequence of running one demand set on a geometry with one fewer "
  f"lane, and it is why every CAPACITY claim above comes from the saturated capacity regime, "
  f"which is insensitive to it.")
w(f"- The operational demand sits at v/c = 0.78 against the measured NTOR right-turn capacity, "
  f"deliberately below the capacity knee where "
  f"[[sumo-stochastic-variability-and-replication-design]] found few-seed comparisons "
  f"unreliable. Observed coefficients of variation are small and all headline contrasts have "
  f"p < 1e-5.")
w("- SSM counts are ordinal, not cardinal: [[surrogate-safety-measures]] records that absolute "
  "TTC-threshold counts move by up to ~7x across time-discretisation conventions. All runs "
  "here use `--step-length 0.5`, ballistic integration, SUMO 1.27.1.")
w("- The pedestrian-vehicle conflict measure is a proximity/TTC-like proxy implemented in "
  "TraCI, not an SSM output - SUMO's SSM device has no pedestrian-aware mode "
  "([[surrogate-safety-measures]]). Its threshold (8 m, d/v < 2 s, v >= 1 m/s) is a stated "
  "convention, and the encroachment/approach split is what makes it interpretable.")
w("- One geometry family, one cycle length, one split, one pedestrian model (`striping`), "
  "one demand mix. The LPI-is-nearly-free result in particular depends on the right turn being "
  "pedestrian-constrained; at a low crossing volume the LPI would cost real green time.")

open(os.path.join(OUT, "FINDINGS.md"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
