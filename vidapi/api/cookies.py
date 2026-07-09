"""Cookie management endpoints for BiliBili."""

from fastapi import APIRouter, Depends, HTTPException, status

from vidapi.models import CookieUploadRequest, CookieStatusResponse
from vidapi.task_manager import TaskManager


router = APIRouter(prefix="/cookies/bilibili", tags=["cookies"])


def get_task_manager() -> TaskManager:
    from vidapi.main import get_task_manager as _get_task_manager
    return _get_task_manager()


@router.post("", response_model=CookieStatusResponse, status_code=status.HTTP_200_OK)
async def upload_cookie(
    request: CookieUploadRequest,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Upload and store a raw BiliBili cookie header."""
    # Verify the cookie first
    result = await task_manager.verify_bilibili_cookie(request.cookie_header)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])

    # Store in config
    config = task_manager.config
    config.cookie_header = request.cookie_header

    return CookieStatusResponse(
        ok=True,
        online=result.get("online", True),
        message="Cookie header stored and verified"
    )


@router.get("/status", response_model=CookieStatusResponse)
async def cookie_status(
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Check status of stored BiliBili cookie."""
    cookie_header = task_manager.config.cookie_header
    if not cookie_header:
        return CookieStatusResponse(
            ok=False,
            online=False,
            message="No cookie header stored"
        )

    result = await task_manager.verify_bilibili_cookie(cookie_header)
    return CookieStatusResponse(**result)