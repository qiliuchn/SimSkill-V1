#!/usr/bin/env python3
"""Genetic-algorithm optimizer for a coordinated fixed-time arterial signal plan.
Genome = [C, g1,g2,g3, o1,o2,o3]. Fitness = SUMO run total timeLoss (+penalty).
Population-based global joint search over cycle/splits/offsets."""
import os, csv, random, json
import ga_common as g

HERE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = os.environ.get("GA_SUFFIX", "")   # "" for primary run, "_wide" for matched-range
SEED = 7
POP = 20
GENS = 15
TOURN = 3
ELITE = 2
PMUT = 0.25          # per-gene mutation probability
CX_PROB = 0.9

# gene bounds: C, g1..g3 (main split frac), o1..o3 (offset abs seconds)
LO = [g.C_MIN, g.SPLIT_MIN, g.SPLIT_MIN, g.SPLIT_MIN, 0.0, 0.0, 0.0]
HI = [g.C_MAX, g.SPLIT_MAX, g.SPLIT_MAX, g.SPLIT_MAX, 120.0, 120.0, 120.0]
SIG = [(hi - lo) * 0.15 for lo, hi in zip(LO, HI)]  # gaussian mutation scale

rng = random.Random(SEED)


def to_genome(x):
    return {"C": x[0], "splits": [x[1], x[2], x[3]], "offsets": [x[4], x[5], x[6]]}


def clamp(x):
    return [min(max(v, lo), hi) for v, lo, hi in zip(x, LO, HI)]


def rand_indiv():
    return [rng.uniform(lo, hi) for lo, hi in zip(LO, HI)]


def tournament(pop, fits):
    best = None
    for _ in range(TOURN):
        i = rng.randrange(len(pop))
        if best is None or fits[i] < fits[best]:
            best = i
    return pop[best][:]


def crossover(a, b):
    if rng.random() > CX_PROB:
        return a[:], b[:]
    c1, c2 = a[:], b[:]
    for i in range(len(a)):
        if rng.random() < 0.5:
            # arithmetic blend
            w = rng.random()
            c1[i] = w * a[i] + (1 - w) * b[i]
            c2[i] = w * b[i] + (1 - w) * a[i]
    return clamp(c1), clamp(c2)


def mutate(x):
    y = x[:]
    for i in range(len(x)):
        if rng.random() < PMUT:
            y[i] += rng.gauss(0, SIG[i])
    return clamp(y)


def main():
    pop = [rand_indiv() for _ in range(POP)]
    fits, metrics = [], []
    for ind in pop:
        obj, m = g.fitness(to_genome(ind), HERE)
        fits.append(obj); metrics.append(m)

    csv_path = os.path.join(HERE, f"ga_log{SUFFIX}.csv")
    fcsv = open(csv_path, "w", newline="")
    w = csv.writer(fcsv)
    w.writerow(["generation", "best_obj", "mean_obj", "best_so_far",
                "best_C", "best_g1", "best_g2", "best_g3", "best_o1", "best_o2", "best_o3"])

    best_so_far = float("inf"); best_ind = None; best_metric = None
    for gen in range(GENS):
        order = sorted(range(len(pop)), key=lambda i: fits[i])
        gbest_i = order[0]
        if fits[gbest_i] < best_so_far:
            best_so_far = fits[gbest_i]; best_ind = pop[gbest_i][:]; best_metric = metrics[gbest_i]
        mean_obj = sum(fits) / len(fits)
        bi = best_ind
        w.writerow([gen, round(fits[gbest_i], 2), round(mean_obj, 2), round(best_so_far, 2),
                    round(bi[0], 1), round(bi[1], 3), round(bi[2], 3), round(bi[3], 3),
                    round(bi[4], 1), round(bi[5], 1), round(bi[6], 1)])
        fcsv.flush()
        print(f"gen {gen:2d}  best={fits[gbest_i]:9.1f}  mean={mean_obj:9.1f}  best_so_far={best_so_far:9.1f}")

        # build next generation
        newpop = [pop[i][:] for i in order[:ELITE]]  # elitism
        while len(newpop) < POP:
            p1 = tournament(pop, fits); p2 = tournament(pop, fits)
            c1, c2 = crossover(p1, p2)
            newpop.append(mutate(c1))
            if len(newpop) < POP:
                newpop.append(mutate(c2))
        pop = newpop
        fits, metrics = [], []
        for ind in pop:
            obj, m = g.fitness(to_genome(ind), HERE)
            fits.append(obj); metrics.append(m)

    # final check on last generation
    order = sorted(range(len(pop)), key=lambda i: fits[i])
    if fits[order[0]] < best_so_far:
        best_so_far = fits[order[0]]; best_ind = pop[order[0]][:]; best_metric = metrics[order[0]]
    # log the final (GENS) row
    mean_obj = sum(fits) / len(fits)
    bi = best_ind
    w.writerow([GENS, round(fits[order[0]], 2), round(mean_obj, 2), round(best_so_far, 2),
                round(bi[0], 1), round(bi[1], 3), round(bi[2], 3), round(bi[3], 3),
                round(bi[4], 1), round(bi[5], 1), round(bi[6], 1)])
    fcsv.close()

    # decode final best to a clean tlLogic file + record clamped genome
    best_genome = to_genome(best_ind)
    C, plans = g.write_tls_add(best_genome, os.path.join(HERE, f"best_ga_tls{SUFFIX}.add.xml"))
    Ceff, plans2, csplits, coffsets = g.decode(best_genome)
    result = {
        "best_objective": best_so_far,
        "raw_genome": best_genome,
        "decoded": {
            "cycle": round(C, 1),
            "eff_cycles": [p[3] for p in plans2],
            "main_green_fractions": [round(x, 3) for x in csplits],
            "offsets": coffsets,
            "green_main_seconds": [p[2][0][1] for p in plans2],
            "green_side_seconds": [p[2][2][1] for p in plans2],
        },
        "best_metric": best_metric,
    }
    with open(os.path.join(HERE, f"ga_best{SUFFIX}.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("\nFINAL BEST:", json.dumps(result["decoded"], indent=2))
    print("best objective:", best_so_far)


if __name__ == "__main__":
    main()
