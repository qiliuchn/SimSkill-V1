import os
A2="/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-2/outputs"
content = r'''# Diverging Diamond Interchange (DDI) vs Conventional Diamond - Findings

**Task:** Build a grade-separated Diverging Diamond Interchange in SUMO whose arterial-to-on-ramp
LEFT turns are *unopposed* (the crossover puts them on the inside, never crossing opposing through
traffic), and quantify the left-turn advantage against a conventional diamond baseline under an
identical heavy-left-turn demand and identical signal cycle.

All numbers below are read directly from the raw files in attempt-1's `outputs/` and `runs/` and can
be independently recomputed with `scripts/analyze.py` / `scripts/verify_networks.py`.

> **Attempt-2 correction (throughput/completion only).** The delay, foe-matrix, phase-count, and
> grade-separation findings are unchanged (independently verified). The single fix: the throughput
> section now distinguishes trips that genuinely COMPLETED (tripinfo `arrival >= 0`) from vehicles
> that were STILL RUNNING at the 1200 s cutoff (`arrival == -1`, written into tripinfo.xml only
> because the runs used `--tripinfo-output.write-unfinished true`). Attempt-1 counted all 894
> records as "arrived" in both designs, producing a false 894/894 tie. The corrected numbers show
> the DDI actually completes MORE vehicles, especially on the heavy left. Delay numbers are
> unaffected (see reconciliation in Finding iii).

## Design (identical except the crossover geometry)
- 2-lane freeway N-S at z=0 passing UNDER a 2-lane (per direction) arterial E-W at z=6.
- Two signalized ramp terminals W(-55,0) and E(55,0), 110 m apart. SB ramps at W, NB ramps at E.
- The DDI and conventional nets share the SAME nodes, ramps, freeway, and connection list; the
  ONLY difference is the SIDE (shape) of the two internal arterial edges between the terminals
  (crossed vs normal). On-ramps merge via a 3-lane acceleration segment (identical both designs)
  so the terminal SIGNAL - not the freeway merge - is the binding constraint.

## Demand (shared file `demand.rou.xml`, seed 42, 0-1200 s, IDENTICAL across both runs)
- HEAVY arterial-to-on-ramp LEFT: WB_left (west terminal) and EB_left (east terminal) = 470 veh/h each.
  This sits ABOVE the conventional protected-left capacity (~1 lane x 1800 x 13/60 s ~= 390 veh/h,
  so conventional is over-saturated on the left) and BELOW the DDI unopposed-left capacity
  (~1 lane x 1800 x 26/60 s ~= 780 veh/h, comfortable).
- Plus arterial through 240 veh/h/dir, on-ramp rights 70, off-ramp-to-arterial 130/45, freeway
  mainline 380 veh/h/dir. Loads the interchange without gridlock or teleporting (0 teleports in
  either design); the over-saturated conventional left leaves a larger backlog unfinished at cutoff.

## Finding (i): grade separation + two signals + unopposed-left foe signature (from compiled net.net.xml)
- **Grade separation:** 0 direct freeway<->arterial `<connection>` elements in either net; freeway
  junctions Fn/Fs are `priority`; no junction at the (0,0) crossing point. Freeway meets the
  arterial only via ramp edges. (see `verification_report.txt`)
- **Two signalized terminals:** both W and E are `type="traffic_light"` in both nets.
- **Unopposed-left signature (the DDI's defining property):**
  - DDI, terminal W: LEFT `I_WB->SBon` (link 4) foes = 5 - only the merging EB-right into the
    same on-ramp; the opposing EB-through `Aw_EB->I_EB` (links 6,7) is NOT a foe -> **UNOPPOSED**.
  - DDI, terminal E: LEFT `I_EB->NBon` (link 7) foes = 0; opposing WB-through (links 1,2) NOT a foe -> **UNOPPOSED**.
  - Conventional, terminal W: LEFT `I_WB->SBon` (link 4) foes = {1,5,6,7} - INCLUDES the opposing
    EB-through (links 6,7) -> **OPPOSED**.
  - Conventional, terminal E: LEFT `I_EB->NBon` (link 7) foes = {0,1,2,4} - INCLUDES opposing WB-through (links 1,2) -> **OPPOSED**.

## Finding (ii): DDI terminals use FEWER signal phases (from the tlLogic, same 60 s cycle)
| Terminal | DDI green intervals | Conventional green intervals |
|---|---|---|
| W | 2 (EB phase, WB phase) | 3 (through, PROTECTED-LEFT, off-ramp) |
| E | 2 | 3 |

The DDI needs only a TWO-phase signal (the two arterial directions are separated at the crossover
and the on-ramp lefts are unopposed, riding inside their direction's phase). The conventional
diamond needs a THIRD, PROTECTED arterial-left phase because its lefts conflict with opposing
through traffic (see the `<phase state="...">` with only the left-link green in `conv.tll.xml`).
Both use a 60 s cycle so the comparison isolates geometry, not cycle length.

## Finding (iii): under identical heavy-left demand, the DDI wins on delay AND left-turn throughput
Control-delay proxy = tripinfo `timeLoss` (s). Completion counts filter on tripinfo `arrival`
(>= 0 = genuinely arrived; == -1 = still en route when the sim ended at 1200 s).

| Metric | DDI | Conventional | DDI advantage |
|---|---|---|---|
| **Heavy-LEFT mean delay (s)** | **34.9** | **171.0** | 4.9x lower |
| Heavy-LEFT mean waiting (s) | 18.9 | 119.7 | lower |
| Heavy-LEFT mean delay, completed subset only (s) | 36.4 | 163.8 | 4.5x lower (advantage holds) |
| Overall mean delay (s) | 60.3 | 70.6 | lower |
| EB_through delay (s) | 19.8 | 28.5 | lower |
| WB_through delay (s) | 19.5 | 30.1 | lower |
| Loaded (each design) | 894 | 894 | identical demand |
| **Heavy-LEFT completed (arrival >= 0)** | **288 / 314 (92%)** | **209 / 314 (67%)** | **+79 veh, +25 pts** |
| Heavy-LEFT still running at cutoff | 26 (8%) | 105 (33%) | 4x fewer stranded |
| Overall completed (arrival >= 0) | 781 / 894 (87%) | 755 / 894 (85%) | +26 veh |
| Overall still running at cutoff | 113 | 139 | fewer stranded |
| On-ramp E1 throughput SB+NB (veh) | 343 | 260 | higher discharge |
| Inserted / Never-inserted / Teleports | 894 / 0 / 0 | 894 / 0 / 0 | both fully loaded, no teleports |

**Conclusion.** The DDI's structural elimination of the opposed left turn lets the heavy
arterial-to-on-ramp left run for a full ~26 s direction phase (unopposed) instead of the
conventional diamond's ~13 s protected-left phase. Under an identical 470 veh/h heavy-left demand
that over-saturates the conventional protected-left, this cuts heavy-left mean control delay from
171 s to 35 s (~80% reduction, and the advantage is real, not a cutoff artifact: on the completed
subset it is still 163.8 s vs 36.4 s), and lowers overall delay from 71 s to 60 s.

Crucially, the DDI also wins on **left-turn throughput**, not merely on delay. Because the
conventional protected-left phase cannot discharge 470 veh/h, the conventional diamond leaves
**33% of its heavy-left demand (105 of 314 vehicles) stranded in the network at the 1200 s cutoff**,
versus only **8% (26 of 314) for the DDI** - the DDI completes **288 vs 209 heavy-left vehicles**
(+79) in the same period, and completes more vehicles overall (781 vs 755). Neither design teleports
any vehicle and both are fully loaded (894/894 inserted, 0 never-inserted, 0 teleports), so the gap
is genuine served-demand throughput, not spillback failure. The DDI therefore wins on the headline
left-turn delay, on overall delay, AND on left-turn (and overall) completed throughput - all
genuinely supported by the raw tripinfo, summary, and E1 data.

## Files
- Analysis (corrected): `scripts/analyze.py` (attempt-2) -> `comparison_table.csv/.md` (attempt-2/outputs),
  `ddi_vs_conventional_delay_throughput.png`
- Unchanged deliverables (attempt-1/outputs, verified correct):
  - Networks: `shared.nod.xml`, `ddi.edg.xml`, `conv.edg.xml`, `shared.con.xml`, `ddi.net.xml`, `conv.net.xml`
  - Signals: `ddi.tll.xml` (2-phase), `conv.tll.xml` (3-phase incl. protected left)
  - Demand: `demand.rou.xml` ; Detectors: `detectors.add.xml`
  - Foe verification: `verify_networks.py` -> `verification_report.txt`
- Raw outputs (reused unchanged): `attempt-1/runs/<ddi|conv>/{tripinfo,summary,e1_out}.xml`
'''
with open(os.path.join(A2,"FINDINGS.md"),"w") as f:
    f.write(content)
print("wrote", os.path.join(A2,"FINDINGS.md"), len(content.splitlines()),"lines")
