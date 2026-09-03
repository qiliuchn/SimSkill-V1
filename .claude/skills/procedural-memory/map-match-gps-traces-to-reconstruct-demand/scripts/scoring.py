"""Three-level scoring of map-matched routes against SUMO's exact ground truth.

Denominator discipline: every metric is reported over the FULL probe fleet, with
  * vehicles whose feed had <2 pings          -> counted, F1 = 0
  * vehicles the matcher emitted no route for -> counted, F1 = 0
Nothing is silently dropped.  Conditional-on-matched versions are also returned so
the size of the survivorship bias is visible.
"""
import os, sys
import numpy as np
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib


# ---------------------------------------------------------------- sequence sims
def lcs_len(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            cur[j] = prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def edit_dist(a, b):
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


class Scorer:
    def __init__(self, netfile, edge2taz, truth):
        self.net = sumolib.net.readNet(netfile)
        self.e2t = edge2taz
        self.truth = truth
        self.elen = {e.getID(): e.getLength() for e in self.net.getEdges()
                     if e.getFunction() != "internal"}
        self._out = {e.getID(): {o.getID() for o in e.getOutgoing()}
                     for e in self.net.getEdges() if e.getFunction() != "internal"}

    def connected(self, edges):
        """True iff every consecutive pair is joined by a real connection."""
        return all(edges[i + 1] in self._out.get(edges[i], ()) for i in range(len(edges) - 1))

    def n_gaps(self, edges):
        """Count of consecutive pairs with NO connection. The binary `connected`
        flag is dominated by rare per-ping snapping errors -- one bad transition in
        a 30-edge route flips it -- so the gap COUNT is the informative version."""
        return sum(1 for i in range(len(edges) - 1)
                   if edges[i + 1] not in self._out.get(edges[i], ()))

    def legal(self, edges):
        for e in edges:
            if not self.net.hasEdge(e) or not self.net.getEdge(e).allows("passenger"):
                return False
        return True

    def length(self, edges):
        return sum(self.elen.get(e, 0.0) for e in edges)

    # ------------------------------------------------------------- per trip
    def score_trip(self, vid, matched, nofeed=False):
        T = self.truth[vid]["edges"]
        Tset, Ln = set(T), self.length(T)
        r = dict(vid=vid, n_true=len(T), true_len=Ln, nofeed=nofeed,
                 failed=(matched is None or len(matched) == 0))
        if r["failed"]:
            r.update(precision=0., recall=0., f1=0., lcs_norm=0., edit_norm=1.,
                     overlap_len_frac=0., n_match=0, match_len=0., len_ratio=np.nan,
                     o_edge_ok=False, d_edge_ok=False, o_taz_ok=False, d_taz_ok=False,
                     connected=False, legal=False, exact=False, plausible_wrong=False,
                     n_gaps=0, gap_frac=1.0)
            return r
        M = matched
        Mset = set(M)
        inter = Tset & Mset
        prec = len(inter) / len(Mset)
        rec = len(inter) / len(Tset)
        f1 = 0. if prec + rec == 0 else 2 * prec * rec / (prec + rec)
        l = lcs_len(T, M)
        Lm = self.length(M)
        ng = self.n_gaps(M)
        conn, leg = (ng == 0), self.legal(M)
        exact = (T == M)
        r.update(precision=prec, recall=rec, f1=f1,
                 lcs_norm=l / max(len(T), len(M)),
                 edit_norm=edit_dist(T, M) / max(len(T), len(M)),
                 overlap_len_frac=(self.length(list(inter)) / Ln if Ln > 0 else 0.),
                 n_match=len(M), match_len=Lm,
                 len_ratio=(Lm / Ln if Ln > 0 else np.nan),
                 o_edge_ok=(M[0] == T[0]), d_edge_ok=(M[-1] == T[-1]),
                 o_taz_ok=(self.e2t.get(M[0]) == self.e2t.get(T[0])),
                 d_taz_ok=(self.e2t.get(M[-1]) == self.e2t.get(T[-1])),
                 connected=conn, legal=leg, exact=exact,
                 n_gaps=ng, gap_frac=(ng / max(1, len(M) - 1)),
                 # THE dangerous failure mode: fully connected, legal, silently wrong
                 plausible_wrong=(conn and leg and not exact))
        return r

    def score_feed(self, fleet, matched_map, nofeed_set):
        rows = [self.score_trip(v, matched_map.get(v), nofeed=(v in nofeed_set))
                for v in fleet]
        return rows


def aggregate(rows):
    n = len(rows)
    ok = [r for r in rows if not r["failed"]]
    g = lambda k, rs: float(np.mean([r[k] for r in rs])) if rs else float("nan")
    tl = sum(r["true_len"] for r in rows)
    ml = sum(r["match_len"] for r in rows)
    a = dict(
        n_fleet=n,
        n_nofeed=sum(1 for r in rows if r["nofeed"]),
        n_failed=sum(1 for r in rows if r["failed"]),
        fail_pct=100. * sum(1 for r in rows if r["failed"]) / n,
        # ---- unconditional (failures scored 0) : the headline numbers
        f1=g("f1", rows), precision=g("precision", rows), recall=g("recall", rows),
        lcs_norm=g("lcs_norm", rows), edit_norm=g("edit_norm", rows),
        overlap_len_frac=g("overlap_len_frac", rows),
        o_edge_pct=100. * g("o_edge_ok", rows), d_edge_pct=100. * g("d_edge_ok", rows),
        o_taz_pct=100. * g("o_taz_ok", rows), d_taz_pct=100. * g("d_taz_ok", rows),
        exact_pct=100. * g("exact", rows),
        # ---- conditional on a route being produced : shows survivorship bias size
        f1_matched=g("f1", ok),
        disconnected_pct=100. * (1 - g("connected", ok)) if ok else float("nan"),
        illegal_pct=100. * (1 - g("legal", ok)) if ok else float("nan"),
        plausible_wrong_pct=100. * g("plausible_wrong", ok) if ok else float("nan"),
        gaps_per_route=g("n_gaps", ok), gap_frac=g("gap_frac", ok),
        # ---- route length bias
        len_ratio_mean=float(np.mean([r["len_ratio"] for r in ok])) if ok else float("nan"),
        len_ratio_median=float(np.median([r["len_ratio"] for r in ok])) if ok else float("nan"),
        total_len_bias_pct=100. * (ml - tl) / tl if tl else float("nan"),
    )
    # plausible-but-wrong over the WHOLE fleet, the practitioner-relevant denominator
    a["plausible_wrong_fleet_pct"] = 100. * sum(1 for r in rows if r["plausible_wrong"]) / n
    return a
