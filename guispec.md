# vidapi GUI Specification

## Overview
Desktop GUI application for YouTube and BiliBili video downloading, built with tkinter.

## Architecture
```
vidapi/
├── gui/
│   └── app.py          # Main GUI application
├── run_gui.py          # Entry point for GUI
└── main.py             # FastAPI backend (must be running)
```

## Features

### 1. URL Input
- **Widget**: ScrolledText
- **Placeholder**: "粘贴 YouTube 或 BiliBili 链接，支持多个链接"
- **Auto-parsing**: Parses URLs as user types
- **Multi-line support**: Supports pasting multiple URLs at once
- **Concatenated URLs**: Handles URLs pasted without separators

### 2. URL Chip Display
- **Visual**: Colored tags for each parsed URL
- **YouTube**: Red background (#ff0000)
- **BiliBili**: Blue background (#00a1d6)
- **Interactive**: Click × to remove individual URLs
- **Limit**: Shows max 10 chips
- **Counter**: Displays "解析到的链接: N 个"

### 3. Settings Section
- **Quality Selection** (Combobox):
  - 最佳
  - 2160p / 4K
  - 1440p / 2K
  - 1080p
  - 720p
  - 480p
  - 360p
  - Default: 最佳

- **Download Mode Selection** (Combobox):
  - 完整视频（画面+声音）
  - 仅视频（无声音）
  - 仅音频
  - Default: 完整视频（画面+声音）

### 4. Action Buttons
- **开始下载** (Primary):
  - Creates task via POST /api/v1/tasks
  - Disabled when no URLs
  - Disabled while download is running
  
- **取消** (Danger):
  - Sends POST /api/v1/tasks/{id}/cancel
  - Only enabled while download is running

- **清空** (Secondary):
  - Clears all input fields
  - Resets URL chips

### 5. Progress Section
- **Task Info**:
  - 任务 ID: Shows task UUID
  - 状态: Shows current state (等待中/下载中/已完成/失败/已取消)
  - 当前文件: Shows filename being downloaded

- **Progress Bar**:
  - Horizontal progress bar
  - 0-100% range
  - Smooth updates from SSE

- **Progress Text**:
  - Shows percentage (e.g., "45%")
  - Updates in real-time

### 6. Log Section
- **Display**: ScrolledText with dark theme
- **Colors**:
  - Info: #79c0ff (light blue)
  - Success: #7ee787 (light green)
  - Warning: #ffa657 (orange)
  - Error: #ff7b72 (red)
  - Time: #858585 (gray)
- **Auto-scroll**: Always scrolls to latest message
- **Limit**: Max 500 lines
- **Clear Button**: 清空日志

## Color Scheme

| Element | Color | Usage |
|---------|-------|-------|
| bg_primary | #f8f9fa | Window background |
| bg_secondary | #ffffff | Card backgrounds |
| text_primary | #212529 | Primary text |
| text_secondary | #6c757d | Secondary text |
| accent | #0d6efd | Primary actions, links |
| success | #198754 | Success states |
| danger | #dc3545 | Danger actions, errors |
| warning | #ffc107 | Warnings |
| border | #dee2e6 | Borders |

## Dependencies

### Required
- Python 3.7+
- tkinter (built-in)
- requests (for API calls)

### Installation
```bash
pip install requests
```

## Usage

### Start FastAPI backend
```bash
./run.sh  # Runs on http://localhost:8000
```

### Start GUI
```bash
python run_gui.py
```

### Workflow
1. Paste YouTube/BiliBili URLs in the input area
2. URLs are automatically parsed and displayed as chips
3. Select quality and download mode
4. Click "开始下载"
5. Monitor progress bar and log output
6. Click "取消" to cancel if needed

## API Integration

| Action | Endpoint | Method | Payload |
|--------|----------|--------|---------|
| Create Task | /api/v1/tasks | POST | {urls, download_mode, quality} |
| Task Stream | /api/v1/tasks/{id}/stream | GET | SSE stream |
| Cancel Task | /api/v1/tasks/{id}/cancel | POST | - |

## Error Handling

- Network errors: Shown in log with "错误:" prefix
- Invalid URLs: Filtered out during parsing
- API errors: Displayed in log and messagebox
- Connection failures: Auto-retry not implemented (single attempt)

## Threading

- **Main Thread**: UI updates only
- **Download Thread**: Background thread for API calls
- **SSE Streaming**: Runs in download thread
- **Log Queue**: Thread-safe queue for log messages

## Limitations

- Single download at a time (no queue)
- No task persistence in GUI (clears on close)
- No cookie management UI
- No config persistence in GUI
- No history of past downloads
- Requires backend server to be running

## Future Enhancements

- [ ] Task queue (multiple downloads)
- [ ] Download history
- [ ] Cookie management UI
- [ ] Config persistence
- [ ] Save/load presets
- [ ] Drag & drop URL input
- [ ] System tray integration
- [ ] Notifications
