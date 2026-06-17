from wc2026brief.fetcher import (
    _enforce_summary_length,
    _limit_words,
    build_participant_stats,
    build_recent_results,
    build_upcoming_matches,
    compute_team_records,
    team_status,
)
from wc2026brief.models import Participant, Squads, Team, TeamRecord


def test_team_status_in():
    assert team_status(TeamRecord(w=2, d=1, l=0)) == "in"


def test_team_status_risk():
    assert team_status(TeamRecord(w=1, d=0, l=1)) == "at_risk"


def test_team_status_out_two_losses():
    assert team_status(TeamRecord(w=0, d=0, l=2)) == "out"


def test_team_status_out_knocked_out():
    assert team_status(TeamRecord(w=2, d=0, l=1, knocked_out=True)) == "out"


def _match(home: str, away: str, hs: int, as_: int, stage: str = "GROUP_STAGE", status: str = "FINISHED") -> dict:
    return {
        "utcDate": "2026-06-15T12:00:00Z",
        "status": status,
        "stage": stage,
        "group": "GROUP_C",
        "homeTeam": {"name": home, "tla": home[:3].upper()},
        "awayTeam": {"name": away, "tla": away[:3].upper()},
        "score": {"fullTime": {"home": hs, "away": as_}},
    }


def test_compute_team_records_win_loss():
    records = compute_team_records([_match("Brazil", "Argentina", 2, 0)])
    assert records["Brazil"].w == 1
    assert records["Brazil"].l == 0
    assert records["Argentina"].l == 1
    assert records["Argentina"].w == 0
    assert records["Brazil"].last_result == "W"
    assert records["Argentina"].last_result == "L"


def test_compute_team_records_draw():
    records = compute_team_records([_match("France", "Germany", 1, 1)])
    assert records["France"].d == 1
    assert records["Germany"].d == 1
    assert records["France"].last_result == "D"


def test_compute_team_records_knockout_loss_sets_knocked_out():
    records = compute_team_records([_match("Spain", "England", 0, 1, stage="ROUND_OF_16")])
    assert records["Spain"].knocked_out is True
    assert records["England"].knocked_out is False


def test_compute_team_records_skips_unfinished():
    records = compute_team_records([_match("Brazil", "Argentina", 0, 0, status="SCHEDULED")])
    assert records == {}


def test_compute_team_records_uses_api_names_directly():
    records = compute_team_records([_match("USA", "Korea Republic", 1, 0)])
    assert "USA" in records
    assert "Korea Republic" in records


def test_compute_team_records_multiple_matches_accumulate():
    records = compute_team_records([
        _match("Brazil", "Argentina", 2, 0),
        _match("Brazil", "France", 1, 2),
    ])
    assert records["Brazil"].w == 1
    assert records["Brazil"].l == 1
    assert records["Brazil"].last_result == "L"


def _squads(*participants: tuple[str, list[tuple[str, str]]]) -> Squads:
    return Squads(participants=[
        Participant(name=name, teams=[Team(name=t, flag=f) for t, f in teams])
        for name, teams in participants
    ])


def test_build_participant_stats_basic():
    squads = _squads(
        ("Alice", [("Brazil", "🇧🇷"), ("France", "🇫🇷")]),
        ("Bob", [("Germany", "🇩🇪")]),
    )
    team_records = {
        "Brazil": TeamRecord(w=1, d=0, l=1),   # at risk
        "France": TeamRecord(w=2, d=0, l=0),   # in
        "Germany": TeamRecord(w=0, d=0, l=2),  # out
    }
    stats = build_participant_stats(squads, team_records)

    alice = next(p for p in stats if p.name == "Alice")
    bob = next(p for p in stats if p.name == "Bob")

    assert alice.teams_remaining == 2  # Brazil (risk) and France (in) both not out
    assert alice.eliminated == 0
    assert alice.at_risk == 1
    assert alice.record.w == 3
    assert alice.record.l == 1

    assert bob.eliminated == 1
    assert bob.teams_remaining == 0
    assert bob.record.l == 2


def test_build_participant_stats_unknown_team_defaults_to_in():
    squads = _squads(("Alice", [("Brazil", "🇧🇷")]))
    stats = build_participant_stats(squads, {})
    assert stats[0].teams[0].status == "in"
    assert stats[0].teams_remaining == 1


def test_build_participant_stats_sort_order():
    squads = _squads(
        ("Danger", [("A", "🅰️"), ("B", "🅱️")]),   # 2 losses = out
        ("Safe", [("C", "🇨🇦")]),                   # no losses
    )
    team_records = {
        "A": TeamRecord(l=2),
        "B": TeamRecord(l=2),
        "C": TeamRecord(w=3),
    }
    stats = build_participant_stats(squads, team_records)
    assert stats[0].name == "Safe"
    assert stats[-1].name == "Danger"


def test_build_recent_results_newest_first_and_group_format():
    squads = _squads(("Alice", [("Brazil", "🇧🇷"), ("Argentina", "🇦🇷")]))
    older = _match("Brazil", "Argentina", 1, 0)
    newer = _match("Argentina", "Brazil", 2, 2)
    older["utcDate"] = "2026-06-14T12:00:00Z"
    newer["utcDate"] = "2026-06-15T12:00:00Z"

    out = build_recent_results([older, newer], squads)
    assert len(out) == 2
    assert out[0].h_code == "ARG"
    assert out[0].h_flag == "🇦🇷"
    assert out[0].group == "GRP C"
    assert out[0].as_ == 2


def test_build_recent_results_skips_unfinished_and_handles_missing_scores():
    squads = _squads(("Alice", [("Brazil", "🇧🇷"), ("Argentina", "🇦🇷")]))
    scheduled = _match("Brazil", "Argentina", 0, 0, status="SCHEDULED")
    null_score = _match("Brazil", "Argentina", 0, 0)
    null_score["score"] = {"fullTime": {"home": None, "away": None}}

    out = build_recent_results([scheduled, null_score], squads)
    assert out == []


def test_build_upcoming_matches_sorted_and_with_owners():
    squads = _squads(
        ("Jay", [("Brazil", "🇧🇷")]),
        ("Mitchell", [("Argentina", "🇦🇷")]),
    )
    timed = _match("Argentina", "Brazil", 0, 0, status="TIMED")
    scheduled = _match("Brazil", "Argentina", 0, 0, status="SCHEDULED")
    timed["utcDate"] = "2026-06-15T12:00:00Z"
    scheduled["utcDate"] = "2026-06-16T12:00:00Z"

    out = build_upcoming_matches([scheduled, timed], squads)
    assert len(out) == 2
    assert out[0].home_team == "Argentina"
    assert out[0].away_team == "Brazil"
    assert out[0].home_manager == "Mitchell"
    assert out[0].away_manager == "Jay"


def test_build_upcoming_matches_skips_non_upcoming_status():
    squads = _squads(("Jay", [("Brazil", "🇧🇷"), ("Argentina", "🇦🇷")]))
    finished = _match("Argentina", "Brazil", 1, 1, status="FINISHED")

    out = build_upcoming_matches([finished], squads)
    assert out == []


def test_limit_words_truncates_to_130_words():
    text = " ".join([f"w{i}" for i in range(150)])
    limited = _limit_words(text, 130)
    assert len(limited.split()) == 130
    assert limited.endswith("…")


def test_enforce_summary_length_caps_each_paragraph_independently():
    short = "one two three"
    long = " ".join([f"w{i}" for i in range(200)])
    out = _enforce_summary_length([short, long])
    assert out[0] == short
    assert len(out[1].split()) == 130
