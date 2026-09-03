---
name: model-urban-freight-delivery-tours
description: Use this skill when the user wants to model urban freight/goods movement in SUMO as multi-stop delivery TOURS rather than independent single-OD trips — nearest-neighbour/2-opt tour sequencing, SUMO's <container>/<transport>/<tranship>/containerStop object family for explicit parcel-level demand, truck-route-restriction sweeps with a vClass exemption (e.g. a delivery-van carve-out from a heavy-truck ban), loading-bay supply, and fleet consolidation. Covers the verified silent-failure modes of the container object family, the tour-vs-trip demand-modeling bias, truck-restriction exchange rates, and a critical vClass-assignment gotcha (screen by route feasibility, not edge permission, or a partial restriction sweep can manufacture a fake "partial bans are worse than complete bans" result). Trigger on mentions of delivery tours, urban freight, goods movement, truck route restrictions, containerStop, delivery van exemption, or last-mile logistics simulation.
related_skills:
  - model-vclass-lane-permissions
  - measure-heavy-vehicle-passenger-car-equivalent
  - model-curbside-delivery-and-lane-blocking-externality
  - simulate-fleet-emissions
  - convert-trips-to-routes
  - validate-congested-scenario-results-against-teleport-artifacts
related_skills_for_graph_view:
  - "[[model-vclass-lane-permissions]]"
  - "[[measure-heavy-vehicle-passenger-car-equivalent]]"
  - "[[model-curbside-delivery-and-lane-blocking-externality]]"
  - "[[simulate-fleet-emissions]]"
  - "[[convert-trips-to-routes]]"
  - "[[validate-congested-scenario-results-against-teleport-artifacts]]"
related_pages:
  - "[[urban-freight-delivery-tours-container-semantics-and-policy-levers]]"
  - "[[curbside-delivery-blocking-externality]]"
---

# Model Urban Freight and Delivery Tours

Models urban freight/goods movement as **delivery tours** — a vehicle visiting an ordered sequence
of stops carrying multiple parcels, with real loading/unloading obligations at each stop — rather
than the single-OD-trip demand paradigm every other demand skill in this memory uses
(`generate-random-trips`, `od2trips`, `activitygen`, etc.). This is a genuinely different demand
form: the vehicle's presence on the network is driven by a routing/scheduling problem (which stops,
in what order, from which depot) before any trip-assignment question is even asked, and its stops
carry a real time cost that a trip-based approximation cannot represent.

## Building tour-based demand

Assign delivery addresses to the nearest depot by **vClass-aware network distance** (not straight-
line distance — a restricted vClass's actual reachable distance can differ substantially), pack
addresses into tours under a parcel-capacity **and** a stop-count/time-budget cap, then sequence
each tour with **nearest-neighbour construction + 2-opt local-search improvement** (a few seeded
restarts is enough — this is not a hard combinatorial-optimization research problem, just a
reasonable, reproducible heuristic). Build each tour's actual driven route by concatenating
vClass-aware shortest paths between consecutive stops (via `sumolib`), so a restriction genuinely
forces a detour rather than silently producing an illegal route. Draw per-stop dwell from a
parcel-count-dependent distribution (e.g. a fixed per-stop overhead plus a per-parcel term,
clipped to a realistic range) rather than a flat duration — this is what makes the tour's time cost
sensitive to how much freight is consolidated onto it, which several of the hypotheses below depend
on.

**Re-plan tours against each restriction arm's own network, not once against the unrestricted
baseline.** A real carrier reassigns an address whose primary vClass is now banned to an exempted
vClass's tour rather than accepting the ban as fixed routing — modeling this "operator adaptation"
step is necessary for a restriction-coverage sweep to represent realistic behavior rather than a
worst-case one.

## The container/transport/tranship/containerStop object family: verified semantics

This is SUMO's freight-analogue of persons — model actual parcels as `<container>` elements with
their own loading/unloading lifecycle, not just as a vehicle dwell duration, if the study needs to
reason about delivered-vs-undelivered goods rather than only vehicle-level metrics. Verified
directly (see also `probe/`-style empirical checking, since several of these fail silently and are
easy to get wrong):

- **A `<transport from="edge" .../>` stage alone does not load the container, and produces no
  warning.** The container is placed at the edge's default position, outside the containerStop's
  range, and simply never boards. An explicit `<stop containerStop="..."/>` waiting stage (or a
  `departPos` inside the stop) is required.
- **Loading/unloading blocks the vehicle and is per-container additive**: effective dwell =
  `max(authored stop duration, loadingDuration * n_containers)`. If the study wants the *authored*,
  parcel-count-dependent dwell distribution to actually govern (rather than being overridden by
  SUMO's own per-container loading time), set `loadingDuration` to a small constant (e.g. 1s) so it
  never dominates.
- **A container that cannot be loaded fails completely silently**: capacity overflow past
  `containerCapacity`, a container referencing a nonexistent `lines=` vehicle, and a container that
  arrives after its intended vehicle has already left are all silent — exit code 0, empty stderr, no
  log warning, and the container simply never appears again. **A study must reconcile `offered`
  parcels (from the demand file) against `unloadedContainers` (from `stop-output`) and
  `<containerinfo>` count (from `tripinfo`) explicitly** — SUMO will not tell you if some fraction
  silently failed to load.
- **`<containerinfo>` in tripinfo appears only for containers that completed their full itinerary.**
  A container still in transit — or one that never boarded at all — is simply absent, **even with
  `--tripinfo-output.write-unfinished true`**. Undelivered parcels are invisible to a tripinfo-only
  analysis; a per-tour ledger tracking offered/loaded/unloaded counts directly from `stop-output` is
  the only reliable way to detect and count undelivered goods.
- **There is no `traci.container` domain in SUMO 1.27.1's Python TraCI.** Only
  `traci.vehicle.isAtContainerStop()`/`setContainerStop()` exist on the vehicle side — a study
  needing live container state cannot get it via TraCI and must reconstruct it from output files
  after the run (or, if live intervention is truly needed, track container-vehicle association
  manually via the vehicle's own stop state).
- **`expectedContainers` on a stop genuinely holds the vehicle** until the named container arrives
  or the stop's own timeout is reached — verified to hold a vehicle for hundreds of extra seconds
  waiting for a late container. Without this attribute, an identical late-arriving container is
  missed by the vehicle in silence (the vehicle simply departs without it), producing an
  undelivered parcel with no error.
- **A route file mixing `<container>` and `<vehicle>` elements out of departure-time order makes
  SUMO silently drop the out-of-order element**, with only a warning (`ignoring '<id>'!`), exit code
  0. This applies to both container and vehicle elements — sort the combined route file by depart
  time before loading it, and verify no `ignoring` warnings appear in the SUMO log as a routine
  validity check on any freight scenario's route file.
- A `parking="true"` (off-lane bay) vs `parking="false"` (in-lane, double-park) `containerStop` stop
  behaves identically for loading/unloading purposes — the two differ only in lane occupancy (see
  `model-curbside-delivery-and-lane-blocking-externality` for verifying and measuring that
  difference).

## Truck route restrictions: two genuinely different policies

Distinguish an **exempted restriction** (e.g. `disallow="truck"` — heavy trucks banned, delivery
vans still legal everywhere) from a **blanket restriction** (`disallow="truck delivery"` — every
freight class banned) when sweeping restriction coverage. These have qualitatively different
failure modes, not just different magnitudes: a blanket ban destroys service in rough proportion to
its coverage (addresses on banned streets simply cannot be served by any freight class), while an
exempted ban's service outcome depends entirely on whether the exempt class can still reach every
address through the *rest* of the network — which is a genuinely different, second-order question
from whether an address's own street is banned.

**Critical vClass-assignment gotcha — verify a candidate vehicle class by round-trip route
feasibility, not by edge permission alone.** A fleet-assignment heuristic that screens each address's
candidate vClass only by whether the *address's own edge* permits that class (e.g. "assign truck if
the street allows trucks, else assign van") can badly misclassify service failures under a *partial*
exempted restriction: an address on a still-truck-legal street can nonetheless sit behind a
restriction-fragmented truck sub-network deeper in the district, with no legal truck route in or out
— but the exempt van class may route there without any difficulty at all. If the heuristic never
retries the exempt class on route-feasibility failure, it will report that address as unservable —
manufacturing a spurious **non-monotone** service-vs-coverage curve (partial coverage looking worse
than complete coverage), because at 100% coverage every address is forced onto the exempt class from
the start and the bug cannot fire, while at partial coverage a fraction of addresses get stuck on a
failing non-exempt class assignment that a real operator would simply have re-routed around. **Fix:
have the demand generator retry every network-legal vClass with an actual round-trip
depot→address→depot route-feasibility check (via `sumolib.net.getShortestPath` or an equivalent
routing check) before declaring an address unservable, not just an edge-permission lookup.** Any
restriction-coverage sweep that finds a non-monotone service curve should check this specific failure
mode before reporting it as a genuine network finding — it is exactly the shape a route-feasibility
bug produces, and this project's own first draft of this study fell into it and had to walk the
finding back after independent review.

## The second-order reachability failure mode: traps, not just no-path

Under a **blanket** freight ban, addresses not directly on a banned street can still become
unservable through second-order network effects, and it's worth distinguishing two distinct
mechanisms rather than lumping them into one "unreachable" bucket: **no-path** (no legal route
exists to the address at all, inbound) and **trap** (a legal route exists *into* the address, but no
legal route exists *out* of it — e.g. because U-turns are disabled and the only legal continuation
from that point requires passing back through a now-banned street). A trapped address is a distinct
and non-obvious failure mode worth reporting separately, since a naive routing check that only tests
inbound reachability will miss it entirely and undercount true service failures. Verify the
classification order in code matches the intended semantics (e.g. test no-path before trap, and
confirm the counting identity — total-affected = no-path + trap-among-the-reachable — holds exactly
across every restriction-coverage level as an internal consistency check).

## Verified findings

- **Tour-vs-trip modeling bias is large and one-signed.** Modeling identical total parcel demand as
  independent single-OD truck trips (the common shortcut when a full freight-specific demand
  generator isn't available) substantially **overstates** truck VKT, freight emissions, and
  freight-attributable car delay relative to genuine tour-based demand, and inflates the apparent
  spatial concentration of truck presence — because a trip-based approximation doesn't capture that
  a single tour serves many nearby stops with much shorter marginal travel between them than a set
  of independent trips would each require. Always disclose which demand paradigm was used when
  reporting freight impact metrics; the two are not interchangeable approximations of the same
  quantity.
- **An exempted restriction's exchange rate collapses as coverage rises, and can refute the
  "worsens emissions" half of the standard exchange-rate framing entirely.** A heavy-truck ban with
  a van exemption reduces residential heavy-vehicle exposure, but total freight emissions can
  **fall** rather than rise with increasing restriction, if the exempt vClass's emission profile is
  cleaner per km than the restricted class's — don't assume a route-restriction's emissions
  consequence without checking the fleet's actual per-class emission factors; the exposure-vs-
  emissions tradeoff the practitioner literature assumes is not automatic once a cleaner exempt class
  exists.
- **A blanket (unexempted) restriction is not a tradeoff at all — it is service destruction
  proportional to coverage**, since there is no legal class left for a banned address to fall back
  to. Don't apply exchange-rate reasoning (a continuous cost/benefit curve) to a scenario where the
  actual outcome is a step function of complete service loss.
- **A loading bay's marginal delay-vs-deficit curve is not automatically convex** — the convex
  "few bays short costs far more than proportionally" shape found for a multi-lane curbside-delivery
  scenario (`curbside-delivery-blocking-externality`) does not automatically transfer to a
  single-lane residential street: with no escape lane, a double-park is already a complete blockage
  at the first deficit unit, so there's no partial-blockage regime left for a convex knee to emerge
  from — the curve can be statistically indistinguishable from linear instead. Check the specific
  road geometry (escape lane present or not) before assuming a convex bay-deficit shape transfers
  from a different study's geometry.
- **Fleet consolidation (fewer, larger vehicles for equal parcel throughput) has a genuine delay
  crossover, not a monotonic win.** VKT falls monotonically with consolidation, but per-vehicle PCE,
  dwell time, and lane-blocking duration all rise — past a specific fleet-size threshold, further
  consolidation can start costing more network delay than it saves, even though total driven
  distance keeps falling. Locate the crossover explicitly rather than assuming consolidation is a
  free win at any scale, and check whether an emissions crossover exists separately from the delay
  crossover — they need not coincide, or exist at all within a realistic range.
- **Off-peak/night delivery-window shifting's benefit curve can be convex (accelerating), not the
  commonly-assumed concave/saturating shape**, meaning a small shift buys disproportionately little
  and most of the achievable benefit only appears once a large majority of tours have shifted — with
  no saturation point below full shifting in some networks. Its noise counter-cost (night-weighted
  residential exposure) can be large enough to outweigh the daytime benefit entirely; report both,
  not just the daytime person-hours improvement.

## Gotchas

- Verify every restriction variant's compiled net directly (no missing or unexpected `disallow` on
  any lane) and every `containerStop`'s placement (lane exists, position within lane bounds, stop
  length exceeds the longest vehicle that will use it) — the same "verify from the compiled artifact,
  not the input intent" discipline every other network-construction skill in this memory applies.
- Injecting a pre-computed signal-timing plan (e.g. from `optimize-signals-by-tlscycleadaptation`)
  into an already-restriction-compiled net via a second additional file can fail with a
  duplicate-programID error — rewriting phase *durations* directly into each compiled net variant
  (after confirming phase *state strings* are byte-identical across variants, i.e. the permission
  edits didn't change link indices) is the reliable alternative.
- A demand generator that reuses a fixed byte-identical parcel/address/depot layout across
  restriction arms (varying only the network) makes a restriction-coverage sweep a clean
  dose-response comparison — regenerate demand once per arm only where the restriction genuinely
  changes routing feasibility, and verify unaffected arms produce byte-identical demand as an
  internal consistency check on the generator itself.
- Reconcile `parcels_by_design = parcels_delivered + parcels_undelivered` exactly in every arm as a
  standing validity check — any gap indicates a bug in the tour/container accounting, not a genuine
  finding.

## Related

- `model-vclass-lane-permissions` — the base `disallow`/`allow` restriction mechanism this skill's
  restriction-coverage sweep is built on, including the `duarouter`-without-`--ignore-errors`
  reachability-check technique this skill's vClass-fallback fix depends on.
- `measure-heavy-vehicle-passenger-car-equivalent` — the PCE measurement methodology used to
  quantify a truck-concentration effect on arterial signal capacity.
- `model-curbside-delivery-and-lane-blocking-externality` — the lane-blocking verification protocol
  (stop-output, laneData, forced lane changes) this skill reuses for loading-bay double-parking, and
  the multi-lane convex-externality finding this skill's single-lane linear-delay result qualifies.
- `simulate-fleet-emissions` — the mixed-fleet HBEFA3 emission-class setup used to quantify the
  restriction-exchange-rate emissions side.
- `convert-trips-to-routes` — `duarouter` route computation/repair, and the reachability-detection
  technique (routing without `--ignore-errors`) this skill uses to independently cross-check
  `sumolib`-based reachability claims.
- `validate-congested-scenario-results-against-teleport-artifacts` — teleport-artifact discipline
  needed to distinguish genuine service failure/gridlock from simulator artifacts.
- [[urban-freight-delivery-tours-container-semantics-and-policy-levers]] — the knowledge page with
  the full verified findings (container semantics, tour-vs-trip bias, restriction exchange rates,
  consolidation crossover, off-peak nonlinearity, the trap failure mode, and the withdrawn
  non-monotonicity finding kept as a documented modeling caution) this skill's workflow is built on.
- [[curbside-delivery-blocking-externality]] — the multi-lane loading-bay externality finding this
  skill's single-lane result contrasts with.
