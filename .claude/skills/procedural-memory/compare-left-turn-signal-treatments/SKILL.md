---
name: compare-left-turn-signal-treatments
description: Use this skill when the user wants to model and compare left-turn signal-control treatments at a SUMO intersection — permissive (share the through green, yield to oncoming), protected (exclusive leading arrow, no yielding), or protected-permissive (leading arrow then a permissive period) — as opposed to every other signal-control skill in memory, which treats phases purely as through-movement green/red splits. Covers authoring a dedicated left-turn lane (turn pocket) as a genuinely separate connection, generating tlLogic state strings PROGRAMMATICALLY from the compiled net's own link-index mapping to prevent G/g/r case drift, filtering SSM conflicts to specific movement pairs (not all intersection conflicts), and the verified finding that protected-permissive can beat protected-only on efficiency, not merely sit between it and permissive. Trigger on mentions of left-turn treatment, permissive left turn, protected left turn, protected-permissive phasing, or turn pocket.
---

# Compare Left-Turn Signal Treatments

Compares permissive, protected, and protected-permissive left-turn signal control at a single intersection — a distinct design axis from every other signal-control skill in memory, which treats phases purely as through-movement green/red splits without addressing how left turns are handled relative to oncoming traffic.

## Dedicated left-turn lane geometry

Give each approach two lanes: lane 0 (through + right, shared) and lane 1 (exclusive left turn), with the left movement as a genuinely separate `<connection>`:

```xml
<connection from="in_N" to="out_S" fromLane="0" toLane="1"/>  <!-- through -->
<connection from="in_N" to="out_W" fromLane="0" toLane="0"/>  <!-- right -->
<connection from="in_N" to="out_E" fromLane="1" toLane="1"/>  <!-- left, dedicated lane -->
```

Verify from the compiled net that left movements (`dir="l"`) are distinct controlled links from through (`dir="s"`) and right (`dir="r"`), not merged.

## Generate tlLogic state strings programmatically, keyed on the compiled net's own link map

**Hand-typing three separate state strings for three treatments is error-prone — a single mistyped 'G' vs 'g' silently invalidates the whole comparison.** Instead, read the compiled net's own `linkIndex`/`dir` attributes and generate every phase string from a movement→index dictionary:

```python
mv = {(approach, c.get("dir")): int(c.get("linkIndex"))
      for c in net.findall("connection") if c.get("tl") == "center"
      for approach in [c.get("from").split("_")[1]]}
L = {a: mv[(a, "l")] for a in "NESW"}   # left-turn link index per approach
# then build each phase as a dict {link_index: char}, defaulting to 'r'
```

See `scripts/gen_programs.py` for the full working generator, which also prints an annotated per-phase table (`leftL(N,S,E,W)=...`) so the actual G/g/r pattern can be visually verified against intent before running.

## The three treatments' state-string signature

- **Permissive-only**: left link is `g` (lowercase, yield) whenever its approach has the green, on every phase — never `G`.
- **Protected-only**: left link is `G` (uppercase, exclusive) only during a dedicated leading phase, and `r` during the subsequent through-green phase — never `g` anywhere.
- **Protected-permissive**: left link is `G` during a leading phase, then `g` during the following through-green phase (permissive fill-in) — the only treatment using both cases.

Keep total cycle length comparable across all three programs so the comparison isolates left-turn treatment rather than confounding it with a different overall capacity allocation.

## Filtering SSM conflicts to specific movement pairs

Don't count every SSM-logged conflict at the intersection — filter specifically to the left-turn-vs-oncoming-through vehicle/route pairs (e.g. N-left vs S-through, S-left vs N-through, etc.) so the safety comparison isolates the treatment's actual effect rather than diluting it with unrelated conflicts (e.g. right-turn or pedestrian encounters). Remember every vehicle carries its own SSM device, so a single physical near-miss is logged from both participants' perspectives — roughly doubling raw counts consistently across all scenarios; this doesn't bias a relative comparison but should be kept in mind when quoting an absolute count.

## Verified finding: protected-permissive can beat protected-only on efficiency, not just sit between

**Textbook intuition suggests protected-permissive's efficiency should fall between permissive (most efficient, least safe) and protected (least efficient, safest) — but this isn't always true.** Verified directly: on a genuine 4-approach intersection with heavy (38.5%) left-turn demand not quite justifying a full protected phase's capacity cost, protected-only had the *highest* overall intersection delay of all three treatments, while protected-permissive was actually the *best* on both overall delay and left-turn wait — not merely intermediate — because left-turners got a protected head-start plus a permissive fill-in window, extracting efficiency from both mechanisms. The safety ordering (protected safest, permissive least safe, protected-permissive between) held as expected; it was specifically the efficiency ordering that deviated from the simple mental model. **Verify actual demand levels against a treatment's capacity cost via simulation rather than trusting a textbook heuristic uncritically.**

## Gotchas

- **Hand-typed state strings across multiple similar treatments are a real source of subtle bugs** — generate them programmatically from the compiled net's link-index mapping instead, and print an annotated verification table before running.
- **Filter SSM conflicts to the specific movement pairs of interest**, not every intersection conflict indiscriminately.
- **Every vehicle's own SSM device double-logs each physical near-miss** (once per participant) — consistent across scenarios, so safe for relative comparison, but worth noting for absolute counts.
- **Don't assume protected-permissive is always "in between" on every metric** — verify the efficiency ordering against your actual demand level; a dedicated protected phase's capacity cost can outweigh its efficiency at moderate left-turn volumes.

## Related

- `create-single-intersection` — the base single-junction network shape this skill's dedicated-lane geometry extends.
- `control-signals-with-actuated-tls` — general tlLogic/state-string conventions background.
- `analyze-intersection-safety-with-ssm` — the SSM device configuration and TTC/PET interpretation this skill's filtered conflict measurement reuses.
- `build-pedestrian-crossings-and-phasing` — a structurally similar exclusive-vs-concurrent phasing comparison, for pedestrian rather than left-turn movements.
- [[left-turn-treatment-tradeoffs]] — the underlying safety/efficiency mechanics and the verified non-textbook efficiency finding.
- `design-left-turn-storage-bay-length` — extends this skill's fixed-length bay geometry to a swept design variable, instrumenting bay overflow and blockage/starvation as separate failure modes and finding signal retiming cannot compensate for an undersized bay while actuated control can help or badly backfire depending on bay length.
