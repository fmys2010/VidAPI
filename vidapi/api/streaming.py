"""SSE streaming endpoint for task progress."""

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from vidapi.task_manager import TaskManager


router = APIRouter(prefix="/tasks", tags=["streaming"])


def get_task_manager() -> TaskManager:
    from vidapi.main import get_task_manager as _get_task_manager
    return _get_task_manager()


def make_sse_event(event: str, data: dict) -> str:
    """Format an SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Stream task progress via Server-Sent Events."""
    # Verify task exists
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        queue, sub_id = task_manager.subscribe(task_id)
        try:
            # Send initial state
            yield make_sse_event("state_change", {
                "task_id": task_id,
                "state": task["state"],
                "progress": task["progress_pct"],
            })

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # event is a dict from task_manager; serialize to SSE format
                    if isinstance(event, dict):
                        yield make_sse_event(event.get("event", "progress"), event.get("data", {}))
                    else:
                        yield event
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield ": heartbeat\n\n"
                except Exception:
                    break
        finally:
            # unsubscribe this client
            task_manager.unsubscribe(task_id, sub_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )