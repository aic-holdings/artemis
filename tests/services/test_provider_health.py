"""Tests for ProviderHealthTracker."""
import pytest
import time

from app.services.provider_health import (
    ProviderHealthTracker,
    ProviderHealth,
    ProviderStatus,
)


@pytest.fixture
def fresh_tracker():
    """Create a fresh tracker instance for testing (bypass singleton)."""
    tracker = object.__new__(ProviderHealthTracker)
    tracker._providers = {}
    tracker._initialized = True
    return tracker


class TestProviderHealth:
    """Test ProviderHealth dataclass."""

    def test_initial_state(self):
        """New health object has zero counts."""
        health = ProviderHealth(provider="openai")
        assert health.success_count == 0
        assert health.failure_count == 0
        assert health.timeout_count == 0

    def test_record_success(self):
        """Recording success updates counts."""
        health = ProviderHealth(provider="openai")
        health.record_success(100)
        health.record_success(200)

        assert health.success_count == 2
        assert health.failure_count == 0

    def test_record_failure(self):
        """Recording failure updates counts and tracks error."""
        health = ProviderHealth(provider="anthropic")
        health.record_failure("timeout", "Request timed out", 30000)

        assert health.failure_count == 1
        assert health.timeout_count == 1
        assert health.last_error == "Request timed out"
        assert health.last_error_type == "timeout"

    def test_status_healthy_when_few_requests(self):
        """Status is healthy with few requests (< 5)."""
        health = ProviderHealth(provider="openai")
        health.record_success(100)
        health.record_failure("error", "Test", 100)

        assert health.status == ProviderStatus.HEALTHY

    def test_status_healthy_when_low_errors(self):
        """Status is healthy with < 10% error rate."""
        health = ProviderHealth(provider="openai")
        # 5% error rate (1 in 20)
        for _ in range(19):
            health.record_success(100)
        health.record_failure("timeout", "Timed out", 100)

        assert health.status == ProviderStatus.HEALTHY

    def test_status_degraded_when_moderate_errors(self):
        """Status is degraded with 10-50% error rate."""
        health = ProviderHealth(provider="openai")
        # 20% error rate (2 in 10)
        for _ in range(8):
            health.record_success(100)
        for _ in range(2):
            health.record_failure("timeout", "Timed out", 100)

        assert health.status == ProviderStatus.DEGRADED

    def test_status_unhealthy_when_high_errors(self):
        """Status is unhealthy with >= 50% error rate."""
        health = ProviderHealth(provider="openai")
        # 50% error rate
        for _ in range(5):
            health.record_success(100)
        for _ in range(5):
            health.record_failure("timeout", "Timed out", 100)

        assert health.status == ProviderStatus.UNHEALTHY

    def test_error_rate_calculation(self):
        """Error rate is calculated correctly."""
        health = ProviderHealth(provider="openai")
        # 25% error rate (1 in 4)
        for _ in range(3):
            health.record_success(100)
        health.record_failure("timeout", "Timed out", 100)

        assert health.error_rate == pytest.approx(0.25, rel=0.01)

    def test_avg_latency_calculation(self):
        """Average latency is calculated correctly."""
        health = ProviderHealth(provider="openai")
        health.record_success(100)
        health.record_success(200)
        health.record_success(300)

        assert health.avg_latency_ms == pytest.approx(200, rel=0.01)

    def test_to_dict(self):
        """to_dict returns expected structure."""
        health = ProviderHealth(provider="openai")
        health.record_success(100)

        data = health.to_dict()
        assert data["provider"] == "openai"
        assert data["status"] == "healthy"
        assert data["total_requests"] == 1
        assert data["total_successes"] == 1
        assert data["total_failures"] == 0


class TestProviderHealthTracker:
    """Test ProviderHealthTracker."""

    def test_get_health_creates_new(self, fresh_tracker):
        """get_health creates a new ProviderHealth if none exists."""
        health = fresh_tracker.get_health("openai")
        assert health.provider == "openai"
        assert health.success_count == 0

    def test_get_health_returns_existing(self, fresh_tracker):
        """get_health returns existing ProviderHealth."""
        fresh_tracker.record_success("openai", 100)
        health = fresh_tracker.get_health("openai")
        assert health.success_count == 1

    def test_record_success(self, fresh_tracker):
        """record_success delegates to provider health."""
        fresh_tracker.record_success("openai", 100)
        fresh_tracker.record_success("openai", 200)

        health = fresh_tracker.get_health("openai")
        assert health.success_count == 2

    def test_record_failure(self, fresh_tracker):
        """record_failure delegates to provider health."""
        fresh_tracker.record_failure("anthropic", "timeout", "Timed out", 100)

        health = fresh_tracker.get_health("anthropic")
        assert health.failure_count == 1
        assert health.last_error_type == "timeout"

    def test_get_status(self, fresh_tracker):
        """get_status returns provider status."""
        for _ in range(10):
            fresh_tracker.record_success("openai", 100)

        status = fresh_tracker.get_status("openai")
        assert status == ProviderStatus.HEALTHY

    def test_get_all_health(self, fresh_tracker):
        """get_all_health returns all provider data."""
        fresh_tracker.record_success("openai", 100)
        fresh_tracker.record_success("anthropic", 200)

        all_health = fresh_tracker.get_all_health()
        assert "openai" in all_health
        assert "anthropic" in all_health
        assert all_health["openai"]["total_successes"] == 1

    def test_get_summary(self, fresh_tracker):
        """get_summary returns summary with healthy/unhealthy lists."""
        # Make openai healthy
        for _ in range(10):
            fresh_tracker.record_success("openai", 100)

        # Make anthropic unhealthy (50%+ errors)
        for _ in range(5):
            fresh_tracker.record_success("anthropic", 100)
        for _ in range(5):
            fresh_tracker.record_failure("anthropic", "error", "Test", 100)

        summary = fresh_tracker.get_summary()
        assert "providers" in summary
        assert summary["all_healthy"] is False
        assert "anthropic" in summary["unhealthy_providers"]

    def test_multiple_providers_independent(self, fresh_tracker):
        """Different providers are tracked independently."""
        fresh_tracker.record_success("openai", 100)
        fresh_tracker.record_failure("anthropic", "error", "Test", 100)

        openai = fresh_tracker.get_health("openai")
        anthropic = fresh_tracker.get_health("anthropic")

        assert openai.success_count == 1
        assert openai.failure_count == 0
        assert anthropic.success_count == 0
        assert anthropic.failure_count == 1


class TestProviderHealthEdgeCases:
    """Test edge cases."""

    def test_zero_latency(self):
        """Handle zero latency."""
        health = ProviderHealth(provider="openai")
        health.record_success(0)

        assert health.avg_latency_ms == 0

    def test_very_high_latency(self):
        """Handle very high latency."""
        health = ProviderHealth(provider="openai")
        health.record_success(300000)  # 5 minutes

        assert health.avg_latency_ms == 300000

    def test_empty_error_message(self):
        """Handle empty error message."""
        health = ProviderHealth(provider="openai")
        health.record_failure("unknown", "", 100)

        assert health.last_error == ""

    def test_many_rapid_updates(self):
        """Handle many rapid updates."""
        health = ProviderHealth(provider="openai")
        for i in range(1000):
            if i % 10 == 0:
                health.record_failure("error", f"Error {i}", i)
            else:
                health.record_success(i)

        assert health.success_count + health.failure_count == 1000
        assert health.failure_count == 100
        assert health.success_count == 900

    def test_error_rate_zero_with_no_requests(self):
        """Error rate is 0 with no requests."""
        health = ProviderHealth(provider="openai")
        assert health.error_rate == 0.0

    def test_avg_latency_none_with_no_samples(self):
        """Average latency is None with no samples."""
        health = ProviderHealth(provider="openai")
        assert health.avg_latency_ms is None
