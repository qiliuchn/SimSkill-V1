import sys, os, json, numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
from equilibrate import equilibrate
cap=json.load(open(os.path.join(WORK,"capacity","capacity.json"))); tf=cap["free_flow"]["tf_mean"]
name=sys.argv[1]; scheme=sys.argv[2]; theta=float(sys.argv[3]); theta_hi=float(sys.argv[4])
ann=int(sys.argv[5]); lam_exp=float(sys.argv[6]); iters=int(sys.argv[7])
res,rows=equilibrate("tune_"+name, np.zeros(NSLOT), tf, iters=iters, scheme=scheme,
                     theta=theta, theta_hi=theta_hi, anneal_iters=ann, lam_exp=lam_exp)
tr=res["trace"]; tail=tr[-15:]
print("RESULT %-10s scheme=%-7s th=%.0f->%.0f ann=%d lam=%.2f it=%d | coreGap=%.4f(tail %.4f) coreSd=%.4f meanCost=%.1f meanQ=%.1f chg=%.4f nCore=%d"
 %(name,scheme,theta_hi,theta,ann,lam_exp,iters,tr[-1]["core_gap_rel"],
   np.mean([t["core_gap_rel"] for t in tail]),tr[-1]["core_wstd_rel"],
   tr[-1]["mean_cost"],tr[-1]["mean_queue"],tr[-1]["frac_changed_slot"],tr[-1]["n_core_slots"]),flush=True)
