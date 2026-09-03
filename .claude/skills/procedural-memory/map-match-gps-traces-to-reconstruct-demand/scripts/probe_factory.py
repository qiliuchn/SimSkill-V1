"""Probe degradation factory: turn ground-truth FCD into realistic sparse GPS feeds.

Three degradation axes, with Common Random Numbers so that the underlying traffic
is byte-identical across every cell and only the degradation varies:

  * ping interval P in {1,5,15,30,60,120} s.  Sampling is NESTED: a vehicle gets a
    fixed integer phase, and is sampled at t == phase (mod P).  Because 1|5|15|30|60|120
    forms a divisibility chain, the P=120 feed is a strict SUBSET of the P=60 feed,
    which is a subset of P=30, ... So moving along the ping axis removes points but
    never substitutes different ones -- the cleanest possible CRN on that axis.
  * positional noise sigma in {0,5,10,20,50} m.  Unit normal draws are generated ONCE
    per (noise-seed, vehicle, record) and REUSED at every sigma and every ping, so the
    sigma axis is a pure scaling of one fixed noise realisation.  Same CRN logic.
  * fleet penetration: a vehicle subset.  Because tracemapper matches every trace
    independently, penetration is applied by subsetting -- see 06 for the empirical check.

Trace files use tracemapper's `readLines` format, one line per vehicle:
    <vehID>: x1,y1 x2,y2 x3,y3 ...
This sidesteps tracemapper's readFCD requirement that FCD be sorted by vehicle id
(SUMO's --fcd-output is sorted by TIME, which readFCD silently mis-parses).
"""
import numpy as np

PINGS = [1, 5, 15, 30, 60, 120]
SIGMAS = [0, 5, 10, 20, 50]


class ProbeFactory:
    def __init__(self, npz_path, vids=None):
        z = np.load(npz_path)
        self.keys = z
        self.vids = vids or sorted({k.split("|")[0] for k in z.files},
                                   key=lambda s: int(s[1:]))
        self.data = {v: (z[v + "|t"], z[v + "|x"], z[v + "|y"]) for v in self.vids}
        self._noise = {}
        self._phase = {}

    def _phases(self, seed):
        """Fixed integer per-vehicle sampling phase; identical at every ping/sigma."""
        if seed not in self._phase:
            rng = np.random.default_rng(900000 + seed)
            self._phase[seed] = {v: int(rng.integers(0, 120)) for v in self.vids}
        return self._phase[seed]

    def _normals(self, seed):
        """Unit normal draws, one pair per (vehicle, FCD record). Reused at all sigma/ping."""
        if seed not in self._noise:
            rng = np.random.default_rng(700000 + seed)
            self._noise[seed] = {v: rng.standard_normal((len(self.data[v][0]), 2))
                                 for v in self.vids}
        return self._noise[seed]

    def feed(self, ping, sigma, seed, dropout=0.0, vids=None):
        """-> dict vid -> Nx2 array of (possibly noisy) probe positions, time-ordered."""
        ph, nz = self._phases(seed), self._normals(seed)
        drng = np.random.default_rng(500000 + seed * 97 + ping)
        out = {}
        for v in (vids or self.vids):
            t, x, y = self.data[v]
            keep = (np.round(t).astype(np.int64) - ph[v]) % ping == 0
            if dropout > 0:
                keep &= drng.random(len(t)) >= dropout
            idx = np.flatnonzero(keep)
            if len(idx) == 0:
                out[v] = np.zeros((0, 2))
                continue
            p = np.column_stack([x[idx], y[idx]])
            if sigma > 0:
                p = p + sigma * nz[v][idx]
            out[v] = p
        return out

    @staticmethod
    def write_lines(feed, path, minpts=2):
        """tracemapper readLines format. Returns (n_written, n_too_few_points)."""
        nw = nf = 0
        with open(path, "w") as f:
            for v, p in feed.items():
                if len(p) < minpts:
                    nf += 1
                    continue
                f.write("%s: %s\n" % (v, " ".join("%.2f,%.2f" % (a, b) for a, b in p)))
                nw += 1
        return nw, nf
