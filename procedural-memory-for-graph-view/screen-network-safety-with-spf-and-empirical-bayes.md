---
name: screen-network-safety-with-spf-and-empirical-bayes
description: Use this skill when the user wants to rank a NETWORK of sites by crash risk rather than evaluate one intersection — hotspot identification, network safety screening, site prioritisation, "which intersections should we fix first" — or when they want to connect SUMO's simulated surrogate conflicts to the crash-prediction machinery that actually governs safety investment: HSM Part C safety performance functions (SPFs), negative-binomial overdispersion, the Empirical Bayes method, regression-to-the-mean bias in crash-based hotspot lists, Part D crash modification factors (CMFs), and conflict-to-crash transfer functions. Covers building a multi-site inventory, replicating the SSM conflict layer, generating synthetic ground-truth crash histories, scoring competing screening methods against known truth with Monte-Carlo confidence intervals, and cross-checking a simulated treatment effect against a published CMF. Trigger on mentions of network screening, hotspot identification, safety performance function, SPF, Empirical Bayes, EB estimate, regression to the mean, crash modification factor, CMF, HSM, site ranking, or conflict-to-crash conversion.
related_skills:
  - analyze-intersection-safety-with-ssm
  - create-single-intersection
  - compare-left-turn-signal-treatments
  - quantify-sumo-run-to-run-variability
  - appraise-project-alternatives-with-benefit-cost-analysis
  - analyze-simulation-outputs
related_skills_for_graph_view:
  - "[[analyze-intersection-safety-with-ssm]]"
  - "[[create-single-intersection]]"
  - "[[compare-left-turn-signal-treatments]]"
  - "[[quantify-sumo-run-to-run-variability]]"
  - "[[appraise-project-alternatives-with-benefit-cost-analysis]]"
  - "[[analyze-simulation-outputs]]"
related_pages:
  - "[[network-safety-screening-and-crash-prediction]]"
  - "[[surrogate-safety-measures]]"
  - "[[left-turn-treatment-tradeoffs]]"
---

# Screen Network Safety with SPFs and Empirical Bayes

Ranks a *network* of intersections by crash risk, and tests whether a simulated
conflict measure can substitute for or complement crash-data screening. Every
other safety skill in memory (`analyze-intersection-safety-with-ssm`,
`compare-left-turn-signal-treatments`, `design-signal-change-and-clearance-intervals`)
evaluates ONE site's conflicts; this one is the network-level, investment-decision
layer that sits on top of them, and it is the first to connect SUMO output to
HSM Part B/C/D methods.

The core design trick: **generate the ground truth yourself.** Define each site's
true long-term mean crash frequency as its SPF value, then sample synthetic
observed crash histories from it. Because truth is known, every screening method
can be *scored*, not merely compared.

## Pipeline

```bash
# 1. build N standalone intersection networks + demand from one inventory module
python scripts/build_sites.py --root outputs/sites          # see `create-single-intersection`
# 2. replicate every site over a seed family
python scripts/run_batch.py --sites-root outputs/sites --out-root runs/base --seeds 1:13
# 3. extract conflicts + efficiency per run
python scripts/extract_ssm.py --runs-root runs/base --out-csv analysis/metrics_base.csv
# 4. how many seeds did you actually need?  (report the noise floor)
python scripts/replication_design.py --metrics-csv analysis/metrics_base.csv \
    --out-csv analysis/replication_design.csv --out-json analysis/replication_summary.json
# 5. SPF + EB + Monte-Carlo scoring against known truth
python scripts/screening.py --metrics-csv analysis/metrics_base.csv \
    --out-dir analysis --years 3 --mc 2000
# 6. treatment before/after + published-CMF cross-check
python scripts/countermeasure_cmf.py --base-csv analysis/metrics_base.csv \
    --var-csv analysis/metrics_variants.csv --out-dir analysis
# 7. conflict-to-crash transfer function + cross-validation
python scripts/transfer_function.py --site-table analysis/site_table.csv --out-dir analysis
```

`scripts/hsm.py` holds every published coefficient, CMF and collision-type share
with its citation inline, and labels each ASSUMED value explicitly. Replace its
constants for a different SPF family; nothing else needs to change.

## Get the SPF coefficients from a source you can actually quote

The HSM's printed coefficient tables are not freely accessible and search results
for them are unreliable — one search returned a confidently wrong 4ST intercept.
**NCHRP Web-Only Document 297, "Draft Text for the Second Edition of the HSM"**
(`onlinepubs.trb.org/onlinepubs/nchrp/nchrp_wod_297Draft.pdf`) is a real,
fetchable TRB document containing full SPF equations, overdispersion parameters,
*stated AADT applicability ranges*, and the collision-type distribution tables.
Download it and `pdftotext -layout` it rather than trusting a web summary.

**Design the site inventory to fit inside each SPF's stated AADT range.** A 10x
AADT span that keeps every site in range beats a 15x span that runs the SPF
outside its validated domain. Record `in_spf_range` per site either way.

## Empirical Bayes, correctly

In annual units, with `Y` years of observed data:

```
w        = 1 / (1 + k * N_spf * Y)
N_eb     = w * N_spf + (1 - w) * N_observed_annual
EB excess = N_eb - N_spf
```

`k` is the SPF's own overdispersion parameter and is **per control type**, not
global. Three dependencies fall out of the formula and all three are worth
reporting, because they tell an agency where EB matters most:

- **years**: w falls ~5-8x from Y=1 to Y=10 — EB converges to the naive count.
- **volume**: at fixed k, w falls as N_spf rises. A high-volume site is trusted
  to its own data; a low-volume site is shrunk hard toward the SPF.
- **overdispersion**: at equal N_spf, a higher-k SPF gets *less* weight on the
  prediction — a noisier SPF is trusted less, which is the whole point of k.

**EB *excess* is a different screening criterion from EB expected frequency, and
it is much worse at finding the highest-crash sites** (verified: rho ≈ −0.04
against total-crash truth vs 0.91 for EB expected). Excess answers "which site is
worst *relative to sites like it*", not "which site has the most crashes". Don't
substitute one for the other.

## Score against truth with a Monte-Carlo loop, not one draw

Sample the observed history as a Poisson-Gamma mixture so the variance is the
HSM's negative-binomial form:

```python
lam   = rng.gamma(shape=1/k, scale=k*n_true, size=(n_sites, years))
counts = rng.poisson(lam)                      # Var = n_true + k*n_true^2
```

Then repeat ~2000 times and report percentile CIs on Spearman rho, top-N hit
rate and false-positive rate. A single synthetic history gives a lucky-draw
answer; the CI on Spearman rho for observed-frequency screening spans roughly
0.76-0.95 at Y=3, which is wider than most of the differences between methods.

**Define the false-positive rate as FP / (S − N), not 1 − hit rate.** When the
flagged set and the true set have the same size N, precision equals recall
identically, so "false-positive rate" defined as 1 − hit rate carries no extra
information. FP over the true negatives does.

## The tautology trap — declare it or the whole study is worthless

If truth is `C * SPF * CMF` and the screening SPF uses the same formula, then the
SPF scores Spearman rho = 1.000 **by construction**. That is arithmetic, not
evidence that SPFs are accurate. Two defences, both worth running:

1. **Run a genuinely mis-specified problem.** Score a *type-matched* truth (e.g.
   angle crashes = SPF x angle-share x CMF_angle) against an SPF that lacks the
   phasing inventory. The CMF is now large, so the blind SPF is really wrong, and
   the comparison is informative.
2. **Add a persistent unmeasured site effect** (`--phi`): make a fraction of the
   overdispersion a fixed per-site multiplier rather than year-to-year noise.
   With phi = 0, shrinking toward the SPF is the exactly-correct Bayes operation,
   which maximally flatters EB. Verified: at phi = 0 the SPF beat observed
   frequency (1.000 vs 0.878); at phi = 0.5 observed frequency *overtook* the SPF
   (0.921 vs 0.887) and EB beat both (0.936). Report both.

## Compare against the TYPE-MATCHED CMF, never the aggregate

Left-turn phasing CMFs differ by nearly an order of magnitude between crash
categories, and the aggregate one is essentially null:

| treatment | total crashes | left-turn crashes | rear-end |
|---|---|---|---|
| permissive -> protected/permissive | 1.023 (SE 0.016, n.s.) | 0.862 | 1.075 |
| permissive -> protected-only | ~1.0 | ~0.30 | — |

(FHWA-HRT-18-044 Table 35 and its literature review of Hauer 2004 and Srinivasan et al.)

So a simulation that reports "protected lefts changed total conflicts by +33%"
is comparing against a CMF of ~1.0 and will look catastrophically wrong, while
the *same run's* crossing-conflict ratio may match the left-turn CMF closely.
Verified on a matched-AADT phasing triplet: simulated crossing-conflict ratio
0.832 vs published left-turn-opposing CMF 0.862 — **3% disagreement** — while the
total-conflict ratio was 1.328 vs a CMF of 1.023, a 30% disagreement. Always
break conflicts down by encounter-type code and match categories before
concluding anything about agreement.

## Report the operational cost alongside the safety change

A treatment's delay/throughput effect belongs in the same table as its conflict
effect, and **the sign is not predictable and flips with demand**. Verified:
converting the highest-volume site from permissive to protected-only cut crossing
conflicts 40.1% and severe (TTC<1.5 s) crossing conflicts 81.9% while *also*
cutting mean time loss 4.4% (p=0.051) and raising throughput 0.6%. The identical
treatment at a medium-volume matched-AADT site *raised* mean time loss 50.5%
(p<10⁻⁶). Measure it per site.

## Pair every before/after on the seed family, and measure whether it helped

Reuse the parent site's demand definition and the identical seed list in the
treated arm, then report the paired correlation and variance-reduction factor
rather than assuming Common Random Numbers helps (the discipline from
`quantify-sumo-run-to-run-variability`, which documents CRN *hurting* a weakly
correlated metric). Verified here: conflict counts at fixed geometry are strongly
seed-correlated (paired r = 0.71–0.85), giving variance-reduction factors of
2.8–6.5 — the favourable end of that range, but measured, not assumed.

## Gotchas

- **A `<tlLogic>` in an additional file cannot override the net's own program 0**
  — SUMO errors `Another logic with id 'X' and programID '0' exists`. Deleting the
  net's `<tlLogic>` does not help either: the junction's tls reference goes
  dangling and SUMO errors `The tls 'X' is not known`. The working route is a
  **two-pass netconvert**: compile once to read the `linkIndex`/`dir` mapping,
  author the program from it, then re-compile the same plain XML with
  `--tllogic-files <file>` so the program is baked into the net.
- **Required replication count varies enormously across a site inventory** — one
  verified jurisdiction needed 7 seeds at its busiest site and 158 at its
  quietest, because CV of conflict count rises as counts fall. Compute required-n
  **per site** and top up only the sites that need it, rather than picking one
  seed count for the whole network.
- **Check `inserted / loaded` per site.** Oversaturated stop-controlled minor
  approaches can leave 6-15% of demand never entering the network, which
  truncates both the conflict count and the entering-vehicle denominator. Flag
  those sites; don't quietly rank them.
- **Conflict frequency and conflict rate rank sites differently, but far less
  than crash frequency and crash rate do.** Verified: Spearman between conflict
  frequency and conflict rate was 0.947 (max rank shift 6 of 20), while between
  *true* crash frequency and crash rate it was 0.556 (max rank shift 13). Crash
  rate per MEV is a badly biased screening criterion because SPF AADT exponents
  are below 1, so rate *decreases* with volume and the criterion systematically
  promotes low-volume sites — verified rho of only 0.354 against truth.
- **`--device.ssm.file` must be passed per run on the command line**, and every
  vehicle double-logs each physical encounter — de-duplicate on the unordered
  {ego, foe} pair with overlapping time windows. See
  `analyze-intersection-safety-with-ssm`.
- **`type="111"` SSM encounters are not simulated collisions.** Verified again
  here: 19 type-111 encounters across 988 runs against 0 in both `summary.xml`'s
  `collisions` field and `--collision-output`.

## Related

- `analyze-intersection-safety-with-ssm` — the single-site SSM device setup, encounter-type codes and TTC/PET conventions this skill's conflict layer reuses.
- `create-single-intersection` — the plain-XML + netconvert network shape each inventory site is built from.
- `compare-left-turn-signal-treatments` — the programmatic `tlLogic` state-string generation (from the compiled net's own link map) used for every signalized site here.
- `quantify-sumo-run-to-run-variability` — the required-n and noise-floor method, and the CRN discipline used for every before-after comparison.
- `appraise-project-alternatives-with-benefit-cost-analysis` — the downstream consumer of a conflict-to-crash factor; this skill quantifies how unstable that factor is (23x across sites).
- `analyze-simulation-outputs` — tripinfo/summary parsing conventions, including the cumulative-`teleports` gotcha.
- [[network-safety-screening-and-crash-prediction]] — SPFs, overdispersion, EB, regression to the mean, CMFs, and the validity limits of surrogate-to-crash conversion.
- [[surrogate-safety-measures]] — the SSM device concepts underneath the conflict layer.
- [[left-turn-treatment-tradeoffs]] — the treatment whose CMF is cross-checked here.
