"""
Synthetic agency jurisdiction: site inventory.

Single source of truth for the 20 intersection sites.  Every downstream script
(network build, demand build, SPF, EB screening, transfer function) reads this
module, so the SPF and the simulation are guaranteed to be fed identical
covariates.

Covariates that an HSM Part C intersection SPF actually uses:
    AADT_major, AADT_minor, control type (4SG / 4ST / 3ST)
Covariates the base SPF does NOT use but which HSM Part D CMFs can adjust:
    left-turn phasing on the major road
Covariates that neither the SPF nor any standard CMF uses:
    number of through lanes, posted speed, signal cycle length

MPH -> m/s.
"""

MPH = 0.44704

# id, control, aadt_major, aadt_minor, lanes_major, lanes_minor, phasing, speed_mph, cycle_mode
# phasing applies to the MAJOR-road left turns only (minor lefts are always permissive).
#   perm     = permissive only            (left link 'g' during major through green)
#   protperm = protected + permissive     (leading dual-left 'G', then 'g' in through green)
#   prot     = protected only             (leading dual-left 'G', 'r' in through green)
#   none     = unsignalized site
# cycle_mode: 'webster' (Webster-optimal cycle) or 'short45' (deliberately short 45 s cycle)
SITES = [
    # --- 4-leg signalized -------------------------------------------------
    dict(site="S01", control="4SG", aadt_major=8000,  aadt_minor=2500,
         lanes_major=1, lanes_minor=1, phasing="perm",     speed_mph=35, cycle_mode="webster"),
    dict(site="S02", control="4SG", aadt_major=12000, aadt_minor=4000,
         lanes_major=1, lanes_minor=1, phasing="protperm", speed_mph=35, cycle_mode="webster"),
    dict(site="S03", control="4SG", aadt_major=16000, aadt_minor=9000,
         lanes_major=2, lanes_minor=2, phasing="perm",     speed_mph=40, cycle_mode="webster"),
    dict(site="S04", control="4SG", aadt_major=20000, aadt_minor=5000,
         lanes_major=2, lanes_minor=1, phasing="prot",     speed_mph=45, cycle_mode="webster"),
    dict(site="S05", control="4SG", aadt_major=23000, aadt_minor=11000,
         lanes_major=2, lanes_minor=2, phasing="protperm", speed_mph=45, cycle_mode="webster"),
    # S06 is the highest-exposure signalized site AND runs permissive lefts:
    # the natural target for the perm -> protected-only countermeasure.
    dict(site="S06", control="4SG", aadt_major=25000, aadt_minor=12500,
         lanes_major=3, lanes_minor=2, phasing="perm",     speed_mph=45, cycle_mode="webster"),
    # --- phasing triplet: identical in every BASE-SPF covariate ----------
    dict(site="S07", control="4SG", aadt_major=18000, aadt_minor=7000,
         lanes_major=2, lanes_minor=2, phasing="perm",     speed_mph=40, cycle_mode="webster"),
    dict(site="S08", control="4SG", aadt_major=18000, aadt_minor=7000,
         lanes_major=2, lanes_minor=2, phasing="protperm", speed_mph=40, cycle_mode="webster"),
    dict(site="S09", control="4SG", aadt_major=18000, aadt_minor=7000,
         lanes_major=2, lanes_minor=2, phasing="prot",     speed_mph=40, cycle_mode="webster"),
    # --- 4-leg two-way stop ----------------------------------------------
    dict(site="S10", control="4ST", aadt_major=2500,  aadt_minor=600,
         lanes_major=1, lanes_minor=1, phasing="none", speed_mph=30, cycle_mode="na"),
    dict(site="S11", control="4ST", aadt_major=5000,  aadt_minor=1200,
         lanes_major=1, lanes_minor=1, phasing="none", speed_mph=35, cycle_mode="na"),
    dict(site="S12", control="4ST", aadt_major=8000,  aadt_minor=2000,
         lanes_major=1, lanes_minor=1, phasing="none", speed_mph=40, cycle_mode="na"),
    dict(site="S13", control="4ST", aadt_major=11000, aadt_minor=2800,
         lanes_major=2, lanes_minor=1, phasing="none", speed_mph=40, cycle_mode="na"),
    dict(site="S14", control="4ST", aadt_major=14000, aadt_minor=3400,
         lanes_major=2, lanes_minor=1, phasing="none", speed_mph=45, cycle_mode="na"),
    # --- 3-leg stop -------------------------------------------------------
    dict(site="S15", control="3ST", aadt_major=4000,  aadt_minor=900,
         lanes_major=1, lanes_minor=1, phasing="none", speed_mph=35, cycle_mode="na"),
    dict(site="S16", control="3ST", aadt_major=8000,  aadt_minor=1800,
         lanes_major=1, lanes_minor=1, phasing="none", speed_mph=40, cycle_mode="na"),
    dict(site="S17", control="3ST", aadt_major=13000, aadt_minor=3000,
         lanes_major=2, lanes_minor=1, phasing="none", speed_mph=40, cycle_mode="na"),
    dict(site="S18", control="3ST", aadt_major=19000, aadt_minor=4200,
         lanes_major=2, lanes_minor=1, phasing="none", speed_mph=45, cycle_mode="na"),
    # --- MATCHED PAIR: identical in EVERY SPF covariate AND phasing -------
    #     differ only in signal cycle length (an operational factor no HSM
    #     SPF or standard CMF can see).
    dict(site="S19", control="4SG", aadt_major=15000, aadt_minor=6000,
         lanes_major=2, lanes_minor=1, phasing="protperm", speed_mph=40, cycle_mode="webster"),
    dict(site="S20", control="4SG", aadt_major=15000, aadt_minor=6000,
         lanes_major=2, lanes_minor=1, phasing="protperm", speed_mph=40, cycle_mode="long140"),
]

# Peak-hour conversion (stated assumptions, applied identically to every site)
K_FACTOR = 0.09    # peak-hour volume as a fraction of AADT (two-way)
D_FACTOR = 0.55    # directional split in the peak direction

# Turning-movement splits (left, through, right)
TURN_MAJOR = (0.10, 0.80, 0.10)
TURN_MINOR_4LEG = (0.30, 0.40, 0.30)
TURN_MINOR_3LEG = (0.50, 0.00, 0.50)   # 3-leg minor approach has no through


def by_id():
    return {s["site"]: s for s in SITES}


def approach_volumes(site):
    """Peak-hour approach volumes (veh/h) keyed by arm name.

    Returns {arm: {'L': v, 'T': v, 'R': v, 'total': v}}.
    Major road = N-S.  Minor road = E-W (4-leg) or E only (3-leg).
    N and E are the peak-direction (D_FACTOR) approaches.
    """
    ph_major = site["aadt_major"] * K_FACTOR
    ph_minor = site["aadt_minor"] * K_FACTOR
    three_leg = site["control"] == "3ST"

    vols = {}
    for arm, share in (("N", D_FACTOR), ("S", 1 - D_FACTOR)):
        v = ph_major * share
        l, t, r = TURN_MAJOR
        vols[arm] = dict(L=v * l, T=v * t, R=v * r, total=v)

    tm = TURN_MINOR_3LEG if three_leg else TURN_MINOR_4LEG
    minor_arms = (("E", 1.0),) if three_leg else (("E", D_FACTOR), ("W", 1 - D_FACTOR))
    for arm, share in minor_arms:
        v = ph_minor * share
        l, t, r = tm
        vols[arm] = dict(L=v * l, T=v * t, R=v * r, total=v)
    return vols


def arms(site):
    return ["N", "S", "E"] if site["control"] == "3ST" else ["N", "S", "E", "W"]


ARM_ANGLE = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
