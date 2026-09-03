"""Shared paths/constants for the heavy-vehicle grade-performance study."""
import os
import sys

SUMO_HOME = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
BIN = "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin"
os.environ["SUMO_HOME"] = SUMO_HOME
if os.path.join(SUMO_HOME, "tools") not in sys.path:
    sys.path.append(os.path.join(SUMO_HOME, "tools"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(ROOT, "net")
WORK = os.path.join(ROOT, "work")
RESULTS = os.path.join(ROOT, "results")
for d in (NET, WORK, RESULTS):
    os.makedirs(d, exist_ok=True)

SUMO_BIN = os.path.join(BIN, "sumo")
NETCONVERT_BIN = os.path.join(BIN, "netconvert")

# ---- AASHTO-design-truck physics defaults (see physics_model.py) ----
G = 9.81                    # m/s^2
RHO_AIR = 1.225              # kg/m^3
DEFAULT_MASS_KG = 36287.0    # 80,000 lb GVW -- standard AASHTO/HCM design truck
DEFAULT_CR = 0.007           # rolling resistance coefficient
DEFAULT_CD = 0.6             # aerodynamic drag coefficient, tractor-trailer
DEFAULT_A = 9.0              # frontal area, m^2
DEFAULT_ETA = 0.85           # driveline efficiency
V_FLOOR = 1.0                # m/s, low-speed force-singularity guard
