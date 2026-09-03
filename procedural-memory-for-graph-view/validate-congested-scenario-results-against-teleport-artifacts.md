---
name: validate-congested-scenario-results-against-teleport-artifacts
description: Use this skill when the user wants to determine how much of a congested/oversaturated SUMO scenario's measured performance is real traffic physics versus an artifact of SUMO's gridlock-resolution teleporting mechanism, or wants to choose a defensible --time-to-teleport setting and reporting convention for a congested-network result. Covers sweeping --time-to-teleport as a treatment variable, the survivorship-censoring danger of disabling teleporting entirely, teleport-free vs. all-trips dual accounting, junction keep-clear (don't-block-the-box) mechanics, a matched-cohort re-test technique for validating a prior finding's teleport sensitivity, and a concrete decision rule for what must be reported alongside any oversaturated-scenario result. Trigger on mentions of time-to-teleport, teleport artifact, gridlock resolution, survivorship censoring, keep-clear, don't-block-the-box, or "is this congestion result real or a simulator artifact."
related_skills:
  - implement-mfd-based-perimeter-gating
  - create-grid-network
  - quantify-sumo-run-to-run-variability
  - analyze-simulation-outputs
  - characterize-pedestrian-flow-and-striping-model-artifacts
  - model-cruising-for-parking-search-externality
  - model-urban-freight-delivery-tours
related_skills_for_graph_view:
  - "[[implement-mfd-based-perimeter-gating]]"
  - "[[create-grid-network]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[analyze-simulation-outputs]]"
  - "[[characterize-pedestrian-flow-and-striping-model-artifacts]]"
  - "[[model-cruising-for-parking-search-externality]]"
  - "[[model-urban-freight-delivery-tours]]"
related_pages:
  - "[[teleport-artifacts-and-gridlock-resolution-validity]]"
---

# Validate Congested-Scenario Results Against Teleport Artifacts

Determines how much of a congested SUMO network's measured performance is genuine traffic physics versus an artifact of SUMO's own gridlock-resolution machinery (`--time-to-teleport`), and establishes what must be reported to make a congested-network result trustworthy. `--time-to-teleport` appears throughout memory's other skills with inconsistent conventions (some use `-1`, some 120s, some the 300s default) and no prior skill or page explained which is correct when — this skill fills that gap and is the first to treat teleporting itself as an object of study rather than an incidental setting.

## Building a genuinely gridlock-capable test network

Use short blocks (so a queue at one intersection reliably spills back into the upstream junction) and a demand pattern with genuine circular-blocking potential (e.g. an explicit saturated ring route that turns the same direction at every corner, in addition to general fringe-to-fringe demand). **Verify the network is well-behaved at low demand first** — identical output across every `--time-to-teleport` value at undersaturated demand is strong evidence the network itself isn't pathologically prone to spurious teleporting, and that any teleport-sensitivity found later is a genuine congestion effect, not a network-design artifact.

## The central danger: disabling teleporting can produce the MOST misleading result, not the safest one

**Verified, important finding: `--time-to-teleport -1` (teleporting fully disabled) is often assumed to be the "safest," most physically-faithful setting for congested scenarios — but it can produce the single most misleading-looking result of all.** `tripinfo` only records vehicles that actually complete their trip. If teleporting is disabled and the network genuinely deadlocks (verified: running vehicle count freezes permanently, zero arrivals, zero speed, for the remainder of the simulation), the reported mean travel time is computed only over the small subset of vehicles lucky enough to complete their trip *before* lockup occurred — a severe **survivorship-censoring artifact**. A permanently gridlocked network can report a *better*-looking mean travel time than a network that used teleporting to keep flowing (badly, but flowing), because the gridlocked network's terrible outcomes for stuck vehicles simply never appear in the average at all. **Always check the running-vehicle-count time series for a permanent freeze before trusting any `ttt=-1` travel-time result** — a frozen running count with zero arrivals for an extended tail of the simulation is the unambiguous signature.

## `tripinfo` has no teleport field — teleport information must come from elsewhere

Confirmed: `tripinfo`'s XML schema contains no attribute recording whether or how many times a vehicle was teleported. The only sources are SUMO's own warning/log output (grep for the teleport warning message and extract affected vehicle IDs) or a live TraCI query (`traci.simulation.getStartingTeleportIDList()`). Any teleport-aware analysis pipeline must parse one of these separately from the standard tripinfo/summary outputs.

## The teleport-counting convention: read the last cumulative value, never sum

`summary` output's `teleports` attribute is a cumulative running count for the whole simulation, not a per-step delta — confirmed directly: summing across all steps in one verified run gave 99,559 versus the true final-step value of 125, a ~800x over-count. Always read the last step's value (or `max()` across steps), consistent with [[sumo-output-files]]'s established convention.

## Teleport-free subsetting narrows the artifact but does not eliminate it

**Verified finding: restricting analysis to only teleport-free vehicles' trips does not remove the dependence on `--time-to-teleport`.** In one test, the teleport-free-vehicle mean travel time still varied substantially (more than 3x) across different `--time-to-teleport` settings at fixed demand and seeds. The mechanism: teleporting doesn't just repair the teleported vehicle's own trip — it changes the entire network's traffic state (freeing capacity, dissolving a blocking jam) for every other vehicle too. **A "teleport-free" subset is not a clean, teleport-independent measurement** — it's a narrower version of the same artifact, still sensitive to how aggressively the simulator intervenes elsewhere in the network.

## A low `--time-to-teleport` can manufacture teleports from ordinary signal queueing

Verified: setting `--time-to-teleport` below the network's own maximum red-signal duration can trigger teleports purely from vehicles waiting through an ordinary (not pathologically congested) red phase, even at *undersaturated* demand. Always confirm `--time-to-teleport` exceeds the longest expected legitimate wait (e.g. the longest red phase) in the network before treating any teleport count as evidence of genuine gridlock.

## Junction keep-clear (don't-block-the-box): the physical mechanism behind spillback-induced gridlock

Permitting vehicles to enter and stall inside a junction box (via `keepClear="false"` on connections, or equivalent netconvert/vType settings) versus SUMO's default keep-clear-on behavior is a genuine, verifiable physical mechanism — confirmed both structurally (the compiled network's connection `keepClear` attribute) and behaviorally (dramatically more vehicle-time spent standing inside junction-box internal edges when keep-clear is off, measurable via `edgeData` with `withInternal="true"`).

**Verified finding: the effect of permitting box-blocking is non-monotone in demand level.** At moderate oversaturation, permitting box-blocking can genuinely *help* — it lets more vehicles queue where they're going rather than being held back, reducing teleports and improving throughput. At severe oversaturation, the same setting becomes *catastrophic* — box-blocking at multiple adjacent junctions compounds into true network gridlock, with throughput and travel time getting dramatically worse. **Don't assume permitting box-blocking is either always harmful (the intuitive "obviously blocking the box is bad" assumption) or always helpful (a naive "more flexibility must help" assumption)** — verify at the specific demand level in question, since the sign of the effect can flip with severity of oversaturation.

## Re-testing a prior finding's teleport sensitivity: the matched-cohort technique

To determine whether a previously-published comparison's benefit was partly a teleport artifact, don't just compare "all trips" against "each arm's own teleport-free subset" naively — **the two arms of a comparison can have different vehicles affected by teleporting, so naive per-arm teleport-free subsetting removes different populations from each arm and is itself a biased comparison.** Instead, compute the **matched common cohort**: the set of vehicles that were teleport-free in *both* arms of the comparison, and compare only that shared population's outcomes across both arms. This is the methodologically correct teleport-free re-test, more defensible than either the raw (teleport-contaminated) comparison or a naive per-arm-subset comparison.

**Verified application**: re-testing a prior perimeter-gating episode's published -44.7% travel-time improvement this way found the benefit survives — roughly 86% of the original effect was genuine, with roughly 14% attributable to teleport-related contamination of the ungated baseline. The original finding's direction and rough magnitude were confirmed correct, even though the specific caveat about possible teleport contamination was worth raising and checking.

## A decision rule for reporting congested-scenario results

1. `--time-to-teleport` must exceed the network's longest legitimate red-signal wait, or it manufactures spurious teleports even without real gridlock.
2. Use `-1` (disabled) only for undersaturated/physical-mechanism studies, or explicitly as a deadlock-diagnostic tool — never trust a `-1` run's mean travel time without first checking for a running-count freeze (survivorship censoring risk).
3. Use a moderate finite value (roughly 120-300s) when travel-time metrics are wanted from a genuinely oversaturated network.
4. A teleport-affected share above roughly 2% of completed trips should be treated as invalidating a stand-alone travel-time number reported without further caveat — always co-report the teleport-affected share alongside any such metric.
5. Whenever validating an intervention (a control, a policy, an infrastructure change) on a congested network, evaluate it under at least: (a) the raw all-trips comparison, (b) the matched-common-cohort teleport-free comparison, and (c) a check of what happens with teleporting disabled (to catch survivorship-censoring reversals) — a benefit that only survives condition (a) is not yet trustworthy.

## Gotchas

- **`--time-to-teleport -1` can make a permanently deadlocked network look BETTER than a functioning-but-congested one**, via survivorship censoring of `tripinfo`'s arrival-only data — always check for a running-count freeze first.
- **`tripinfo` has no teleport field** — parse the warning log or use TraCI for teleport-affected vehicle identification.
- **`summary`'s `teleports` attribute is cumulative** — read the last step, never sum across steps.
- **Teleport-free subsetting reduces but does not eliminate `--time-to-teleport` sensitivity** — teleporting changes the whole network's state, not just the teleported vehicle's own trip.
- **A too-low `--time-to-teleport` manufactures teleports from ordinary signal-queueing waits**, not genuine gridlock — verify it exceeds the network's longest legitimate red phase.
- **The effect of permitting junction-box blocking is non-monotone in demand severity** — helpful at moderate oversaturation, catastrophic at severe oversaturation.
- **Naive per-arm teleport-free subsetting is itself a biased re-test of a two-arm comparison** — use the matched common cohort (vehicles teleport-free in both arms), not each arm's own independently-filtered subset.

## Related

- `implement-mfd-based-perimeter-gating` — the prior episode whose open teleport-contamination caveat this skill directly resolves; the gating controller's core/gate-derivation and negative-control-verification technique was reused for the re-test.
- `create-grid-network` — the base network-generation technique this skill's gridlock-prone grid is built from.
- `quantify-sumo-run-to-run-variability` — the replication/per-seed-directional-agreement methodology this skill's teleport sweep applies.
- `analyze-simulation-outputs` — general tripinfo/summary parsing conventions, including the teleport-counting convention this skill relies on.
- [[teleport-artifacts-and-gridlock-resolution-validity]] — the verified survivorship-censoring, dose-response, keep-clear, and gating-validity-re-test findings.
- `characterize-pedestrian-flow-and-striping-model-artifacts` — applies this skill's artifact-validation discipline to the pedestrian analog of teleporting (`--pedestrian.striping.jamtime`'s jam-resolution push-through mechanism), and found the commonly-assumed default value for that parameter is wrong — the real default is far less artifact-prone than the value often assumed.
- `model-cruising-for-parking-search-externality` — applies this skill's teleport-artifact discipline to a parking-undersupply failure-mode study, and separately documents a teleport-by-reason logging gotcha (SUMO emits two log lines per teleport event, only one carrying a reason keyword, which double-counts if not filtered) worth checking for in any teleport-reason-breakdown analysis, not just this skill's own count-based checks.
- `model-urban-freight-delivery-tours` — applies this skill's teleport-artifact discipline to a freight-tour reachability-failure study, and adds a container-specific analog: delivered-vs-undelivered parcel accounting must be reconciled explicitly, since an undelivered container is invisible in `tripinfo` even with `--tripinfo-output.write-unfinished`, the same silent-omission risk this skill's vehicle-side teleport/completion checks guard against.
