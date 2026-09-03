"""Run tracemapper.py, chunked across cores. Exact, not approximate: tracemapper
matches every trace independently (see its `for tid, trace in traces:` loop), so
splitting the trace file by vehicle and merging the outputs is bit-identical to a
single run. Verified empirically in 05.
"""
import os, sys, subprocess, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor

TM = os.path.join(os.environ["SUMO_HOME"], "tools", "route", "tracemapper.py")
NCPU = 10


def _one(args):
    tracepath, netfile, outpath, opts = args
    cmd = [sys.executable, TM, "-n", netfile, "-t", tracepath, "-o", outpath] + opts
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def read_routes(path):
    """tracemapper writes bare <route id=.. edges=../> under a <routes> root."""
    out = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s.startswith("<route "):
                i = s.index('id="') + 4
                vid = s[i:s.index('"', i)]
                j = s.index('edges="') + 7
                out[vid] = s[j:s.index('"', j)].split()
    return out


def run_matcher(trace_lines, netfile, opts, workdir=None, ncpu=NCPU, tag="tm"):
    """trace_lines: list of 'vid: x,y x,y ...' strings. Returns (routes, n_traces, stderr)."""
    wd = workdir or tempfile.mkdtemp(prefix=tag + "_")
    os.makedirs(wd, exist_ok=True)
    n = len(trace_lines)
    if n == 0:
        return {}, 0, ""
    k = min(ncpu, max(1, n))
    chunks = [trace_lines[i::k] for i in range(k)]
    jobs = []
    for i, ch in enumerate(chunks):
        if not ch:
            continue
        tp = os.path.join(wd, "c%d.trace" % i)
        op = os.path.join(wd, "c%d.rou.xml" % i)
        with open(tp, "w") as f:
            f.write("\n".join(ch) + "\n")
        jobs.append((tp, netfile, op, opts))
    routes, errs = {}, []
    # threads, not processes: all real work happens inside subprocess.run,
    # so there is no GIL contention, and this avoids py3.13's spawn-start
    # requirement for an `if __name__ == '__main__'` guard in every driver.
    with ThreadPoolExecutor(max_workers=k) as ex:
        for (rc, so, se), j in zip(ex.map(_one, jobs), jobs):
            if rc != 0:
                errs.append("rc=%d %s" % (rc, se[-500:]))
            else:
                routes.update(read_routes(j[2]))
            if se.strip():
                errs.append(se.strip()[-300:])
    if workdir is None:
        shutil.rmtree(wd, ignore_errors=True)
    return routes, n, "\n".join(errs)


def opts_for(delta=20., adf=2., direction=False, fill_gaps=0., gap_penalty=-1.,
             geo=False, vclass=None):
    o = ["-d", str(delta), "-a", str(adf), "--fill-gaps", str(fill_gaps),
         "-g", str(gap_penalty)]
    if direction:
        o.append("--direction")
    if geo:
        o.append("--geo")
    if vclass:
        o += ["--vehicle-class", vclass]
    return o
