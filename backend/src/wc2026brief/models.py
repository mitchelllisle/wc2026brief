from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Team(BaseModel):
    name: str
    flag: str


class TeamRecord(BaseModel):
    w: int = 0
    d: int = 0
    l: int = 0
    last_result: str | None = None
    knocked_out: bool = False


class TeamResult(BaseModel):
    name: str
    flag: str
    status: str  # "in" | "at_risk" | "out"
    last_result: str | None = None


class Record(BaseModel):
    w: int
    d: int
    l: int


class Participant(BaseModel):
    name: str
    teams: list[Team]


class Squads(BaseModel):
    participants: list[Participant]


class ParticipantStats(BaseModel):
    name: str
    teams: list[TeamResult]
    eliminated: int
    at_risk: int
    teams_remaining: int
    teams_total: int
    record: Record


class LeaderboardEntry(BaseModel):
    name: str
    teams_remaining: int
    teams_total: int
    eliminated: int
    at_risk: int
    record: Record


class RecentResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    h_code: str
    h_flag: str
    hs: int
    a_code: str
    a_flag: str
    as_: int = Field(alias="as")
    group: str


class UpcomingMatch(BaseModel):
    home_team: str
    away_team: str
    home_manager: str
    away_manager: str


class StatsOutput(BaseModel):
    generated_at: str
    summary: list[str]
    leaderboard: list[LeaderboardEntry]
    squads: dict[str, list[TeamResult]]
    recent_results: list[RecentResult]
    upcoming_matches: list[UpcomingMatch]


class SummaryOutput(BaseModel):
    paragraphs: list[str]
