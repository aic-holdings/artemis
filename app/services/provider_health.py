"""
Provider health tracking service.

Tracks success/failure rates for each provider to enable:
- Graceful error reporting
- Health status visibility
- Future: circuit breakers, failover

Health data is persisted to the database and loaded on startup.
"""

import time
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    """Provider health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # >10% error rate in last 5 min
    UNHEALTHY = "unhealthy"  # >50% error rate or circuit open


@dataclass
class ProviderHealth:
    """Health metrics for a single provider."""
    provider: str

    # Counters (reset on app restart - intentionally stateless)
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0

    # Recent history for rate calculation (sliding window)
    recent_successes: list = field(default_factory=list)
    recent_failures: list = field(default_factory=list)

    # Last error info
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    last_error_type: Optional[str] = None

    # Latency tracking
    latency_samples: list = field(default_factory=list)

    # Error type breakdown - counts by error type
    error_type_counts: dict = field(default_factory=dict)

    # Time-series data for sparklines (1-hour buckets)
    # Each entry: (bucket_timestamp, successes, failures)
    time_series: list = field(default_factory=list)

    # Window size for "recent" calculations (24 hours)
    WINDOW_SECONDS: int = 86400  # 24 hours
    MAX_SAMPLES: int = 10000
    BUCKET_SECONDS: int = 3600  # 1-hour buckets for sparkline

    def record_success(self, latency_ms: int):
        """Record a successful request."""
        now = time.time()
        self.success_count += 1
        self.recent_successes.append(now)
        self.latency_samples.append((now, latency_ms))
        self._update_time_series(now, is_success=True)
        self._prune_old_data(now)

    def record_failure(self, error_type: str, error_message: str, latency_ms: int = 0):
        """Record a failed request."""
        now = time.time()
        self.failure_count += 1
        self.recent_failures.append(now)
        self.last_error = error_message
        self.last_error_time = now
        self.last_error_type = error_type

        # Track error type breakdown
        self.error_type_counts[error_type] = self.error_type_counts.get(error_type, 0) + 1

        if error_type == "timeout":
            self.timeout_count += 1

        if latency_ms > 0:
            self.latency_samples.append((now, latency_ms))

        self._update_time_series(now, is_success=False)
        self._prune_old_data(now)

        logger.warning(
            f"Provider {self.provider} request failed",
            extra={
                "provider": self.provider,
                "error_type": error_type,
                "error_message": error_message,
                "failure_count": self.failure_count,
            }
        )

    def load_historical_record(self, timestamp: float, is_success: bool, latency_ms: Optional[int],
                               error_type: Optional[str], error_message: Optional[str]):
        """Load a historical record from database (called during startup)."""
        if is_success:
            self.success_count += 1
            self.recent_successes.append(timestamp)
            if latency_ms:
                self.latency_samples.append((timestamp, latency_ms))
            self._update_time_series(timestamp, is_success=True)
        else:
            self.failure_count += 1
            self.recent_failures.append(timestamp)
            if error_type:
                self.error_type_counts[error_type] = self.error_type_counts.get(error_type, 0) + 1
                if error_type == "timeout":
                    self.timeout_count += 1
            # Update last error if this is more recent
            if not self.last_error_time or timestamp > self.last_error_time:
                self.last_error = error_message
                self.last_error_time = timestamp
                self.last_error_type = error_type
            if latency_ms:
                self.latency_samples.append((timestamp, latency_ms))
            self._update_time_series(timestamp, is_success=False)

    def _get_bucket(self, timestamp: float) -> int:
        """Get the bucket timestamp for a given timestamp."""
        return int(timestamp // self.BUCKET_SECONDS) * self.BUCKET_SECONDS

    def _update_time_series(self, now: float, is_success: bool):
        """Update time-series data for sparklines."""
        bucket = self._get_bucket(now)

        # Find or create the bucket
        if self.time_series and self.time_series[-1][0] == bucket:
            # Update existing bucket
            ts, successes, failures = self.time_series[-1]
            if is_success:
                self.time_series[-1] = (ts, successes + 1, failures)
            else:
                self.time_series[-1] = (ts, successes, failures + 1)
        else:
            # Create new bucket
            if is_success:
                self.time_series.append((bucket, 1, 0))
            else:
                self.time_series.append((bucket, 0, 1))

    def _prune_old_data(self, now: float):
        """Remove data older than the window."""
        cutoff = now - self.WINDOW_SECONDS
        self.recent_successes = [t for t in self.recent_successes if t > cutoff][-self.MAX_SAMPLES:]
        self.recent_failures = [t for t in self.recent_failures if t > cutoff][-self.MAX_SAMPLES:]
        self.latency_samples = [(t, l) for t, l in self.latency_samples if t > cutoff][-self.MAX_SAMPLES:]
        # Keep 24 buckets (24 hours / 1 hour = 24)
        self.time_series = [(t, s, f) for t, s, f in self.time_series if t > cutoff][-24:]

    @property
    def recent_success_count(self) -> int:
        """Successes in the last window."""
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        return len([t for t in self.recent_successes if t > cutoff])

    @property
    def recent_failure_count(self) -> int:
        """Failures in the last window."""
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        return len([t for t in self.recent_failures if t > cutoff])

    @property
    def recent_total(self) -> int:
        """Total requests in the last window."""
        return self.recent_success_count + self.recent_failure_count

    @property
    def error_rate(self) -> float:
        """Error rate in the last window (0.0 to 1.0)."""
        total = self.recent_total
        if total == 0:
            return 0.0
        return self.recent_failure_count / total

    @property
    def status(self) -> ProviderStatus:
        """Current health status."""
        # Need at least 5 requests to make a determination
        if self.recent_total < 5:
            return ProviderStatus.HEALTHY

        error_rate = self.error_rate
        if error_rate >= 0.5:
            return ProviderStatus.UNHEALTHY
        elif error_rate >= 0.1:
            return ProviderStatus.DEGRADED
        return ProviderStatus.HEALTHY

    @property
    def avg_latency_ms(self) -> Optional[float]:
        """Average latency in the last window."""
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        recent = [l for t, l in self.latency_samples if t > cutoff]
        if not recent:
            return None
        return sum(recent) / len(recent)

    @property
    def p95_latency_ms(self) -> Optional[float]:
        """95th percentile latency in the last window."""
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        recent = sorted([l for t, l in self.latency_samples if t > cutoff])
        if not recent:
            return None
        idx = int(len(recent) * 0.95)
        return recent[min(idx, len(recent) - 1)]

    def to_dict(self) -> dict:
        """Export health data for API/dashboard."""
        # Build sparkline data - list of error rates per bucket
        sparkline_data = []
        for ts, successes, failures in self.time_series:
            total = successes + failures
            if total > 0:
                error_rate = round((failures / total) * 100, 1)
            else:
                error_rate = 0
            sparkline_data.append({
                "timestamp": ts,
                "successes": successes,
                "failures": failures,
                "error_rate": error_rate,
            })

        return {
            "provider": self.provider,
            "status": self.status.value,
            "total_requests": self.success_count + self.failure_count,
            "total_successes": self.success_count,
            "total_failures": self.failure_count,
            "total_timeouts": self.timeout_count,
            "recent_requests": self.recent_total,
            "recent_successes": self.recent_success_count,
            "recent_failures": self.recent_failure_count,
            "error_rate": round(self.error_rate * 100, 2),  # As percentage
            "avg_latency_ms": round(self.avg_latency_ms) if self.avg_latency_ms else None,
            "p95_latency_ms": round(self.p95_latency_ms) if self.p95_latency_ms else None,
            "last_error": self.last_error,
            "last_error_type": self.last_error_type,
            "last_error_age_seconds": round(time.time() - self.last_error_time) if self.last_error_time else None,
            # New fields
            "error_type_breakdown": dict(self.error_type_counts),
            "sparkline": sparkline_data,
        }


class ProviderHealthTracker:
    """
    Singleton tracker for all provider health.

    Thread-safe for use in async context (no locks needed for counter increments).
    Persists health records to database for durability across restarts.
    """

    _instance: Optional["ProviderHealthTracker"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._providers: dict[str, ProviderHealth] = {}
        self._initialized = True
        self._db_initialized = False
        self._pending_writes: list = []  # Queue for batch writes
        self._write_task: Optional[asyncio.Task] = None

    def get_health(self, provider: str) -> ProviderHealth:
        """Get or create health tracker for a provider."""
        if provider not in self._providers:
            self._providers[provider] = ProviderHealth(provider=provider)
        return self._providers[provider]

    def record_success(self, provider: str, latency_ms: int):
        """Record a successful request."""
        self.get_health(provider).record_success(latency_ms)
        # Queue for database persistence
        self._queue_write(provider, True, latency_ms, None, None)

    def record_failure(self, provider: str, error_type: str, error_message: str, latency_ms: int = 0):
        """Record a failed request."""
        self.get_health(provider).record_failure(error_type, error_message, latency_ms)
        # Queue for database persistence
        self._queue_write(provider, False, latency_ms, error_type, error_message)

    def _queue_write(self, provider: str, is_success: bool, latency_ms: int,
                     error_type: Optional[str], error_message: Optional[str]):
        """Queue a health record for async database write."""
        self._pending_writes.append({
            "provider": provider,
            "is_success": is_success,
            "latency_ms": latency_ms if latency_ms > 0 else None,
            "error_type": error_type,
            "error_message": error_message,
            "created_at": datetime.now(timezone.utc),
        })

        # Start the background write task if not running
        if self._write_task is None or self._write_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._write_task = loop.create_task(self._flush_writes())
            except RuntimeError:
                # No running loop - writes will be flushed later
                pass

    async def _flush_writes(self):
        """Flush pending writes to the database."""
        # Small delay to batch multiple writes together
        await asyncio.sleep(0.5)

        if not self._pending_writes:
            return

        # Grab all pending writes
        writes = self._pending_writes[:]
        self._pending_writes = []

        try:
            from app.database import async_session
            from app.models import ProviderHealthRecord

            async with async_session() as session:
                for write in writes:
                    record = ProviderHealthRecord(
                        provider=write["provider"],
                        is_success=write["is_success"],
                        latency_ms=write["latency_ms"],
                        error_type=write["error_type"],
                        error_message=write["error_message"],
                        created_at=write["created_at"],
                    )
                    session.add(record)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist health records: {e}")
            # Put writes back for retry (at the front)
            self._pending_writes = writes + self._pending_writes

    async def load_from_database(self):
        """Load recent health records from database on startup."""
        if self._db_initialized:
            return

        try:
            from app.database import async_session
            from app.models import ProviderHealthRecord
            from sqlalchemy import select

            # Load records from the last 24 hours (matching WINDOW_SECONDS)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

            async with async_session() as session:
                result = await session.execute(
                    select(ProviderHealthRecord)
                    .where(ProviderHealthRecord.created_at >= cutoff)
                    .order_by(ProviderHealthRecord.created_at.asc())
                )
                records = result.scalars().all()

                for record in records:
                    health = self.get_health(record.provider)
                    # Convert datetime to timestamp
                    timestamp = record.created_at.timestamp()
                    health.load_historical_record(
                        timestamp=timestamp,
                        is_success=record.is_success,
                        latency_ms=record.latency_ms,
                        error_type=record.error_type,
                        error_message=record.error_message,
                    )

                logger.info(f"Loaded {len(records)} health records from database")

            self._db_initialized = True

        except Exception as e:
            logger.error(f"Failed to load health records from database: {e}")

    async def cleanup_old_records(self):
        """Remove records older than 1 hour to prevent database bloat."""
        try:
            from app.database import async_session
            from app.models import ProviderHealthRecord
            from sqlalchemy import delete

            # Keep 48 hours of data (well beyond the 24-hour window needed)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

            async with async_session() as session:
                result = await session.execute(
                    delete(ProviderHealthRecord)
                    .where(ProviderHealthRecord.created_at < cutoff)
                )
                await session.commit()
                if result.rowcount > 0:
                    logger.info(f"Cleaned up {result.rowcount} old health records")

        except Exception as e:
            logger.error(f"Failed to cleanup old health records: {e}")

    def get_status(self, provider: str) -> ProviderStatus:
        """Get current status for a provider."""
        return self.get_health(provider).status

    def get_all_health(self) -> dict[str, dict]:
        """Get health data for all tracked providers."""
        return {
            provider: health.to_dict()
            for provider, health in self._providers.items()
        }

    def get_summary(self) -> dict:
        """Get summary of all provider health for /health endpoint."""
        all_health = self.get_all_health()

        unhealthy = [p for p, h in all_health.items() if h["status"] == "unhealthy"]
        degraded = [p for p, h in all_health.items() if h["status"] == "degraded"]

        return {
            "providers": all_health,
            "unhealthy_providers": unhealthy,
            "degraded_providers": degraded,
            "all_healthy": len(unhealthy) == 0 and len(degraded) == 0,
        }


# Global instance
provider_health = ProviderHealthTracker()
