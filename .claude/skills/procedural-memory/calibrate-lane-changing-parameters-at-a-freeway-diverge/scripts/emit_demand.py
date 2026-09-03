#!/usr/bin/env python3
"""Write the demand / additional files as standalone deliverables (the exact
XML that lc_common.run_scenario generates in each run directory)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L

def emit(name, p, **kw):
    open(os.path.join(L.DEMDIR, name + ".rou.xml"), "w").write(
        L.routes_xml(p, **kw))
    print("wrote", os.path.join(L.DEMDIR, name + ".rou.xml"))

if __name__ == "__main__":
    emit("train_default", L.full_params())
    calp = os.path.join(L.TBL, "calibration.json")
    if os.path.exists(calp):
        c = {k: float(v) for k, v in json.load(open(calp))["best_params"].items()}
        emit("train_calibrated", c)
        emit("holdout_H1_1200vphpl_20pct", c, mainline_per_lane=1200.0,
             exit_share=0.20)
        emit("holdout_H2_1600vphpl_35pct", c, mainline_per_lane=1600.0,
             exit_share=0.35)
        emit("holdout_H3_1200vphpl_35pct", c, mainline_per_lane=1200.0,
             exit_share=0.35)
    open(os.path.join(L.DEMDIR, "instrumentation.add.xml"), "w").write(
        L.additional_xml())
    print("wrote", os.path.join(L.DEMDIR, "instrumentation.add.xml"))
