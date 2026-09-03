"""
HSM Part C safety-performance functions, Part D crash-modification factors, and
the Empirical Bayes estimator.

EVERY NUMBER IN THIS FILE IS SOURCED.  Values marked ASSUMED are stated
assumptions of this experiment, not published quantities.

=====================================================================
SPF coefficients -- VERIFIED, quoted verbatim
=====================================================================
Source: NCHRP Web-Only Document 297, "Draft Text for the Second Edition of the
Highway Safety Manual", Chapter 10 -- Predictive Method for Rural Two-Lane,
Two-Way Roads (Appendix A, pp. A-22..A-28).
  https://onlinepubs.trb.org/onlinepubs/nchrp/nchrp_wod_297Draft.pdf

  Eq. 10-8   3ST: Nspf = exp[-9.86 + 0.79 ln(AADTmaj) + 0.49 ln(AADTmin)], k=0.54
  Eq. 10-9   4ST: Nspf = exp[-8.56 + 0.60 ln(AADTmaj) + 0.61 ln(AADTmin)], k=0.24
  Eq. 10-EB  3SG: Nspf = exp[-5.88 + 0.54 ln(AADTmaj) + 0.23 ln(AADTmin)], k=0.31
  Eq. 10-10  4SG: Nspf = exp[-5.13 + 0.60 ln(AADTmaj) + 0.20 ln(AADTmin)], k=0.11

Each SPF's document-stated applicability range is recorded and enforced here;
the site inventory was designed so that EVERY site lies inside its own range.
Units: intersection-related crashes per YEAR, all severities, all collision types.

=====================================================================
Collision-type proportions -- VERIFIED, quoted verbatim
=====================================================================
Same source, Table 10-6 ("Default Distribution for Collision Type and Manner of
Collision at Rural Two-Way Intersections"), "Total" column:
                    Angle    Rear-end
  3ST               23.7%     27.8%
  4ST               45.7%     29.2%
  3SG               19.3%     46.0%
  4SG               27.4%     42.6%

=====================================================================
Left-turn phasing CMFs -- VERIFIED, with an explicitly flagged mapping step
=====================================================================
Source: FHWA-HRT-18-044, "Safety Evaluation of Protected Left-Turn Phasing and
Leading Pedestrian Intervals" (October 2018).
  https://www.fhwa.dot.gov/publications/research/safety/18044/18044.pdf

  * Table 35 (all cities combined, treatment dominated by permissive-only ->
    protected/permissive):
        vehicle-vehicle, all severities   CMF = 1.023   SE = 0.016  (n.s.)
        vehicle-vehicle, injury           CMF = 0.942   SE = 0.028  (sig. @95%)
        vehicle-pedestrian                CMF = 1.091   SE = 0.066  (n.s.)
  * Literature review, p.7, citing Srinivasan et al.: permissive-only ->
    protected/permissive or protected-only, EB before-after, intersection level:
        left-turn-opposing crashes   CMF = 0.862
        total crashes                CMF = 1.031  (n.s.)
        injury crashes               CMF = 0.962  (n.s.)
        rear-end crashes             CMF = 1.075
  * Literature review, p.7, citing Hauer (2004): changing to protected-only from
    either permissive-only or protected/permissive:
        left-turn crashes            CMF ~ 0.30   ("70-percent reduction")
        other crashes                CMF ~ 1.0    (no effect)

MAPPING STEP (FLAGGED): the published left-turn CMFs are for "left-turn" or
"left-turn-opposing" crashes.  This experiment's type-matched crash category is
HSM Table 10-6's "Angle collision", which is BROADER than left-turn-opposing.
Applying an LT CMF to the whole angle category therefore OVERSTATES the
treatable share.  Stated, not corrected.

Standard errors are published only for the FHWA Table 35 CMFs.  For the Hauer
and Srinivasan values no SE is given in the source; they are carried without
one and that is flagged wherever they are used.
"""
import math

SPF = {
    #                a       b(lnmaj) c(lnmin)   k    maj_max  min_max   eq
    "3ST": dict(a=-9.86, b=0.79, c=0.49, k=0.54, maj_max=19500, min_max=4300,
                eq="HSM2 draft Eq. 10-8"),
    "4ST": dict(a=-8.56, b=0.60, c=0.61, k=0.24, maj_max=14700, min_max=3500,
                eq="HSM2 draft Eq. 10-9"),
    "3SG": dict(a=-5.88, b=0.54, c=0.23, k=0.31, maj_max=23591, min_max=23320,
                eq="HSM2 draft Eq. 10-EB"),
    "4SG": dict(a=-5.13, b=0.60, c=0.20, k=0.11, maj_max=25200, min_max=12500,
                eq="HSM2 draft Eq. 10-10"),
}

# HSM2 draft Table 10-6, "Total" column
COLLISION_TYPE_SHARE = {
    "3ST": dict(angle=0.237, rear_end=0.278),
    "4ST": dict(angle=0.457, rear_end=0.292),
    "3SG": dict(angle=0.193, rear_end=0.460),
    "4SG": dict(angle=0.274, rear_end=0.426),
}

# ---- CMFs applied to the ground-truth generator -------------------------
# Baseline (CMF = 1.0) is permissive-only phasing.
CMF_TOTAL = {
    "none": 1.000,        # unsignalized: no left-turn phasing
    "perm": 1.000,        # reference condition
    "protperm": 1.023,    # FHWA-HRT-18-044 Tbl 35, veh-veh all severities (SE 0.016)
    "prot": 1.000,        # Hauer (2004): CMF ~ 1.0 for non-left-turn crashes; no SE published
}
CMF_ANGLE = {
    "none": 1.000,
    "perm": 1.000,
    "protperm": 0.862,    # Srinivasan et al. via FHWA-HRT-18-044 p.7; no SE published
    "prot": 0.300,        # Hauer (2004) via FHWA-HRT-18-044 p.7; no SE published
}
CMF_REAR_END = {
    "none": 1.000,
    "perm": 1.000,
    "protperm": 1.075,    # Srinivasan et al. via FHWA-HRT-18-044 p.7; no SE published
    "prot": 1.075,        # ASSUMED equal to the protperm value (no published prot-only value found)
}

CMF_TOTAL_SE = {"protperm": 0.016}      # only this one has a published SE

# ASSUMED: local calibration factor.  HSM Part C requires a jurisdiction-specific
# C; 1.00 means "this synthetic agency's crash experience exactly matches the
# base SPF".  C is a common multiplier so it cannot change any method's RANK,
# but it DOES change EB weights (w = 1/(1 + k*N_spf*Y)).
CALIBRATION_C = 1.00


def spf_base(control, aadt_maj, aadt_min):
    p = SPF[control]
    return math.exp(p["a"] + p["b"] * math.log(aadt_maj) + p["c"] * math.log(aadt_min))


def in_range(control, aadt_maj, aadt_min):
    p = SPF[control]
    return aadt_maj <= p["maj_max"] and aadt_min <= p["min_max"]


def n_predicted(control, aadt_maj, aadt_min, phasing, C=CALIBRATION_C, cmf=None):
    """HSM Part C predicted average crash frequency, total crashes, per year."""
    cmf = CMF_TOTAL if cmf is None else cmf
    return C * spf_base(control, aadt_maj, aadt_min) * cmf.get(phasing, 1.0)


def n_predicted_angle(control, aadt_maj, aadt_min, phasing, C=CALIBRATION_C):
    """Type-matched (angle-collision) predicted frequency, per year."""
    return (C * spf_base(control, aadt_maj, aadt_min)
            * COLLISION_TYPE_SHARE[control]["angle"] * CMF_ANGLE.get(phasing, 1.0))


def overdispersion(control):
    return SPF[control]["k"]


def eb_estimate(n_spf, n_obs_annual, k, years):
    """HSM Part C site-specific Empirical Bayes estimator, in ANNUAL units.

    w         = 1 / (1 + k * N_spf * Y)
    N_expected = w * N_spf + (1 - w) * N_observed_annual
    (This is the HSM total-over-Y-years form divided through by Y.)
    """
    w = 1.0 / (1.0 + k * n_spf * years)
    return w * n_spf + (1.0 - w) * n_obs_annual, w


def eb_excess(n_spf, n_obs_annual, k, years):
    """EB expected EXCESS crash frequency over the SPF prediction."""
    eb, w = eb_estimate(n_spf, n_obs_annual, k, years)
    return eb - n_spf, w
