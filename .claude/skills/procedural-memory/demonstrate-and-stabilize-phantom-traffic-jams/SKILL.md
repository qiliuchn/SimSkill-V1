---
name: demonstrate-and-stabilize-phantom-traffic-jams
description: Use this skill when the user wants to demonstrate spontaneous stop-and-go ("phantom"/jamiton) traffic waves emerging from car-following STRING INSTABILITY on a closed ring road with NO bottleneck at constant density, and/or show that a single automated vehicle (AV) can suppress them — the classic Sugiyama/Stern ring experiment. Distinct from form-platoons-with-simpla (CACC damping a FORCED perturbation on a demand-driven freeway line) and build-macroscopic-fundamental-diagram (bottleneck-induced congestion); here instability must emerge ENDOGENOUSLY at constant vehicle count on a closed loop. Covers bottleneck-free ring construction with circularity verification, the one-shot brake-pulse technique for breaking a deterministic car-following model's symmetric unstable equilibrium, a density-threshold negative control, backward wave-speed measurement from FCD, and a FollowerStopper-style single-AV wave-damping controller. Trigger on mentions of phantom traffic jam, jamiton, string instability, stop-and-go waves, ring road experiment, or Sugiyama experiment.
---

# Demonstrate and Stabilize Phantom Traffic Jams

Demonstrates spontaneous stop-and-go ("phantom"/jamiton) traffic waves emerging purely from car-following string instability on a bottleneck-free closed ring at constant vehicle density — the classic Sugiyama (2008) / Stern (2018) ring experiment — and a single automated vehicle's ability to suppress them.

## Distinguishing this from adjacent instability skills

- `form-platoons-with-simpla` tests CACC damping a **forced** disturbance on a **demand-driven freeway line** — not endogenous emergence.
- `build-macroscopic-fundamental-diagram` induces congestion via a genuine **downstream bottleneck** — here there must be **no bottleneck anywhere**, only density.
- This skill: instability emerges **endogenously** at **constant vehicle count** on a **closed loop** with uniform geometry throughout.

## Building a genuinely bottleneck-free closed ring

Verify from the compiled net that the ring has zero traffic lights, zero internal-lane conflicts, uniform speed limit, and single-lane throughout — any lane drop, merge, or signal would confound "endogenous" instability with bottleneck-induced congestion. A circumference around 230m (the classic Sugiyama scale) with `carFollowModel="IDM"` at a density known to be string-unstable is a reasonable starting point.

## Breaking symmetry: the one-shot brake-pulse technique

**A perfectly evenly-spaced, deterministic IDM fleet is at an unstable equilibrium that a simulation may never spontaneously leave without some initial perturbation** — this is not a flaw in "spontaneity," it's the same methodology real ring experiments use (a human driver's initial minor variation is what seeds the real Sugiyama jam). Apply a single, transient, one-shot brake pulse to one designated vehicle (brief `setSpeed(0)` then release back to pure IDM) — identical across every scenario for a fair comparison — rather than relying on car-following stochasticity alone:

```python
if pstart <= t < pend:
    traci.vehicle.setSpeed(perturb_id, 0.0)
elif t >= pend:
    traci.vehicle.setSpeed(perturb_id, -1)   # release back to pure IDM
```

Disclose this explicitly (in code comments, findings, and ideally annotated on plots) — it's a legitimate, standard technique, not a shortcut to hide.

## Verifying the phantom jam from raw FCD

1. **Growing speed variance**: cross-vehicle speed standard deviation should start near zero (uniform flow) and grow to a large, sustained value after the perturbation.
2. **Genuine full stops**: minimum instantaneous speed across the fleet should reach ~0 m/s at constant density with no bottleneck — the signature that this is a real jam, not just increased variance.
3. **Backward wave propagation**: extract the position of the congestion minimum at several time points from the raw FCD, fit a line to (time, unwrapped ring position), and confirm a genuinely negative (upstream) propagation speed with a reasonable fit quality (R²) — don't just eyeball a time-space diagram.

## The density-threshold negative control

Rerun the identical scenario (same perturbation, same network) at a much lower vehicle density and confirm the instability does NOT develop — speed variance stays low/decaying, no full stops. This positively confirms the phenomenon is genuinely density-driven rather than an artifact of the perturbation itself.

## Single-AV stabilization: FollowerStopper and the equilibrium-targeting gotcha

Convert exactly one vehicle to an AV controlled via TraCI, changing nothing else about the scenario. A simple effective policy: hold a steady target speed near the ring's homogeneous equilibrium, refusing to chase the stop-and-go oscillation — the AV neither amplifies nor transmits the wave. See `scripts/run_ring.py` for both a simple "hold" controller and a full FollowerStopper (Stern et al. 2018) implementation with speed-dependent gap thresholds.

**Critical gotcha, verified empirically: targeting exactly the analytical equilibrium speed can fail to damp the waves.** Holding precisely at equilibrium leaves the AV on a "knife's edge" — SUMO's safety speed-mode brakes it on every minor dip, so it ends up participating in the oscillation rather than damping it. **Target a speed slightly below the true equilibrium** instead; this gave a robust, verified damping effect (steady-state speed variance collapsing by over 95%, full stops eliminated, mean throughput up nearly 20% in a real test) where exact-equilibrium targeting did not.

## Verified findings

At string-unstable density, a single brake pulse grew into a sustained phantom jam: speed variance grew from near-zero to a large sustained value, vehicles reached full stops despite constant density and no bottleneck, and the congestion band traveled backward around the ring at a measurable, roughly constant speed. A negative control at lower density confirmed this was genuinely density-driven. Converting one vehicle in twenty-two to a below-equilibrium-targeting AV nearly eliminated the instability and raised throughput substantially — a striking illustration of how a small fraction of automated vehicles can stabilize traffic flow.

## Gotchas

- **A perfectly symmetric deterministic fleet needs a seed perturbation to leave its unstable equilibrium** — use a disclosed, transient, identical-across-scenarios brake pulse rather than hoping stochasticity alone triggers instability, and don't treat this as contradicting "spontaneous" emergence.
- **Verify the backward wave speed by fitting a line to extracted congestion-marker positions over time**, not by eyeballing a time-space diagram.
- **Always run a density-threshold negative control** — without it, you can't rule out the perturbation itself (rather than density) as the cause of any observed instability.
- **An AV targeting exactly the analytical equilibrium speed can fail to damp waves** — target slightly below equilibrium instead, and verify via a target-speed sweep if the first choice doesn't work.
- **Disable teleporting (`--time-to-teleport -1`)** — a stopped vehicle must genuinely stay stopped and visible in the data, not be silently removed by SUMO's default congestion-avoidance mechanism.

## Related

- `demonstrate-and-control-bus-bunching` — the closed-loop network-construction pattern and "confirm the phenomenon before controlling it" discipline this skill directly reuses.
- `form-platoons-with-simpla` — the related-but-distinct forced-perturbation string-stability concept on a demand-driven line.
- `visualize-trajectories-and-timeseries` — FCD-based time-space diagram construction.
- [[phantom-traffic-jams-and-single-av-stabilization]] — the underlying string-instability mechanics and the verified stop-and-go/backward-wave/AV-damping findings.
- `measure-av-penetration-effect-on-bottleneck-capacity` — a different AV scenario (bottleneck capacity vs. market penetration, rather than ring-road wave suppression by a single AV) that shares this skill's "verify from raw FCD, don't trust configuration" discipline, applied to SUMO's ACC/CACC car-following models.
- `validate-kinematic-wave-theory-across-car-following-models` — reuses this skill's closed-ring construction and brake-pulse perturbation technique for controlled-density fundamental-diagram fitting and a fundamental-diagram bistability test, across five car-following models rather than one.
