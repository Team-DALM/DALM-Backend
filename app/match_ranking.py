from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FeatureScores:
    scene: float
    semantic: float
    objects: float
    composition: float
    color: float
    mood: float

    def __post_init__(self) -> None:
        if any(not 0 <= value <= 1 for value in self.values()):
            raise ValueError("feature scores must be between 0 and 1")

    def values(self) -> tuple[float, ...]:
        return (
            self.scene,
            self.semantic,
            self.objects,
            self.composition,
            self.color,
            self.mood,
        )


@dataclass(frozen=True, slots=True)
class MatchWeights:
    scene: float = 0.25
    semantic: float = 0.25
    objects: float = 0.15
    composition: float = 0.15
    color: float = 0.10
    mood: float = 0.10

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.values()):
            raise ValueError("match weights cannot be negative")
        if abs(sum(self.values()) - 1) > 1e-9:
            raise ValueError("match weights must sum to 1")

    def values(self) -> tuple[float, ...]:
        return (
            self.scene,
            self.semantic,
            self.objects,
            self.composition,
            self.color,
            self.mood,
        )


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    photo_id: UUID
    scores: FeatureScores


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    photo_id: UUID
    scores: FeatureScores
    final_score: float


def rank_candidates(
    candidates: list[MatchCandidate],
    *,
    weights: MatchWeights | None = None,
    scene_minimum: float = 0.45,
    semantic_minimum: float = 0.50,
    final_minimum: float = 0.65,
) -> list[RankedCandidate]:
    resolved_weights = weights or MatchWeights()
    thresholds = (scene_minimum, semantic_minimum, final_minimum)
    if any(not 0 <= value <= 1 for value in thresholds):
        raise ValueError("match thresholds must be between 0 and 1")

    ranked = []
    for candidate in candidates:
        if candidate.scores.scene < scene_minimum:
            continue
        if candidate.scores.semantic < semantic_minimum:
            continue
        final_score = sum(
            score * weight
            for score, weight in zip(
                candidate.scores.values(), resolved_weights.values(), strict=True
            )
        )
        if final_score >= final_minimum:
            ranked.append(
                RankedCandidate(
                    photo_id=candidate.photo_id,
                    scores=candidate.scores,
                    final_score=round(final_score, 6),
                )
            )
    return sorted(ranked, key=lambda item: (-item.final_score, str(item.photo_id)))


def select_best_candidate(
    candidates: list[MatchCandidate],
    **ranking_options,
) -> RankedCandidate | None:
    ranked = rank_candidates(candidates, **ranking_options)
    return ranked[0] if ranked else None
