from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Team(BaseModel):
    name: str
    flag: str


class TeamRecord(BaseModel):
    w: int = 0
    d: int = 0
    l: int = 0
    played: int = 0
    points: int = 0
    gf: int = 0
    ga: int = 0
    last_result: str | None = None
    knocked_out: bool = False
    current_stage: str = "GROUP_STAGE"


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


class TeamProjection(BaseModel):
    name: str
    flag: str
    manager: str
    status: str
    next_stage_probability: float
    title_probability: float


class ManagerProjection(BaseModel):
    name: str
    title_probability: float
    expected_teams_next_stage: float
    favourite_team: str | None = None


class ProjectionsOutput(BaseModel):
    managers: list[ManagerProjection]
    teams: list[TeamProjection]


class StatsOutput(BaseModel):
    generated_at: str
    summary: list[str]
    leaderboard: list[LeaderboardEntry]
    squads: dict[str, list[TeamResult]]
    recent_results: list[RecentResult]
    projections: ProjectionsOutput


class SummaryOutput(BaseModel):
    paragraphs: list[str]
