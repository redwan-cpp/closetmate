"""
usage_report.py — what is the AI actually costing us?

    python scripts/usage_report.py                 # last 7 days, grouped by feature
    python scripts/usage_report.py --days 30 --by user
    python scripts/usage_report.py --by model

Reads the ``ai_usage`` table. Dollar figures need per-model prices (USD per 1M
tokens) in the environment — look them up on the provider's pricing page rather
than trusting a number baked into code:

    PRICE_GPT_4O_MINI_IN=...  PRICE_GPT_4O_MINI_OUT=...
    PRICE_GEMINI_2_5_FLASH_IN=...  PRICE_GEMINI_2_5_FLASH_OUT=...

(model id upper-cased, non-alphanumerics become underscores). Without prices
the report still shows calls, failures, tokens and latency.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from settings import load_env  # noqa: E402

load_env()

from sqlalchemy import text  # noqa: E402

from database import engine  # noqa: E402


def _price(model: str, direction: str):
    key = "PRICE_" + re.sub(r"[^A-Za-z0-9]+", "_", model).upper().strip("_") + f"_{direction}"
    raw = os.getenv(key, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _cost(model: str, tokens_in: int, tokens_out: int):
    p_in, p_out = _price(model, "IN"), _price(model, "OUT")
    if p_in is None or p_out is None:
        return None
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--by", choices=("feature", "model", "user"), default="feature")
    args = parser.parse_args()

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""SELECT user_id, feature, provider, model, input_tokens, output_tokens,
                           latency_ms, ok
                    FROM ai_usage WHERE created_at >= :since"""),
            {"since": since},
        ).fetchall()

    if not rows:
        print(f"No AI calls recorded in the last {args.days} days.")
        return 0

    groups = defaultdict(lambda: {"calls": 0, "ok": 0, "in": 0, "out": 0, "lat": [], "cost": 0.0, "priced": True})
    users = set()
    for user_id, feature, provider, model, t_in, t_out, latency, ok in rows:
        key = {"feature": feature, "model": f"{provider}/{model}", "user": user_id or "(anonymous)"}[args.by]
        g = groups[key]
        g["calls"] += 1
        g["ok"] += 1 if ok else 0
        g["in"] += t_in or 0
        g["out"] += t_out or 0
        if latency is not None:
            g["lat"].append(latency)
        cost = _cost(model, t_in or 0, t_out or 0)
        if cost is None:
            g["priced"] = False
        else:
            g["cost"] += cost
        if user_id:
            users.add(user_id)

    print(f"AI usage, last {args.days} days — grouped by {args.by}\n")
    print(f"{args.by:<34} {'calls':>7} {'ok%':>5} {'in tok':>10} {'out tok':>9} {'p50 ms':>7} {'est $':>9}")
    total_cost, all_priced = 0.0, True
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["calls"]):
        p50 = int(statistics.median(g["lat"])) if g["lat"] else 0
        cost = f"{g['cost']:.4f}" if g["priced"] else "n/a"
        total_cost += g["cost"] if g["priced"] else 0
        all_priced = all_priced and g["priced"]
        print(f"{str(key)[:34]:<34} {g['calls']:>7} {100 * g['ok'] // g['calls']:>4}% "
              f"{g['in']:>10} {g['out']:>9} {p50:>7} {cost:>9}")

    if all_priced and users:
        print(f"\nTotal est. ${total_cost:.4f} across {len(users)} user(s) "
              f"= ${total_cost / len(users):.4f} per active user over {args.days} days.")
    elif not all_priced:
        print("\nSet PRICE_<MODEL>_IN / PRICE_<MODEL>_OUT (USD per 1M tokens) to see dollar costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
