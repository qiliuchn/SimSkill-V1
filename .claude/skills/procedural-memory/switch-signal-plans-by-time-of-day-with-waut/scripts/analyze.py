import os, csv
import xml.etree.ElementTree as ET
W=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
runs=["waut","fixedA","fixedB","fixedC"]
labels={"waut":"WAUT (A->B->C)","fixedA":"Fixed A all day","fixedB":"Fixed B all day","fixedC":"Fixed C all day"}
res={}
for r in runs:
    tree=ET.parse(os.path.join(W,f"{r}_tripinfo.xml"))
    wait=[]; dur=[]
    n=0
    for t in tree.getroot().findall("tripinfo"):
        wait.append(float(t.get("waitingTime")))
        dur.append(float(t.get("duration")))
        n+=1
    total_wait=sum(wait)
    res[r]=dict(n=n, total_wait=total_wait,
                mean_wait=total_wait/n if n else 0,
                mean_dur=sum(dur)/n if n else 0)
# print table
print(f"{'Run':<20}{'#veh':>6}{'TotWait(s)':>12}{'MeanWait(s)':>13}{'MeanTravel(s)':>15}")
for r in runs:
    d=res[r]
    print(f"{labels[r]:<20}{d['n']:>6}{d['total_wait']:>12.1f}{d['mean_wait']:>13.2f}{d['mean_dur']:>15.2f}")
# claim b
best_base=min(res[b]['total_wait'] for b in ["fixedA","fixedB","fixedC"])
best_base_run=min(["fixedA","fixedB","fixedC"], key=lambda b:res[b]['total_wait'])
w=res['waut']['total_wait']
print()
print(f"Best single-plan baseline: {labels[best_base_run]} total_wait={best_base:.1f}")
print(f"WAUT total_wait={w:.1f}")
imp=(best_base-w)/best_base*100
print(f"WAUT vs best baseline: {imp:+.2f}%  (positive = WAUT lower/better)")
print(f"WAUT lower than ALL baselines: {all(w<res[b]['total_wait'] for b in ['fixedA','fixedB','fixedC'])}")
# switch log
print()
for r in ["waut","fixedA","fixedB","fixedC"]:
    prev=None; changes=[]
    with open(os.path.join(W,f"{r}_progswitch.csv")) as f:
        for row in csv.DictReader(f):
            p=row["activeProgram"]
            if prev is not None and p!=prev: changes.append((row["time"],prev,p))
            prev=p
        # also first
    with open(os.path.join(W,f"{r}_progswitch.csv")) as f:
        rows=list(csv.DictReader(f))
    print(f"{r}: first={rows[0]['time']}:{rows[0]['activeProgram']} changes={changes} last={rows[-1]['time']}:{rows[-1]['activeProgram']}")
