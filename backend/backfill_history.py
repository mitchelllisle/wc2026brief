"""One-off script: rebuild history.json from the tournament start using the live API.

Run from the backend/ directory:
    uv run python backfill_history.py

Fetches all WC2026 matches, groups by matchday, and for each completed matchday
computes projections using only matches from that matchday and earlier — producing
one history.json snapshot per matchday.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

# Allow importing the package without installing
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wc2026brief.config import Config
from wc2026brief.fetcher import (
    FOOTBALL_API_BASE,
    _HISTORY_TOP_N,
    _KNOCKOUT_ROUND_LABELS,
    build_projections,
    compute_advancement,
    compute_team_records,
    deepest_finished_stage,
    fetch_fifa_rankings,
)
from wc2026brief.models import Squads

AEST = ZoneInfo("Australia/Sydney")
DATA_DIR = Path(__file__).parents[1] / "data"


def fetch_matches(api_key: str) -> list[dict]:
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{FOOTBALL_API_BASE}/competitions/WC/matches",
            headers={"X-Auth-Token": api_key},
        )
        resp.raise_for_status()
    return resp.json()["matches"]


def snapshot_ts(matches: list[dict]) -> str:
    """Return the latest utcDate from a list of matches as an AEST ISO string."""
    latest = max(m["utcDate"] for m in matches)
    dt = datetime.fromisoformat(latest.replace("Z", "+00:00")).astimezone(AEST)
    # Set time to end-of-day so it clearly represents "after this matchday"
    return dt.replace(hour=23, minute=59, second=0, microsecond=0).isoformat()


def round_label(matchday: int | None) -> str:
    return f"MD{matchday}" if matchday else "MD?"


def main() -> None:
    config = Config(_env_file=str(Path(__file__).parent.parent / ".env"), _env_file_encoding="utf-8")  # type: ignore[call-arg]
    api_key = config.football_data_api_key.get_secret_value()

    print("Fetching all WC2026 matches…")
    all_matches = fetch_matches(api_key)
    finished = [m for m in all_matches if m["status"] == "FINISHED"]
    print(f"  {len(finished)} finished matches found")

    print("Fetching FIFA rankings…")
    try:
        rankings = fetch_fifa_rankings()
        print(f"  {len(rankings)} teams ranked")
    except Exception as exc:
        print(f"  WARNING: could not fetch rankings ({exc}), proceeding without")
        rankings = None

    squads = Squads.model_validate_json((DATA_DIR / "squads.json").read_text())

    # Group finished matches by matchday; also capture all matchdays present
    matchdays_seen = sorted(set(m["matchday"] for m in finished if m.get("matchday")))
    print(f"  Matchdays with finished games: {matchdays_seen}")

    # Load existing history so we can merge rather than overwrite.
    # The live CI fetcher accumulates daily snapshots; backfill must not
    # destroy entries it cannot regenerate (e.g. GS data once knockout begins).
    history_file = DATA_DIR / "history.json"
    wt_file = Path(__file__).parents[1] / "data" / "history.json"
    target = wt_file if (wt_file != history_file and wt_file.parent.exists()) else history_file

    existing: dict[str, dict] = {}
    if target.exists():
        try:
            for s in json.loads(target.read_text()).get("snapshots", []):
                existing[s["round"]] = s
        except Exception:
            pass

    generated: dict[str, dict] = {}
    for md in matchdays_seen:
        # Matches from this and all earlier matchdays
        subset = [m for m in finished if m.get("matchday", 0) <= md]
        team_records = compute_team_records(subset)
        advancement = compute_advancement(subset)
        projections = build_projections(squads, team_records, rankings=rankings, advancement=advancement)

        stage = deepest_finished_stage(subset)
        label = _KNOCKOUT_ROUND_LABELS.get(stage, round_label(md))
        ts = snapshot_ts(subset)

        ranked = sorted(projections.teams, key=lambda t: t.title_probability, reverse=True)
        teams = [
            {
                "name": t.name,
                "flag": t.flag,
                "manager": t.manager,
                "rank": i + 1,
                "score": t.title_probability,
            }
            for i, t in enumerate(ranked)  # store all teams so the chart can show any zoom level
        ]

        snap = {"ts": ts, "stage": stage, "round": label, "teams": teams}
        generated[label] = snap
        print(f"  {label}: top5 = {[t['name'] for t in teams[:5]]}  (ts={ts[:10]})")

    # Merge: backfill-generated entries win over existing for the same round;
    # rounds only the live fetcher has (e.g. daily R32 entries) are preserved.
    merged: dict[str, dict] = {**existing, **generated}

    # Sort by ts so the chart x-axis is chronological
    snapshots = sorted(merged.values(), key=lambda s: s["ts"])

    target.write_text(json.dumps({"snapshots": snapshots}, indent=2))
    print(f"\nWrote {len(snapshots)} snapshots to {target}")


if __name__ == "__main__":
    main()
