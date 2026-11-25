""









from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("rq.missing_data")

CONFIG_PATH = Path(__file__).resolve().parent / "scoring-config-v3.json"


OBSERVED_STRONG = "OBSERVED_STRONG"
OBSERVED_WEAK = "OBSERVED_WEAK"
PARTIALLY_OBSERVED = "PARTIALLY_OBSERVED"
UNOBSERVED = "UNOBSERVED"


class MissingDataHandler:
    ""

    def __init__(self, config_path: Path | None = None):
        if config_path is None:
            config_path = CONFIG_PATH
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        self.signal_thresholds: dict = config.get("signal_thresholds", {})
        self.signal_to_dimension: dict[str, str] = config.get("signal_to_dimension", {})
        self.type_priors: dict[str, dict[str, float]] = config.get("type_priors", {})
        self.score_floors: dict[str, float] = config.get("score_floors", {})
        self.confidence_weights: dict[str, float] = config.get(
            "confidence_weights",
            {
                OBSERVED_STRONG: 1.0,
                OBSERVED_WEAK: 0.5,
                PARTIALLY_OBSERVED: 0.3,
                UNOBSERVED: 0.0,
            },
        )

    def classify_status(
        self,
        signal_name: str,
        value: float | int | bool | None,
        sample_count: int | None = None,
    ) -> str:
        ""










        thresholds = self.signal_thresholds.get(signal_name)


        if value is None:
            return UNOBSERVED


        if thresholds and sample_count is not None:
            if sample_count >= thresholds.get("strong", 10):
                return OBSERVED_STRONG
            if sample_count >= thresholds.get("weak", 2):
                return OBSERVED_WEAK
            if sample_count > 0:
                return OBSERVED_WEAK
            return UNOBSERVED


        if thresholds:
            default = thresholds.get("default")
            if default is not None and value == default:
                return UNOBSERVED


        if isinstance(value, bool):
            return OBSERVED_STRONG if value else UNOBSERVED


        if isinstance(value, int | float):
            import math

            if math.isnan(value):
                return UNOBSERVED
            return OBSERVED_STRONG

        return OBSERVED_STRONG

    def apply_prior(
        self,
        value: float | None,
        status: str,
        dimension: str,
        rel_type: str,
    ) -> float:
        ""






        prior = self.type_priors.get(rel_type, {}).get(dimension, 0.0)

        if status == OBSERVED_STRONG:
            return value if value is not None else prior
        if status == OBSERVED_WEAK:
            obs = value if value is not None else 0.0
            return 0.7 * obs + 0.3 * prior
        if status == PARTIALLY_OBSERVED:
            return value if value is not None else prior

        return prior

    def apply_floor(self, score: float, rel_type: str) -> float:
        ""



        floor = self.score_floors.get(rel_type)
        if floor is not None:
            return max(floor, score)
        return score

    def compute_confidence(self, statuses: dict[str, str]) -> float:
        ""



        if not statuses:
            return 0.0
        total_weight = sum(self.confidence_weights.get(status, 0.0) for status in statuses.values())
        return round(total_weight / len(statuses), 4)

    def classify_all_signals(
        self,
        signals: dict[str, float | int | bool | None],
    ) -> dict[str, str]:
        ""







        statuses: dict[str, str] = {}
        for signal_name in self.signal_to_dimension:
            value = signals.get(signal_name)
            statuses[signal_name] = self.classify_status(signal_name, value)
        return statuses

    def get_dimension_status(
        self,
        statuses: dict[str, str],
        dimension: str,
    ) -> str:
        ""






        dim_statuses = [
            status
            for sig, status in statuses.items()
            if self.signal_to_dimension.get(sig) == dimension
        ]
        if not dim_statuses:
            return UNOBSERVED
        if OBSERVED_STRONG in dim_statuses:
            return OBSERVED_STRONG
        if OBSERVED_WEAK in dim_statuses:
            return OBSERVED_WEAK
        if PARTIALLY_OBSERVED in dim_statuses:
            return PARTIALLY_OBSERVED
        return UNOBSERVED

    def process_person(
        self,
        signals: dict[str, float | int | bool | None],
        rel_type: str,
    ) -> dict:
        ""











        statuses = self.classify_all_signals(signals)


        dimensions = set(self.signal_to_dimension.values())
        dim_statuses: dict[str, str] = {}
        dim_adjustments: dict[str, float] = {}

        for dim in sorted(dimensions):
            dim_status = self.get_dimension_status(statuses, dim)
            dim_statuses[dim] = dim_status


            prior = self.type_priors.get(rel_type, {}).get(dim, 0.0)
            if dim_status == UNOBSERVED:
                dim_adjustments[dim] = prior
            else:
                dim_adjustments[dim] = 0.0


        confidence = self.compute_confidence(statuses)


        floor = self.score_floors.get(rel_type)

        return {
            "data_statuses": statuses,
            "dimension_statuses": dim_statuses,
            "dimension_adjustments": dim_adjustments,
            "confidence": confidence,
            "floor": floor,
        }
