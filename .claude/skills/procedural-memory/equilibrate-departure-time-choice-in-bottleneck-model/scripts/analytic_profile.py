import os,sys,json,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *
from equilibrate import largest_remainder, smooth_cost_curve

def analytic_counts(N,s,tf,alpha=ALPHA,beta=BETA,gamma=GAMMA,t_star=T_STAR):
    a=vickrey_analytic(N,s,tf,alpha,beta,gamma,t_star)
    ts,te=a["t_first_depart"],a["t_last_depart"]
    tn=ts+ (a["frac_early"]*N)/ (alpha*s/(alpha-beta))   # duration of the early branch
    r_e=alpha*s/(alpha-beta); r_l=alpha*s/(alpha+gamma)
    st=slot_starts(); dens=np.zeros(NSLOT)
    for k,t0 in enumerate(st):
        t1=t0+SLOT
        ov_e=max(0.0,min(t1,tn)-max(t0,ts)); ov_l=max(0.0,min(t1,te)-max(t0,tn))
        dens[k]=r_e*ov_e+r_l*ov_l
    return largest_remainder(dens,N), a, ts,tn,te

if __name__=="__main__":
    cap=json.load(open(os.path.join(WORK,"capacity","capacity.json")))
    tf=cap["free_flow"]["tf_mean"]; s=cap["capacity_vps"]
    cnts,a,ts,tn,te=analytic_counts(N_COMMUTERS,s,tf)
    print("s=%.5f veh/s (%.1f veh/h)  Tf=%.2f"%(s,s*3600,tf))
    print("analytic: t_s=%.0f t_n=%.0f t_e=%.0f peak=%.0f excessCost=%.1f Tmax=%.1f meanQ=%.1f"
          %(ts,tn,te,a["peak_len"],a["excess_cost_per_traveller"],a["max_queue_delay"],a["mean_queue_delay"]))
    d=os.path.join(WORK,"analytic"); os.makedirs(d,exist_ok=True)
    rou=os.path.join(d,"an.rou.xml"); ti=os.path.join(d,"an.tripinfo.xml")
    slot_of=write_routes(cnts,rou); run_sumo(rou,ti,seed=1)
    recs=parse_tripinfo(ti)
    rows=vehicle_costs(recs,slot_of,tf,np.zeros(NSLOT))
    c=np.array([r["cost"] for r in rows]); q=np.array([r["queue"] for r in rows])
    dd=np.array([r["depart_delay"] for r in rows])
    print("SUMO on analytic profile: meanCost=%.1f sd=%.1f  meanQ=%.1f maxQ=%.1f  dd(mean=%.2f max=%.1f)"
          %(c.mean(),c.std(),q.mean(),q.max(),dd.mean(),dd.max()))
    print("predicted meanCost = Tf + delta*N/s = %.1f"%(tf+a["excess_cost_per_traveller"]))
    cnt,mc,mq=slot_stats(rows); sm,valid=smooth_cost_curve(rows,halfwin=12)
    st=slot_starts()
    print("\n  t      n   meanCost  smoothCost   meanQ")
    for k in np.where(cnt>0)[0][::3]:
        print("  %6.0f %3d  %8.1f  %8.1f  %7.1f"%(st[k],cnt[k],mc[k],sm[k],mq[k]))
    np.save(os.path.join(d,"analytic_counts.npy"),cnts)
