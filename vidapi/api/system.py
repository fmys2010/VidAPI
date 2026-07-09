"""System info endpoint."""

from fastapi import APIRouter, Depends

from vidapi.models import SystemInfoResponse
from vidapi.core import get_ffmpeg_location, detect_system_proxy, get_downloads_folder
from vidapi.task_manager import TaskManager


router = APIRouter(prefix="/system", tags=["system"])


def get_task_manager() -> TaskManager:
    from vidapi.main import get_task_manager as _get_task_manager
    return _get_task_manager()


@router.get("/info", response_model=SystemInfoResponse)
async def system_info(
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Get system information."""
    import platform
    import yt_dlp

    ffmpeg_path, ffmpeg_error = get_ffmpeg_location()
    proxy = detect_system_proxy()
    downloads_folder = get_downloads_folder()

    return SystemInfoResponse(
        downloads_folder=str(downloads_folder),
        ffmpeg_available=ffmpeg_path is not None,
        ffmpeg_path=ffmpeg_path,
        proxy_detected=proxy,
        yt_dlp_version=yt_dlp.version.__version__,
        platform=platform.system(),
    )