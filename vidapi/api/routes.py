"""Main API routes for tasks."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from vidapi.models import (
    CreateTaskRequest,
    TaskResponse,
    TaskListResponse,
    TaskStatus,
    Site,
    DownloadMode,
    Quality,
)
from vidapi.task_manager import TaskManager


router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_task_manager() -> TaskManager:
    from vidapi.main import get_task_manager as _get_task_manager
    return _get_task_manager()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: CreateTaskRequest,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Create a new download task."""
    # Validate URLs - at least one should be BiliBili or YouTube
    valid_urls = []
    for url in request.urls:
        site = task_manager.classify_site(url)
        if site:
            valid_urls.append(url)
        else:
            # Still allow but will be skipped
            valid_urls.append(url)

    if not valid_urls:
        raise HTTPException(status_code=422, detail="No valid BiliBili or YouTube URLs provided")

    task_id = await task_manager.create_task({
        "urls": valid_urls,
        "download_mode": request.download_mode,
        "quality": request.quality,
        "proxy": request.proxy,
        "cookie_header": request.cookie_header,
    })

    # Start download in background
    import asyncio
    asyncio.create_task(task_manager.run_download(task_id))

    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=500, detail="Failed to create task")

    return TaskResponse(**task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    state: Optional[TaskStatus] = Query(None, description="Filter by task state"),
    site: Optional[Site] = Query(None, description="Filter by site"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    task_manager: TaskManager = Depends(get_task_manager),
):
    """List tasks with optional filters."""
    tasks = await task_manager.list_tasks(state=state, site=site.value if site else None, limit=limit, offset=offset)
    return TaskListResponse(tasks=[TaskResponse(**t) for t in tasks], total=len(tasks))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Get task details."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Cancel and delete a task."""
    success = await task_manager.cancel_task(task_id)
    if not success:
        # Try delete even if not cancellable
        deleted = await task_manager.delete_task(task_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Cancel a running or pending task."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["state"] not in ("pending", "downloading"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel task in state: {task['state']}")

    await task_manager.cancel_task(task_id)
    return {"message": "Task cancelled"}