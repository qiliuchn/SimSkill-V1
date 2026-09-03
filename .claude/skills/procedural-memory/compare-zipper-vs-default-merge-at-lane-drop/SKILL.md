---
name: compare-zipper-vs-default-merge-at-lane-drop
description: Use this skill when the user wants to compare SUMO's zipper junction type (cooperative alternating late-merge) against the default merge behavior at a 2-lane-to-1-lane work-zone/lane-drop bottleneck under oversaturating demand, measuring bottleneck discharge throughput, delay, and upstream queue length. Distinct from implement-alinea-ramp-metering's ramp-merges-onto-mainline topology — this is a straight lane drop (both approach lanes converge into one downstream lane), not a ramp joining a through movement. Trigger on mentions of zipper merge, lane drop, work-zone bottleneck, late merge, or 2-into-1 merge comparison.
---

# Compare Zipper vs Default Merge at a Lane Drop

Builds two SUMO networks of an identical 2-lane→1-lane bottleneck topology, differing ONLY in the merge junction's `type` attribute (`priority`/default vs `zipper`), and quantifies whether the cooperative alternating late-merge actually improves bottleneck discharge and delay under oversaturating demand. This is a straight lane-drop (both approach lanes converge to one downstream lane at the same junction), structurally different from `implement-alinea-ramp-metering`'s ramp-onto-mainline topology — but the zipper-junction-type mechanism and its compiled-net verification transfer directly.

## Building the two variants

Same edge/connection files (`scripts/lanedrop.edg.xml`, `scripts/lanedrop.con.xml`); only the merge node's `type` differs between `scripts/lanedrop_default.nod.xml` (`type="priority"`, or simply omit `type` and let netconvert default it) and `scripts/lanedrop_zipper.nod.xml` (`type="zipper"`). An explicit `.con.xml` forcing both approach lanes onto the single downstream lane makes the 2-into-1 merge unambiguous rather than relying on netconvert's automatic connection-guessing.

```bash
netconvert --node-files lanedrop_default.nod.xml --edge-files lanedrop.edg.xml \
    --connection-files lanedrop.con.xml -o net_default.net.xml
netconvert --node-files lanedrop_zipper.nod.xml  --edge-files lanedrop.edg.xml \
    --connection-files lanedrop.con.xml -o net_zipper.net.xml
```

## Verifying the merge type took effect (compiled net, not source)

Check both the junction's own `type` and — more importantly — the **connection state** on the contested lane, since that's what actually governs merge behavior at runtime:

```bash
grep 'junction id="n_merge"' net_default.net.xml net_zipper.net.xml
grep 'from="app3".*to="bott"' net_default.net.xml net_zipper.net.xml
```

Default (`priority`) shows one connection `state="m"` (minor, must yield) and the other `state="M"` (major, right-of-way) — one approach lane is picked to yield. Zipper shows **both** connections `state="Z"` — the cooperative alternating discipline (same `Z` marker documented in `implement-alinea-ramp-metering` for the ramp-merge context). **Diff the full compiled nets** to confirm the ONLY substantive difference is the junction type/connection state/internal request-response logic — edges and lanes should be byte-identical, or the comparison is confounded by an unintended geometry difference.

`netconvert` trims internal junction geometry slightly regardless of junction type — verify actual compiled lane lengths (not source node-to-node coordinates) if a spec calls for a specific approach length, and confirm the trim is identical across both variants (it should be, since only `type` differs).

## Choosing demand that actually oversaturates

**SUMO's default car-following `tau` (desired time headway, ~1.0s) gives a single lane a capacity high enough (~2600+ veh/h) that a demand level that sounds oversaturating on paper may not actually queue.** Verified directly: 2400 veh/h at default tau produced zero queue and near-free-flow time loss. Raising `tau` to ~1.5s (a more cautious, realistic work-zone-adjacent following gap) drops single-lane capacity to ~2030 veh/h, so the same 2400 veh/h demand genuinely oversaturates (~1.18x). **Apply the same tau value identically to both the default and zipper runs** — an asymmetric tau invalidates the comparison. Always confirm oversaturation actually occurred (nonzero, sustained queue/time-loss) before trusting a "bottleneck comparison" — don't assume a demand number oversaturates just because it exceeds a textbook per-lane capacity figure.

## Metrics: discharge throughput, delay, and the queue-length ceiling effect

`scripts/analyze_merge_comparison.py` (adapt paths as needed) computes, from `edgeData` and `tripinfo`:
- **Sustained discharge throughput**: sum the bottleneck edge's `entered` (or `flow`) attribute over edgeData intervals covering the *sustained* window (exclude the startup transient, e.g. skip the first ~300s).
- **Mean time loss and mean depart delay** from tripinfo, averaged across all vehicles.
- **Max upstream queue length**: contiguous congested-edge length (e.g. speed below a halting threshold) summed from the merge upstream.

**Watch for a queue-length ceiling effect**: if the approach is short enough that the queue fills its entire physical length in BOTH variants, on-road queue length ties and stops being a discriminating metric — the real difference then shows up as **depart delay** (vehicles queued at their origin, unable to even insert into the network), which the on-road queue-length metric can't see. Report both metrics; don't conclude "no difference" from a tied queue length alone if depart delay tells a different story.

## Verified counter-intuitive finding

On a 1046m 2-lane approach dropping to a 596m single lane, 2400 veh/h sustained demand (tau=1.5s, oversaturating ~1.18x): **zipper made the bottleneck perform WORSE than the default merge, not better** — sustained discharge fell 1900.4→1791.3 veh/h (-5.7%), mean time loss rose 209.9s→252.7s (+20.4%), mean depart delay rose 267.9s→356.5s (+33.1%). Both variants' on-road queue tied at the full 1046m approach length (a ceiling effect); depart delay was the metric that actually revealed the difference. Confirmed robust in direction across 4 random seeds. **Interpretation: zipper is a fairness/merge-discipline device (forces strict lane-alternation) rather than a capacity booster — at this saturated 2-into-1 drop, strict alternation slightly depressed throughput relative to letting the merge opportunistically favor whichever lane has a vehicle ready sooner.** This directly contradicts the naive assumption that a "smarter, cooperative" merge type should always help — always measure, never assume, when evaluating a merge-discipline change.

## Gotchas

- **Confirm oversaturation actually occurred** (nonzero sustained queue/time-loss) before trusting any bottleneck comparison — a demand level that sounds high on paper may not exceed SUMO's actual per-lane capacity at default car-following parameters.
- **Apply any car-following parameter change (e.g. `tau`) identically to both compared runs.**
- **Diff the full compiled nets**, not just the junction line, to rule out an unintended geometry difference confounding the comparison.
- **A tied on-road queue length across variants can mask a real difference that shows up as depart delay instead** — always check both.
- **Don't assume zipper is strictly better** — it's a fairness/discipline mechanism, and this verified test found it can reduce discharge at saturation; test, don't assume, for a given topology/demand level.

## Related

- `implement-alinea-ramp-metering` — the ramp-onto-mainline context where `zipper` was first used in this memory, including the same compiled-net `Z`-state verification technique and the netconvert-geometry-trim note.
- `analyze-simulation-outputs` — general tripinfo/summary/edgeData comparison; this skill's discharge-throughput/queue-length metrics are a custom addition on top since they're not part of that skill's generic script.
- [[zipper-merge-lane-drop-discharge]] — the underlying finding and SUMO connection-state mechanics.
