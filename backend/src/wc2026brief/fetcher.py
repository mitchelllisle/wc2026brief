import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from wc2026brief.config import Config
from wc2026brief.models import (
    LeaderboardEntry,
    ParticipantStats,
    RecentResult,
    Record,
    Squads,
    StatsOutput,
    SummaryOutput,
    TeamRecord,
    TeamResult,
)

logger = logging.getLogger(__name__)

AEST = ZoneInfo("Australia/Sydney")
FOOTBALL_API_BASE = "https://api.football-data.org/v4"
MAX_RECENT_RESULTS = 24
MAX_SUMMARY_WORDS = 130

_AGENT_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "agent_instructions.md").read_text()


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
        stage = match.get("stage", "")
        is_knockout = stage not in ("GROUP_STAGE", "")

        for team, is_home in [(home, True), (away, False)]:
            rec = records.setdefault(team, TeamRecord())
            score_for = hs if is_home else as_
            score_against = as_ if is_home else hs

            if score_for > score_against:
                rec.w += 1
                rec.last_result = "W"
            elif score_for == score_against:
                rec.d += 1
                rec.last_result = "D"
            else:
                rec.l += 1
                rec.last_result = "L"
                if is_knockout:
                    rec.knocked_out = True

    return records


def team_status(rec: TeamRecord) -> str:
    """Derive a sweep status string from a team's match record.

    Group stage: 0 losses → "in", 1 loss → "at_risk", 2+ losses → "out".
    Knockout: any loss sets knocked_out, which immediately → "out".

    Args:
        rec: Accumulated win/draw/loss record for a single team.

    Returns:
        One of "in", "at_risk", or "out".
    """
    if rec.knocked_out or rec.l >= 2:
        return "out"
    if rec.l == 1:
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


def build_participant_stats(squads: Squads, team_records: dict[str, TeamRecord]) -> list[ParticipantStats]:
    """Compute per-participant standings by combining squad data with team records.

    Teams not present in team_records are treated as having played no matches
    and receive "in" status. Results are sorted safest-first: fewest eliminated,
    then fewest at-risk, then fewest losses, then most wins.

    Args:
        squads: Parsed squads.json containing each participant's drafted teams.
        team_records: Output of compute_team_records.

    Returns:
        List of ParticipantStats sorted from safest to most-at-risk participant.
    """
    stats = []
    for p in squads.participants:
        teams_out: list[TeamResult] = []
        eliminated = at_risk = w = d = l = 0

        for t in p.teams:
            rec = team_records.get(t.name, TeamRecord())
            status = team_status(rec)
            teams_out.append(TeamResult(name=t.name, flag=t.flag, status=status, last_result=rec.last_result))
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

    def _generate_summary(self, participant_stats: list[ParticipantStats], upcoming: list[dict]) -> list[str]:
        """Generate a 2-paragraph AI briefing for the current sweep standings.

        Args:
            participant_stats: Sorted participant standings from build_participant_stats.
            upcoming: List of scheduled/timed match dicts to preview (up to 12 used).

        Returns:
            List of paragraph strings as produced by the summary agent.
        """
        leaderboard_text = "\n".join(
            f"{'💀' if i == len(participant_stats) - 1 else i + 1}. {p.name}: "
            f"{p.teams_remaining}/12 alive, {p.eliminated} out, {p.at_risk} at risk, "
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

        prompt = f"""Standings:
            {leaderboard_text}

            Upcoming matches:
            {upcoming_text}

            Team ownership (for reference):
            {json.dumps(team_to_owner, ensure_ascii=False)}

            Write the 2-paragraph briefing now.
            Each paragraph must be 130 words or fewer.
        """

        result = self._agent.run_sync(prompt)
        return _enforce_summary_length(result.output.paragraphs)

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

        team_records = compute_team_records(matches)
        participant_stats = build_participant_stats(squads, team_records)

        upcoming = sorted(
            [m for m in matches if m["status"] in ("SCHEDULED", "TIMED")],
            key=lambda m: m["utcDate"],
        )

        logger.info("Generating summary…")
        summary = self._generate_summary(participant_stats, upcoming)

        now = datetime.now(AEST)
        output = StatsOutput(
            generated_at=now.isoformat(),
            summary=summary,
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
        )

        self._stats_file.write_text(output.model_dump_json(indent=2, by_alias=True))
        logger.info("stats.json updated at %s", now.strftime("%Y-%m-%d %H:%M:%S %Z"))
