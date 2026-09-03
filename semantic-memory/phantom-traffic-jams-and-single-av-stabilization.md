---
summary: SUMO's IDM car-following model produces genuine, spontaneous stop-and-go ("phantom"/jamiton) waves on a bottleneck-free closed ring at string-unstable density, given a one-shot brake-pulse perturbation to break a deterministic model's symmetric unstable equilibrium (a legitimate, disclosed technique, not a shortcut); verified via growing speed variance, genuine full stops at constant density, and a measurable backward-traveling congestion wave, confirmed density-dependent via a negative control, and shown to be substantially suppressed by converting a single vehicle to an AV that targets a speed slightly BELOW (not exactly at) the true equilibrium speed.
keywords:
  - phantom-traffic-jam
  - jamiton
  - string-instability
  - ring-experiment
  - followerstopper
created: 2026-07-30T09:35:00
last_updated: 2026-07-30T09:35:00
sources:
  - "[[episodic-memory/2026-07-30_09-06-21/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-30_09-06-21/attempts/attempt-1/critic-agent-feedback.json]]"
related_pages:
  - "[[simpla-platooning]]"
  - "[[macroscopic-fundamental-diagram]]"
  - "[[bus-bunching-and-forward-headway-holding]]"
  - "[[av-penetration-and-carfollowing-model-mechanism]]"
  - "[[kinematic-wave-theory-validity-across-car-following-models]]"
related_skills:
  - demonstrate-and-stabilize-phantom-traffic-jams
  - form-platoons-with-simpla
  - visualize-trajectories-and-timeseries
  - measure-av-penetration-effect-on-bottleneck-capacity
  - validate-kinematic-wave-theory-across-car-following-models
related_skills_for_graph_view:
  - "[[demonstrate-and-stabilize-phantom-traffic-jams]]"
  - "[[form-platoons-with-simpla]]"
  - "[[visualize-trajectories-and-timeseries]]"
  - "[[measure-av-penetration-effect-on-bottleneck-capacity]]"
  - "[[validate-kinematic-wave-theory-across-car-following-models]]"
---

# Phantom Traffic Jams and Single-AV Stabilization

Spontaneous stop-and-go ("phantom"/jamiton) traffic waves — congestion that emerges purely from car-following dynamics, with no bottleneck, lane drop, or signal — are a genuine, reproducible phenomenon in SUMO's IDM car-following model at sufficiently high, string-unstable density, replicating the classic real-world Sugiyama (2008) ring-road experiment.

## Breaking symmetry requires a disclosed, transient perturbation

A perfectly evenly-spaced, fully deterministic IDM fleet sits at an *unstable* equilibrium — mathematically, it can persist there indefinitely without some initial nudge to break the symmetry, exactly as the real Sugiyama experiment required a driver's minor speed variation to seed the observed jam. **A one-shot, transient brake pulse applied identically across every compared scenario is the standard, legitimate way to trigger this** — not a methodological shortcut, provided it's explicitly disclosed and doesn't differ between the scenarios being compared.

## Verified: the instability signature is real and measurable

At string-unstable density with a seed perturbation: cross-vehicle speed standard deviation grows from near-zero to a large, sustained value; the minimum instantaneous vehicle speed reaches genuine full stops (0 m/s) despite constant vehicle density and no bottleneck anywhere on the ring; and the congestion band measurably propagates **backward** (upstream, opposite the direction of travel) around the ring at a roughly constant characteristic speed — independently confirmed by fitting a line to the congestion minimum's position over time from raw FCD data. A negative control at substantially lower density, subjected to the identical perturbation, does not develop sustained instability — confirming the emergence is genuinely density-driven rather than an artifact of the perturbation technique itself.

## Verified: a single AV substantially suppresses the instability, but only with the right target speed

Converting exactly one vehicle in a fleet to an automated vehicle running a simple speed-holding wave-damping controller (or a full FollowerStopper implementation, Stern et al. 2018, with speed-dependent gap thresholds) can nearly eliminate the phantom jam: steady-state speed variance collapsing by over 95%, full stops eliminated entirely, and mean throughput rising by nearly 20% in a verified test — from a single vehicle among many.

**Critical, verified gotcha: the AV's target speed must be set slightly BELOW the exact analytical equilibrium speed, not at it.** Targeting exactly the equilibrium leaves the AV on a "knife's edge" — SUMO's default safety speed-mode brakes it on every minor gap fluctuation, so it ends up participating in the oscillation rather than damping it. A modestly below-equilibrium target gave robust, verified stabilization where exact-equilibrium targeting did not.

See the `demonstrate-and-stabilize-phantom-traffic-jams` skill for the full ring-construction, perturbation, verification, and AV-controller workflow.
