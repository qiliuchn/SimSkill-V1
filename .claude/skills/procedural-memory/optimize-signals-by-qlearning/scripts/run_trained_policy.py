"""
Run a previously-trained (greedy, no exploration) Q-learning policy for
traffic signal control, using sumo-rl's SumoEnvironment.

Usage:
    python run_trained_policy.py --net-file net.net.xml --route-file routes.rou.xml \
        --qtables-dir qlearning_run/qtables --out-dir qlearning_eval --num-seconds 3600

IMPORTANT: --delta-time/--yellow-time/--min-green/--max-green must match
what was used during training (train_qlearning.py) — they define the
action space the Q-table was learned against.

Requires `pip install sumo-rl` and $SUMO_HOME set.
"""

import argparse
import glob
import os
import pickle
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate a trained Q-learning policy via sumo-rl.")

    p.add_argument("--net-file", required=True, help="Input .net.xml")
    p.add_argument("--route-file", required=True, help="Routed demand .rou.xml")
    p.add_argument("--qtables-dir", required=True, help="Directory of pickled Q-tables from train_qlearning.py")
    p.add_argument("--out-dir", required=True, help="Directory for evaluation CSV metrics and SUMO logs")

    p.add_argument("--num-seconds", type=int, default=3600, help="Simulated seconds to run (default: 3600)")

    p.add_argument("--delta-time", type=int, default=5, help="Must match training (default: 5)")
    p.add_argument("--yellow-time", type=int, default=2, help="Must match training (default: 2)")
    p.add_argument("--min-green", type=int, default=5, help="Must match training (default: 5)")
    p.add_argument("--max-green", type=int, default=50, help="Must match training (default: 50)")

    p.add_argument("--sumo-seed", default="random", help="'random' or an int (default: random)")
    p.add_argument("--begin-time", type=int, default=0, help="Simulation start time, s (default: 0)")
    p.add_argument("--gui", action="store_true", help="Run with sumo-gui to watch the policy drive the signals")
    p.add_argument("--additional-sumo-cmd", help="Raw extra SUMO command-line args, passed through")

    return p.parse_args()


def load_qtables(qtables_dir: str) -> dict:
    qtables = {}
    for path in glob.glob(os.path.join(qtables_dir, "*.pkl")):
        ts_id = os.path.splitext(os.path.basename(path))[0]
        with open(path, "rb") as f:
            qtables[ts_id] = pickle.load(f)
    return qtables


def greedy_action(qtable: dict, state, num_actions: int) -> int:
    """Pick the argmax action for a state; fall back to action 0 for unseen states."""
    if state not in qtable:
        return 0
    q_values = qtable[state]
    return max(range(num_actions), key=lambda a: q_values[a])


def main():
    args = parse_args()

    if not os.path.exists(args.net_file):
        sys.exit(f"Net file not found: {args.net_file}")
    if not os.path.exists(args.route_file):
        sys.exit(f"Route file not found: {args.route_file}")
    if not os.path.isdir(args.qtables_dir):
        sys.exit(f"Q-tables directory not found: {args.qtables_dir}")

    try:
        from sumo_rl import SumoEnvironment
    except ImportError as e:
        sys.exit(
            f"Could not import sumo-rl ({e}). Install it with `pip install sumo-rl`, "
            "and make sure $SUMO_HOME is set."
        )

    qtables = load_qtables(args.qtables_dir)
    if not qtables:
        sys.exit(f"No .pkl Q-tables found in {args.qtables_dir}")
    print(f"Loaded Q-tables for: {list(qtables.keys())}")

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    sumo_seed = args.sumo_seed
    if sumo_seed != "random":
        try:
            sumo_seed = int(sumo_seed)
        except ValueError:
            pass

    env = SumoEnvironment(
        net_file=args.net_file,
        route_file=args.route_file,
        out_csv_name=os.path.join(out_dir, "eval_results"),
        use_gui=args.gui,
        begin_time=args.begin_time,
        num_seconds=args.num_seconds,
        delta_time=args.delta_time,
        yellow_time=args.yellow_time,
        min_green=args.min_green,
        max_green=args.max_green,
        single_agent=False,
        ts_ids=list(qtables.keys()),
        sumo_seed=sumo_seed,
        sumo_warnings=False,
        additional_sumo_cmd=args.additional_sumo_cmd,
    )

    unseen_state_count = {ts_id: 0 for ts_id in qtables}

    try:
        obs = env.reset()
        if isinstance(obs, tuple):
            obs = obs[0]

        done_all = False
        total_reward = 0.0
        step_count = 0

        while not done_all:
            actions = {}
            for ts_id, ts_obs in obs.items():
                if ts_id not in qtables:
                    continue
                state = env.encode(ts_obs, ts_id)
                num_actions = env.action_spaces(ts_id).n
                if state not in qtables[ts_id]:
                    unseen_state_count[ts_id] += 1
                actions[ts_id] = greedy_action(qtables[ts_id], state, num_actions)

            step_result = env.step(actions)

            if len(step_result) == 4:
                next_obs, rewards, dones, _info = step_result
                done_all = bool(dones.get("__all__", all(dones.values()) if dones else False))
            elif len(step_result) == 5:
                next_obs, rewards, terminated, truncated, _info = step_result
                done_all = bool(terminated.get("__all__", False)) or bool(truncated.get("__all__", False))
            else:
                sys.exit(f"Unexpected step() return shape: {len(step_result)} values")

            total_reward += sum(float(r) for r in rewards.values())
            obs = next_obs
            step_count += 1

        env.save_csv(env.out_csv_name, env.episode)

    finally:
        env.close()

    print(f"\nEvaluation done: steps={step_count} total_reward={total_reward:.2f}")
    for ts_id, count in unseen_state_count.items():
        if count:
            print(f"  Warning: {ts_id} hit {count} state(s) not seen during training (fell back to action 0)")
    print(f"Metrics written under {out_dir}")


if __name__ == "__main__":
    main()
