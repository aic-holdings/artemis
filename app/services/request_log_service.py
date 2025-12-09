"""
Request logging service - handles structured logging of proxy requests to the database.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models import RequestLog


def generate_request_id() -> str:
    """Generate a unique request ID for correlation."""
    return str(uuid.uuid4())


class RequestLogService:
    """Service for logging proxy requests to the database."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def start_request(
        self,
        request_id: str,
        provider: str,
        endpoint: str,
        api_key_id: Optional[str] = None,
        model: Optional[str] = None,
        method: str = "POST",
        is_streaming: bool = False,
        app_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_metadata: Optional[dict] = None,
        attempt_number: int = 1,
    ) -> RequestLog:
        """
        Log the start of a request.

        Returns the created RequestLog for later update.
        """
        log = RequestLog(
            request_id=request_id,
            api_key_id=api_key_id,
            provider=provider,
            model=model,
            endpoint=endpoint,
            method=method,
            is_streaming=is_streaming,
            app_id=app_id,
            client_ip=client_ip,
            user_agent=user_agent,
            request_metadata=request_metadata,
            attempt_number=attempt_number,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def complete_request(
        self,
        log_id: str,
        status_code: int,
        latency_ms: int,
        response_metadata: Optional[dict] = None,
    ) -> Optional[RequestLog]:
        """
        Mark a request as completed successfully.
        """
        result = await self.db.execute(
            select(RequestLog).where(RequestLog.id == log_id)
        )
        log = result.scalar_one_or_none()
        if not log:
            return None

        log.status_code = status_code
        log.completed_at = datetime.now(timezone.utc)
        log.latency_ms = latency_ms
        log.response_metadata = response_metadata
        await self.db.commit()
        return log

    async def fail_request(
        self,
        log_id: str,
        error_type: str,
        error_message: str,
        status_code: Optional[int] = None,
        latency_ms: Optional[int] = None,
        was_retried: bool = False,
    ) -> Optional[RequestLog]:
        """
        Mark a request as failed with error details.
        """
        result = await self.db.execute(
            select(RequestLog).where(RequestLog.id == log_id)
        )
        log = result.scalar_one_or_none()
        if not log:
            return None

        log.status_code = status_code
        log.error_type = error_type
        log.error_message = error_message
        log.completed_at = datetime.now(timezone.utc)
        log.latency_ms = latency_ms
        log.was_retried = was_retried
        await self.db.commit()
        return log

    async def get_recent_errors(
        self,
        provider: Optional[str] = None,
        limit: int = 50,
    ) -> list[RequestLog]:
        """
        Get recent failed requests for debugging.
        """
        query = select(RequestLog).where(RequestLog.error_type.isnot(None))
        if provider:
            query = query.where(RequestLog.provider == provider)
        query = query.order_by(RequestLog.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_error_stats(
        self,
        since: datetime,
        provider: Optional[str] = None,
    ) -> dict:
        """
        Get error statistics for a time period.
        """
        conditions = [
            RequestLog.created_at >= since,
        ]
        if provider:
            conditions.append(RequestLog.provider == provider)

        # Total requests
        total_result = await self.db.execute(
            select(func.count(RequestLog.id)).where(and_(*conditions))
        )
        total_requests = total_result.scalar() or 0

        # Failed requests
        error_conditions = conditions + [RequestLog.error_type.isnot(None)]
        error_result = await self.db.execute(
            select(func.count(RequestLog.id)).where(and_(*error_conditions))
        )
        failed_requests = error_result.scalar() or 0

        # Error breakdown by type
        error_types_result = await self.db.execute(
            select(RequestLog.error_type, func.count(RequestLog.id))
            .where(and_(*error_conditions))
            .group_by(RequestLog.error_type)
        )
        error_breakdown = {row[0]: row[1] for row in error_types_result}

        # Retry count
        retry_result = await self.db.execute(
            select(func.count(RequestLog.id)).where(
                and_(*conditions, RequestLog.was_retried == True)
            )
        )
        retried_requests = retry_result.scalar() or 0

        return {
            "total_requests": total_requests,
            "failed_requests": failed_requests,
            "error_rate": (failed_requests / total_requests * 100) if total_requests > 0 else 0,
            "retried_requests": retried_requests,
            "error_breakdown": error_breakdown,
        }

    async def get_latency_stats(
        self,
        since: datetime,
        provider: Optional[str] = None,
    ) -> dict:
        """
        Get latency statistics for a time period.
        """
        conditions = [
            RequestLog.created_at >= since,
            RequestLog.latency_ms.isnot(None),
            RequestLog.error_type.is_(None),  # Only successful requests
        ]
        if provider:
            conditions.append(RequestLog.provider == provider)

        result = await self.db.execute(
            select(
                func.count(RequestLog.id),
                func.avg(RequestLog.latency_ms),
                func.min(RequestLog.latency_ms),
                func.max(RequestLog.latency_ms),
            ).where(and_(*conditions))
        )
        row = result.one()

        return {
            "count": row[0] or 0,
            "avg_latency_ms": round(row[1]) if row[1] else 0,
            "min_latency_ms": row[2] or 0,
            "max_latency_ms": row[3] or 0,
        }
