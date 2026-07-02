import math
import os
import random
import struct
from typing import Optional

from pydantic import BaseModel, Field

class TransactionFeatures(BaseModel):
    amount: int
    frequency: float
    counterparty_count: int
    avg_ttl: float
    dispute_rate: float
    time_since_first: int
    total_volume: int
    max_single: int
    stddev_amount: float
    hour_of_day: int

class RiskScore(BaseModel):
    escrow_id: str
    score: int = Field(ge=0, le=100)
    anomaly_flag: bool
    features_used: list[str]
    feature_values: dict[str, float]
    model_version: str = "iforest-v1"
    scored_at: int
    explanation: str

class IsolationNode(BaseModel):
    feature: Optional[str] = None
    threshold: Optional[float] = None
    left: Optional["IsolationNode"] = None
    right: Optional["IsolationNode"] = None
    size: int = 0

    class Config:
        arbitrary_types_allowed = True

class IsolationTree:
    @classmethod
    def build(cls, data: list[dict], max_depth: int = 8, rng: random.Random | None = None) -> IsolationNode:
        if rng is None:
            rng = random.Random()
        return cls._build_recursive(data, max_depth, 0, rng)

    @classmethod
    def _build_recursive(cls, data: list[dict], max_depth: int, current_depth: int, rng: random.Random) -> IsolationNode:
        node = IsolationNode(size=len(data))
        if current_depth >= max_depth or len(data) <= 1:
            return node
        features = list(data[0].keys())
        feature = rng.choice(features)
        values = [row[feature] for row in data]
        min_val = min(values)
        max_val = max(values)
        if min_val == max_val:
            return node
        threshold = rng.uniform(min_val, max_val)
        left_data = [row for row in data if row[feature] < threshold]
        right_data = [row for row in data if row[feature] >= threshold]
        node.feature = feature
        node.threshold = threshold
        node.left = cls._build_recursive(left_data, max_depth, current_depth + 1, rng)
        node.right = cls._build_recursive(right_data, max_depth, current_depth + 1, rng)
        return node

    @classmethod
    def path_length(cls, node: IsolationNode, sample: dict) -> float:
        if node.feature is None or node.threshold is None:
            return cls._c(node.size) if node.size > 1 else 0.0
        if sample[node.feature] < node.threshold:
            if node.left is None:
                return cls._c(node.size) if node.size > 1 else 0.0
            return 1.0 + cls.path_length(node.left, sample)
        else:
            if node.right is None:
                return cls._c(node.size) if node.size > 1 else 0.0
            return 1.0 + cls.path_length(node.right, sample)

    @staticmethod
    def _c(n: int) -> float:
        if n <= 1:
            return 0.0
        return 2.0 * (math.log(n - 1) + 0.5772156649) - (2.0 * (n - 1) / n)

class IsolationForest:
    def __init__(self, n_trees: int = 100, sample_size: int = 256, max_depth: int = 8, seed: int | None = None):
        self.n_trees = n_trees
        self.sample_size = sample_size
        self.max_depth = max_depth
        # Use cryptographically secure seed if none provided
        if seed is None:
            seed = struct.unpack("I", os.urandom(4))[0]
        self.seed = seed
        self.trees: list[IsolationNode] = []
        self.rng = random.Random(seed)
        self._feature_names: list[str] = []

    def fit(self, data: list[TransactionFeatures]) -> None:
        if not data:
            return
        self._feature_names = list(TransactionFeatures.model_fields.keys())
        dict_data = [self._to_dict(f) for f in data]
        n_samples = min(self.sample_size, len(dict_data))
        for _ in range(self.n_trees):
            sample = self._subsample(dict_data, n_samples)
            tree = IsolationTree.build(sample, self.max_depth, random.Random(self.rng.randint(0, 2**31 - 1)))
            self.trees.append(tree)

    def score_sample(self, sample: TransactionFeatures) -> float:
        sample_dict = self._to_dict(sample)
        avg_path = sum(IsolationTree.path_length(tree, sample_dict) for tree in self.trees) / len(self.trees)
        return 2.0 ** (-avg_path / IsolationTree._c(self.sample_size)) if self.trees else 0.5

    def score_escrow(self, escrow_id: str, features: TransactionFeatures) -> RiskScore:
        anomaly_score = self.score_sample(features)
        risk_int = min(100, max(0, int(anomaly_score * 100)))
        feature_values = self._to_dict(features)
        import time as _time
        return RiskScore(
            escrow_id=escrow_id,
            score=risk_int,
            anomaly_flag=anomaly_score > 0.65,
            features_used=list(feature_values.keys()),
            feature_values=feature_values,
            model_version="iforest-v1",
            scored_at=int(_time.time()),
            explanation=f"Anomaly score: {anomaly_score:.4f}"
        )

    def _to_dict(self, features: TransactionFeatures) -> dict[str, float]:
        return {
            "amount": float(features.amount),
            "frequency": features.frequency,
            "counterparty_count": float(features.counterparty_count),
            "avg_ttl": features.avg_ttl,
            "dispute_rate": features.dispute_rate,
            "time_since_first": float(features.time_since_first),
            "total_volume": float(features.total_volume),
            "max_single": float(features.max_single),
            "stddev_amount": features.stddev_amount,
            "hour_of_day": float(features.hour_of_day),
        }

    def _subsample(self, data: list[dict], n: int) -> list[dict]:
        if len(data) <= n:
            return data
        indices = self.rng.sample(range(len(data)), n)
        return [data[i] for i in indices]

class RiskEngine:
    def __init__(self, threshold: float = 0.65, model: IsolationForest | None = None):
        self.threshold = threshold
        self.model = model or IsolationForest()

    async def train_from_history(self, history: list[TransactionFeatures]) -> None:
        self.model.fit(history)

    async def assess(self, escrow_id: str, features: TransactionFeatures) -> RiskScore:
        score = self.model.score_escrow(escrow_id, features)
        score.anomaly_flag = score.score / 100.0 > self.threshold
        score.explanation = self.explain(score)
        return score

    def explain(self, score: RiskScore) -> str:
        flag = "ANOMALOUS" if score.anomaly_flag else "NORMAL"
        top_features = sorted(score.feature_values.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        feature_str = ", ".join([f"{k}={v:.2f}" for k, v in top_features])
        return f"Risk {score.score}/100 ({flag}). Key features: {feature_str}. Model: {score.model_version}"

    async def batch_assess(self, items: list[tuple[str, TransactionFeatures]]) -> list[RiskScore]:
        return [await self.assess(eid, feat) for eid, feat in items]
