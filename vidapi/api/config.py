"""Configuration endpoints."""

from fastapi import APIRouter, Depends

from vidapi.models import ConfigResponse, ConfigUpdate
from vidapi.task_manager import TaskManager


router = APIRouter(prefix="/config", tags=["config"])


def get_task_manager() -> TaskManager:
    from vidapi.main import get_task_manager as _get_task_manager
    return _get_task_manager()


@router.get("", response_model=ConfigResponse)
async def get_config(
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Get current configuration."""
    config = task_manager.config
    return ConfigResponse(
        download_dir=config.download_dir or "",
        proxy=config.proxy or "",
        quality=config.quality,
        download_mode=config.download_mode,
        concurrency=config.concurrency,
        auto_merge=config.auto_merge,
        cookie_header=config.cookie_header or "",
    )


@router.put("", response_model=ConfigResponse)
async def update_config(
    update: ConfigUpdate,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Update configuration (partial update allowed)."""
    config = task_manager.config

    if update.download_dir is not None:
        config.download_dir = update.download_dir
    if update.proxy is not None:
        config.proxy = update.proxy
    if update.quality is not None:
        config.quality = update.quality
    if update.download_mode is not None:
        config.download_mode = update.download_mode
    if update.concurrency is not None:
        config.concurrency = update.concurrency
        # Recreate executor with new concurrency - don't wait for running tasks
        task_manager.executor.shutdown(wait=False, cancel_futures=True)
        from concurrent.futures import ThreadPoolExecutor
        task_manager.executor = ThreadPoolExecutor(max_workers=update.concurrency)
    if update.auto_merge is not None:
        config.auto_merge = update.auto_merge
    if update.cookie_header is not None:
        config.cookie_header = update.cookie_header

    return await get_config(task_manager)