from __future__ import annotations

import math


class MatryoshkaSearchService:
    STAGES = [
        {"dimensions": 64, "top_k_multiplier": 10},
        {"dimensions": 128, "top_k_multiplier": 5},
        {"dimensions": 256, "top_k_multiplier": 2},
    ]

    def truncate_embedding(self, embedding: list[float], dimensions: int) -> list[float]:
        truncated = embedding[:dimensions]
        norm = math.sqrt(sum(x * x for x in truncated))
        if norm == 0:
            return truncated
        return [x / norm for x in truncated]

    def compute_coarse_top_k(self, final_top_k: int) -> int:
        coarse = self.STAGES[0]
        return final_top_k * coarse["top_k_multiplier"]

    def should_use_multi_stage(self, embedding: list[float], top_k: int) -> bool:
        return len(embedding) >= 256 and top_k >= 5

    def get_stage_params(self, final_top_k: int) -> list[dict]:
        params = []
        for stage in self.STAGES:
            params.append(
                {
                    "dimensions": stage["dimensions"],
                    "top_k": final_top_k * stage["top_k_multiplier"],
                }
            )
        params.append({"dimensions": None, "top_k": final_top_k})
        return params
