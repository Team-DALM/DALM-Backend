from uuid import UUID, uuid4

import pytest

from app.match_ranking import (
    FeatureScores,
    MatchCandidate,
    MatchWeights,
    rank_candidates,
    select_best_candidate,
)


def scores(value: float, *, scene=None, semantic=None) -> FeatureScores:
    return FeatureScores(
        scene=value if scene is None else scene,
        semantic=value if semantic is None else semantic,
        objects=value,
        composition=value,
        color=value,
        mood=value,
    )


def test_rank_candidates_applies_hard_floors_and_weighted_score():
    accepted = MatchCandidate(uuid4(), scores(0.8))
    weak_scene = MatchCandidate(uuid4(), scores(0.9, scene=0.2))
    weak_semantic = MatchCandidate(uuid4(), scores(0.9, semantic=0.2))

    ranked = rank_candidates([weak_scene, accepted, weak_semantic])

    assert [item.photo_id for item in ranked] == [accepted.photo_id]
    assert ranked[0].final_score == 0.8


def test_ranking_is_deterministic_when_scores_are_equal():
    low_id = UUID("00000000-0000-0000-0000-000000000001")
    high_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    candidates = [MatchCandidate(high_id, scores(0.8)), MatchCandidate(low_id, scores(0.8))]

    ranked = rank_candidates(candidates)

    assert [item.photo_id for item in ranked] == [low_id, high_id]


def test_select_best_candidate_returns_none_below_threshold():
    assert select_best_candidate([MatchCandidate(uuid4(), scores(0.6))]) is None


def test_scores_and_weights_validate_configuration():
    with pytest.raises(ValueError, match="between 0 and 1"):
        scores(1.1)
    with pytest.raises(ValueError, match="sum to 1"):
        MatchWeights(scene=0.5)
