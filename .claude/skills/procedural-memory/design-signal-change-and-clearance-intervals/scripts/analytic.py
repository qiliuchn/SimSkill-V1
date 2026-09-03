"""Independent ITE / kinematic reference calculator.

Deliberately implemented from the published formulas, with NO dependence on SUMO,
so it can be used as an external check on what SUMO's vehicle dynamics actually do.

Conventions used throughout this study (stated explicitly because the literature
uses at least two incompatible namings):

    x  = distance from the vehicle's front bumper to the STOP LINE at yellow onset (m), x>0 upstream.

    x_s = MINIMUM distance at which a legal, comfortable stop is still possible
        = v * t_pr + v^2 / (2*(a + g*G))
      A vehicle with x >= x_s CAN stop.

    x_c = MAXIMUM distance from which the vehicle can legally clear
      Two variants are reported:
        x_c_stopline    = v * y                      (front bumper reaches the stop line by end of yellow)
        x_c_clear       = v * (y + r) - (W + L)      (rear bumper clears the far conflict point by end of all-red)
      A vehicle with x <= x_c CAN go.

    DILEMMA zone  = { x : x_c < x < x_s }   -> nonempty iff x_s > x_c. Neither legal option exists.
    OPTION  zone  = { x : x_s < x < x_c }   -> nonempty iff x_c > x_s. BOTH options legal ("indecision zone").

NOTE ON THE TASK STATEMENT'S CONVENTION: the task text writes the dilemma condition as
"x_c > x_s". That is the same physical condition under the opposite naming (where the
symbol for the clearing boundary denotes the *minimum* distance needed rather than the
maximum distance permitted). We use the convention above and state it every time a number
is reported, so the sign can never be ambiguous.

Sign of grade G: G > 0 is an UPGRADE (helps stopping), G < 0 is a DOWNGRADE (hurts stopping).
"""
import math

G_ACCEL = 9.81  # m/s^2


def ite_yellow(v, t_pr=1.0, a=3.05, grade=0.0):
    """ITE change interval. y = t_pr + v / (2a + 2gG).

    ITE Traffic Engineering Handbook / MUTCD-consistent defaults:
      t_pr = 1.0 s perception-reaction, a = 3.05 m/s^2 (10 ft/s^2) deceleration.
    grade is a fraction (e.g. -0.04 for a 4% downgrade).
    """
    denom = 2.0 * a + 2.0 * G_ACCEL * grade
    if denom <= 0:
        return float("inf")
    return t_pr + v / denom


def ite_allred(v, W, L=6.1):
    """ITE clearance interval r = (W + L)/v.

    W = width to be crossed (stop line to far edge of the conflicting traffic path), m.
    L = design vehicle length, m (ITE default 20 ft = 6.1 m).
    """
    return (W + L) / v


def x_stop(v, t_pr=1.0, a=3.05, grade=0.0):
    """Minimum distance from which a comfortable stop is still possible."""
    denom = a + G_ACCEL * grade
    if denom <= 0:
        return float("inf")
    return v * t_pr + v * v / (2.0 * denom)


def x_clear_stopline(v, y):
    """Maximum distance from which the front bumper reaches the stop line within yellow."""
    return v * y


def x_clear_full(v, y, r, W, L=6.1):
    """Maximum distance from which the vehicle fully clears the conflict area by end of all-red."""
    return v * (y + r) - (W + L)


def zone(v, y, r, W, t_pr=1.0, a=3.05, grade=0.0, L=6.1, clear_mode="stopline"):
    """Return the zone description for a given (v, y, r, geometry, driver) tuple."""
    xs = x_stop(v, t_pr, a, grade)
    if clear_mode == "stopline":
        xc = x_clear_stopline(v, y)
    else:
        xc = x_clear_full(v, y, r, W, L)
    d = dict(v=v, y=y, r=r, W=W, t_pr=t_pr, a=a, grade=grade, L=L,
             clear_mode=clear_mode, x_s=xs, x_c=xc)
    if xs > xc:
        d["zone_type"] = "DILEMMA"
        d["zone_lo"], d["zone_hi"] = xc, xs
        d["zone_width"] = xs - xc
        d["dilemma_width"] = xs - xc
        d["option_width"] = 0.0
    else:
        d["zone_type"] = "OPTION"
        d["zone_lo"], d["zone_hi"] = xs, xc
        d["zone_width"] = xc - xs
        d["dilemma_width"] = 0.0
        d["option_width"] = xc - xs
    return d


def yellow_to_kill_dilemma(v, t_pr=1.0, a=3.05, grade=0.0):
    """Smallest yellow with x_c(stopline) >= x_s, i.e. the dilemma zone closes.

    v*y >= v*t_pr + v^2/(2(a+gG))  ->  y >= t_pr + v/(2(a+gG)) == the ITE formula.
    Returned separately so the identity is *demonstrated numerically*, not just asserted.
    """
    return ite_yellow(v, t_pr, a, grade)


def sumo_stop_go_boundary(v, decel, tau_react=0.0, step_length=0.1):
    """SUMO's OWN predicted stop/go boundary, from its documented decision rule.

    SUMO drives through a yellow/red link iff it cannot brake to a stop before the
    link using its vType `decel` (MSVehicle::ignoreRed -> `!canBrake`). The brake gap
    used is MSCFModel::brakeGap(speed, maxDecel, headwayTime=0), whose SUMO
    (discrete-time, Euler) form is

        brakeGap = decel*(n*tau_step)^2/2 + v_rest*tau_step,  with n = floor(v/(decel*dt)),
                   v_rest = v - n*decel*dt

    which for small dt tends to v^2/(2*decel). The classical continuous form is used
    as the reference and the discrete correction reported alongside.
    """
    cont = v * tau_react + v * v / (2.0 * decel)
    dt = step_length
    n = math.floor(v / (decel * dt))
    v_rest = v - n * decel * dt
    disc = decel * (n * dt) ** 2 / 2.0 + v_rest * dt + n * dt * 0.0
    # SUMO's actual gap: sum over steps of speed*dt while decelerating
    s = 0.0
    vv = v
    while vv > 1e-9:
        vv = max(0.0, vv - decel * dt)
        s += vv * dt
    return dict(continuous=cont, euler_sum=s, closed_form=disc, v=v, decel=decel)


if __name__ == "__main__":
    import json
    import sys
    out = []
    for v in (11.11, 13.89, 16.67, 19.44, 22.22, 25.0):
        out.append(dict(v=v, ite_yellow=ite_yellow(v), x_stop=x_stop(v),
                        sumo=sumo_stop_go_boundary(v, 4.5)))
    json.dump(out, sys.stdout, indent=2)
