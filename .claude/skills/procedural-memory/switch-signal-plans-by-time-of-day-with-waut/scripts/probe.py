import os, sys
os.environ.setdefault("SUMO_HOME","/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(os.environ["SUMO_HOME"],"tools"))
import traci
from sumolib import checkBinary
W=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cmd=[checkBinary("sumo"),"-n",W+"/intersection.net.xml","-r",W+"/demand.rou.xml",
     "-a",W+"/programs.add.xml,"+W+"/waut.add.xml","--no-step-log","true","-e","1300","--start"]
traci.start(cmd)
# read-before-step ordering
t=0
prev=None
while t<1300:
    p=traci.trafficlight.getProgram("center")
    if p!=prev:
        print("BEFORE-step time=%d prog=%s"%(t,p))
        prev=p
    traci.simulationStep()
    t=int(traci.simulation.getTime())
traci.close()
