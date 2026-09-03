"""
Train one tabular Q-learning agent per traffic signal using sumo-rl's
SumoEnvironment + QLAgent.

Usage:
    python train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run
    python train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run --episodes 50 --reward-fn queue
    python train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run --ts-ids tls_A,tls_B
    python train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run --gui

Requires `pip install sumo-rl` and $SUMO_HOME set (sumo-rl raises
ImportError at import time otherwise). Imports are done lazily so this
file can at least be parsed/inspected without either being present.
"""

import argparse
import os
import pickle
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Train per-signal Q-learning agents via sumo-rl.")

    p.add_argument("--net-file", required=True, help="Input .net.xml")
    p.add_argument("--route-file", required=True, help="Routed demand .rou.xml (not raw trips/flows)")
    p.add_argument("--out-dir", required=True, help="Directory for Q-tables, training CSVs, and SUMO logs")

    p.add_argument("--episodes", type=int, default=5, help="Number of training episodes (default: 5)")
    p.add_argument("--num-seconds", type=int, default=3600, help="Simulated seconds per episode (default: 3600)")

    p.add_argument("--alpha", type=float, default=0.1, help="Q-learning learning rate (default: 0.1)")
    p.add_argument("--gamma", type=float, default=0.99, help="Discount factor (default: 0.99)")

    p.add_argument("--delta-time", type=int, default=5, help="Seconds between agent decisions (default: 5)")
    p.add_argument("--yellow-time", type=int, default=2, help="Yellow phase duration, s (default: 2)")
    p.add_argument("--min-green", type=int, default=5, help="Minimum green duration, s (default: 5)")
    p.add_argument("--max-green", type=int, default=50, help="Maximum green duration, s (default: 50)")

    p.add_argument(
        "--reward-fn",
        default="diff-waiting-time",
        choices=["diff-waiting-time", "average-speed", "queue", "pressure", "co2"],
        help="Reward function (default: diff-waiting-time)",
    )
    p.add_argument("--sumo-seed", default="random", help="'random' or an int, for reproducibility (default: random)")
    p.add_argument("--ts-ids", help="Comma-separated traffic-light ids to control (default: every tlLogic in the network)")
    p.add_argument("--begin-time", type=int, default=0, help="Simulation start time, s (default: 0)")
    p.add_argument("--gui", action="store_true", help="Run with sumo-gui instead of headless (much slower)")
    p.add_argument("--additional-sumo-cmd", help="Raw extra SUMO command-line args, passed through")

    return p.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.net_file):
        sys.exit(f"Net file not found: {args.net_file}")
    if not os.path.exists(args.route_file):
        sys.exit(f"Route file not found: {args.route_file}")

    try:
        from sumo_rl import SumoEnvironment
        from sumo_rl.agents import QLAgent
    except ImportError as e:
        sys.exit(
            f"Could not import sumo-rl ({e}). Install it with `pip install sumo-rl`, "
            "and make sure $SUMO_HOME is set (sumo-rl imports traci internally)."
        )

    out_dir = os.path.abspath(args.out_dir)
    qtables_dir = os.path.join(out_dir, "qtables")
    os.makedirs(qtables_dir, exist_ok=True)

    sumo_seed = args.sumo_seed
    if sumo_seed != "random":
        try:
            sumo_seed = int(sumo_seed)
        except ValueError:
            pass  # leave as string; sumo-rl will pass it through and let sumo complain if invalid

    env = SumoEnvironment(
        net_file=args.net_file,
        route_file=args.route_file,
        out_csv_name=os.path.join(out_dir, "train_results"),
        use_gui=args.gui,
        begin_time=args.begin_time,
        num_seconds=args.num_seconds,
        delta_time=args.delta_time,
        yellow_time=args.yellow_time,
        min_green=args.min_green,
        max_green=args.max_green,
        single_agent=False,
        reward_fn=args.reward_fn,
        sumo_seed=sumo_seed,
        ts_ids=args.ts_ids.split(",") if args.ts_ids else None,
        sumo_warnings=False,
        additional_sumo_cmd=args.additional_sumo_cmd,
    )

    if not getattr(env, "ts_ids", None):
        env.close()
        sys.exit(
            "No traffic lights found in the network (or none matched --ts-ids). "
            "RL training needs at least one tlLogic-controlled intersection."
        )

    print(f"Controlling {len(env.ts_ids)} traffic signal(s): {env.ts_ids}")

    agents = {}

    try:
        for ep in range(1, args.episodes + 1):
            obs = env.reset()
            if isinstance(obs, tuple):  # some gym versions return (obs, info)
                obs = obs[0]

            for ts_id, ts_obs in obs.items():
                state = env.encode(ts_obs, ts_id)
                if ts_id not in agents:
                    agents[ts_id] = QLAgent(
                        starting_state=state,
                        state_space=env.observation_spaces(ts_id),
                        action_space=env.action_spaces(ts_id),
                        alpha=args.alpha,
                        gamma=args.gamma,
                    )
                else:
                    agent = agents[ts_id]
                    if state not in agent.q_table:
                        agent.q_table[state] = [0 for _ in range(agent.action_space.n)]
                    agent.state = state
                    agent.action = None
                    agent.acc_reward = 0

            done_all = False
            ep_total_reward = 0.0
            step_count = 0
            while not done_all:
                actions = {ts_id: agents[ts_id].act() for ts_id in obs.keys() if ts_id in agents}
                step_result = env.step(actions)

                if len(step_result) == 4:
                    next_obs, rewards, dones, _info = step_result
                    done_all = bool(dones.get("__all__", all(dones.values()) if dones else False))
                elif len(step_result) == 5:
                    next_obs, rewards, terminated, truncated, _info = step_result
                    done_all = bool(terminated.get("__all__", False)) or bool(truncated.get("__all__", False))
                    dones = {"__all__": done_all}
                else:
                    sys.exit(f"Unexpected step() return shape: {len(step_result)} values")

                for ts_id, reward in rewards.items():
                    if ts_id not in agents or ts_id not in next_obs:
                        continue
                    agents[ts_id].learn(
                        next_state=env.encode(next_obs[ts_id], ts_id),
                        reward=reward,
                        done=dones.get(ts_id, False),
                    )
                    ep_total_reward += float(reward)

                obs = next_obs
                step_count += 1

            print(f"Episode {ep}/{args.episodes}: steps={step_count} total_reward={ep_total_reward:.2f}")

        # sumo-rl only auto-saves the previous episode's CSV on reset(); save the last one explicitly.
        env.save_csv(env.out_csv_name, env.episode)

    finally:
        env.close()

    for ts_id, agent in agents.items():
        path = os.path.join(qtables_dir, f"{ts_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(dict(agent.q_table), f)
        print(f"Saved Q-table for {ts_id}: {path} ({len(agent.q_table)} states)")

    print(f"\nDone. Q-tables in {qtables_dir}, training metrics in {out_dir}")


if __name__ == "__main__":
    main()
