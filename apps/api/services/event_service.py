"""Redis-backed SSE event bus for cross-process real-time events."""
import asyncio
import json
from typing import AsyncGenerator
import redis.asyncio as aioredis
from ..config import settings

_pool = None


def _get_redis():
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return aioredis.Redis(connection_pool=_pool)


async def publish(project_id: str, event_type: str, payload: dict) -> None:
    """Publish an event to a Redis channel for the project."""
    r = _get_redis()
    message = json.dumps({"type": event_type, "payload": payload})
    await r.publish(f"project:{project_id}", message)


def publish_sync(project_id: str, event_type: str, payload: dict) -> None:
    """Sync counterpart to publish(), for the (sync-style) route handlers -
    same pattern tasks/transcode_tasks.py's _publish_event uses from Celery.
    Best-effort: a Redis hiccup here must never fail the request that
    triggered it (e.g. posting a comment).
    """
    try:
        from .redis_service import get_redis
        r = get_redis()
        message = json.dumps({"type": event_type, "payload": payload})
        r.publish(f"project:{project_id}", message)
    except Exception:
        pass


async def event_stream(project_id: str) -> AsyncGenerator[str, None]:
    """Subscribe to a Redis channel and yield SSE messages."""
    r = _get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"project:{project_id}")
    try:
        while True:
            try:
                message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=30.0)
                if message and message["type"] == "message":
                    try:
                        parsed = json.loads(message["data"])
                        event_type = parsed.get("type", "message")
                        payload = json.dumps(parsed.get("payload", parsed))
                        yield f"event: {event_type}\ndata: {payload}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        yield f"data: {message['data']}\n\n"
                else:
                    yield ": keepalive\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        await pubsub.unsubscribe(f"project:{project_id}")
        await pubsub.aclose()
