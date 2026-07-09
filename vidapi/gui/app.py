"""vidapi - Desktop GUI Application
Modern, restrained GUI for YouTube/BiliBili video downloader.
Uses tkinter (built-in) with custom styling.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from pathlib import Path
from queue import Queue
from typing import Any

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog


class GUIApp:
    """Main GUI application for vidapi."""

    # Color scheme - modern dark theme
    COLORS = {
        "bg_primary": "#0d1117",          # Main background - very dark
        "bg_secondary": "#161b22",        # Secondary background - panels
        "bg_card": "#161b22",             # Card background
        "bg_hover": "#21262d",            # Hover states
        "text_primary": "#e6edf3",        # Primary text - high contrast
        "text_secondary": "#8b949e",      # Secondary text - muted
        "text_muted": "#6e7681",          # Muted text
        "accent": "#58a6ff",              # Blue accent - bright for dark bg
        "accent_hover": "#388bfd",
        "accent_active": "#1f6feb",
        "success": "#3fb950",
        "success_hover": "#2ea043",
        "danger": "#f85149",
        "danger_hover": "#da3633",
        "warning": "#d29922",
        "border": "#30363d",              # Subtle borders
        "border_focus": "#58a6ff",        # Focus borders
        "input_bg": "#0d1117",            # Input backgrounds
        "log_bg": "#0d1117",              # Log background
    }

    # Quality options
    QUALITY_OPTIONS = [
        "最佳",
        "2160p / 4K",
        "1440p / 2K", 
        "1080p",
        "720p",
        "480p",
        "360p",
    ]

    # Download mode options
    MODE_OPTIONS = [
        "完整视频（画面+声音）",
        "仅视频（无声音）",
        "仅音频",
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("vidapi - 视频下载")
        self.root.geometry("1000x850")
        self.root.minsize(900, 750)
        
        # Set window icon (placeholder)
        try:
            self.root.iconname("vidapi")
        except:
            pass

        # Configure styles
        self.configure_styles()
        
        # State
        self.current_task_id: str | None = None
        self.running = False
        self.log_queue = Queue()
        
        # Create UI
        self.create_widgets()
        
        # Start log processor
        self.root.after(100, self.process_log_queue)

    def configure_styles(self):
        """Configure custom ttk styles for modern dark theme."""
        style = ttk.Style()
        
        # Use clam theme (most customizable)
        style.theme_use("clam")
        
        # Configure colors
        bg = self.COLORS["bg_primary"]
        card_bg = self.COLORS["bg_card"]
        accent = self.COLORS["accent"]
        text = self.COLORS["text_primary"]
        text_secondary = self.COLORS["text_secondary"]
        border = self.COLORS["border"]
        input_bg = self.COLORS["input_bg"]
        hover_bg = self.COLORS["bg_hover"]
        
        # Frame style
        style.configure("TFrame", background=bg)
        
        # Card frame
        style.configure("Card.TFrame", background=card_bg, bordercolor=border)
        
        # Labels
        style.configure("TLabel", background=bg, foreground=text, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=card_bg, foreground=text, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), background=bg, foreground=text)
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), background=bg, foreground=text_secondary)
        
        # Buttons
        style.configure("TButton", font=("Segoe UI", 10), bordercolor=border, background=card_bg, foreground=text)
        style.map("TButton", 
                  background=[("active", hover_bg), ("pressed", border)],
                  foreground=[("active", text), ("pressed", text)])
        
        # Primary button
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), bordercolor=accent, foreground="white")
        style.map("Primary.TButton", 
                  background=[("active", self.COLORS["accent_hover"]), ("pressed", self.COLORS["accent_active"])],
                  bordercolor=[("active", self.COLORS["accent_hover"]), ("pressed", self.COLORS["accent_active"])])
        
        # Danger button
        style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), bordercolor=self.COLORS["danger"], foreground="white")
        style.map("Danger.TButton",
                  background=[("active", self.COLORS["danger_hover"]), ("pressed", self.COLORS["danger"])],
                  bordercolor=[("active", self.COLORS["danger_hover"]), ("pressed", self.COLORS["danger"])])
        
        # Combobox
        style.configure("TCombobox", font=("Segoe UI", 10), bordercolor=border, fieldbackground=input_bg, background=card_bg, foreground=text)
        style.map("TCombobox",
                  fieldbackground=[("readonly", input_bg)],
                  background=[("readonly", input_bg)],
                  foreground=[("readonly", text)],
                  selectbackground=[("readonly", accent)],
                  selectforeground=[("readonly", "white")])
        
        # Entry
        style.configure("TEntry", font=("Consolas", 10), bordercolor=border, fieldbackground=input_bg, foreground=text, insertcolor=text)
        style.map("TEntry",
                  fieldbackground=[("focus", input_bg)],
                  bordercolor=[("focus", self.COLORS["border_focus"])])
        
        # Progress bar
        style.configure("TProgressbar", thickness=8, background=accent, troughcolor=self.COLORS["bg_primary"], bordercolor=border)
        style.configure("Horizontal.TProgressbar", troughcolor=self.COLORS["bg_primary"], bordercolor=border)
        
        # Notebook (tabs)
        style.configure("TNotebook", background=bg, bordercolor=border, tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab", font=("Segoe UI", 10), padding=[12, 6], background=card_bg, foreground=text_secondary, bordercolor=border)
        style.map("TNotebook.Tab",
                  background=[("selected", card_bg), ("active", hover_bg)],
                  foreground=[("selected", accent), ("active", text)],
                  bordercolor=[("selected", accent)])
        
        # Root background
        self.root.configure(background=bg)

    def create_widgets(self):
        """Create all UI widgets."""
        self.create_header()
        self.create_input_section()
        self.create_settings_section()
        self.create_progress_section()
        self.create_log_section()

    def create_header(self):
        """Create header with title and subtitle."""
        header_frame = ttk.Frame(self.root, style="TFrame")
        header_frame.pack(fill="x", padx=20, pady=20)
        
        title = ttk.Label(header_frame, text="vidapi", style="Title.TLabel")
        title.pack(side="left")
        
        subtitle = ttk.Label(header_frame, text="YouTube & BiliBili 视频下载", style="Subtitle.TLabel")
        subtitle.pack(side="left", padx=(10, 0))
        
        # Add links on right
        links_frame = ttk.Frame(header_frame, style="TFrame")
        links_frame.pack(side="right")
        
        api_docs_btn = ttk.Button(links_frame, text="API 文档", command=lambda: webbrowser.open("http://localhost:8000/docs"))
        api_docs_btn.pack(side="left", padx=5)

    def create_input_section(self):
        """Create URL input section with card."""
        card = ttk.Frame(self.root, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=20, pady=10)
        
        # Title
        title = ttk.Label(card, text="视频链接", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w", pady=(0, 10))
        
        # URL input
        self.url_text = scrolledtext.ScrolledText(
            card, 
            wrap=tk.WORD,
            height=6,
            width=80,
            font=("Consolas", 10),
            bg=self.COLORS["input_bg"],
            fg=self.COLORS["text_primary"],
            insertbackground=self.COLORS["text_primary"],
            selectbackground=self.COLORS["accent"],
            selectforeground="white",
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightcolor=self.COLORS["border_focus"],
            highlightbackground=self.COLORS["border"],
        )
        self.url_text.pack(fill="x", expand=True)
        self.url_text.insert("1.0", "粘贴 YouTube 或 BiliBili 链接，支持多个链接\n例如: https://youtu.be/abc123\n       https://b23.tv/xyz789")
        self.url_text.bind("<FocusIn>", lambda e: self.clear_placeholder())
        self.url_text.bind("<KeyRelease>", lambda e: self.on_url_change())
        
        # URL chips display
        self.url_chips_frame = ttk.Frame(card, style="Card.TFrame")
        self.url_chips_frame.pack(fill="x", pady=(10, 0))
        
        # Parsed URLs label
        self.urls_label = ttk.Label(self.url_chips_frame, text="解析到的链接: 0 个", style="Card.TLabel", foreground=self.COLORS["text_secondary"])
        self.urls_label.pack(anchor="w")

    def create_settings_section(self):
        """Create settings section with quality and mode selection."""
        card = ttk.Frame(self.root, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=20, pady=10)
        
        title = ttk.Label(card, text="下载设置", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w", pady=(0, 15))
        
        # Grid for settings
        settings_frame = ttk.Frame(card, style="Card.TFrame")
        settings_frame.pack(fill="x")
        
        # Quality
        ttk.Label(settings_frame, text="清晰度:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.quality_var = tk.StringVar(value=self.QUALITY_OPTIONS[0])
        quality_combo = ttk.Combobox(settings_frame, textvariable=self.quality_var, values=self.QUALITY_OPTIONS, state="readonly", width=15)
        quality_combo.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        
        # Download mode
        ttk.Label(settings_frame, text="下载模式:", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(20, 5), pady=5)
        self.mode_var = tk.StringVar(value=self.MODE_OPTIONS[0])
        mode_combo = ttk.Combobox(settings_frame, textvariable=self.mode_var, values=self.MODE_OPTIONS, state="readonly", width=20)
        mode_combo.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        
        # Buttons
        btn_frame = ttk.Frame(card, style="Card.TFrame")
        btn_frame.pack(fill="x", pady=(15, 0))
        
        self.start_btn = ttk.Button(btn_frame, text="开始下载", style="Primary.TButton", command=self.start_download)
        self.start_btn.pack(side="left", padx=5)
        
        self.cancel_btn = ttk.Button(btn_frame, text="取消", style="Danger.TButton", command=self.cancel_download, state="disabled")
        self.cancel_btn.pack(side="left", padx=5)
        
        # Clear button
        clear_btn = ttk.Button(btn_frame, text="清空", command=self.clear_all)
        clear_btn.pack(side="right", padx=5)

    def create_progress_section(self):
        """Create progress display section."""
        card = ttk.Frame(self.root, style="Card.TFrame", padding=20)
        card.pack(fill="x", padx=20, pady=10)
        
        title = ttk.Label(card, text="下载进度", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w", pady=(0, 15))
        
        # Task info frame
        self.task_info_frame = ttk.Frame(card, style="Card.TFrame")
        self.task_info_frame.pack(fill="x", pady=(0, 15))
        
        # Task ID
        ttk.Label(self.task_info_frame, text="任务 ID:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.task_id_var = tk.StringVar(value="-")
        ttk.Label(self.task_info_frame, textvariable=self.task_id_var, style="Card.TLabel", foreground=self.COLORS["accent"]).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        # Status
        ttk.Label(self.task_info_frame, text="状态:", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(20, 5), pady=2)
        self.status_var = tk.StringVar(value="等待中")
        self.status_label = ttk.Label(self.task_info_frame, textvariable=self.status_var, style="Card.TLabel")
        self.status_label.grid(row=0, column=3, sticky="w", padx=5, pady=2)
        
        # Current file
        ttk.Label(self.task_info_frame, text="当前文件:", style="Card.TLabel").grid(row=0, column=4, sticky="w", padx=(20, 5), pady=2)
        self.file_var = tk.StringVar(value="-")
        ttk.Label(self.task_info_frame, textvariable=self.file_var, style="Card.TLabel").grid(row=0, column=5, sticky="w", padx=5, pady=2)
        
        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(card, variable=self.progress_var, maximum=100, style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(10, 5))
        
        # Progress text
        self.progress_text_var = tk.StringVar(value="0%")
        ttk.Label(card, textvariable=self.progress_text_var, style="Card.TLabel", foreground=self.COLORS["text_secondary"]).pack(anchor="center")

    def create_log_section(self):
        """Create log display section."""
        card = ttk.Frame(self.root, style="Card.TFrame", padding=20)
        card.pack(fill="both", expand=True, padx=20, pady=10)
        
        top_frame = ttk.Frame(card, style="Card.TFrame")
        top_frame.pack(fill="x")
        
        title = ttk.Label(top_frame, text="日志输出", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
        title.pack(side="left", anchor="w")
        
        # Clear logs button
        clear_log_btn = ttk.Button(top_frame, text="清空日志", command=self.clear_logs)
        clear_log_btn.pack(side="right", padx=5)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            card,
            wrap=tk.WORD,
            height=10,
            font=("Consolas", 10),
            bg=self.COLORS["log_bg"],
            fg=self.COLORS["text_primary"],
            insertbackground=self.COLORS["text_primary"],
            selectbackground=self.COLORS["accent"],
            selectforeground="white",
            state="disabled",
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightcolor=self.COLORS["border_focus"],
            highlightbackground=self.COLORS["border"],
        )
        self.log_text.pack(fill="both", expand=True, pady=(10, 0))
        
        # Add initial log message
        self.add_log("vidapi GUI 已启动", "info")

    def clear_placeholder(self):
        """Clear placeholder text on focus."""
        current = self.url_text.get("1.0", "end-1c")
        if "粘贴 YouTube" in current:
            self.url_text.delete("1.0", "end")

    def on_url_change(self):
        """Handle URL input changes."""
        self.parse_urls()

    def parse_urls(self):
        """Parse URLs from input text."""
        text = self.url_text.get("1.0", "end-1c").strip()
        if not text:
            self.update_url_chips([])
            return
        
        # Split by newlines or spaces
        urls = []
        for line in text.split("\n"):
            line = line.strip()
            if line:
                urls.extend(line.split())
        
        # Filter valid URLs
        parsed = []
        for url in urls:
            url = url.strip().rstrip(",.;!? ")
            if not url:
                continue
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            if self.is_valid_video_url(url):
                parsed.append(url)
        
        self.update_url_chips(parsed)

    def is_valid_video_url(self, url: str) -> bool:
        """Check if URL is a valid YouTube or BiliBili URL."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            host = host.lower()
            
            # YouTube
            if "youtube.com" in host or "youtu.be" in host or "youtube-nocookie.com" in host:
                return True
            
            # BiliBili
            if "b23.tv" in host or "bilibili.com" in host:
                return True
            
            return False
        except:
            return False

    def get_site_name(self, url: str) -> str:
        """Get site name from URL."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            host = host.lower()
            
            if "youtube.com" in host or "youtu.be" in host or "youtube-nocookie.com" in host:
                return "YouTube"
            if "b23.tv" in host or "bilibili.com" in host:
                return "BiliBili"
            return "Unknown"
        except:
            return "Unknown"

    def update_url_chips(self, urls: list[str]):
        """Update URL chips display."""
        # Clear existing chips
        for widget in self.url_chips_frame.winfo_children():
            if widget != self.urls_label:
                widget.destroy()
        
        # Update label
        self.urls_label.config(text=f"解析到的链接: {len(urls)} 个")
        
        # Create chips
        self.parsed_urls = urls
        
        for i, url in enumerate(urls[:10]):  # Limit to 10 chips
            site = self.get_site_name(url)
            # Use theme-appropriate colors with good contrast on dark bg
            color = self.COLORS["danger"] if site == "YouTube" else self.COLORS["accent"]
            
            chip = tk.Frame(self.url_chips_frame, bg=color, padx=8, pady=4, relief="flat", borderwidth=0)
            chip.pack(side="left", padx=(0, 5), pady=5)
            
            site_label = tk.Label(chip, text=site, bg=color, fg="white", font=("Segoe UI", 8, "bold"))
            site_label.pack(side="left")
            
            url_label = tk.Label(chip, text=self.shorten_url(url), bg=color, fg="white", font=("Segoe UI", 8))
            url_label.pack(side="left", padx=(4, 0))
            
            remove_btn = tk.Label(chip, text="×", bg=color, fg="white", font=("Segoe UI", 8), cursor="hand2")
            remove_btn.pack(side="left", padx=(4, 0))
            remove_btn.bind("<Button-1>", lambda e, idx=i: self.remove_url(idx))
        
        # Update start button
        self.start_btn.config(state="normal" if urls else "disabled")

    def shorten_url(self, url: str, max_len: int = 20) -> str:
        """Shorten URL for display."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            if "youtu.be" in parsed.hostname:
                path = parsed.path.strip("/")
                return path[:max_len] + "..." if len(path) > max_len else path
            if "b23.tv" in parsed.hostname:
                path = parsed.path.strip("/")
                return path[:max_len] + "..." if len(path) > max_len else path
            if parsed.query:
                return parsed.query.split("&")[0].split("=")[1][:max_len] + "..." if len(parsed.query) > max_len else parsed.query
            return url[:max_len] + "..." if len(url) > max_len else url
        except:
            return url[:max_len] + "..." if len(url) > max_len else url

    def remove_url(self, index: int):
        """Remove URL at index."""
        if 0 <= index < len(self.parsed_urls):
            self.parsed_urls.pop(index)
            self.update_url_chips(self.parsed_urls)
            # Update textarea
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", "\n".join(self.parsed_urls))

    def clear_all(self):
        """Clear all inputs."""
        self.url_text.delete("1.0", "end")
        self.update_url_chips([])
        self.add_log("已清空所有输入", "info")

    def clear_logs(self):
        """Clear log display."""
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.add_log("日志已清空", "info")

    def add_log(self, message: str, level: str = "info"):
        """Add log message."""
        colors = {
            "info": "#79c0ff",
            "success": "#7ee787", 
            "warning": "#ffa657",
            "error": "#ff7b72",
            "time": "#858585",
        }
        color = colors.get(level, "#d4d4d4")
        timestamp = f"[{message[0]}]" if message.startswith("[") else ""
        
        self.log_queue.put((message, color))

    def process_log_queue(self):
        """Process log messages from queue."""
        while not self.log_queue.empty():
            message, color = self.log_queue.get()
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"{message}\n", color)
            self.log_text.see("end")
            self.log_text.config(state="disabled")
            
            # Limit to 500 lines
            lines = self.log_text.get("1.0", "end").split("\n")
            if len(lines) > 500:
                self.log_text.delete("1.0", f"{len(lines) - 400}.0")
        
        self.root.after(100, self.process_log_queue)

    def update_status(self, state: str, message: str = ""):
        """Update task status."""
        self.status_var.set(state)
        
        # Update color - use theme colors
        colors = {
            "等待中": self.COLORS["text_secondary"],
            "下载中": self.COLORS["accent"],
            "已完成": self.COLORS["success"],
            "失败": self.COLORS["danger"],
            "已取消": self.COLORS["danger"],
        }
        self.status_label.config(foreground=colors.get(state, self.COLORS["text_primary"]))
        
        if message:
            self.file_var.set(message)

    def update_progress(self, percent: float, message: str = ""):
        """Update progress bar."""
        self.progress_var.set(min(100, max(0, percent)))
        self.progress_text_var.set(f"{int(percent)}%")
        if message:
            self.add_log(message, "info")

    def start_download(self):
        """Start download task."""
        if not self.parsed_urls:
            messagebox.showwarning("错误", "请输入有效的视频链接")
            return
        
        if self.running:
            messagebox.showwarning("错误", "已有一个下载任务在运行中")
            return
        
        self.running = True
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        
        self.add_log("开始创建下载任务...", "info")
        self.update_status("等待中")
        self.update_progress(0)
        
        # Start download in background thread
        thread = threading.Thread(target=self._start_download_thread, daemon=True)
        thread.start()

    def _start_download_thread(self):
        """Download thread."""
        import requests
        import json
        
        try:
            # Prepare request
            request = {
                "urls": self.parsed_urls,
                "download_mode": self.mode_var.get(),
                "quality": self.quality_var.get(),
            }
            
            self.add_log(f"请求参数: {json.dumps(request, ensure_ascii=False)}", "info")
            
            # Create task
            response = requests.post(
                "http://localhost:8000/api/v1/tasks",
                json=request,
                timeout=30
            )
            
            if response.status_code != 201 and response.status_code != 200:
                error = response.json() if response.text else {}
                self.add_log(f"创建任务失败: {error.get('error', error.get('message', f'HTTP {response.status_code}'))}", "error")
                self.running = False
                self.start_btn.config(state="normal")
                self.cancel_btn.config(state="disabled")
                return
            
            data = response.json()
            task_id = data.get("task_id")
            self.current_task_id = task_id
            
            self.add_log(f"任务创建成功: {task_id}", "success")
            self.task_id_var.set(task_id)
            self.update_status("下载中")
            
            # Start SSE streaming
            self.stream_task_progress(task_id)
            
        except Exception as e:
            self.add_log(f"创建任务时出错: {e}", "error")
            self.running = False
            self.start_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")

    def stream_task_progress(self, task_id: str):
        """Stream task progress via SSE."""
        import requests
        import json
        
        url = f"http://localhost:8000/api/v1/tasks/{task_id}/stream"
        
        try:
            with requests.get(url, stream=True, timeout=30) as response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    
                    line = line.decode("utf-8")
                    if line.startswith("event: "):
                        event = line[7:].strip()
                    elif line.startswith("data: "):
                        data_str = line[6:].strip()
                        try:
                            data = json.loads(data_str)
                            self.handle_sse_event(event, data)
                        except json.JSONDecodeError:
                            self.add_log(f"无法解析数据: {data_str}", "warning")
        except Exception as e:
            self.add_log(f"流连接错误: {e}", "error")
        finally:
            self.running = False
            self.start_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")

    def handle_sse_event(self, event: str, data: dict):
        """Handle SSE event."""
        if event == "state_change":
            state = data.get("state", "")
            state_map = {
                "pending": "等待中",
                "downloading": "下载中", 
                "completed": "已完成",
                "failed": "失败",
                "cancelled": "已取消",
            }
            self.update_status(state_map.get(state, state))
            
        elif event == "progress":
            progress = data.get("progress_pct", 0)
            message = data.get("message", "")
            self.update_progress(float(progress), message)
            
            if data.get("current_file"):
                self.file_var.set(data["current_file"])
                
        elif event == "log":
            message = data.get("message", "")
            if message:
                self.add_log(message, "info")
                
        elif event == "complete":
            success = data.get("success", False)
            if success:
                self.update_status("已完成")
                self.update_progress(100)
                self.add_log("下载完成!", "success")
            else:
                self.update_status("失败")
                self.add_log("下载失败", "error")
                
        elif event == "error":
            error_msg = data.get("error_msg", data.get("message", "未知错误"))
            self.add_log(f"错误: {error_msg}", "error")

    def cancel_download(self):
        """Cancel current download."""
        if not self.current_task_id:
            return
        
        self.add_log(f"取消任务: {self.current_task_id}", "warning")
        
        try:
            import requests
            response = requests.post(
                f"http://localhost:8000/api/v1/tasks/{self.current_task_id}/cancel",
                timeout=10
            )
            if response.ok:
                self.add_log("取消请求已发送", "info")
            else:
                self.add_log("取消请求失败", "error")
        except Exception as e:
            self.add_log(f"取消时出错: {e}", "error")


def main():
    """Run the GUI application."""
    root = tk.Tk()
    app = GUIApp(root)
    
    # Center window
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    
    root.mainloop()


if __name__ == "__main__":
    main()
