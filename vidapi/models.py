"""Pydantic models for vidapi API."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Site(str, Enum):
    BILIBILI = "BiliBili"
    YOUTUBE = "Youtube"


class DownloadMode(str, Enum):
    AV = "完整视频（画面+声音）"
    VIDEO_ONLY = "仅视频（无声音）"
    AUDIO_ONLY = "仅音频"


class Quality(str, Enum):
    BEST = "最佳"
    P2160 = "2160p / 4K"
    P1440 = "1440p / 2K"
    P1080 = "1080p"
    P720 = "720p"
    P480 = "480p"
    P360 = "360p"


class SubtitleLanguage(str, Enum):
    NATIVE = "原生"
    ZH = "中文"
    EN = "英文"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CreateTaskRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, description="List of video URLs to download")
    download_mode: DownloadMode = Field(default=DownloadMode.AV, description="Download mode")
    quality: Quality = Field(default=Quality.BEST, description="Video quality")
    proxy: Optional[str] = Field(default=None, description="Proxy URL (http/socks)")
    cookie_header: Optional[str] = Field(default=None, description="Raw Cookie header for BiliBili")
    subtitle_language: SubtitleLanguage = Field(default=SubtitleLanguage.NATIVE, description="Subtitle language preference")
    embed_subtitles: bool = Field(default=True, description="Embed subtitles into video file")

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one URL is required")
        return v


class TaskResponse(BaseModel):
    task_id: str
    urls: list[str]
    state: TaskStatus
    progress_pct: float = 0.0
    current_file: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    download_dir: Optional[str] = None
    download_mode: DownloadMode
    quality: Quality
    subtitle_language: SubtitleLanguage = SubtitleLanguage.NATIVE
    embed_subtitles: bool = True

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


class CookieUploadRequest(BaseModel):
    cookie_header: str = Field(..., description="Raw Cookie: header string (e.g., 'SESSDATA=xxx; bili_jct=yyy')")


class CookieStatusResponse(BaseModel):
    ok: bool
    online: bool
    message: str


class SystemInfoResponse(BaseModel):
    downloads_folder: str
    ffmpeg_available: bool
    ffmpeg_path: Optional[str] = None
    proxy_detected: Optional[str] = None
    yt_dlp_version: str
    platform: str


class ConfigResponse(BaseModel):
    download_dir: str = ""
    proxy: str = ""
    quality: Quality = Quality.BEST
    download_mode: DownloadMode = DownloadMode.AV
    concurrency: int = 3
    auto_merge: bool = True
    cookie_header: str = ""


class ConfigUpdate(BaseModel):
    download_dir: Optional[str] = None
    proxy: Optional[str] = None
    quality: Optional[Quality] = None
    download_mode: Optional[DownloadMode] = None
    concurrency: Optional[int] = Field(default=None, ge=1, le=16)
    auto_merge: Optional[bool] = None
    cookie_header: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[dict[str, Any]] = None


class ProgressEvent(BaseModel):
    event: str  # "progress", "log", "state_change", "complete", "error"
    data: dict[str, Any]

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"