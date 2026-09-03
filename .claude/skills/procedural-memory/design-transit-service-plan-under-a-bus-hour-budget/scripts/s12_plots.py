"""Plots + summary tables for the transit service-planning study."""
import os, sys, json, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import tspcore as T
from tspcore import WORK, OUT, ensure
import plans as P
import harness as H

ensure(OUT)
C = dict(access="#4C78A8", wait="#F58518", ivt="#54A24B", xwalk="#B279A2",
         xwait="#E45756", pen="#9D755D")


def J(n):
    p = os.path.join(WORK, n)
    return json.load(open(p)) if os.path.exists(p) else None


def p1_decomposition():
    s4 = J("stage4_compare.json")
    if not s4: return
    names = sorted(s4["summary"], key=lambda n: s4["summary"][n]["gc_total_mean"])
    parts = [("access", T.W_ACCESS, "access+egress walk (x2.0)"),
             ("wait", T.W_WAIT, "initial wait (x2.0)"),
             ("ivt", T.W_IVT, "in-vehicle (x1.0)"),
             ("xwalk", T.W_XWALK, "transfer walk (x2.0)"),
             ("xwait", T.W_XWAIT, "transfer wait (x2.0)")]
    fig, ax = plt.subplots(figsize=(8, 5))
    bottom = [0.0] * len(names)
    for key, w, lab in parts:
        v = [s4["summary"][n][f"mean_{key}"] * w / 60.0 for n in names]
        ax.bar(names, v, bottom=bottom, label=lab, color=C[key])
        bottom = [a + b for a, b in zip(bottom, v)]
    pen = [s4["summary"][n]["transfers_per_rider"] * T.P_TRANSFER / 60.0 for n in names]
    ax.bar(names, pen, bottom=bottom, label=f"transfer penalty ({T.P_TRANSFER:.0f}s each)",
           color=C["pen"])
    for i, n in enumerate(names):
        ax.text(i, bottom[i] + pen[i] + 0.4,
                f"{bottom[i]+pen[i]:.1f} min\n{s4['summary'][n]['ridership']:.0f} riders",
                ha="center", fontsize=9)
    ax.set_ylabel("generalized time per transit rider (min)")
    ax.set_title(f"Generalized-cost decomposition at equal budget "
                 f"({s4['budget']} bus-hours, {len(s4['seeds'])} CRN seeds)")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p1_gc_decomposition.png"), dpi=140)
    plt.close(fig)


def p2_frontier():
    h1 = J("h1_frontier.json")
    if not h1: return
    r = h1["rows"]
    B = [x["budget"] for x in r]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    axes[0].errorbar(B, [x["gc_per_completed"]/60 for x in r],
                     yerr=[x["gc_sd"]/x["gc_total"]*x["gc_per_completed"]/60 for x in r],
                     marker="o", color="#4C78A8")
    axes[0].set_xlabel("budget (bus-hours)")
    axes[0].set_ylabel("generalized time per completed traveller (min)")
    axes[0].set_title("H1: is per-passenger cost convex in budget?")
    axes[0].grid(alpha=.3)
    ben = [x["benefit_pax_h"] for x in r]
    axes[1].plot(B, ben, marker="o", color="#54A24B", label="measured benefit")
    if len(B) > 1:
        sl = (ben[-1]-ben[0])/(B[-1]-B[0])
        axes[1].plot(B, [ben[0]+sl*(b-B[0]) for b in B], "--", color="grey",
                     label="linear (constant returns)")
    axes[1].set_xlabel("budget (bus-hours)")
    axes[1].set_ylabel("benefit vs smallest budget (pax-h saved)")
    axes[1].set_title("H1: budget-benefit frontier concavity")
    axes[1].legend(fontsize=8); axes[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p2_budget_benefit_frontier.png"), dpi=140)
    plt.close(fig)


def p3_ridership_coverage():
    s4 = J("stage4_compare.json"); post = J("h5_h6_post.json"); h1 = J("h1_frontier.json")
    if not (s4 and post): return
    fig, ax = plt.subplots(figsize=(7, 5))
    for n, d in s4["summary"].items():
        c = post["coverage"][n]["share"]
        ax.scatter(c*100, d["ridership"], s=110)
        ax.annotate(f"{n}\n{d['gc_per_person_mean']:.0f}s/pax",
                    (c*100, d["ridership"]), textcoords="offset points",
                    xytext=(8, -4), fontsize=9)
    if h1 and "coverage_by_budget" in (post or {}):
        pass
    ax.set_xlabel(f"coverage: share of population within {post['cover_radius']:.0f} m of a stop "
                  f"served >= {post['cover_min_freq_per_h']:.0f} bus/h (%)")
    ax.set_ylabel("ridership (transit trips completed)")
    ax.set_title("H6: ridership-coverage frontier at equal bus-hours")
    ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p3_ridership_coverage.png"), dpi=140)
    plt.close(fig)


def p4_wait():
    post = J("h5_h6_post.json")
    if not post: return
    rows = [r for r in post["h5"] if r["realized_mean_wait"]]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    x = [r["half_headway"]/60 for r in rows]
    y = [r["realized_mean_wait"]/60 for r in rows]
    y2 = [r["corrected"]/60 for r in rows]
    cv = [r["headway_cv"] for r in rows]
    sc = ax.scatter(x, y, c=cv, cmap="viridis", s=80, label="realized wait")
    ax.scatter(x, y2, marker="x", color="crimson", s=50,
               label=r"predicted $(h/2)(1+CV^2)$")
    lim = [0, max(max(x), max(y))*1.1]
    ax.plot(lim, lim, "--", color="grey", label="h/2 (the classical assumption)")
    plt.colorbar(sc, ax=ax, label="realized headway CV")
    ax.set_xlabel("nominal half-headway h/2 (min)")
    ax.set_ylabel("mean wait (min)")
    ax.set_title("H5: realized wait vs the half-headway assumption")
    ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p4_wait_vs_half_headway.png"), dpi=140)
    plt.close(fig)


def p5_allocation():
    s5 = J("stage5_optimize.json")
    if not s5: return
    arms = ["equal", "proportional", "sqrt_rule", "optimizer"]
    arms = [a for a in arms if a in s5["allocations"]]
    ids = list(next(iter(s5["allocations"].values())).keys())
    fig, ax = plt.subplots(figsize=(9, 4.6))
    w = 0.8/len(arms)
    for i, a in enumerate(arms):
        v = [s5["allocations"][a][l] for l in ids]
        ax.bar([j + i*w for j in range(len(ids))], v, width=w, label=a)
    ax.set_xticks([j + 0.4 - w/2 for j in range(len(ids))]); ax.set_xticklabels(ids)
    ax.set_ylabel("buses allocated (= bus-hours)")
    ax.set_title(f"Line-level frequency allocation, {s5['structure']}, "
                 f"B = {s5['budget']} bus-hours")
    ax.legend(fontsize=8); ax.grid(alpha=.3, axis="y")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p5_allocation.png"), dpi=140)
    plt.close(fig)


def p6_transfer_crossover():
    s4 = J("stage4_compare.json")
    if not s4: return
    fig, ax = plt.subplots(figsize=(7.5, 5))
    pens = sorted((int(p) for p in next(iter(s4["summary"].values()))["gc_by_penalty"]))
    for n, d in s4["summary"].items():
        ax.plot([p/60 for p in pens],
                [d["gc_by_penalty"][str(p)] / 3600 if str(p) in d["gc_by_penalty"]
                 else d["gc_by_penalty"][p] / 3600 for p in pens],
                marker="o", label=n)
    ax.set_xlabel("assumed transfer penalty (min per transfer)")
    ax.set_ylabel("total passenger generalized time (pax-h)")
    ax.set_title("H2: is there a transfer-penalty crossover between structures?")
    ax.legend(fontsize=9); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p6_transfer_crossover.png"), dpi=140)
    plt.close(fig)


def p7_optimizer():
    s5 = J("stage5_optimize.json")
    csv = os.path.join(WORK, "optimizer_evals.csv")
    if not (s5 and os.path.exists(csv)): return
    xs, ys, bs = [], [], []
    for i, ln in enumerate(open(csv).read().splitlines()[1:]):
        f = ln.split(",")
        xs.append(int(f[0])); ys.append(float(f[3])/3600); bs.append(float(f[4])/3600)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.scatter(xs, ys, s=10, alpha=.45, label="evaluated design (search seed)")
    ax.plot(xs, bs, color="crimson", label="best so far (in-sample)")
    for a, st_ in s5["heldout_stats"].items():
        ax.axhline(st_["mean"]/3600, ls="--", lw=1,
                   label=f"{a}: held-out {st_['mean']/3600:.1f}")
    ax.set_xlabel("simulation evaluations consumed")
    ax.set_ylabel("total passenger generalized time (pax-h)")
    ax.set_title(f"Simulation-in-the-loop allocation search "
                 f"({s5['evals_used']}/{s5['eval_budget']} evaluations)")
    ax.legend(fontsize=7); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "p7_optimizer.png"), dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    for f in (p1_decomposition, p2_frontier, p3_ridership_coverage, p4_wait,
              p5_allocation, p6_transfer_crossover, p7_optimizer):
        try:
            f(); print("ok", f.__name__)
        except Exception as e:
            import traceback; traceback.print_exc()
    print("plots ->", OUT)
