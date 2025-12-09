"""Tests for RequestLogService."""
import pytest
from datetime import datetime, timedelta, timezone

from app.services.request_log_service import RequestLogService, generate_request_id
from app.models import User, APIKey, RequestLog


class TestRequestIdGeneration:
    """Test request ID generation."""

    def test_generate_request_id_format(self):
        """Request ID is a valid UUID string."""
        request_id = generate_request_id()
        assert isinstance(request_id, str)
        assert len(request_id) == 36  # UUID format

    def test_generate_request_id_unique(self):
        """Generated IDs are unique."""
        ids = [generate_request_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestRequestLogServiceStart:
    """Test request start logging."""

    @pytest.mark.asyncio
    async def test_start_request(self, test_db):
        """Log the start of a request."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            api_key = APIKey(
                user_id=user.id,
                key_hash="hash",
                key_prefix="art_1234",
                name="Test Key",
            )
            session.add(api_key)
            await session.commit()
            await session.refresh(api_key)

            service = RequestLogService(session)
            log = await service.start_request(
                request_id="test-req-123",
                provider="openai",
                endpoint="/v1/openai/chat/completions",
                api_key_id=api_key.id,
                model="gpt-4",
                is_streaming=False,
                app_id="test-app",
            )

            assert log is not None
            assert log.request_id == "test-req-123"
            assert log.provider == "openai"
            assert log.endpoint == "/v1/openai/chat/completions"
            assert log.model == "gpt-4"
            assert log.is_streaming is False
            assert log.app_id == "test-app"
            assert log.started_at is not None
            assert log.completed_at is None

    @pytest.mark.asyncio
    async def test_start_request_with_client_info(self, test_db):
        """Log request with client info."""
        async with test_db() as session:
            service = RequestLogService(session)
            log = await service.start_request(
                request_id="test-req-456",
                provider="anthropic",
                endpoint="/v1/anthropic/messages",
                client_ip="192.168.1.1",
                user_agent="Mozilla/5.0",
            )

            assert log.client_ip == "192.168.1.1"
            assert log.user_agent == "Mozilla/5.0"


class TestRequestLogServiceComplete:
    """Test request completion logging."""

    @pytest.mark.asyncio
    async def test_complete_request(self, test_db):
        """Mark a request as completed."""
        async with test_db() as session:
            service = RequestLogService(session)
            log = await service.start_request(
                request_id="complete-test",
                provider="openai",
                endpoint="/v1/openai/chat/completions",
            )

            completed = await service.complete_request(
                log.id,
                status_code=200,
                latency_ms=150,
            )

            assert completed is not None
            assert completed.status_code == 200
            assert completed.latency_ms == 150
            assert completed.completed_at is not None
            assert completed.error_type is None

    @pytest.mark.asyncio
    async def test_complete_request_with_metadata(self, test_db):
        """Complete request with response metadata."""
        async with test_db() as session:
            service = RequestLogService(session)
            log = await service.start_request(
                request_id="metadata-test",
                provider="openai",
                endpoint="/v1/openai/chat/completions",
            )

            completed = await service.complete_request(
                log.id,
                status_code=200,
                latency_ms=100,
                response_metadata={"tokens": 500},
            )

            assert completed.response_metadata == {"tokens": 500}

    @pytest.mark.asyncio
    async def test_complete_nonexistent_request(self, test_db):
        """Completing nonexistent request returns None."""
        async with test_db() as session:
            service = RequestLogService(session)
            result = await service.complete_request(
                "nonexistent-id",
                status_code=200,
                latency_ms=100,
            )
            assert result is None


class TestRequestLogServiceFail:
    """Test request failure logging."""

    @pytest.mark.asyncio
    async def test_fail_request(self, test_db):
        """Mark a request as failed."""
        async with test_db() as session:
            service = RequestLogService(session)
            log = await service.start_request(
                request_id="fail-test",
                provider="openai",
                endpoint="/v1/openai/chat/completions",
            )

            failed = await service.fail_request(
                log.id,
                error_type="timeout",
                error_message="Request timed out after 120s",
                status_code=504,
                latency_ms=120000,
            )

            assert failed is not None
            assert failed.error_type == "timeout"
            assert failed.error_message == "Request timed out after 120s"
            assert failed.status_code == 504
            assert failed.latency_ms == 120000
            assert failed.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_request_with_retry_flag(self, test_db):
        """Mark failed request as retried."""
        async with test_db() as session:
            service = RequestLogService(session)
            log = await service.start_request(
                request_id="retry-test",
                provider="openai",
                endpoint="/v1/openai/chat/completions",
            )

            failed = await service.fail_request(
                log.id,
                error_type="connection_error",
                error_message="Connection refused",
                was_retried=True,
            )

            assert failed.was_retried is True


class TestRequestLogServiceErrors:
    """Test error querying."""

    @pytest.mark.asyncio
    async def test_get_recent_errors(self, test_db):
        """Get recent failed requests."""
        async with test_db() as session:
            service = RequestLogService(session)

            # Create some successful requests
            log1 = await service.start_request(
                request_id="success-1",
                provider="openai",
                endpoint="/test",
            )
            await service.complete_request(log1.id, 200, 100)

            # Create some failed requests
            log2 = await service.start_request(
                request_id="fail-1",
                provider="openai",
                endpoint="/test",
            )
            await service.fail_request(log2.id, "timeout", "Timed out")

            log3 = await service.start_request(
                request_id="fail-2",
                provider="anthropic",
                endpoint="/test",
            )
            await service.fail_request(log3.id, "connection_error", "Connection failed")

            errors = await service.get_recent_errors()
            assert len(errors) == 2

    @pytest.mark.asyncio
    async def test_get_recent_errors_by_provider(self, test_db):
        """Filter errors by provider."""
        async with test_db() as session:
            service = RequestLogService(session)

            log1 = await service.start_request(
                request_id="fail-openai",
                provider="openai",
                endpoint="/test",
            )
            await service.fail_request(log1.id, "timeout", "Timed out")

            log2 = await service.start_request(
                request_id="fail-anthropic",
                provider="anthropic",
                endpoint="/test",
            )
            await service.fail_request(log2.id, "timeout", "Timed out")

            openai_errors = await service.get_recent_errors(provider="openai")
            assert len(openai_errors) == 1
            assert openai_errors[0].provider == "openai"


class TestRequestLogServiceStats:
    """Test statistics gathering."""

    @pytest.mark.asyncio
    async def test_get_error_stats(self, test_db):
        """Get error statistics."""
        async with test_db() as session:
            service = RequestLogService(session)

            # Create requests
            for i in range(5):
                log = await service.start_request(
                    request_id=f"success-{i}",
                    provider="openai",
                    endpoint="/test",
                )
                await service.complete_request(log.id, 200, 100)

            for i in range(2):
                log = await service.start_request(
                    request_id=f"timeout-{i}",
                    provider="openai",
                    endpoint="/test",
                )
                await service.fail_request(log.id, "timeout", "Timed out")

            log = await service.start_request(
                request_id="conn-error",
                provider="openai",
                endpoint="/test",
            )
            await service.fail_request(log.id, "connection_error", "Failed")

            since = datetime.now(timezone.utc) - timedelta(hours=1)
            stats = await service.get_error_stats(since)

            assert stats["total_requests"] == 8
            assert stats["failed_requests"] == 3
            assert stats["error_rate"] == pytest.approx(37.5, rel=0.1)
            assert stats["error_breakdown"]["timeout"] == 2
            assert stats["error_breakdown"]["connection_error"] == 1

    @pytest.mark.asyncio
    async def test_get_latency_stats(self, test_db):
        """Get latency statistics."""
        async with test_db() as session:
            service = RequestLogService(session)

            latencies = [100, 200, 300, 400, 500]
            for i, latency in enumerate(latencies):
                log = await service.start_request(
                    request_id=f"latency-{i}",
                    provider="openai",
                    endpoint="/test",
                )
                await service.complete_request(log.id, 200, latency)

            since = datetime.now(timezone.utc) - timedelta(hours=1)
            stats = await service.get_latency_stats(since)

            assert stats["count"] == 5
            assert stats["avg_latency_ms"] == 300
            assert stats["min_latency_ms"] == 100
            assert stats["max_latency_ms"] == 500
