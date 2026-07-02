import pytest
from unittest.mock import patch, MagicMock
import random
import math
from typing import Optional
from pydantic import ValidationError
from server.risk_scoring import (
    TransactionFeatures,
    RiskScore,
    IsolationNode,
    IsolationTree,
    IsolationForest
)

class TestTransactionFeatures:
    """Test TransactionFeatures Pydantic model validation."""

    def test_transaction_features_valid_data(self):
        """Test creating TransactionFeatures with valid data."""
        features = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )
        assert features.amount == 1000
        assert features.frequency == 0.5

    def test_transaction_features_negative_amount(self):
        """Test TransactionFeatures rejects negative amount."""
        with pytest.raises(ValidationError):
            TransactionFeatures(
                amount=-100,
                frequency=0.5,
                counterparty_count=5,
                avg_ttl=30.0,
                dispute_rate=0.01,
                time_since_first=100,
                total_volume=5000,
                max_single=2000,
                stddev_amount=100.0,
                hour_of_day=14
            )

    def test_transaction_features_invalid_frequency(self):
        """Test TransactionFeatures rejects frequency outside [0, 1]."""
        with pytest.raises(ValidationError):
            TransactionFeatures(
                amount=1000,
                frequency=1.5,
                counterparty_count=5,
                avg_ttl=30.0,
                dispute_rate=0.01,
                time_since_first=100,
                total_volume=5000,
                max_single=2000,
                stddev_amount=100.0,
                hour_of_day=14
            )

    def test_transaction_features_negative_dispute_rate(self):
        """Test TransactionFeatures rejects negative dispute_rate."""
        with pytest.raises(ValidationError):
            TransactionFeatures(
                amount=1000,
                frequency=0.5,
                counterparty_count=5,
                avg_ttl=30.0,
                dispute_rate=-0.01,
                time_since_first=100,
                total_volume=5000,
                max_single=2000,
                stddev_amount=100.0,
                hour_of_day=14
            )

    def test_transaction_features_hour_of_day_boundary(self):
        """Test TransactionFeatures hour_of_day boundary values."""
        min_hour = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=0
        )
        max_hour = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=23
        )
        assert min_hour.hour_of_day == 0
        assert max_hour.hour_of_day == 23

class TestRiskScore:
    """Test RiskScore Pydantic model validation."""

    def test_risk_score_valid_data(self):
        """Test creating RiskScore with valid data."""
        risk_score = RiskScore(
            escrow_id="escrow_123",
            score=75,
            anomaly_flag=True,
            features_used=["amount", "frequency"],
            feature_values={"amount": 1000.0, "frequency": 0.5},
            model_version="iforest-v1",
            scored_at=1234567890,
            explanation="High frequency anomaly detected"
        )
        assert risk_score.score == 75
        assert risk_score.anomaly_flag is True

    def test_risk_score_score_boundary(self):
        """Test RiskScore score field boundary values."""
        min_score = RiskScore(
            escrow_id="escrow_123",
            score=0,
            anomaly_flag=False,
            features_used=["amount"],
            feature_values={"amount": 1000.0},
            model_version="iforest-v1",
            scored_at=1234567890,
            explanation="Normal transaction"
        )
        max_score = RiskScore(
            escrow_id="escrow_123",
            score=100,
            anomaly_flag=False,
            features_used=["amount"],
            feature_values={"amount": 1000.0},
            model_version="iforest-v1",
            scored_at=1234567890,
            explanation="Normal transaction"
        )
        assert min_score.score == 0
        assert max_score.score == 100

    def test_risk_score_invalid_score_high(self):
        """Test RiskScore rejects score > 100."""
        with pytest.raises(ValidationError):
            RiskScore(
                escrow_id="escrow_123",
                score=101,
                anomaly_flag=False,
                features_used=["amount"],
                feature_values={"amount": 1000.0},
                model_version="iforest-v1",
                scored_at=1234567890,
                explanation="Normal transaction"
            )

    def test_risk_score_invalid_score_low(self):
        """Test RiskScore rejects score < 0."""
        with pytest.raises(ValidationError):
            RiskScore(
                escrow_id="escrow_123",
                score=-1,
                anomaly_flag=False,
                features_used=["amount"],
                feature_values={"amount": 1000.0},
                model_version="iforest-v1",
                scored_at=1234567890,
                explanation="Normal transaction"
            )

class TestIsolationNode:
    """Test IsolationNode Pydantic model."""

    def test_isolation_node_with_all_fields(self):
        """Test IsolationNode with all fields populated."""
        node = IsolationNode(
            feature="amount",
            threshold=500.0,
            left=IsolationNode(size=10),
            right=IsolationNode(size=20),
            size=30
        )
        assert node.feature == "amount"
        assert node.threshold == 500.0
        assert node.size == 30

    def test_isolation_node_minimal(self):
        """Test IsolationNode with minimal fields."""
        node = IsolationNode()
        assert node.feature is None
        assert node.threshold is None
        assert node.size == 0

    def test_isolation_node_optional_fields(self):
        """Test IsolationNode with only some optional fields."""
        node = IsolationNode(
            feature="frequency",
            size=5
        )
        assert node.feature == "frequency"
        assert node.threshold is None
        assert node.left is None
        assert node.right is None
        assert node.size == 5

class TestIsolationTree:
    """Test IsolationTree class methods."""

    @patch('server.risk_scoring.IsolationTree._build_recursive')
    def test_build_calls_recursive_with_correct_params(self, mock_build_recursive):
        """Test IsolationTree.build calls _build_recursive with correct parameters."""
        mock_build_recursive.return_value = IsolationNode(size=10)
        data = [{"amount": 100}, {"amount": 200}]

        tree = IsolationTree.build(data, max_depth=5)

        mock_build_recursive.assert_called_once_with(
            data, 5, 0, random.Random()
        )
        assert tree.size == 10

    def test_build_recursive_base_case_depth(self):
        """Test _build_recursive returns leaf when current_depth >= max_depth."""
        data = [{"amount": 100}, {"amount": 200}]
        node = IsolationTree._build_recursive(data, max_depth=0, current_depth=0, rng=random.Random())

        assert node.feature is None
        assert node.threshold is None
        assert node.size == 2

    def test_build_recursive_base_case_size(self):
        """Test _build_recursive returns leaf when len(data) <= 1."""
        data = [{"amount": 100}]
        node = IsolationTree._build_recursive(data, max_depth=10, current_depth=0, rng=random.Random())

        assert node.feature is None
        assert node.threshold is None
        assert node.size == 1

    def test_build_recursive_feature_selection(self):
        """Test _build_recursive selects a feature from available ones."""
        data = [
            {"amount": 100, "frequency": 0.5},
            {"amount": 200, "frequency": 0.3}
        ]
        rng = random.Random(42)
        node = IsolationTree._build_recursive(data, max_depth=10, current_depth=0, rng=rng)

        assert node.feature in ["amount", "frequency"]
        assert node.threshold is not None
        assert node.left is not None
        assert node.right is not None

    def test_build_recursive_equal_values(self):
        """Test _build_recursive handles equal values for a feature."""
        data = [{"amount": 100}, {"amount": 100}]
        node = IsolationTree._build_recursive(data, max_depth=10, current_depth=0, rng=random.Random())

        assert node.feature is None
        assert node.threshold is None
        assert node.size == 2

    def test_path_length_leaf_node(self):
        """Test path_length returns c(n) for leaf nodes."""
        leaf_node = IsolationNode(size=10)
        sample = {"amount": 50}

        path_len = IsolationTree.path_length(leaf_node, sample)

        expected = IsolationTree._c(10)
        assert path_len == expected

    def test_path_length_left_branch(self):
        """Test path_length traverses left branch correctly."""
        node = IsolationNode(
            feature="amount",
            threshold=150.0,
            left=IsolationNode(size=5),
            right=IsolationNode(size=3),
            size=8
        )
        sample = {"amount": 100}

        path_len = IsolationTree.path_length(node, sample)

        expected = 1.0 + IsolationTree._c(5)
        assert path_len == expected

    def test_path_length_right_branch(self):
        """Test path_length traverses right branch correctly."""
        node = IsolationNode(
            feature="amount",
            threshold=150.0,
            left=IsolationNode(size=5),
            right=IsolationNode(size=3),
            size=8
        )
        sample = {"amount": 200}

        path_len = IsolationTree.path_length(node, sample)

        expected = 1.0 + IsolationTree._c(3)
        assert path_len == expected

    def test_path_length_none_feature(self):
        """Test path_length handles None feature/threshold gracefully."""
        leaf_node = IsolationNode(size=5)
        sample = {"amount": 100}

        path_len = IsolationTree.path_length(leaf_node, sample)

        expected = IsolationTree._c(5)
        assert path_len == expected

    def test_c_function_edge_cases(self):
        """Test _c function edge cases."""
        assert IsolationTree._c(0) == 0.0
        assert IsolationTree._c(1) == 0.0
        assert IsolationTree._c(2) > 0.0

class TestIsolationForest:
    """Test IsolationForest class."""

    def test_init_default_params(self):
        """Test IsolationForest initialization with default parameters."""
        forest = IsolationForest()

        assert forest.n_trees == 100
        assert forest.sample_size == 256
        assert forest.max_depth == 8
        assert forest.seed == 42
        assert forest.trees == []
        assert forest._feature_names == []

    def test_init_custom_params(self):
        """Test IsolationForest initialization with custom parameters."""
        forest = IsolationForest(n_trees=50, sample_size=128, max_depth=10, seed=123)

        assert forest.n_trees == 50
        assert forest.sample_size == 128
        assert forest.max_depth == 10
        assert forest.seed == 123

    def test_fit_empty_data(self):
        """Test fit handles empty data gracefully."""
        forest = IsolationForest()
        forest.fit([])
        assert forest.trees == []
        assert forest._feature_names == []

    def test_fit_single_sample(self):
        """Test fit with single sample."""
        forest = IsolationForest(n_trees=1, sample_size=1, max_depth=5, seed=42)
        data = [TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )]
        forest.fit(data)
        assert len(forest.trees) == 1
        assert forest._feature_names == list(TransactionFeatures.model_fields.keys())

    def test_fit_multiple_samples(self):
        """Test fit with multiple samples."""
        forest = IsolationForest(n_trees=3, sample_size=10, max_depth=5, seed=42)
        data = [
            TransactionFeatures(
                amount=1000 + i,
                frequency=0.5 + i * 0.01,
                counterparty_count=5 + i,
                avg_ttl=30.0 + i * 2.0,
                dispute_rate=0.01 + i * 0.001,
                time_since_first=100 + i * 10,
                total_volume=5000 + i * 100,
                max_single=2000 + i * 50,
                stddev_amount=100.0 + i * 5.0,
                hour_of_day=14
            ) for i in range(20)
        ]
        forest.fit(data)
        assert len(forest.trees) == 3
        assert len(forest._feature_names) == 10

    @patch('server.risk_scoring.IsolationTree.build')
    def test_fit_calls_build_correctly(self, mock_build):
        """Test fit calls IsolationTree.build with correct parameters."""
        mock_build.return_value = IsolationNode(size=10)
        forest = IsolationForest(n_trees=2, sample_size=5, max_depth=6, seed=42)
        data = [TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )] * 10

        forest.fit(data)

        assert mock_build.call_count == 2
        calls = mock_build.call_args_list
        for call in calls:
            args, kwargs = call
            assert len(args[0]) == 5  # sample size
            assert args[1] == 6  # max_depth
            assert isinstance(args[2], random.Random)  # rng

    def test_to_dict_conversion(self):
        """Test _to_dict converts TransactionFeatures correctly."""
        features = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )
        forest = IsolationForest()
        result = forest._to_dict(features)

        expected_keys = set(TransactionFeatures.model_fields.keys())
        assert set(result.keys()) == expected_keys
        assert result["amount"] == 1000
        assert result["frequency"] == 0.5

    def test_subsample_size(self):
        """Test _subsample returns correct number of samples."""
        data = list(range(100))
        forest = IsolationForest(sample_size=25, seed=42)
        sample = forest._subsample(data, 25)

        assert len(sample) == 25
        assert all(x in data for x in sample)

    def test_subsample_randomness(self):
        """Test _subsample produces different results with different seeds."""
        data = list(range(100))
        forest1 = IsolationForest(sample_size=25, seed=42)
        forest2 = IsolationForest(sample_size=25, seed=123)

        sample1 = forest1._subsample(data, 25)
        sample2 = forest2._subsample(data, 25)

        assert sample1 != sample2

    @patch('server.risk_scoring.IsolationTree.path_length')
    def test_score_sample_average_path(self, mock_path_length):
        """Test score_sample calculates average path length correctly."""
        mock_path_length.return_value = 5.0
        forest = IsolationForest(n_trees=3)
        forest.trees = [IsolationNode(size=10)] * 3

        sample = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )

        score = forest.score_sample(sample)

        assert mock_path_length.call_count == 3
        assert score == 5.0

    def test_score_sample_empty_trees(self):
        """Test score_sample handles empty trees list."""
        forest = IsolationForest()
        sample = TransactionFeatures(
            amount=1000,
            frequency=0.5,
            counterparty_count=5,
            avg_ttl=30.0,
            dispute_rate=0.01,
            time_since_first=100,
            total_volume=5000,
            max_single=2000,
            stddev_amount=100.0,
            hour_of_day=14
        )

        with pytest.raises(ZeroDivisionError):
            forest.score_sample(sample)

class TestIntegration:
    """Integration tests for the risk scoring module."""

    def test_full_pipeline(self):
        """Test end-to-end pipeline from features to risk score."""
        # Create sample data
        features = [
            TransactionFeatures(
                amount=1000 + i * 100,
                frequency=0.5 + i * 0.01,
                counterparty_count=5 + i,
                avg_ttl=30.0 + i * 2.0,
                dispute_rate=0.01 + i * 0.001,
                time_since_first=100 + i * 10,
                total_volume=5000 + i * 100,
                max_single=2000 + i * 50,
                stddev_amount=100.0 + i * 5.0,
                hour_of_day=14
            ) for i in range(50)
        ]

        # Train forest
        forest = IsolationForest(n_trees=10, sample_size=32, max_depth=6, seed=42)
        forest.fit(features)

        # Score a sample
        sample = TransactionFeatures(
            amount=1200,
            frequency=0.6,
            counterparty_count=7,
            avg_ttl=35.0,
            dispute_rate=0.015,
            time_since_first=150,
            total_volume=6000,
            max_single=2200,
            stddev_amount=110.0,
            hour_of_day=15
        )

        score = forest.score_sample(sample)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_anomaly_detection_logic(self):
        """Test that anomalies are detected based on path length."""
        # Create normal and anomalous data
        normal_data = [
            TransactionFeatures(
                amount=1000,
                frequency=0.5,
                counterparty_count=5,
                avg_ttl=30.0,
                dispute_rate=0.01,
                time_since_first=100,
                total_volume=5000,
                max_single=2000,
                stddev_amount=100.0,
                hour_of_day=14
            ) for _ in range(100)
        ]

        anomalous_data = [
            TransactionFeatures(
                amount=10000,  # Very high amount
                frequency=2.0,  # Very high frequency
                counterparty_count=50,  # High counterparty count
                avg_ttl=300.0,  # High average TTL
                dispute_rate=0.5,  # High dispute rate
                time_since_first=1,  # Very recent
                total_volume=50000,  # High volume
                max_single=10000,  # High single transaction
                stddev_amount=5000.0,  # High stddev
                hour_of_day=3  # Unusual hour
            ) for _ in range(10)
        ]

        # Train forest
        forest = IsolationForest(n_trees=20, sample_size=64, max_depth=8, seed=42)
        forest.fit(normal_data + anomalous_data)

        # Score normal sample
        normal_sample = TransactionFeatures(
            amount=1050,
            frequency=0.55,
            counterparty_count=6,
            avg_ttl=32.0,
            dispute_rate=0.012,
            time_since_first=120,
            total_volume=5200,
            max_single=2100,
            stddev_amount=105.0,
            hour_of_day=14
        )

        # Score anomalous sample
        anomalous_sample = TransactionFeatures(
            amount=9500,
            frequency=1.8,
            counterparty_count=45,
            avg_ttl=250.0,
            dispute_rate=0.45,
            time_since_first=2,
            total_volume=45000,
            max_single=9000,
            stddev_amount=4500.0,
            hour_of_day=4
        )

        normal_score = forest.score_sample(normal_sample)
        anomalous_score = forest.score_sample(anomalous_sample)

        # Anomalous samples should have shorter path lengths (lower scores)
        assert anomalous_score < normal_score
