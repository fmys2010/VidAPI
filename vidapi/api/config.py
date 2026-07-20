"""Configuration endpoints."""

from fastapi import APIRouter, Depends, HTTPException

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
        # ponytail: Config stores raw str ("1080p"). update.quality is a Quality
        # enum (pydantic coerces "1080p" -> Quality.P1080). Store its .value,
        # not the enum — str(Quality.P1080) is "Quality.P1080" on Python 3.13
        # and that bogus string would break the next ConfigResponse validation.
        config.quality = update.quality.value
    if update.download_mode is not None:
        config.download_mode = update.download_mode.value
    if update.concurrency is not None and update.concurrency != config.concurrency:
        if task_manager.has_running_tasks():
            raise HTTPException(
                status_code=409,
                detail="Cannot change concurrency while downloads are active or queued; "
                "cancel or wait for them to finish",
            )
        config.concurrency = update.concurrency
        task_manager.resize_executor(update.concurrency)
    if update.auto_merge is not None:
        config.auto_merge = update.auto_merge
    if update.cookie_header is not None:
        config.cookie_header = update.cookie_header

    return await get_config(task_manager)
