#!/usr/bin/env python3
"""
Metric extraction + CRN paired statistics for the AIM study.

Accounting conventions (from `validate-congested-scenario-results-against-teleport-artifacts`
and `compare-unsignalized-intersection-control-types`):
  * summary's `teleports` is CUMULATIVE -> read the last step, never sum.
  * tripinfo has no teleport field -> teleport counts come from the SUMO log.
  * `inserted - arrived` undercounts failed demand -> also report
    never_inserted = loaded - inserted and unserved = loaded - arrived.
  * delay is reported as timeLoss + departDelay so that demand which could not
    even be inserted onto the 300 m approach is not silently dropped from the
    average.
"""
import json
import math
import os
import statistics as st
import xml.etree.ElementTree as ET


# --------------------------------------------------------------------- parsing
def run_metrics(d, meta=None):
    m = {"dir": d}
    tp = os.path.join(d, "tripinfo.xml")
    if not os.path.exists(tp):
        return None
    try:
        ts = ET.parse(tp).getroot().findall("tripinfo")
    except ET.ParseError:
        return None
    if not ts:
        return None

    dur, tl, wt, dd, delay = [], [], [], [], []
    by_arm, by_cls, by_mv = {}, {}, {}
    for t in ts:
        vid = t.get("id")
        d_ = float(t.get("duration")); l_ = float(t.get("timeLoss"))
        w_ = float(t.get("waitingTime")); p_ = float(t.get("departDelay"))
        dur.append(d_); tl.append(l_); wt.append(w_); dd.append(p_)
        delay.append(l_ + p_)
        cls = t.get("vType") or "hdv"
        by_cls.setdefault(cls, []).append(l_ + p_)
        if meta and vid in meta:
            by_arm.setdefault(meta[vid]["arm"], []).append(l_ + p_)
            by_mv.setdefault(meta[vid]["mv"], []).append(l_ + p_)

    m["arrived"] = len(ts)
    m["mean_duration"] = st.mean(dur)
    m["mean_timeloss"] = st.mean(tl)
    m["mean_waiting"] = st.mean(wt)
    m["mean_departdelay"] = st.mean(dd)
    m["mean_delay"] = st.mean(delay)
    m["p95_delay"] = sorted(delay)[int(0.95 * (len(delay) - 1))]
    m["by_arm"] = {k: st.mean(v) for k, v in by_arm.items()}
    m["by_arm_n"] = {k: len(v) for k, v in by_arm.items()}
    m["by_class"] = {k: st.mean(v) for k, v in by_cls.items()}
    m["by_class_n"] = {k: len(v) for k, v in by_cls.items()}
    m["by_mv"] = {k: st.mean(v) for k, v in by_mv.items()}
    m["gini_delay"] = gini(delay)
    if m["by_arm"]:
        vals = list(m["by_arm"].values())
        m["arm_delay_ratio"] = max(vals) / max(min(vals), 1e-6)
        m["arm_delay_max"] = max(vals)

    sp = os.path.join(d, "summary.xml")
    if os.path.exists(sp):
        try:
            steps = ET.parse(sp).getroot().findall("step")
            last = steps[-1]
            m["loaded"] = int(last.get("loaded"))
            m["inserted"] = int(last.get("inserted"))
            m["ended"] = int(last.get("ended"))
            m["still_running"] = int(last.get("running"))
            m["teleports_summary"] = max(int(s.get("teleports")) for s in steps)
            m["collisions_summary"] = max(int(s.get("collisions")) for s in steps)
            m["never_inserted"] = m["loaded"] - m["inserted"]
            m["unserved"] = m["loaded"] - m["arrived"]
        except Exception:
            pass

    stj = os.path.join(d, "stats.json")
    if os.path.exists(stj):
        s = json.load(open(stj))
        m["collisions"] = s.get("collisions", {}).get("n", None)
        m["collisions_junction"] = s.get("collisions", {}).get("junction", None)
        m["teleports_log"] = s.get("teleports", {}).get("total", None)
        m["teleports_jam"] = s.get("teleports", {}).get("jam", None)
        m["ctrl"] = {k: v for k, v in s.items()
                     if k not in ("collisions", "teleports", "stderr")}
    return m


def gini(x):
    x = sorted(max(v, 0.0) for v in x)
    n = len(x)
    s = sum(x)
    if n == 0 or s <= 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(x))
    return (2.0 * cum) / (n * s) - (n + 1.0) / n


# ------------------------------------------------------------------ statistics
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 14: 2.145,
        15: 2.131, 19: 2.093, 20: 2.086, 24: 2.064, 29: 2.045, 39: 2.023}


def tcrit(df):
    if df in T975:
        return T975[df]
    ks = sorted(T975)
    for k in ks:
        if df <= k:
            return T975[k]
    return 1.96


def mean_ci(xs):
    n = len(xs)
    mu = st.mean(xs)
    if n < 2:
        return mu, 0.0, (mu, mu)
    sd = st.stdev(xs)
    h = tcrit(n - 1) * sd / math.sqrt(n)
    return mu, h, (mu - h, mu + h)


def paired(a, b):
    """CRN paired comparison of b vs a (same seed list). Returns dict."""
    d = [y - x for x, y in zip(a, b)]
    n = len(d)
    mu = st.mean(d)
    sd = st.stdev(d) if n > 1 else 0.0
    h = tcrit(n - 1) * sd / math.sqrt(n) if n > 1 and sd > 0 else 0.0
    t = mu / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    base = st.mean(a)
    return {"n": n, "mean_diff": mu, "ci": (mu - h, mu + h), "halfwidth": h,
            "t": t, "sig": (mu - h) * (mu + h) > 0 if h > 0 else False,
            "pct": 100.0 * mu / base if base else float("nan"),
            "base_mean": base, "treat_mean": st.mean(b),
            "sign_agree": sum(1 for x in d if (x > 0) == (mu > 0)) / float(n)}
