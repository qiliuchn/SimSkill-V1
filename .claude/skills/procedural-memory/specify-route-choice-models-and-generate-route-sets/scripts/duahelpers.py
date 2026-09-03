#!/usr/bin/env python3
"""Helpers to drive duarouter against explicit hand-written .rou.alt.xml inputs and read
back the recomputed <route probability=...> values -- the core measurement primitive for
sub-goal 1 (reverse-engineering the route-choice formulas) and sub-goal 2 (overlap testbed).
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from altparse import parse_alt_file_flows  # noqa: E402


def find_duarouter():
    p = shutil.which("duarouter")
    if p:
        return p
    cand = os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "duarouter")
    if os.path.exists(cand):
        return cand
    raise SystemExit("duarouter not found")


DUAROUTER = None


def duarouter():
    global DUAROUTER
    if DUAROUTER is None:
        DUAROUTER = find_duarouter()
    return DUAROUTER


def write_hand_alt(path, veh_id, route_specs, depart="0.00"):
    """route_specs: list of (edges_str, cost, probability)."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
             f'    <vehicle id="{veh_id}" depart="{depart}">',
             f'        <routeDistribution last="0">']
    for edges, cost, prob in route_specs:
        lines.append(f'            <route cost="{cost:.6f}" probability="{prob:.8f}" '
                     f'edges="{edges}"/>')
    lines.append('        </routeDistribution>')
    lines.append('    </vehicle>')
    lines.append('</routes>')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def run_duarouter(net, alt_in, out_prefix, method=None, extra_args=None, seed=None):
    """Feed alt_in (a .rou.alt.xml) back into duarouter against `net`, using route-choice
    method `method` (gawron/logit/lohse/None). Returns parsed {vehid: [(edges,cost,prob)]}
    from the freshly written .rou.alt.xml.
    """
    out_rou = out_prefix + ".rou.xml"
    cmd = [duarouter(), "-n", net, "-r", alt_in, "-o", out_rou,
           "--keep-all-routes", "--write-costs", "--no-step-log", "--ignore-errors"]
    if method:
        cmd += ["--route-choice-method", method]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if extra_args:
        cmd += extra_args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD:", " ".join(cmd), file=sys.stderr)
        print(r.stdout, file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        raise SystemExit("duarouter failed")
    alt_out = out_prefix + ".rou.alt.xml"
    return parse_alt_file_flows(alt_out), r.stderr
