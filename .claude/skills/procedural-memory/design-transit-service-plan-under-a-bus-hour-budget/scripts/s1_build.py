"""Stage 1: network, zones, demand.  Builds everything that is FIXED across all
service plans (common random numbers for the fair comparison)."""
import os, json, sys, time
import tspcore as T
from tspcore import WORK, ensure

def main():
    ensure(WORK)
    t0 = time.time()
    net_file = T.build_network(WORK, tag="base")
    net = T.Net(net_file)
    print(f"network: {len(net.edge_len)} normal edges, "
          f"{sum(1 for e in net.edge_len if e in net.ped_lane)} with sidewalk lane")
    assert len(net.ped_lane) == len(net.edge_len), "some edges lack a sidewalk lane"

    pf, cf, meta = T.build_demand(net, WORK, n_trips=1800, seed=7)
    print(f"demand: {len(meta)} transit-market persons, "
          f"{1800-len(meta)} mode-choice car trips")
    bg = T.build_background(net, WORK, n_veh=10000, seed=11)
    cars = T.route_cars(net, WORK, [cf, bg], "cars.rou.xml")
    print("cars routed ->", cars)

    # OD documentation
    od = T.build_od()
    with open(os.path.join(WORK, "od_shares.csv"), "w") as f:
        f.write("o_zone,d_zone,share\n")
        for (i, j), v in sorted(od.items()):
            f.write(f"{T.ZONE_NAME[i]},{T.ZONE_NAME[j]},{v:.5f}\n")
    print(f"done in {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
