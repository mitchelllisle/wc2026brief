import json
import logging
from collections import defaultdict
from itertools import combinations, product
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from wc2026brief.config import Config
from wc2026brief.models import (
    FormEntry,
    LeaderboardEntry,
    ManagerProjection,
    ParticipantStats,
    ProjectionsOutput,
    RecentResult,
    Record,
    Squads,
    StatsOutput,
    SummaryOutput,
    TeamProjection,
    TeamRecord,
    TeamResult,
    TitleStrengthBreakdown,
)

logger = logging.getLogger(__name__)

AEST = ZoneInfo("Australia/Sydney")
FOOTBALL_API_BASE = "https://api.football-data.org/v4"
FIFA_RANKINGS_URL = "https://api.fifa.com/api/v3/fifarankings/rankings/live?gender=1&sportType=0&language=en"
MAX_RECENT_RESULTS = 24
MAX_SUMMARY_WORDS = 130
STAGE_WEIGHT = 0.30
_BASE_FORM_WEIGHT = 0.50
_BASE_RANK_WEIGHT = 0.20

# Depth index per stage — all teams at the same stage share the same weight vector,
# keeping cross-team scores on a uniform basis inside the normalisation sum.
_STAGE_DEPTH: dict[str, int] = {
    "GROUP_STAGE":    0,
    "LAST_32":        1,
    "LAST_16":        2,
    "QUARTER_FINALS": 3,
    "SEMI_FINALS":    4,
    "THIRD_PLACE":    4,
    "FINAL":          5,
}
_MAX_STAGE_DEPTH = 5   # GROUP(0) → FINAL(5)
_MIN_RANK_WEIGHT = 0.02  # rank never fully zeroed — retains a small prior even at the final


def _dynamic_weights(stage: str) -> tuple[float, float]:
    """Decay rank weight by tournament round, not per-team games played.
    Group stage: form=50%, rank=20%. Final: form=68%, rank=2%.
    All teams at the same round share one weight vector."""
    depth = _STAGE_DEPTH.get(stage, 0)
    decay = depth / _MAX_STAGE_DEPTH
    rank_w = max(_MIN_RANK_WEIGHT, _BASE_RANK_WEIGHT * (1.0 - decay))
    form_w = _BASE_FORM_WEIGHT + (_BASE_RANK_WEIGHT - rank_w)
    return form_w, rank_w

# Names used in squads.json that differ from FIFA's English team names
FIFA_NAME_ALIASES: dict[str, str] = {
    "United States": "USA",
    "Iran": "IR Iran",
    "Turkey": "Türkiye",
    "Ivory Coast": "Côte d'Ivoire",
    "Cape Verde Islands": "Cabo Verde",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "South Korea": "Korea Republic",
}

_AGENT_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "agent_instructions.md").read_text()


def fetch_fifa_rankings() -> dict[str, int]:
    """Fetch live FIFA rankings and return a name → rank mapping.

    Applies FIFA_NAME_ALIASES so squad team names map correctly to FIFA entries.
    """
    with httpx.Client(timeout=30) as client:
        resp = client.get(FIFA_RANKINGS_URL)
        resp.raise_for_status()
    alias_lookup = {v: k for k, v in FIFA_NAME_ALIASES.items()}
    result: dict[str, int] = {}
    for entry in resp.json()["Results"]:
        fifa_name = entry["TeamName"][0]["Description"]
        rank = entry["Rank"]
        # Store under the FIFA name
        result[fifa_name] = rank
        # Also store under the squad alias if one exists
        if squad_name := alias_lookup.get(fifa_name):
            result[squad_name] = rank
    return result


_STAGE_SCORES: dict[str, float] = {
    "GROUP_STAGE":    0.00,
    "LAST_32":        0.20,
    "LAST_16":        0.40,
    "QUARTER_FINALS": 0.60,
    "SEMI_FINALS":    0.80,
    "THIRD_PLACE":    0.85,
    "FINAL":          1.00,
}

_STAGE_LABELS: dict[str, str] = {
    "GROUP_STAGE":    "Group stage",
    "LAST_32":        "Round of 32",
    "LAST_16":        "Round of 16",
    "QUARTER_FINALS": "Quarter-final",
    "SEMI_FINALS":    "Semi-final",
    "THIRD_PLACE":    "Third place",
    "FINAL":          "Final",
}


def _form_score(rec: TeamRecord) -> float:
    """0–1. Points/24 is the primary signal (8 games × 3 pts max in 2026 format).
    Goals per game adds a small tiebreaker; presented separately in the breakdown."""
    if rec.played == 0:
        return 0.0
    pts = rec.points / 24
    gpg = (rec.gf / rec.played) * 0.02
    return _clamp(pts + gpg, 0.0, 1.0)


def _stage_score(rec: TeamRecord) -> float:
    """0–1 based on how far the team has progressed."""
    return _STAGE_SCORES.get(rec.current_stage, 0.0)


def _rank_score(fifa_rank: int | None) -> float:
    """0–1 based on FIFA world ranking. Rank 1 = 1.0, rank 80+ = 0.1."""
    if fifa_rank is None:
        return 0.5
    return _clamp(1.0 - (fifa_rank - 1) / 80, 0.1, 1.0)


def compute_team_records(matches: list[dict]) -> dict[str, TeamRecord]:
    """Build a per-team win/draw/loss record from a list of API match objects.

    Only FINISHED matches with non-null scores are counted. Matches played
    outside the GROUP_STAGE are treated as knockout rounds; a loss there sets
    knocked_out=True on the losing team's record.

    Args:
        matches: Raw match dicts as returned by the football-data.org API.

    Returns:
        Mapping of team name to its accumulated TeamRecord.
    """
    records: dict[str, TeamRecord] = {}

    for match in sorted(matches, key=lambda m: m["utcDate"]):
        if match["status"] != "FINISHED":
            continue

        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        hs = match["score"]["fullTime"]["home"]
        as_ = match["score"]["fullTime"]["away"]
        if hs is None or as_ is None:
            continue
        stage = match.get("stage") or "GROUP_STAGE"
        is_knockout = stage not in ("GROUP_STAGE", "")
        winner = match.get("score", {}).get("winner")

        for team, is_home in [(home, True), (away, False)]:
            rec = records.setdefault(team, TeamRecord())
            score_for = hs if is_home else as_
            score_against = as_ if is_home else hs
            opponent = away if is_home else home
            score_str = f"{score_for}–{score_against}"
            rec.played += 1
            rec.gf += score_for
            rec.ga += score_against
            rec.current_stage = stage

            if is_knockout and winner in {"HOME_TEAM", "AWAY_TEAM"}:
                team_won = (winner == "HOME_TEAM") == is_home
                if team_won:
                    rec.w += 1
                    rec.points += 3
                    rec.last_result = "W"
                    rec.form = (rec.form + [FormEntry(result="W", opponent=opponent, score=score_str)])[-5:]
                else:
                    rec.l += 1
                    rec.last_result = "L"
                    rec.knocked_out = True
                    rec.form = (rec.form + [FormEntry(result="L", opponent=opponent, score=score_str)])[-5:]
            elif score_for > score_against:
                rec.w += 1
                rec.points += 3
                rec.last_result = "W"
                rec.form = (rec.form + [FormEntry(result="W", opponent=opponent, score=score_str)])[-5:]
            elif score_for == score_against:
                rec.d += 1
                rec.points += 1
                rec.last_result = "D"
                rec.form = (rec.form + [FormEntry(result="D", opponent=opponent, score=score_str)])[-5:]
            else:
                rec.l += 1
                rec.last_result = "L"
                if is_knockout:
                    rec.knocked_out = True
                rec.form = (rec.form + [FormEntry(result="L", opponent=opponent, score=score_str)])[-5:]

    return records


def compute_advancement(
    matches: list[dict],
    advance_per_group: int = 2,
    best_thirds: int = 8,
) -> dict[str, str]:
    """Classify every group-stage team's chance of reaching the knockout round.

    FIFA World Cup 2026 uses 12 groups of four and sends 32 of the 48 teams
    through: the top ``advance_per_group`` (2) of every group **plus** the
    ``best_thirds`` (8) best third-placed teams across all groups. A team is
    therefore only eliminated once it can neither finish in the top two of its
    group nor reach a points total that could still rank among the best
    third-placed teams — losing two matches is no longer enough on its own.

    Remaining group fixtures are reconstructed from the round-robin structure
    (each pair of a group's four teams meets exactly once), so the verdict is
    correct whether or not the as-yet-unplayed matches appear in ``matches`` —
    this keeps historical back-fill snapshots honest, where only finished
    matches are supplied.

    Elimination is decided conservatively: a rival group only counts against a
    team when it is *guaranteed* a better third-placed team. Goal difference and
    goals scored break ties only between groups that have both finished (where
    those numbers can no longer change); while matches remain, comparison is on
    points alone, so a team is never declared out while a winnable tie-breaker
    could still save it.

    Args:
        matches: Raw match dicts as returned by the football-data.org API.
        advance_per_group: Automatic qualifiers per group (default 2).
        best_thirds: Third-placed teams that also advance (default 8).

    Returns:
        Mapping of team name to ``"clinched"`` (guaranteed a top-two finish),
        ``"eliminated"`` (cannot reach the knockout round), or ``"alive"``.
        Teams with no group-stage matches are absent from the mapping.
    """
    teams_by_group: dict[str, set[str]] = defaultdict(set)
    played_pairs: dict[str, set[frozenset[str]]] = defaultdict(set)
    pts: dict[str, int] = defaultdict(int)
    gd: dict[str, int] = defaultdict(int)
    gf: dict[str, int] = defaultdict(int)

    for match in matches:
        group = match.get("group")
        if match.get("stage") != "GROUP_STAGE" or not group:
            continue
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        teams_by_group[group].update((home, away))
        if match.get("status") != "FINISHED":
            continue
        hs = match.get("score", {}).get("fullTime", {}).get("home")
        as_ = match.get("score", {}).get("fullTime", {}).get("away")
        if hs is None or as_ is None:
            continue
        played_pairs[group].add(frozenset((home, away)))
        gf[home] += hs; gd[home] += hs - as_
        gf[away] += as_; gd[away] += as_ - hs
        if hs > as_:
            pts[home] += 3
        elif hs < as_:
            pts[away] += 3
        else:
            pts[home] += 1; pts[away] += 1

    # Enumerate every still-possible final points table for each group.
    group_outcomes: dict[str, list[dict[str, int]]] = {}
    third_floor: dict[str, int] = {}       # fewest points the 3rd-placed slot can end on
    third_exact: dict[str, tuple[int, int, int] | None] = {}  # set only once a group has finished
    for group, members in teams_by_group.items():
        gteams = sorted(members)
        remaining = [
            pair for pair in combinations(gteams, 2)
            if frozenset(pair) not in played_pairs[group]
        ]
        outcomes: list[dict[str, int]] = []
        for combo in product((0, 1, 2), repeat=len(remaining)):
            table = {t: pts[t] for t in gteams}
            for (home, away), result in zip(remaining, combo):
                if result == 0:
                    table[home] += 3
                elif result == 1:
                    table[home] += 1; table[away] += 1
                else:
                    table[away] += 3
            outcomes.append(table)
        group_outcomes[group] = outcomes
        third_floor[group] = min(
            sorted(o.values(), reverse=True)[2] for o in outcomes
        ) if len(gteams) >= 3 else 0
        if not remaining and len(gteams) >= 3:
            order = sorted(gteams, key=lambda t: (-pts[t], -gd[t], -gf[t]))
            third = order[2]
            third_exact[group] = (pts[third], gd[third], gf[third])
        else:
            third_exact[group] = None

    outlook: dict[str, str] = {}
    for group, members in teams_by_group.items():
        gteams = sorted(members)
        outcomes = group_outcomes[group]
        complete = third_exact[group] is not None
        for team in gteams:
            best_ranks: list[int] = []   # rank if this team wins every remaining tie-breaker
            worst_ranks: list[int] = []  # rank if it loses every remaining tie-breaker
            third_points: list[int] = [] # points in scenarios where it can finish exactly 3rd
            for table in outcomes:
                p = table[team]
                above = sum(1 for x in gteams if x != team and table[x] > p)
                level = sum(1 for x in gteams if x != team and table[x] == p)
                best_ranks.append(1 + above)
                worst_ranks.append(1 + above + level)
                if 1 + above == advance_per_group + 1:
                    third_points.append(p)

            if all(r <= advance_per_group for r in worst_ranks):
                outlook[team] = "clinched"
                continue
            if any(r <= advance_per_group for r in best_ranks):
                outlook[team] = "alive"
                continue
            # Cannot reach the top two — survival now depends on the best-thirds race.
            if not third_points:
                outlook[team] = "eliminated"
                continue
            ceiling = max(third_points)
            guaranteed_better = 0
            for other in teams_by_group:
                if other == group:
                    continue
                floor = third_floor[other]
                if floor > ceiling:
                    guaranteed_better += 1
                elif (
                    complete
                    and third_exact[other] is not None
                    and floor == ceiling
                    and third_exact[other] > third_exact[group]
                ):
                    guaranteed_better += 1
            outlook[team] = "eliminated" if guaranteed_better >= best_thirds else "alive"

    return outlook


def team_status(rec: TeamRecord, outlook: str | None = None) -> str:
    """Derive a sweep status string from a team's record and advancement outlook.

    A team is "out" only once it is actually eliminated: knocked out of a
    knockout tie, or — per the 2026 group format — unable to reach the knockout
    round via a top-two or best-third finish (``outlook == "eliminated"``).
    Simply losing matches in the group stage no longer forces "out"; a beaten
    team that can still sneak through as a best third stays alive.

    Args:
        rec: Accumulated win/draw/loss record for a single team.
        outlook: This team's group-stage outlook from :func:`compute_advancement`
            (``"clinched"``, ``"eliminated"``, ``"alive"``), or ``None`` when no
            group-stage context is available.

    Returns:
        One of "in", "at_risk", or "out".
    """
    if rec.knocked_out:
        return "out"
    if rec.current_stage != "GROUP_STAGE" and rec.played >= 1:
        return "in"  # survived into (or through) a knockout round
    if outlook == "eliminated":
        return "out"
    if outlook == "clinched":
        return "in"
    if rec.l >= 1:
        return "at_risk"
    return "in"


def _fallback_code(team_name: str) -> str:
    compact = "".join(ch for ch in team_name.upper() if ch.isalpha())
    return (compact[:3] or "TBD").ljust(3, "X")


def _group_label(match: dict) -> str:
    group = match.get("group")
    if isinstance(group, str) and group:
        if group.startswith("GROUP_"):
            return f"GRP {group.split('_')[-1]}"
        return group.replace("_", " ")

    stage = match.get("stage", "")
    stage_map = {
        "ROUND_OF_16": "RO16",
        "QUARTER_FINALS": "QF",
        "SEMI_FINALS": "SF",
        "THIRD_PLACE": "3RD",
        "FINAL": "FINAL",
    }
    return stage_map.get(stage, "KO")


def build_recent_results(matches: list[dict], squads: Squads) -> list[RecentResult]:
    team_flags = {team.name: team.flag for p in squads.participants for team in p.teams}
    results: list[RecentResult] = []

    finished = sorted(
        [m for m in matches if m.get("status") == "FINISHED"],
        key=lambda m: m.get("utcDate", ""),
        reverse=True,
    )

    for match in finished:
        score = match.get("score", {}).get("fullTime", {})
        hs = score.get("home")
        as_ = score.get("away")
        if hs is None or as_ is None:
            continue

        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        home_name = home_team.get("name", "")
        away_name = away_team.get("name", "")

        h_code = home_team.get("tla") or _fallback_code(home_name)
        a_code = away_team.get("tla") or _fallback_code(away_name)
        h_flag = team_flags.get(home_name, "🏳️")
        a_flag = team_flags.get(away_name, "🏳️")

        results.append(RecentResult(
            h_code=h_code,
            h_flag=h_flag,
            hs=hs,
            a_code=a_code,
            a_flag=a_flag,
            as_=as_,
            group=_group_label(match),
        ))

        if len(results) >= MAX_RECENT_RESULTS:
            break

    return results


def _limit_words(text: str, max_words: int = MAX_SUMMARY_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:-") + "…"


def _enforce_summary_length(paragraphs: list[str]) -> list[str]:
    return [_limit_words(p, MAX_SUMMARY_WORDS) for p in paragraphs]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))




def build_projections(
    squads: Squads,
    team_records: dict[str, TeamRecord],
    rankings: dict[str, int] | None = None,
    advancement: dict[str, str] | None = None,
) -> ProjectionsOutput:
    team_entries: list[TeamProjection] = []
    raw_title_scores: list[tuple[TeamProjection, float]] = []

    for participant in squads.participants:
        for team in participant.teams:
            rec = team_records.get(team.name, TeamRecord())
            fifa_rank = rankings.get(team.name) if rankings else None
            status = team_status(rec, (advancement or {}).get(team.name))
            form  = _form_score(rec)
            stage = _stage_score(rec)
            rank  = _rank_score(fifa_rank)
            form_w, rank_w = _dynamic_weights(rec.current_stage)
            title_score = (
                form_w       * form
                + STAGE_WEIGHT * stage
                + rank_w       * rank
            ) if status != "out" else 0.0
            title_breakdown = TitleStrengthBreakdown(
                form_score=round(form, 3),
                stage_score=round(stage, 2),
                rank_score=round(rank, 3),
                stage_label=_STAGE_LABELS.get(rec.current_stage, rec.current_stage),
                form_weight=round(form_w, 3),
                rank_weight=round(rank_w, 3),
            )
            projection = TeamProjection(
                name=team.name,
                flag=team.flag,
                manager=participant.name,
                status=status,
                title_probability=0.0,
                fifa_rank=fifa_rank,
                title_breakdown=title_breakdown,
            )
            team_entries.append(projection)
            raw_title_scores.append((projection, title_score))

    total_title_score = sum(score for _, score in raw_title_scores)
    title_probability_scale = (100 / total_title_score) if total_title_score else 0.0
    for projection, title_score in raw_title_scores:
        projection.title_probability = round(title_score * title_probability_scale, 1)

    manager_entries: list[ManagerProjection] = []
    for participant in squads.participants:
        participant_teams = [team for team in team_entries if team.manager == participant.name]
        favourite = max(participant_teams, key=lambda team: team.title_probability) if participant_teams else None
        manager_entries.append(
            ManagerProjection(
                name=participant.name,
                title_probability=round(sum(team.title_probability for team in participant_teams), 1),
                expected_teams_next_stage=0.0,
                favourite_team=favourite.name if favourite else None,
            )
        )

    manager_entries.sort(key=lambda manager: manager.title_probability, reverse=True)
    team_entries.sort(key=lambda team: team.title_probability, reverse=True)
    return ProjectionsOutput(managers=manager_entries, teams=team_entries)


def build_participant_stats(
    squads: Squads,
    team_records: dict[str, TeamRecord],
    advancement: dict[str, str] | None = None,
) -> list[ParticipantStats]:
    """Compute per-participant standings by combining squad data with team records.

    Teams not present in team_records are treated as having played no matches
    and receive "in" status. Results are sorted safest-first: fewest eliminated,
    then fewest at-risk, then fewest losses, then most wins.

    Args:
        squads: Parsed squads.json containing each participant's drafted teams.
        team_records: Output of compute_team_records.
        advancement: Output of compute_advancement, mapping team name to its
            knockout-round outlook. Drives the "out" verdict so a team is only
            eliminated when it truly cannot advance.

    Returns:
        List of ParticipantStats sorted from safest to most-at-risk participant.
    """
    stats = []
    for p in squads.participants:
        teams_out: list[TeamResult] = []
        eliminated = at_risk = w = d = l = 0

        for t in p.teams:
            rec = team_records.get(t.name, TeamRecord())
            status = team_status(rec, (advancement or {}).get(t.name))
            teams_out.append(TeamResult(name=t.name, flag=t.flag, status=status, last_result=rec.last_result, form=rec.form))
            if status == "out":
                eliminated += 1
            elif status == "at_risk":
                at_risk += 1
            w += rec.w
            d += rec.d
            l += rec.l

        teams_remaining = sum(1 for t in teams_out if t.status != "out")
        stats.append(ParticipantStats(
            name=p.name,
            teams=teams_out,
            eliminated=eliminated,
            at_risk=at_risk,
            teams_remaining=teams_remaining,
            teams_total=len(p.teams),
            record=Record(w=w, d=d, l=l),
        ))

    stats.sort(key=lambda p: (p.eliminated, p.at_risk, p.record.l, -p.record.w))
    return stats


_HISTORY_TOP_N = 48  # store all teams so the bump chart can show any team at any zoom level

_KNOCKOUT_ROUND_LABELS: dict[str, str] = {
    "LAST_32":        "R32",
    "LAST_16":        "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS":    "SF",
    "THIRD_PLACE":    "3rd Place",
    "FINAL":          "Final",
}
_KNOCKOUT_STAGE_ORDER = tuple(_KNOCKOUT_ROUND_LABELS)


def deepest_finished_stage(matches: list[dict]) -> str:
    """Return the deepest knockout stage with a finished match, else group stage."""
    finished_knockout_stages = {
        m.get("stage")
        for m in matches
        if m.get("stage") in _KNOCKOUT_STAGE_ORDER and m.get("status") == "FINISHED"
    }
    for stage in reversed(_KNOCKOUT_STAGE_ORDER):
        if stage in finished_knockout_stages:
            return stage
    return "GROUP_STAGE"


def _round_label(stage: str, matchday: int | None) -> str:
    """Return a short round label for the x-axis of the bump chart."""
    if stage in _KNOCKOUT_ROUND_LABELS:
        return _KNOCKOUT_ROUND_LABELS[stage]
    return f"MD{matchday}" if matchday else "MD?"


def _sticky_delta(
    new_prob: float, old_prob: float | None, prev_delta: float | None
) -> float | None:
    """Return the sticky trend for a manager/team's title score.

    Keeps the latest run where the score actually moved: a non-zero rounded
    change becomes the new trend, otherwise the previous trend carries forward
    so each entity always shows its latest change rather than resetting to zero
    on quiet days. A change that rounds to 0.0 counts as no movement.

    Args:
        new_prob: Current title-strength score.
        old_prob: Previous score, or None when the entity is newly tracked.
        prev_delta: Trend stored on the previous run.

    Returns:
        The fresh rounded change when the score moved, else the carried-forward
        trend (which may be None).
    """
    change = round(new_prob - old_prob, 1) if old_prob is not None else None
    return change if change else prev_delta


def _write_history(data_dir: Path, current_stats: dict, matchday: int | None = None, team_records: dict | None = None) -> None:
    """Append team-ranking snapshot to data/history.json when title scores change.

    Reads the existing history.json (committed in git, persists across CI runs),
    then appends a new entry only when the top-team score vector differs from the
    last recorded entry. One entry per calendar day maximum. Stores the top
    _HISTORY_TOP_N teams so the bump chart can track teams that rise into the
    visible top-10 from just outside it.
    """
    def _teams_from(data: dict) -> list[dict] | None:
        teams = data.get("projections", {}).get("teams", [])
        if not teams:
            return None
        ranked = sorted(teams, key=lambda t: t.get("title_probability", 0), reverse=True)
        return [
            {
                "name": t["name"],
                "flag": t.get("flag", ""),
                "manager": t.get("manager", ""),
                "rank": i + 1,
                "score": t.get("title_probability", 0),
                "status": t.get("status", "in"),
                "stage": team_records[t["name"]].current_stage if team_records and t["name"] in team_records else None,
            }
            for i, t in enumerate(ranked[:_HISTORY_TOP_N])
        ]

    def _score_key(teams: list[dict]) -> tuple:
        return tuple((t["name"], t["score"]) for t in sorted(teams, key=lambda t: t["name"]))

    history_file = data_dir / "history.json"
    existing: list[dict] = []
    if history_file.exists():
        try:
            existing = json.loads(history_file.read_text()).get("snapshots", [])
        except Exception:
            existing = []

    teams = _teams_from(current_stats)
    if not teams:
        return

    stage = current_stats.get("stage", "GROUP_STAGE")
    new_key = _score_key(teams)
    ts = current_stats.get("generated_at", "")
    today = ts[:10]  # YYYY-MM-DD

    # Replace any existing entry for today; otherwise check if scores changed
    same_day_idx = next((i for i, e in enumerate(existing) if e["ts"][:10] == today), None)
    if same_day_idx is not None:
        old = existing[same_day_idx]
        new_round = _round_label(stage, matchday)
        if _score_key(old["teams"]) == new_key and old.get("stage") == stage:
            return  # same day, same scores, same stage — nothing to do
        existing[same_day_idx] = {"ts": ts, "stage": stage, "round": new_round, "teams": teams}
    else:
        if existing and _score_key(existing[-1]["teams"]) == new_key:
            return  # scores unchanged from last day — skip
        label = _round_label(stage, matchday)
        existing.append({"ts": ts, "stage": stage, "round": label, "teams": teams})

    history_file.write_text(json.dumps({"snapshots": existing}, indent=2))
    logger.info("history.json updated with %d snapshots", len(existing))


class WCFetcher:
    """Orchestrates fetching match data, computing standings, and writing stats.json."""

    def __init__(self, config: Config, data_dir: Path | None = None) -> None:
        """Initialise the fetcher with credentials and optional data directory override.

        Args:
            config: Application config containing API keys and competition ID.
            data_dir: Directory to read squads.json from and write stats.json to.
                Defaults to the ``data/`` directory at the project root.
        """
        self.config = config
        self._data_dir = data_dir or Path(__file__).parents[3] / "data"
        self._squads_file = self._data_dir / "squads.json"
        self._stats_file = self._data_dir / "stats.json"
        model = AnthropicModel(
            "claude-sonnet-4-6",
            provider=AnthropicProvider(api_key=config.anthropic_api_key.get_secret_value()),
        )
        self._agent: Agent[None, SummaryOutput] = Agent(
            model,
            output_type=SummaryOutput,
            instructions=_AGENT_INSTRUCTIONS,
        )

    def _fetch_matches(self) -> list[dict]:
        """Fetch all matches for the configured competition from football-data.org.

        Returns:
            List of raw match dicts from the API.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx response.
        """
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{FOOTBALL_API_BASE}/competitions/{self.config.competition_id}/matches",
                headers={"X-Auth-Token": self.config.football_data_api_key.get_secret_value()},
            )
            resp.raise_for_status()
        return resp.json()["matches"]

    def _generate_summary(self, participant_stats: list[ParticipantStats], upcoming: list[dict], projections: ProjectionsOutput | None = None) -> SummaryOutput:
        """Generate a headline and 2-paragraph AI briefing for the current sweep standings."""
        strength_by_name = {m.name: m.title_probability for m in projections.managers} if projections else {}
        leaderboard_text = "\n".join(
            f"{'💀' if i == len(participant_stats) - 1 else i + 1}. {p.name}: "
            + (f"{strength_by_name[p.name]:.1f}% strength, " if p.name in strength_by_name else "")
            + f"{p.teams_remaining}/12 alive, {p.eliminated} out, {p.at_risk} at risk, "
            f"{p.record.w}W-{p.record.d}D-{p.record.l}L"
            for i, p in enumerate(participant_stats)
        )

        if upcoming:
            lines = []
            for m in upcoming[:12]:
                utc = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
                aest = utc.astimezone(AEST)
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                lines.append(f"  {home} vs {away} — {aest.strftime('%a %-d %b, %-I:%M%p AEST')}")
            upcoming_text = "\n".join(lines)
        else:
            upcoming_text = "  No upcoming matches scheduled"

        team_to_owner = {t.name: p.name for p in participant_stats for t in p.teams}

        prompt = f"""Standings (sorted by survival, strength % = title probability index):
            {leaderboard_text}
            Upcoming matches:
            {upcoming_text}

            Team ownership (for reference):
            {json.dumps(team_to_owner, ensure_ascii=False)}

            Write the headline and 2-paragraph briefing now.
            Each paragraph must be 130 words or fewer.
        """

        result = self._agent.run_sync(prompt)
        output = result.output
        output.paragraphs = _enforce_summary_length(output.paragraphs)
        return output

    def run(self) -> None:
        """Fetch match data, compute standings, generate a summary, and write stats.json.

        Reads squads.json from the configured data directory, fetches live match
        data from football-data.org, calls the AI summary agent, then writes the
        combined output to stats.json in the same directory.
        """
        self._data_dir.mkdir(exist_ok=True)
        squads = Squads.model_validate_json(self._squads_file.read_text())

        logger.info("Fetching match data…")
        matches = self._fetch_matches()

        logger.info("Fetching FIFA rankings…")
        try:
            rankings = fetch_fifa_rankings()
        except Exception as exc:
            logger.warning("Could not fetch FIFA rankings, proceeding without them: %s", exc)
            rankings = None

        stage = deepest_finished_stage(matches)

        finished_gs_matchdays = [
            m.get("matchday")
            for m in matches
            if m.get("status") == "FINISHED"
            and m.get("stage") not in set(_KNOCKOUT_ROUND_LABELS)
            and m.get("matchday") is not None
        ]
        current_matchday = max(finished_gs_matchdays) if finished_gs_matchdays else None

        team_records = compute_team_records(matches)
        advancement = compute_advancement(matches)
        participant_stats = build_participant_stats(squads, team_records, advancement=advancement)

        upcoming = sorted(
            [m for m in matches if m["status"] in ("SCHEDULED", "TIMED")],
            key=lambda m: m["utcDate"],
        )

        projections = build_projections(squads, team_records, rankings=rankings, advancement=advancement)

        logger.info("Generating summary…")
        summary_output = self._generate_summary(participant_stats, upcoming, projections=projections)

        now = datetime.now(AEST)
        output = StatsOutput(
            generated_at=now.isoformat(),
            stage=stage,
            headline=summary_output.headline,
            summary=summary_output.paragraphs,
            leaderboard=[
                LeaderboardEntry(
                    name=p.name,
                    teams_remaining=p.teams_remaining,
                    teams_total=p.teams_total,
                    eliminated=p.eliminated,
                    at_risk=p.at_risk,
                    record=p.record,
                )
                for p in participant_stats
            ],
            squads={p.name: p.teams for p in participant_stats},
            recent_results=build_recent_results(matches, squads),
            projections=projections,
        )

        def _strip_volatile(obj: object) -> object:
            """Recursively remove fields that vary every run or are derived state."""
            if isinstance(obj, dict):
                return {k: _strip_volatile(v) for k, v in obj.items()
                        if k not in {"generated_at", "headline", "summary", "delta"}}
            if isinstance(obj, list):
                return [_strip_volatile(i) for i in obj]
            return obj

        snapshots_dir = self._data_dir / "snapshots"

        if self._stats_file.exists():
            current_json = self._stats_file.read_text()
            # Validate the previous file the moment it is read — everything below
            # (snapshot filename included) works off typed `prev`, never a raw
            # dict, and no snapshot is written from unvalidated data.
            prev = StatsOutput.model_validate_json(current_json)
            current_data = json.loads(current_json)
            new_data = json.loads(output.model_dump_json(by_alias=True))

            # Save a snapshot whenever any non-volatile data changes (form, results, etc.)
            if _strip_volatile(current_data) != _strip_volatile(new_data):
                snapshots_dir.mkdir(exist_ok=True)
                snapshot_date = (prev.generated_at or "")[:10] or now.strftime("%Y-%m-%d")
                (snapshots_dir / f"{snapshot_date}.json").write_text(current_json)

            # Sticky trend: every manager and team carries its most recent *non-zero*
            # change in title score, persisted in stats.json so the trend survives day
            # to day. Recompute a delta only when the score actually moves; otherwise
            # carry the previous delta forward so each entity always shows its latest
            # change instead of being reset to zero on days it didn't move.
            prev_mgr = {m.name: m for m in prev.projections.managers}
            prev_team = {t.name: t for t in prev.projections.teams}

            for m in output.projections.managers:
                old = prev_mgr.get(m.name)
                m.delta = _sticky_delta(
                    m.title_probability,
                    old.title_probability if old else None,
                    old.delta if old else None,
                )
            for t in output.projections.teams:
                old = prev_team.get(t.name)
                t.delta = _sticky_delta(
                    t.title_probability,
                    old.title_probability if old else None,
                    old.delta if old else None,
                )

        self._stats_file.write_text(output.model_dump_json(indent=2, by_alias=True))
        logger.info("stats.json updated at %s", now.strftime("%Y-%m-%d %H:%M:%S %Z"))

        _write_history(self._data_dir, output.model_dump(by_alias=True), matchday=current_matchday, team_records=team_records)
