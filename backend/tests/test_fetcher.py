from wc2026brief.fetcher import (
    _enforce_summary_length,
    _limit_words,
    _sticky_delta,
    build_participant_stats,
    build_projections,
    build_recent_results,
    compute_team_records,
    team_status,
)
from wc2026brief.models import Participant, Squads, Team, TeamRecord
from hypothesis import given, strategies as st


def test_team_status_in():
    assert team_status(TeamRecord(w=2, d=1, l=0)) == "in"


def test_team_status_risk():
    assert team_status(TeamRecord(w=1, d=0, l=1)) == "at_risk"


def test_team_status_out_two_losses():
    assert team_status(TeamRecord(w=0, d=0, l=2)) == "out"


def test_team_status_out_knocked_out():
    assert team_status(TeamRecord(w=2, d=0, l=1, knocked_out=True)) == "out"


def test_team_status_knockout_survivor_is_in():
    assert team_status(TeamRecord(w=2, d=0, l=1, played=4, current_stage="ROUND_OF_16")) == "in"


def _match(home: str, away: str, hs: int, as_: int, stage: str = "GROUP_STAGE", status: str = "FINISHED") -> dict:
    return {
        "utcDate": "2026-06-15T12:00:00Z",
        "status": status,
        "stage": stage,
        "group": "GROUP_C",
        "homeTeam": {"name": home, "tla": home[:3].upper()},
        "awayTeam": {"name": away, "tla": away[:3].upper()},
        "score": {"fullTime": {"home": hs, "away": as_}, "winner": "HOME_TEAM" if hs > as_ else "AWAY_TEAM" if as_ > hs else "DRAW"},
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
    assert records["France"].points == 1
    assert records["France"].played == 1


def test_compute_team_records_knockout_loss_sets_knocked_out():
    records = compute_team_records([_match("Spain", "England", 0, 1, stage="ROUND_OF_16")])
    assert records["Spain"].knocked_out is True
    assert records["England"].knocked_out is False
    assert records["England"].current_stage == "ROUND_OF_16"


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


def test_build_projections_rolls_up_manager_odds():
    squads = _squads(
        ("Jay", [("Spain", "🇪🇸"), ("Brazil", "🇧🇷")]),
        ("Ryan", [("Germany", "🇩🇪")]),
    )
    team_records = {
        "Spain": TeamRecord(played=1, points=3, w=1, gf=2, ga=0),
        "Brazil": TeamRecord(played=1, points=1, d=1, gf=1, ga=1),
        "Germany": TeamRecord(played=1, points=0, l=1, gf=0, ga=1),
    }

    projections = build_projections(squads, team_records)

    assert projections.managers[0].name == "Jay"
    assert projections.teams[0].name == "Spain"
    assert abs(sum(manager.title_probability for manager in projections.managers) - 100.0) < 0.2


def test_build_projections_zeroes_title_odds_when_everyone_is_out():
    squads = _squads(("Jay", [("Spain", "🇪🇸")]), ("Ryan", [("Germany", "🇩🇪")]))
    team_records = {
        "Spain": TeamRecord(l=2, played=2, current_stage="GROUP_STAGE"),
        "Germany": TeamRecord(l=2, played=2, current_stage="GROUP_STAGE"),
    }

    projections = build_projections(squads, team_records)

    assert all(manager.title_probability == 0.0 for manager in projections.managers)
    assert all(team.title_probability == 0.0 for team in projections.teams)


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


def test_sticky_delta_fresh_change_on_movement():
    # Score moved up by 0.3 -> trend reflects the fresh change, ignoring old trend.
    assert _sticky_delta(3.4, 3.1, -0.2) == 0.3


def test_sticky_delta_carries_forward_when_unchanged():
    # Score unchanged -> keep the previous trend so it survives quiet days.
    assert _sticky_delta(3.4, 3.4, -0.2) == -0.2


def test_sticky_delta_tiny_change_rounds_to_zero_carries_forward():
    # Change rounds to 0.0 -> treated as no movement, previous trend retained.
    assert _sticky_delta(3.43, 3.40, 0.5) == 0.5


def test_sticky_delta_no_prior_score_and_no_prior_trend_is_none():
    # Brand-new entity with no history -> no trend yet.
    assert _sticky_delta(2.0, None, None) is None


def test_sticky_delta_no_prior_score_keeps_existing_trend():
    # No comparable prior score but a stored trend exists -> keep it.
    assert _sticky_delta(2.0, None, 0.4) == 0.4


def test_sticky_delta_negative_movement():
    assert _sticky_delta(0.0, 1.7, 0.1) == -1.7


@given(
    new=st.floats(min_value=0, max_value=100),
    old=st.floats(min_value=0, max_value=100),
    prev=st.one_of(st.none(), st.floats(min_value=-100, max_value=100)),
)
def test_sticky_delta_carries_forward_iff_no_movement(new, old, prev):
    result = _sticky_delta(new, old, prev)
    if round(new - old, 1):
        assert result == round(new - old, 1)  # moved -> fresh change
    else:
        assert result == prev  # quiet day -> previous trend carried forward
