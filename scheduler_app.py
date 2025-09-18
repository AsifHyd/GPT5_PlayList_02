# filename: scheduler_app.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import subprocess
import sys
from pathlib import Path
import time
import threading
from datetime import datetime

# Optional drag & drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False

import obsws_python as obs


def seconds_since_midnight() -> int:
    now = datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second


class PlaylistScheduler:
    def __init__(self, root):
        self.root = root
        self.root.title("OBS Playlist Scheduler v1.5 - Live Broadcast Automation")
        self.root.geometry("1480x900")

        # Data
        self.videos = []
        self.clipboard_data = []
        self.fillers = []               # filler media files
        self.broadcasting = False
        self.broadcast_thread = None
        self.obs_client = None
        self.current_video_index = -1
        self.fillers_active = False

        # Absolute schedule (seconds since midnight) for each item
        self.abs_starts = []
        self.abs_ends = []
        self.total_duration = 0

        # OBS connection fields (defaults for OBS 28+/31.x)
        self.obs_host_var = tk.StringVar(value="127.0.0.1")
        self.obs_port_var = tk.StringVar(value="4455")
        self.obs_password_var = tk.StringVar(value="")

        # Scene -> input name map
        self.scene_to_input = {}

        # Theme colors
        self.bg = "#2d2d2d"
        self.fg = "#e6e6e6"
        self.acc = "#3b3b3b"
        self.sel = "#4a4a4a"
        self.ok = "#66ff99"
        self.warn = "#ffcc66"
        self.err = "#ff6666"

        self.setup_ui()
        self.apply_dark_theme()
        self.setup_drag_drop()

    # ---------- Utilities ----------
    def _sanitize_name(self, name: str, max_len: int = 64) -> str:
        allowed = "-_.() []{}abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        cleaned = "".join(ch if ch in allowed else "_" for ch in name)
        return cleaned[:max_len]

    def recompute_schedule_times(self):
        """Compute absolute start/end for each video from Start Time field (seconds since midnight)."""
        start_seconds = self.time_to_seconds(self.start_time_var.get())
        self.abs_starts = []
        self.abs_ends = []
        t = start_seconds
        for v in self.videos:
            self.abs_starts.append(t)
            t2 = t + int(v['duration'])
            self.abs_ends.append(t2)
            t = t2
        self.total_duration = (t - start_seconds)

    # ---------- UI / Theme ----------
    def apply_dark_theme(self):
        try:
            self.root.configure(bg=self.bg)
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

            style.configure(".", background=self.bg, foreground=self.fg)
            style.configure("TFrame", background=self.bg)
            style.configure("TLabelframe", background=self.bg, foreground=self.fg)
            style.configure("TLabelframe.Label", background=self.bg, foreground=self.fg)
            style.configure("TLabel", background=self.bg, foreground=self.fg)
            style.configure("TButton", background=self.acc, foreground=self.fg, padding=5)
            style.map("TButton",
                      background=[("active", self.sel)],
                      relief=[("pressed", "sunken"), ("!pressed", "raised")])
            style.configure("TEntry", fieldbackground=self.acc, foreground=self.fg, insertcolor=self.fg)
            style.configure("Treeview",
                            background=self.acc,
                            fieldbackground=self.acc,
                            foreground=self.fg,
                            rowheight=26)
            style.configure("Treeview.Heading", background=self.acc, foreground=self.fg)
            style.map("Treeview",
                      background=[("selected", self.sel)],
                      foreground=[("selected", self.fg)])
            style.configure("TScrollbar", background=self.acc, troughcolor=self.bg)
        except Exception:
            pass

    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # Left panel with vertical scroll
        left_container = ttk.Frame(main_frame)
        left_container.grid(row=0, column=0, rowspan=2, sticky=(tk.N, tk.S))
        self.left_canvas = tk.Canvas(left_container, width=360, highlightthickness=0, bg=self.bg)
        left_scroll = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=self.left_canvas.yview)
        self.left_inner = ttk.Frame(self.left_canvas)
        self.left_inner.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self.left_canvas.create_window((0, 0), window=self.left_inner, anchor="nw")
        self.left_canvas.configure(yscrollcommand=left_scroll.set)
        self.left_canvas.grid(row=0, column=0, sticky=(tk.N, tk.S))
        left_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        left_container.rowconfigure(0, weight=1)

        # Section: Broadcast Control Center
        left_panel = ttk.LabelFrame(self.left_inner, text="Broadcast Control Center", padding="6")
        left_panel.grid(row=0, column=0, sticky=(tk.W, tk.E))
        left_panel.columnconfigure(0, weight=1)

        # File operations
        ttk.Label(left_panel, text="📁 File Management", font=('Arial', 9, 'bold')).grid(row=0, column=0, pady=(0, 5), sticky=tk.W)
        ttk.Button(left_panel, text="Add Videos", command=self.add_videos).grid(row=1, column=0, pady=2, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Add Folder", command=self.add_folder).grid(row=2, column=0, pady=2, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=3, column=0, sticky=(tk.W, tk.E), pady=5)

        # Schedule Settings
        ttk.Label(left_panel, text="⏰ Schedule Settings", font=('Arial', 9, 'bold')).grid(row=4, column=0, pady=(0, 5), sticky=tk.W)
        time_frame = ttk.Frame(left_panel)
        time_frame.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=2)
        time_frame.columnconfigure(1, weight=1)
        ttk.Label(time_frame, text="Start Time:").grid(row=0, column=0, padx=(0, 5))
        self.start_time_var = tk.StringVar(value="00:00:00")
        ttk.Entry(time_frame, textvariable=self.start_time_var, width=10).grid(row=0, column=1, sticky=tk.W)
        ttk.Button(left_panel, text="⏰ Set Current Time", command=self.set_current_time).grid(row=6, column=0, pady=2, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=7, column=0, sticky=(tk.W, tk.E), pady=5)

        # Edit operations
        ttk.Label(left_panel, text="✏️ Playlist Editing", font=('Arial', 9, 'bold')).grid(row=8, column=0, pady=(0, 5), sticky=tk.W)
        ttk.Button(left_panel, text="Move Up", command=self.move_up).grid(row=9, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Move Down", command=self.move_down).grid(row=10, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Delete Selected", command=self.delete_selected).grid(row=11, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Clear All", command=self.clear_all).grid(row=12, column=0, pady=1, sticky=(tk.W, tk.E))

        # Copy/Paste block
        ttk.Separator(left_panel, orient='horizontal').grid(row=13, column=0, sticky=(tk.W, tk.E), pady=5)
        cp_frame = ttk.Frame(left_panel)
        cp_frame.grid(row=14, column=0, sticky=(tk.W, tk.E))
        ttk.Button(cp_frame, text="📋 Copy Block", command=self.copy_block).grid(row=0, column=0, padx=(0, 4), sticky=(tk.W, tk.E))
        ttk.Button(cp_frame, text="📥 Paste Block", command=self.paste_block).grid(row=0, column=1, sticky=(tk.W, tk.E))
        cp_frame.columnconfigure(0, weight=1)
        cp_frame.columnconfigure(1, weight=1)

        ttk.Separator(left_panel, orient='horizontal').grid(row=15, column=0, sticky=(tk.W, tk.E), pady=5)

        # OBS Connection
        ttk.Label(left_panel, text="🔗 OBS Connection", font=('Arial', 9, 'bold')).grid(row=16, column=0, pady=(0, 5), sticky=tk.W)
        conn_frame = ttk.Frame(left_panel)
        conn_frame.grid(row=17, column=0, sticky=(tk.W, tk.E), pady=(0, 4))
        conn_frame.columnconfigure(1, weight=1)
        ttk.Label(conn_frame, text="Host").grid(row=0, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_host_var, width=14).grid(row=0, column=1, sticky=(tk.W, tk.E))
        ttk.Label(conn_frame, text="Port").grid(row=1, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_port_var, width=8).grid(row=1, column=1, sticky=(tk.W, tk.E))
        ttk.Label(conn_frame, text="Password").grid(row=2, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_password_var, show="*", width=14).grid(row=2, column=1, sticky=(tk.W, tk.E))
        self.connect_btn = ttk.Button(left_panel, text="Connect to OBS", command=self.connect_obs)
        self.connect_btn.grid(row=18, column=0, pady=2, sticky=(tk.W, tk.E))
        self.connection_status = ttk.Label(left_panel, text="● Disconnected", foreground=self.err, font=('Arial', 8))
        self.connection_status.grid(row=19, column=0, sticky=tk.W)
        self.setup_btn = ttk.Button(left_panel, text="🎬 Setup OBS Scenes", command=self.setup_obs_scenes)
        self.setup_btn.grid(row=20, column=0, pady=2, sticky=(tk.W, tk.E))
        self.setup_btn.configure(state='disabled')
        self.remove_btn = ttk.Button(left_panel, text="🗑 Remove Your Scenes", command=self.remove_app_scenes)
        self.remove_btn.grid(row=21, column=0, pady=2, sticky=(tk.W, tk.E))
        self.remove_btn.configure(state='disabled')

        ttk.Separator(left_panel, orient='horizontal').grid(row=22, column=0, sticky=(tk.W, tk.E), pady=5)

        # Live broadcast controls
        ttk.Label(left_panel, text="🔴 Live Broadcast", font=('Arial', 9, 'bold')).grid(row=23, column=0, pady=(0, 5), sticky=tk.W)
        self.start_btn = ttk.Button(left_panel, text="▶ Start Broadcasting", command=self.start_broadcast)
        self.start_btn.grid(row=24, column=0, pady=2, sticky=(tk.W, tk.E))
        self.start_btn.configure(state='disabled')
        self.stop_btn = ttk.Button(left_panel, text="⏹ Stop Broadcasting", command=self.stop_broadcast)
        self.stop_btn.grid(row=25, column=0, pady=2, sticky=(tk.W, tk.E))
        self.stop_btn.configure(state='disabled')
        self.skip_btn = ttk.Button(left_panel, text="⏭ Skip to Next", command=self.skip_to_next)
        self.skip_btn.grid(row=26, column=0, pady=1, sticky=(tk.W, tk.E))
        self.skip_btn.configure(state='disabled')

        ttk.Separator(left_panel, orient='horizontal').grid(row=27, column=0, sticky=(tk.W, tk.E), pady=5)

        # Fillers management
        ttk.Label(left_panel, text="🧩 Fillers (loop when idle)", font=('Arial', 9, 'bold')).grid(row=28, column=0, sticky=tk.W)
        ttk.Button(left_panel, text="➕ Add Fillers", command=self.add_fillers).grid(row=29, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="🧹 Clear Fillers", command=self.clear_fillers).grid(row=30, column=0, pady=1, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=31, column=0, sticky=(tk.W, tk.E), pady=5)
        ttk.Button(left_panel, text="💾 Export Playlist", command=self.export_playlist).grid(row=32, column=0, pady=5, sticky=(tk.W, tk.E))

        # Right: Timeline & status
        right_panel = ttk.LabelFrame(main_frame, text="🎬 Timeline & Live Status", padding="6")
        right_panel.grid(row=0, column=1, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(2, weight=1)

        status_frame = ttk.Frame(right_panel)
        status_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        status_frame.columnconfigure(1, weight=1)
        ttk.Label(status_frame, text="🔴 STATUS:", font=('Arial', 10, 'bold')).grid(row=0, column=0, padx=(0, 6))
        self.live_status_label = ttk.Label(status_frame, text="Not Broadcasting", font=('Arial', 10))
        self.live_status_label.grid(row=0, column=1, sticky=tk.W)
        self.time_label = ttk.Label(status_frame, text="", font=('Arial', 10, 'bold'))
        self.time_label.grid(row=0, column=2, padx=(5, 0), sticky=tk.E)

        # Current file progress
        self.file_time_label = ttk.Label(right_panel, text="", font=('Arial', 10))
        self.file_time_label.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(2, 6))

        columns = ('status', 'filename', 'duration', 'start_time', 'end_time')
        self.tree = ttk.Treeview(right_panel, columns=columns, show='headings', height=28, selectmode='extended')
        self.tree.heading('status', text='●')
        self.tree.heading('filename', text='Filename')
        self.tree.heading('duration', text='Duration')
        self.tree.heading('start_time', text='Start Time')
        self.tree.heading('end_time', text='End Time')
        self.tree.column('status', width=34, minwidth=30, anchor=tk.CENTER)
        self.tree.column('filename', width=520, minwidth=260)
        self.tree.column('duration', width=100, minwidth=80, anchor=tk.CENTER)
        self.tree.column('start_time', width=100, minwidth=80, anchor=tk.CENTER)
        self.tree.column('end_time', width=100, minwidth=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(right_panel, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=2, column=1, sticky=(tk.N, tk.S))

        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Jump to This Video", command=self.jump_to_video)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Move Up", command=self.move_up)
        self.context_menu.add_command(label="Move Down", command=self.move_down)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete", command=self.delete_selected)

        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Double-1>", self.on_double_click)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready - Set start time and connect to OBS for live automation")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # Start UI update loop
        self.update_ui_loop()

    # ---------- Time helpers ----------
    def set_current_time(self):
        current_time = datetime.now().strftime("%H:%M:%S")
        self.start_time_var.set(current_time)
        self.update_timeline()
        self.status_var.set(f"Schedule start time set to {current_time}")

    def time_to_seconds(self, time_str):
        try:
            h, m, s = map(int, time_str.split(':'))
            return h * 3600 + m * 60 + s
        except Exception:
            return 0

    def format_duration(self, seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ---------- DnD ----------
    def setup_drag_drop(self):
        try:
            if HAS_DND:
                self.tree.drop_target_register(DND_FILES)
                self.tree.dnd_bind('<<Drop>>', self.on_drop)
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.on_drop)
        except Exception:
            pass

    # ---------- UI loop ----------
    def update_ui_loop(self):
        # Global elapsed (telecast)
        if self.broadcasting:
            # show time since schedule start based on wall-clock
            now_sod = seconds_since_midnight()
            sched_start = self.abs_starts[0] if self.abs_starts else 0
            tele_elapsed = max(0, now_sod - sched_start)
            self.time_label.configure(text=f"Elapsed: {self.format_duration(tele_elapsed)}")
        else:
            self.time_label.configure(text="")

        # Per-file progress using GetMediaInputStatus
        try:
            if self.obs_client:
                input_name = None
                if 0 <= self.current_video_index < len(self.videos):
                    base = os.path.splitext(self.videos[self.current_video_index]['filename'])[0]
                    scene_name = f"Video_{self.current_video_index+1:03d}_{self._sanitize_name(base, 32)}"
                    input_name = self.scene_to_input.get(scene_name)
                elif self.fillers_active:
                    input_name = self.scene_to_input.get("Fillers_Scene")

                if input_name:
                    st = self.obs_client.get_media_input_status(input_name)  # mediaState, mediaCursor, mediaDuration (ms)
                    data = getattr(st, "responseData", None) or {}
                    cursor = int(data.get("mediaCursor", 0))
                    dur = int(data.get("mediaDuration", 0))
                    state = data.get("mediaState", "")
                    # Convert ms -> s where appropriate
                    if dur >= 1000:
                        played_s = cursor / 1000
                        total_s = dur / 1000
                    else:
                        played_s = cursor
                        total_s = dur
                    remaining_s = max(total_s - played_s, 0)
                    self.file_time_label.configure(
                        text=f"File: {self.format_duration(played_s)} / {self.format_duration(total_s)}  (−{self.format_duration(remaining_s)}) [{state}]"
                    )
                else:
                    self.file_time_label.configure(text="Fillers are playing" if self.fillers_active else "Nothing is playing")
        except Exception:
            pass

        self.root.after(1000, self.update_ui_loop)

    # ---------- OBS connect/disconnect ----------
    def connect_obs(self):
        """Connect to OBS WebSocket v5 server (default 127.0.0.1:4455)."""
        try:
            if self.obs_client:
                try:
                    self.obs_client.disconnect()
                except Exception:
                    pass

            host = (self.obs_host_var.get() or "127.0.0.1").strip()
            try:
                port = int((self.obs_port_var.get() or "4455").strip())
            except Exception:
                port = 4455
            password = self.obs_password_var.get()

            self.obs_client = obs.ReqClient(host=host, port=port, password=password, timeout=4)
            version_info = self.obs_client.get_version()

            self.connection_status.configure(text="● Connected", foreground=self.ok)
            self.connect_btn.configure(text="Disconnect", command=self.disconnect_obs)
            self.setup_btn.configure(state='normal')
            self.remove_btn.configure(state='normal')
            if self.videos:
                self.start_btn.configure(state='normal')

            self.status_var.set(f"Connected to OBS {version_info.obs_version} at {host}:{port}")
        except Exception as e:
            messagebox.showerror(
                "Connection Failed",
                f"Could not connect to OBS WebSocket:\n\n{str(e)}\n\n"
                "Please verify:\n"
                "1. OBS is running\n"
                "2. Tools → WebSocket Server Settings → Enable WebSocket server\n"
                "3. Port is 4455 and the password here matches OBS"
            )
            self.disconnect_obs()

    def disconnect_obs(self):
        if self.broadcasting:
            self.stop_broadcast()
        if self.obs_client:
            try:
                self.obs_client.disconnect()
            except Exception:
                pass
            self.obs_client = None

        self.connection_status.configure(text="● Disconnected", foreground=self.err)
        self.connect_btn.configure(text="Connect to OBS", command=self.connect_obs)
        self.setup_btn.configure(state='disabled')
        self.remove_btn.configure(state='disabled')
        self.start_btn.configure(state='disabled')
        self.status_var.set("Disconnected from OBS")

    # ---------- Scene setup / removal ----------
    def setup_obs_scenes(self):
        """Create scenes and attach media sources; input names mirror file names."""
        if not self.obs_client or not self.videos:
            messagebox.showwarning("Setup Error", "Connect to OBS and add videos first.")
            return

        try:
            self.scene_to_input.clear()
            success_count = 0
            failed_count = 0

            for i, video in enumerate(self.videos):
                base = os.path.splitext(video['filename'])[0]
                safe_base = self._sanitize_name(base)
                scene_name = f"Video_{i+1:03d}_{self._sanitize_name(base, 32)}"

                # Unique input name using the file name
                input_name = safe_base
                existing = set(self.scene_to_input.values())
                suffix = 1
                while input_name in existing:
                    suffix += 1
                    input_name = f"{safe_base}_{suffix}"

                try:
                    self.obs_client.create_scene(scene_name)
                except Exception:
                    pass

                try:
                    file_path = os.path.abspath(video['filepath']).replace("\\", "/")
                    input_settings = {
                        "local_file": file_path,
                        "is_local_file": True,
                        "looping": False,
                        "restart_on_activate": True,
                        "clear_on_media_end": False,
                        "close_when_inactive": False,
                        "hardware_decode": False
                    }

                    self.obs_client.create_input(
                        scene_name,
                        input_name,
                        "ffmpeg_source",
                        input_settings,
                        True
                    )
                    self.scene_to_input[scene_name] = input_name
                    success_count += 1
                except Exception as e:
                    print(f"Failed to create {scene_name}: {e}")
                    failed_count += 1

            if self.fillers:
                self.ensure_fillers_scene()

            if success_count > 0:
                if self.obs_client:
                    self.start_btn.configure(state='normal')
                msg = f"🎉 SUCCESS!\n\n✅ {success_count} scenes created with sources!"
                if failed_count > 0:
                    msg += f"\n❌ {failed_count} scenes failed"
                messagebox.showinfo("Setup Complete", msg)
                self.status_var.set(f"Scenes: {success_count} working, {failed_count} failed")
            else:
                messagebox.showerror("Setup Failed", "❌ No working scenes created.\nCheck console for errors.")
        except Exception as e:
            messagebox.showerror("Setup Error", f"Critical error:\n{str(e)}")

    def remove_app_scenes(self):
        """Delete only scenes created by this app: prefix 'Video_###_' and 'Fillers_Scene'."""
        if not self.obs_client:
            messagebox.showwarning("Remove Scenes", "Connect to OBS first.")
            return
        try:
            resp = self.obs_client.get_scene_list()
            data = getattr(resp, "responseData", None) or {}
            raw_scenes = data.get("scenes", []) if isinstance(data, dict) else []
            scenes = []
            for s in raw_scenes:
                if isinstance(s, dict) and "sceneName" in s:
                    scenes.append(s["sceneName"])

            to_delete = []
            for name in scenes:
                if name == "Fillers_Scene":
                    to_delete.append(name)
                elif name.startswith("Video_"):
                    parts = name.split("_", 2)
                    if len(parts) >= 2 and len(parts[1]) == 3 and parts[1].isdigit():
                        to_delete.append(name)

            safe_scene = None
            for name in scenes:
                if name not in to_delete:
                    safe_scene = name
                    break

            if not to_delete:
                messagebox.showinfo("Remove Scenes", "No app-created scenes found.")
                return
            if not safe_scene:
                messagebox.showwarning("Remove Scenes", "No safe scene to switch to before deletion; create one manually.")
                return

            if messagebox.askyesno("Confirm", f"Remove {len(to_delete)} scenes created by the app?"):
                try:
                    self.obs_client.set_current_program_scene(safe_scene)
                except Exception:
                    pass

                removed = 0
                for name in to_delete:
                    try:
                        self.obs_client.remove_scene(name)  # obsws-python v5 method
                        removed += 1
                    except Exception as e:
                        print(f"Remove failed for {name}: {e}")

                self.status_var.set(f"Removed {removed} app scenes")
                messagebox.showinfo("Remove Scenes", f"Removed {removed} scenes.")
        except Exception as e:
            messagebox.showerror("Remove Scenes", f"Error: {e}")

    # ---------- Fillers ----------
    def add_fillers(self):
        files = filedialog.askopenfilenames(title="Select filler files (videos/audio)",
                                            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.flac *.webm"), ("All files", "*.*")])
        if not files:
            return
        self.fillers = list(files)
        self.status_var.set(f"Fillers set: {len(self.fillers)} item(s)")
        if self.obs_client:
            self.ensure_fillers_scene()

    def clear_fillers(self):
        self.fillers = []
        self.status_var.set("Fillers cleared")

    def ensure_fillers_scene(self):
        """Create/refresh Fillers_Scene using VLC playlist if possible, else single loop."""
        try:
            try:
                self.obs_client.create_scene("Fillers_Scene")
            except Exception:
                pass
            try:
                self.obs_client.remove_input("Fillers_Playlist")
            except Exception:
                pass

            if len(self.fillers) > 1:
                playlist = [{"value": os.path.abspath(p).replace("\\", "/"), "hidden": False, "selected": True}
                            for p in self.fillers]
                input_settings = {"playlist": playlist, "loop": True, "shuffle": False, "playback_behavior": "always_play"}
                self.obs_client.create_input("Fillers_Scene", "Fillers_Playlist", "vlc_source", input_settings, True)
            else:
                file_path = os.path.abspath(self.fillers[0]).replace("\\", "/")
                input_settings = {
                    "local_file": file_path,
                    "is_local_file": True,
                    "looping": True,
                    "restart_on_activate": True,
                    "clear_on_media_end": False,
                    "close_when_inactive": False,
                    "hardware_decode": False
                }
                self.obs_client.create_input("Fillers_Scene", "Fillers_Playlist", "ffmpeg_source", input_settings, True)

            self.scene_to_input["Fillers_Scene"] = "Fillers_Playlist"
            self.status_var.set("Fillers_Scene ready")
        except Exception as e:
            messagebox.showerror("Fillers", f"Could not create fillers scene:\n{e}")

    def play_fillers_if_needed(self):
        if not self.obs_client:
            return
        if not self.fillers:
            self.fillers_active = False
            self.live_status_label.configure(text="Nothing is playing", foreground=self.fg)
            self.file_time_label.configure(text="Nothing is playing")
            return
        self.ensure_fillers_scene()
        try:
            self.obs_client.set_current_program_scene("Fillers_Scene")
            inp = self.scene_to_input.get("Fillers_Scene")
            if inp:
                self.obs_client.trigger_media_input_action(inp, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
            self.fillers_active = True
            self.live_status_label.configure(text="Fillers are playing", foreground=self.warn)
            self.file_time_label.configure(text="Fillers are playing")
        except Exception as e:
            print(f"Filler playback error: {e}")

    # ---------- Broadcast control ----------
    def start_broadcast(self):
        if not self.obs_client:
            messagebox.showwarning("Broadcast Error", "Connect to OBS first.")
            return

        self.recompute_schedule_times()
        if not self.videos:
            self.broadcasting = False
            self.play_fillers_if_needed()
            return

        self.broadcasting = True
        self.fillers_active = False
        self.current_video_index = -1

        self.broadcast_thread = threading.Thread(target=self.broadcast_controller, daemon=True)
        self.broadcast_thread.start()

        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.skip_btn.configure(state='normal')
        self.remove_btn.configure(state='disabled')

        # Immediately play whichever item is active by wall‑clock
        try:
            now_sod = seconds_since_midnight()
            idx = self.index_for_time(now_sod)
            if idx is not None:
                self.switch_to_video(idx)
                self.current_video_index = idx
            else:
                self.play_fillers_if_needed()
        except Exception as e:
            print(f"Immediate start error: {e}")

        self.live_status_label.configure(text="🔴 BROADCASTING LIVE", foreground=self.err)
        self.status_var.set("🔴 Live broadcast active")

    def stop_broadcast(self):
        self.broadcasting = False
        if self.broadcast_thread:
            self.broadcast_thread.join(timeout=1)

        self.play_fillers_if_needed()

        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self.skip_btn.configure(state='disabled')
        self.remove_btn.configure(state='normal')

        self.current_video_index = -1
        self.update_timeline()
        self.status_var.set("Broadcast stopped")

    def index_for_time(self, now_sod: int):
        if not self.videos:
            return None
        # If before schedule start or after schedule end, return None
        if now_sod < self.abs_starts[0] or now_sod >= self.abs_ends[-1]:
            return None
        # Find active segment
        for i, (s, e) in enumerate(zip(self.abs_starts, self.abs_ends)):
            if s <= now_sod < e:
                return i
        return None

    def broadcast_controller(self):
        while self.broadcasting:
            try:
                now_sod = seconds_since_midnight()
                target_idx = self.index_for_time(now_sod)

                # If the schedule says a clip should be on-air, ensure we are there
                if target_idx is not None and target_idx != self.current_video_index:
                    self.switch_to_video(target_idx)
                    self.current_video_index = target_idx

                # If schedule idle (before first or after last), go to fillers
                if target_idx is None:
                    if not self.fillers_active:
                        self.play_fillers_if_needed()
                else:
                    self.fillers_active = False

                # Additional media-ended guard: if current ended early, hop to next
                if target_idx is not None:
                    base = os.path.splitext(self.videos[target_idx]['filename'])[0]
                    scene_name = f"Video_{target_idx+1:03d}_{self._sanitize_name(base, 32)}"
                    input_name = self.scene_to_input.get(scene_name)
                    if input_name:
                        try:
                            st = self.obs_client.get_media_input_status(input_name)
                            data = getattr(st, "responseData", None) or {}
                            state = data.get("mediaState", "")
                            cursor = int(data.get("mediaCursor", 0))
                            dur = int(data.get("mediaDuration", 0))
                            if state == "OBS_MEDIA_STATE_ENDED" or (dur and cursor >= dur):
                                # switch immediately to next by wall-clock (if within schedule)
                                next_idx = target_idx + 1 if (target_idx + 1) < len(self.videos) else None
                                if next_idx is not None and now_sod < self.abs_ends[-1]:
                                    self.switch_to_video(next_idx)
                                    self.current_video_index = next_idx
                        except Exception:
                            pass

                time.sleep(0.5)
            except Exception as e:
                print(f"Broadcast controller error: {e}")
                time.sleep(1)

    def switch_to_video(self, video_index):
        """Switch Program scene and explicitly restart its media input."""
        try:
            if 0 <= video_index < len(self.videos):
                base = os.path.splitext(self.videos[video_index]['filename'])[0]
                scene_name = f"Video_{video_index+1:03d}_{self._sanitize_name(base, 32)}"
                self.obs_client.set_current_program_scene(scene_name)
                input_name = self.scene_to_input.get(scene_name)
                if input_name:
                    self.obs_client.trigger_media_input_action(
                        input_name,
                        "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
                    )
                filename = self.videos[video_index]['filename']
                self.live_status_label.configure(text=f"🔴 NOW: {filename}", foreground=self.err)
                # Update marker
                for child in self.tree.get_children():
                    self.tree.set(child, 'status', '')
                if 0 <= video_index < len(self.tree.get_children()):
                    curr = self.tree.get_children()[video_index]
                    self.tree.set(curr, 'status', '▶')
        except Exception as e:
            print(f"Error switching/starting media: {e}")

    def skip_to_next(self):
        if not self.broadcasting:
            return
        next_idx = (self.current_video_index + 1) if self.current_video_index >= 0 else 0
        if next_idx < len(self.videos):
            self.switch_to_video(next_idx)
            self.current_video_index = next_idx
        else:
            self.stop_broadcast()

    def jump_to_video(self):
        selection = self.tree.selection()
        if not selection:
            return
        if not self.broadcasting:
            self.start_broadcast()
        index = self.tree.index(selection[0])
        self.switch_to_video(index)
        self.current_video_index = index

    # ---------- Editing helpers ----------
    def get_selected_indices(self):
        return [self.tree.index(item) for item in self.tree.selection()]

    def move_up(self):
        indices = self.get_selected_indices()
        if not indices or indices[0] == 0:
            return
        for i in indices:
            self.videos[i - 1], self.videos[i] = self.videos[i], self.videos[i - 1]
        self.update_timeline()

    def move_down(self):
        indices = self.get_selected_indices()
        if not indices or indices[-1] == len(self.videos) - 1:
            return
        for i in reversed(indices):
            self.videos[i + 1], self.videos[i] = self.videos[i], self.videos[i + 1]
        self.update_timeline()

    def delete_selected(self):
        indices = self.get_selected_indices()
        if not indices:
            return
        if messagebox.askyesno("Confirm", f"Delete {len(indices)} videos?"):
            for i in reversed(indices):
                del self.videos[i]
            self.update_timeline()

    def clear_all(self):
        if self.videos and messagebox.askyesno("Clear All", "Clear entire playlist?"):
            self.videos.clear()
            self.update_timeline()
            if self.obs_client and self.fillers:
                self.play_fillers_if_needed()

    def copy_block(self):
        sel = self.get_selected_indices()
        if not sel:
            return
        self.clipboard_data = [self.videos[i].copy() for i in sel]
        self.status_var.set(f"Copied {len(sel)} item(s)")

    def paste_block(self):
        if not self.clipboard_data:
            return
        sel = self.get_selected_indices()
        insert_at = sel[-1] + 1 if sel else len(self.videos)
        for i, v in enumerate(self.clipboard_data):
            self.videos.insert(insert_at + i, v.copy())
        self.update_timeline()
        self.status_var.set(f"Pasted {len(self.clipboard_data)} item(s) at position {insert_at+1}")

    # ---------- Export ----------
    def export_playlist(self):
        if not self.videos:
            messagebox.showinfo("Export", "No videos to export.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Export schedule",
            defaultextension=".json",
            filetypes=[("Schedule", "*.json"), ("All", "*.*")]
        )
        if not filepath:
            return

        self.recompute_schedule_times()
        schedule = {
            "videos": [],
            "start_time": self.start_time_var.get(),
            "total_duration": self.total_duration
        }

        for i, video in enumerate(self.videos):
            schedule["videos"].append({
                "index": i,
                "filename": video["filename"],
                "filepath": os.path.abspath(video["filepath"]),
                "duration": float(video["duration"]),
                "start_time_abs": int(self.abs_starts[i]),
                "start_formatted": self.format_duration(self.abs_starts[i]),
                "end_formatted": self.format_duration(self.abs_ends[i]),
                "scene_name": f"Video_{i+1:03d}_{self._sanitize_name(os.path.splitext(video['filename'])[0], 32)}"
            })

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(schedule, f, indent=2)
            messagebox.showinfo("Success", f"Schedule exported!\n\n{filepath}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not write file:\n{e}")

    # ---------- File/time UI ----------
    def update_current_video_indicator(self, now_sod):
        idx = self.index_for_time(now_sod) if self.broadcasting else None
        for child in self.tree.get_children():
            self.tree.set(child, 'status', '')
        if idx is not None and 0 <= idx < len(self.tree.get_children()):
            current_item = self.tree.get_children()[idx]
            self.tree.set(current_item, 'status', '▶')

    # ---------- Video IO ----------
    def get_video_duration(self, filepath):
        """Prefer ffprobe when bundled; otherwise fallback heuristic."""
        try:
            if getattr(sys, 'frozen', False):
                ffprobe_path = os.path.join(sys._MEIPASS, 'ffprobe.exe')
            else:
                ffprobe_path = 'ffprobe'

            cmd = [ffprobe_path, '-v', 'quiet', '-print_format', 'json', '-show_format', filepath]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data['format']['duration'])
            else:
                return max(os.path.getsize(filepath) / (1024 * 1024 * 2), 30)
        except Exception:
            return 60

    # ---------- Add files ----------
    def add_videos(self):
        filetypes = [("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm"), ("All files", "*.*")]
        files = filedialog.askopenfilenames(title="Select videos", filetypes=filetypes)
        if files:
            self.process_files(files)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select video folder")
        if folder:
            extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
            files = [os.path.join(folder, f) for f in os.listdir(folder) if Path(f).suffix.lower() in extensions]
            if files:
                files.sort()
                self.process_files(files)

    def process_files(self, files, insert_at=None):
        self.status_var.set("Processing videos...")
        self.root.update()

        new_videos = []
        for filepath in files:
            filename = os.path.basename(filepath)
            duration = self.get_video_duration(filepath)
            new_videos.append({'filepath': filepath, 'filename': filename, 'duration': duration})

        if insert_at is not None:
            for i, video in enumerate(new_videos):
                self.videos.insert(insert_at + i, video)
        else:
            self.videos.extend(new_videos)

        self.update_timeline()  # recompute schedule + totals

    # ---------- Timeline ----------
    def update_timeline(self):
        self.recompute_schedule_times()

        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, video in enumerate(self.videos):
            start_time = self.format_duration(self.abs_starts[i])
            end_time = self.format_duration(self.abs_ends[i])
            duration_str = self.format_duration(video['duration'])
            status = '▶' if i == self.current_video_index else ''
            self.tree.insert('', 'end', values=(status, video['filename'], duration_str, start_time, end_time))

        total_str = self.format_duration(self.total_duration)
        end_time_str = self.format_duration(self.abs_ends[-1]) if self.abs_ends else "00:00:00"
        self.status_var.set(f"Schedule: {self.start_time_var.get()} to {end_time_str} | Duration: {total_str} ({len(self.videos)} videos)")

    # ---------- Misc ----------
    def on_drop(self, event):
        if not HAS_DND:
            return
        files = self.root.tk.splitlist(event.data)
        video_files = []
        for file in files:
            path = file.strip('{}')
            if os.path.isfile(path) and Path(path).suffix.lower() in {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}:
                video_files.append(path)
        if video_files:
            self.process_files(video_files)

    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def on_double_click(self, event):
        selection = self.tree.selection()
        if selection:
            index = self.tree.index(selection[0])
            video = self.videos[index]
            info = f"File: {video['filename']}\nPath: {video['filepath']}\nDuration: {self.format_duration(video['duration'])}"
            messagebox.showinfo("Video Info", info)


def main():
    # Ensure a single Tk root to avoid stray blank windows
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    app = PlaylistScheduler(root)
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f"+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()
