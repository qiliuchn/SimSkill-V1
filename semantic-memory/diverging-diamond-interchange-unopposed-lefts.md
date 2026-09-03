---
summary: A SUMO Diverging Diamond Interchange (DDI) — where the arterial's two directions cross over between two ramp-terminal signals — genuinely makes arterial-to-freeway left turns unopposed in the compiled network's junction foe matrix (verified via request/response bitstring decoding, not merely visually apparent), letting it run a two-phase signal versus a conventional diamond's three-phase protected-left plan; verified under identical heavy-left demand that the DDI cuts left-turn delay by roughly 80% and achieves substantially higher completed left-turn throughput once completed-vs-still-running trips are correctly distinguished (a naive arrival count can otherwise mask a real, meaningfully different completion-rate gap).
keywords:
  - diverging-diamond-interchange
  - DDI
  - crossover-interchange
  - unopposed-left-turn
  - foe-matrix
created: 2026-07-30T23:20:00
last_updated: 2026-07-30T23:20:00
sources:
  - "[[episodic-memory/2026-07-30_09-43-42/attempts/attempt-1/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-30_09-43-42/attempts/attempt-2/action-agent-output.json]]"
  - "[[episodic-memory/2026-07-30_09-43-42/attempts/attempt-2/critic-agent-feedback.json]]"
related_pages:
  - "[[roundabout-modeling-and-comparison]]"
  - "[[unsignalized-vs-signalized-intersection-control]]"
  - "[[left-turn-treatment-tradeoffs]]"
  - "[[diamond-interchange-signal-offset-and-spillback]]"
  - "[[rcut-and-michigan-left-alternative-intersection-design]]"
related_skills:
  - build-diverging-diamond-interchange
  - build-diamond-interchange-with-signal-offset-spillback
  - compare-left-turn-signal-treatments
  - design-restricted-crossing-uturn-and-michigan-left-intersections
related_skills_for_graph_view:
  - "[[build-diverging-diamond-interchange]]"
  - "[[build-diamond-interchange-with-signal-offset-spillback]]"
  - "[[compare-left-turn-signal-treatments]]"
  - "[[design-restricted-crossing-uturn-and-michigan-left-intersections]]"
---

# Diverging Diamond Interchange and Unopposed Lefts

A Diverging Diamond Interchange (DDI) is an unconventional grade-separated freeway interchange design where the surface arterial's two directions cross over to the opposite side of the roadway between two ramp-terminal signals, so that a left turn from the arterial onto a freeway on-ramp is made from what is now the left/inside lane — without ever crossing the opposing arterial through movement. This is a distinct topology from the conventional diamond interchange (see [[diamond-interchange-signal-offset-and-spillback]]), where those same left turns must cross opposing through traffic and require a protected signal phase.

## The unopposed-left property is a genuine, verifiable network fact — not just visual

**The DDI's defining property — that arterial-to-on-ramp left turns are unopposed by opposing through traffic — is directly checkable in the compiled network's junction request/response (foe) matrix, not merely apparent from the crossover layout's visual appearance.** Verified: decoding the `<request response=".." foes=".."/>` bitstrings for the arterial-to-on-ramp left-turn connection at each terminal showed the opposing arterial-through link genuinely absent from the DDI's foe set, while the same left-turn connection's foe set in an otherwise-identical conventional-diamond network (differing only in whether the internal arterial edges' geometry crosses sides) genuinely included the opposing-through link. This can be produced by varying only the *shape* of the internal arterial edges between two otherwise-identical network definitions — the connection list itself doesn't need to change; netconvert derives the different foe relationships purely from the crossed-vs-normal edge geometry.

## Fewer signal phases as a direct consequence

Because DDI lefts are unopposed, each ramp terminal needs only a two-phase signal (one phase per arterial direction, no protected-left interval) — verified against a conventional diamond's three-phase plan (through, protected left, off-ramp/side movements) at the identical cycle length.

## Verified delay and throughput advantage — and a genuine analysis pitfall

Under identical heavy arterial-to-freeway left-turn demand and seed: the DDI's heavy-left-turn vehicles experienced roughly 80% lower mean delay than the conventional design's (34.9s vs. 171.0s in a verified test), with overall interchange delay also lower (60.3s vs. 70.6s).

**A genuine analysis pitfall surfaced when first computing throughput**: a simulation run with `--tripinfo-output.write-unfinished true` (needed to preserve data for vehicles still in the network when the simulation ends) produces a `<tripinfo>` record for every vehicle, including ones that never actually completed their trip — marked `arrival="-1.00"`. Counting every record as "arrived" without filtering on this attribute produced a false "equal throughput, 0 incomplete" result in an initial pass. Correctly distinguishing `arrival >= 0` (genuinely completed) from `arrival == -1` (still running at cutoff) revealed the true picture: the DDI actually completed 92% of its heavy left-turn demand versus the conventional design's 67% — a real, substantially larger DDI advantage than the initial naive count suggested, not merely an "equal" tie. **Any throughput comparison using `--tripinfo-output.write-unfinished` must filter on the `arrival` attribute, or risk silently masking a meaningful completion-rate difference between scenarios.**

See the `build-diverging-diamond-interchange` skill for the full shared-topology network construction, foe-matrix verification, and completed-vs-still-running throughput measurement workflow.
