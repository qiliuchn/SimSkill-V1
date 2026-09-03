"""Zone-to-zone impedance (skim) construction.

Edge-expanded Dijkstra: nodes = network edges, arc e->f (f a successor of e) costs
cost(f); the source's own cost is included, so the path cost from edge s to edge t is
the full traversal time of s..t inclusive.  Running one Dijkstra per connector edge
gives the whole edge-to-edge cost matrix; zone-to-zone costs are then the
source-weight x sink-weight weighted mean over the zones' connector edges.

Two cost bases:
  free-flow   cost(e) = length(e) / speed(e)          (no signal delay)
  congested   cost(e) = measured edgeData traveltime  (falls back to free-flow where
                        no vehicle was observed)

Intrazonal impedance c_ii is computed the same way over within-zone connector pairs,
excluding s == t (which would be a zero-cost degenerate trip).
"""
import heapq
import xml.etree.ElementTree as ET

import numpy as np


class EdgeGraph:
    def __init__(self, net, connectors_by_zone, source_w, sink_w):
        self.net = net
        self.edges = [e.getID() for e in net.getEdges()]
        self.idx = {eid: i for i, eid in enumerate(self.edges)}
        self.succ = []
        for e in net.getEdges():
            self.succ.append([self.idx[o.getID()] for o in e.getOutgoing()])
        self.ff = np.array([e.getLength() / e.getSpeed() for e in net.getEdges()])
        self.length = np.array([e.getLength() for e in net.getEdges()])
        self.connectors_by_zone = connectors_by_zone
        self.source_w = source_w
        self.sink_w = sink_w
        self.zones = list(connectors_by_zone.keys())

    def dijkstra(self, src_i, cost, aux=None):
        """Shortest path by `cost`; if `aux` is given, also accumulate that per-edge
        quantity ALONG THE COST-SHORTEST PATH (e.g. distance under a time skim)."""
        n = len(self.edges)
        dist = np.full(n, np.inf)
        acc = np.full(n, np.inf) if aux is not None else None
        dist[src_i] = cost[src_i]
        if aux is not None:
            acc[src_i] = aux[src_i]
        pq = [(dist[src_i], src_i)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v in self.succ[u]:
                nd = d + cost[v]
                if nd < dist[v] - 1e-12:
                    dist[v] = nd
                    if aux is not None:
                        acc[v] = acc[u] + aux[v]
                    heapq.heappush(pq, (nd, v))
        return dist, acc

    def edge_matrix(self, cost, aux=None):
        """Cost matrix over all connector edges (and optionally the aux matrix)."""
        srcs = sorted({e for z in self.zones for e in self.connectors_by_zone[z]})
        si = {e: k for k, e in enumerate(srcs)}
        n = len(self.edges)
        M = np.full((len(srcs), n), np.inf)
        Maux = np.full((len(srcs), n), np.inf) if aux is not None else None
        for e in srcs:
            d, a = self.dijkstra(self.idx[e], cost, aux)
            M[si[e]] = d
            if aux is not None:
                Maux[si[e]] = a
        return srcs, si, M, Maux

    def zone_skim(self, cost, aux=None):
        """-> (NZ x NZ) zone-to-zone weighted-mean cost matrix (and aux matrix)."""
        srcs, si, M, Maux = self.edge_matrix(cost, aux)
        Z = len(self.zones)
        S = np.zeros((Z, Z))
        Sa = np.zeros((Z, Z)) if aux is not None else None
        for i, zi in enumerate(self.zones):
            se = self.connectors_by_zone[zi]
            sw = np.array([self.source_w[zi][e] for e in se])
            rows = M[[si[e] for e in se]]
            rowsa = Maux[[si[e] for e in se]] if aux is not None else None
            for j, zj in enumerate(self.zones):
                te = self.connectors_by_zone[zj]
                tw = np.array([self.sink_w[zj][e] for e in te])
                cols = [self.idx[e] for e in te]
                sub = rows[:, cols]
                W = np.outer(sw, tw).copy()
                if i == j:  # exclude degenerate s == t intrazonal pairs
                    for a, ea in enumerate(se):
                        for b, eb in enumerate(te):
                            if ea == eb:
                                W[a, b] = 0.0
                ok = np.isfinite(sub)
                W = W * ok
                assert W.sum() > 0, "no reachable connector pair for %s->%s" % (zi, zj)
                S[i, j] = float((sub[ok] * W[ok]).sum() / W.sum())
                if aux is not None:
                    Sa[i, j] = float((rowsa[:, cols][ok] * W[ok]).sum() / W.sum())
        return S, Sa


def read_edgedata_traveltime(path, net, ff_cost, idx):
    """Congested per-edge travel time from an edgeData dump; free-flow fallback."""
    cost = ff_cost.copy()
    nobs = 0
    tree = ET.parse(path)
    for interval in tree.getroot().findall("interval"):
        for e in interval.findall("edge"):
            eid = e.get("id")
            tt = e.get("traveltime")
            if eid in idx and tt is not None:
                cost[idx[eid]] = float(tt)
                nobs += 1
    return cost, nobs
