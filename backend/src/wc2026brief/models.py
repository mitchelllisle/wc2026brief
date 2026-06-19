from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Team(BaseModel):
    name: str
    flag: str


class FormEntry(BaseModel):
    result: str       # "W" | "D" | "L"
    opponent: str
    score: str        # e.g. "2–1"


class TeamRecord(BaseModel):
    w: int = 0
    d: int = 0
    l: int = 0
    played: int = 0
    points: int = 0
    gf: int = 0
    ga: int = 0
    last_result: str | None = None
    form: list[FormEntry] = []
    knocked_out: bool = False
    current_stage: str = "GROUP_STAGE"


class TeamResult(BaseModel):
    name: str
    flag: str
    status: str  # "in" | "at_risk" | "out"
    last_result: str | None = None
    form: list[FormEntry] = []


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


class TitleStrengthBreakdown(BaseModel):
    form_score: float   # 0–1, based on tournament results
    stage_score: float  # 0–1, how far the team has progressed
    rank_score: float   # 0–1, FIFA world ranking quality
    stage_label: str
    form_weight: float  # decays from 0.50 → 0.70 by tournament round
    rank_weight: float  # decays from 0.20 → 0.00 by tournament round


class TeamProjection(BaseModel):
    name: str
    flag: str
    manager: str
    status: str
    title_probability: float
    fifa_rank: int | None = None
    title_breakdown: TitleStrengthBreakdown | None = None


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
    stage: str  # "GROUP_STAGE" | "KNOCKOUT"
    headline: str
    summary: list[str]
    leaderboard: list[LeaderboardEntry]
    squads: dict[str, list[TeamResult]]
    recent_results: list[RecentResult]
    projections: ProjectionsOutput


class SummaryOutput(BaseModel):
    headline: str
    paragraphs: list[str]
