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


class PlaylistScheduler:
    def __init__(self, root):
        self.root = root
        self.root.title("OBS Playlist Scheduler v1.3 - Live Broadcast Automation")
        self.root.geometry("1400x820")

        # Data
        self.videos = []
        self.fillers = []  # list of file paths used for filler playback
        self.broadcasting = False
        self.broadcast_thread = None
        self.obs_client = None
        self.current_video_index = -1
        self.broadcast_start_time = None
        self.manual_time_offset = 0
        self.fillers_active = False

        # OBS connection fields (defaults for OBS 28+/31.x)
        self.obs_host_var = tk.StringVar(value="127.0.0.1")
        self.obs_port_var = tk.StringVar(value="4455")
        self.obs_password_var = tk.StringVar(value="")

        # Map scene -> input name (for media control)
        self.scene_to_input = {}

        # UI
        self.setup_ui()
        self.setup_drag_drop()
        self.apply_dark_theme()

    # ---------- Utilities ----------
    def _sanitize_name(self, name: str, max_len: int = 64) -> str:
        allowed = "-_.() []{}abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        cleaned = "".join(ch if ch in allowed else "_" for ch in name)
        return cleaned[:max_len]

    # ---------- UI ----------
    def apply_dark_theme(self):
        # Simple professional dark theme
        bg = "#2d2d2d"
        fg = "#e6e6e6"
        acc = "#3b3b3b"
        sel = "#4a4a4a"

        try:
            self.root.configure(bg=bg)
            style = ttk.Style()
            # Use 'clam' for broad widget coverage
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

            style.configure(".", background=bg, foreground=fg)
            style.configure("TFrame", background=bg)
            style.configure("TLabelframe", background=bg, foreground=fg)
            style.configure("TLabelframe.Label", background=bg, foreground=fg)
            style.configure("TLabel", background=bg, foreground=fg)
            style.configure("TButton", background=acc, foreground=fg)
            style.map("TButton",
                      background=[("active", sel)],
                      relief=[("pressed", "sunken"), ("!pressed", "raised")])
            style.configure("TEntry", fieldbackground=acc, foreground=fg, insertcolor=fg)
            style.configure("Treeview",
                            background=acc,
                            fieldbackground=acc,
                            foreground=fg)
            style.map("Treeview",
                      background=[("selected", sel)],
                      foreground=[("selected", fg)])
            style.configure("TScrollbar", background=acc, troughcolor=bg)
        except Exception:
            pass

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # Left panel
        left_panel = ttk.LabelFrame(main_frame, text="Broadcast Control Center", padding="5")
        left_panel.grid(row=0, column=0, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))

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
        self.start_time_entry = ttk.Entry(time_frame, textvariable=self.start_time_var, width=10)
        self.start_time_entry.grid(row=0, column=1, sticky=tk.W)

        ttk.Button(left_panel, text="⏰ Set Current Time", command=self.set_current_time).grid(row=6, column=0, pady=2, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=7, column=0, sticky=(tk.W, tk.E), pady=5)

        # Edit operations
        ttk.Label(left_panel, text="✏️ Playlist Editing", font=('Arial', 9, 'bold')).grid(row=8, column=0, pady=(0, 5), sticky=tk.W)
        ttk.Button(left_panel, text="Move Up", command=self.move_up).grid(row=9, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Move Down", command=self.move_down).grid(row=10, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Delete Selected", command=self.delete_selected).grid(row=11, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="Clear All", command=self.clear_all).grid(row=12, column=0, pady=1, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=13, column=0, sticky=(tk.W, tk.E), pady=5)

        # OBS Connection
        ttk.Label(left_panel, text="🔗 OBS Connection", font=('Arial', 9, 'bold')).grid(row=14, column=0, pady=(0, 5), sticky=tk.W)

        conn_frame = ttk.Frame(left_panel)
        conn_frame.grid(row=15, column=0, sticky=(tk.W, tk.E), pady=(0, 4))
        conn_frame.columnconfigure(1, weight=1)

        ttk.Label(conn_frame, text="Host").grid(row=0, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_host_var, width=14).grid(row=0, column=1, sticky=(tk.W, tk.E))

        ttk.Label(conn_frame, text="Port").grid(row=1, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_port_var, width=8).grid(row=1, column=1, sticky=(tk.W, tk.E))

        ttk.Label(conn_frame, text="Password").grid(row=2, column=0, padx=(0, 5), sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.obs_password_var, show="*", width=14).grid(row=2, column=1, sticky=(tk.W, tk.E))

        self.connect_btn = ttk.Button(left_panel, text="Connect to OBS", command=self.connect_obs)
        self.connect_btn.grid(row=16, column=0, pady=2, sticky=(tk.W, tk.E))

        self.connection_status = ttk.Label(left_panel, text="● Disconnected", foreground="#ff6666", font=('Arial', 8))
        self.connection_status.grid(row=17, column=0, sticky=tk.W)

        self.setup_btn = ttk.Button(left_panel, text="🎬 Setup OBS Scenes", command=self.setup_obs_scenes)
        self.setup_btn.grid(row=18, column=0, pady=2, sticky=(tk.W, tk.E))
        self.setup_btn.configure(state='disabled')

        # Remove app scenes
        self.remove_btn = ttk.Button(left_panel, text="🗑 Remove Your Scenes", command=self.remove_app_scenes)
        self.remove_btn.grid(row=19, column=0, pady=2, sticky=(tk.W, tk.E))
        self.remove_btn.configure(state='disabled')

        ttk.Separator(left_panel, orient='horizontal').grid(row=20, column=0, sticky=(tk.W, tk.E), pady=5)

        # Live broadcast controls
        ttk.Label(left_panel, text="🔴 Live Broadcast", font=('Arial', 9, 'bold')).grid(row=21, column=0, pady=(0, 5), sticky=tk.W)

        self.start_btn = ttk.Button(left_panel, text="▶ Start Broadcasting", command=self.start_broadcast)
        self.start_btn.grid(row=22, column=0, pady=2, sticky=(tk.W, tk.E))
        self.start_btn.configure(state='disabled')

        self.stop_btn = ttk.Button(left_panel, text="⏹ Stop Broadcasting", command=self.stop_broadcast)
        self.stop_btn.grid(row=23, column=0, pady=2, sticky=(tk.W, tk.E))
        self.stop_btn.configure(state='disabled')

        self.skip_btn = ttk.Button(left_panel, text="⏭ Skip to Next", command=self.skip_to_next)
        self.skip_btn.grid(row=24, column=0, pady=1, sticky=(tk.W, tk.E))
        self.skip_btn.configure(state='disabled')

        # Fillers management
        ttk.Separator(left_panel, orient='horizontal').grid(row=25, column=0, sticky=(tk.W, tk.E), pady=5)
        ttk.Label(left_panel, text="🧩 Fillers (loop when idle)", font=('Arial', 9, 'bold')).grid(row=26, column=0, sticky=tk.W)
        ttk.Button(left_panel, text="➕ Add Fillers", command=self.add_fillers).grid(row=27, column=0, pady=1, sticky=(tk.W, tk.E))
        ttk.Button(left_panel, text="🧹 Clear Fillers", command=self.clear_fillers).grid(row=28, column=0, pady=1, sticky=(tk.W, tk.E))

        ttk.Separator(left_panel, orient='horizontal').grid(row=29, column=0, sticky=(tk.W, tk.E), pady=5)
        ttk.Button(left_panel, text="💾 Export Playlist", command=self.export_playlist).grid(row=30, column=0, pady=5, sticky=(tk.W, tk.E))

        left_panel.columnconfigure(0, weight=1)

        # Right panel - Timeline & status
        right_panel = ttk.LabelFrame(main_frame, text="🎬 Timeline & Live Status", padding="5")
        right_panel.grid(row=0, column=1, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

        status_frame = ttk.Frame(right_panel)
        status_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 5))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="🔴 STATUS:", font=('Arial', 10, 'bold')).grid(row=0, column=0, padx=(0, 6))
        self.live_status_label = ttk.Label(status_frame, text="Not Broadcasting", font=('Arial', 10))
        self.live_status_label.grid(row=0, column=1, sticky=tk.W)

        self.time_label = ttk.Label(status_frame, text="", font=('Arial', 10, 'bold'))
        self.time_label.grid(row=0, column=2, padx=(5, 0), sticky=tk.E)

        # Current file progress
        self.file_time_label = ttk.Label(status_frame, text="", font=('Arial', 10))
        self.file_time_label.grid(row=1, column=0, columnspan=3, sticky=tk.W)

        columns = ('status', 'filename', 'duration', 'start_time', 'end_time')
        self.tree = ttk.Treeview(right_panel, columns=columns, show='headings', height=26, selectmode='extended')

        self.tree.heading('status', text='●')
        self.tree.heading('filename', text='Filename')
        self.tree.heading('duration', text='Duration')
        self.tree.heading('start_time', text='Start Time')
        self.tree.heading('end_time', text='End Time')

        self.tree.column('status', width=34, minwidth=30)
        self.tree.column('filename', width=380, minwidth=220)
        self.tree.column('duration', width=90, minwidth=80, anchor=tk.CENTER)
        self.tree.column('start_time', width=90, minwidth=80, anchor=tk.CENTER)
        self.tree.column('end_time', width=90, minwidth=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(right_panel, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))

        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(1, weight=1)

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
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
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
            current_time = time.time()
            if self.broadcast_start_time:
                elapsed = (current_time - self.broadcast_start_time) + self.manual_time_offset
                self.time_label.configure(text=f"Elapsed: {self.format_duration(elapsed)}")
        else:
            self.time_label.configure(text="")

        # Per-file progress using GetMediaInputStatus
        try:
            if self.obs_client:
                # Determine current Program scene and its input
                input_name = None
                if 0 <= self.current_video_index < len(self.videos):
                    base = os.path.splitext(self.videos[self.current_video_index]['filename'])[0]
                    scene_name = f"Video_{self.current_video_index+1:03d}_{self._sanitize_name(base, 32)}"
                    input_name = self.scene_to_input.get(scene_name)
                elif self.fillers_active:
                    scene_name = "Fillers_Scene"
                    input_name = self.scene_to_input.get(scene_name)

                if input_name:
                    st = self.obs_client.get_media_input_status(input_name)
                    data = getattr(st, "responseData", None) or getattr(st, "datain", None) or getattr(st, "data", lambda: {})()
                    # obsws_python returns a dict-like; try common accessors
                    if isinstance(data, dict):
                        cursor = int(data.get("mediaCursor", 0))
                        dur = int(data.get("mediaDuration", 0))
                        state = data.get("mediaState", "")
                    else:
                        # Fallback: object with attributes
                        cursor = int(getattr(data, "mediaCursor", 0))
                        dur = int(getattr(data, "mediaDuration", 0))
                        state = getattr(data, "mediaState", "")

                    played = self.format_duration(cursor / 1000 if cursor > 1000 else cursor)
                    total = self.format_duration(dur / 1000 if dur > 1000 else max(dur, 1))
                    remaining_sec = max((dur - cursor) / 1000, 0) if dur and cursor else 0
                    remaining = self.format_duration(remaining_sec)
                    self.file_time_label.configure(text=f"File: {played} / {total}  (−{remaining}) [{state}]")
                else:
                    # No active media
                    if self.fillers_active:
                        self.file_time_label.configure(text="Fillers are playing")
                    else:
                        self.file_time_label.configure(text="Nothing is playing")
        except Exception:
            # Non-fatal UI update error
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

            self.obs_client = obs.ReqClient(host=host, port=port, password=password, timeout=3)
            version_info = self.obs_client.get_version()

            self.connection_status.configure(text="● Connected", foreground="#66ff99")
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

        self.connection_status.configure(text="● Disconnected", foreground="#ff6666")
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

            # Prepare Fillers_Scene if fillers exist
            if self.fillers:
                self.ensure_fillers_scene()

            if success_count > 0:
                if self.obs_client:
                    self.start_btn.configure(state='normal')
                msg = f"🎉 SUCCESS!\n\n✅ {success_count} scenes created with sources!"
                if failed_count > 0:
                    msg += f"\n❌ {failed_count} scenes failed"
                msg += f"\n\n📺 Check OBS - sources should now appear!"
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
            # Get scenes
            sl = self.obs_client.get_scene_list()
            data = getattr(sl, "responseData", None) or getattr(sl, "datain", None) or getattr(sl, "data", lambda: {})()
            scenes = []
            if isinstance(data, dict) and "scenes" in data:
                scenes = [s.get("sceneName") for s in data["scenes"] if isinstance(s, dict)]
            elif hasattr(sl, "scenes"):
                scenes = [s.sceneName for s in sl.scenes]  # fallback

            # Choose a safe target scene (first non-app scene) for switching before removals
            to_delete = []
            for name in scenes:
                if name == "Fillers_Scene":
                    to_delete.append(name)
                elif name.startswith("Video_"):
                    # Very conservative: ensure name has Video_###_ pattern
                    parts = name.split("_", 2)
                    if len(parts) >= 2 and len(parts[1]) == 3 and parts[1].isdigit():
                        to_delete.append(name)

            safe_scene = None
            for name in scenes:
                if name not in to_delete:
                    safe_scene = name
                    break

            if not safe_scene and to_delete:
                messagebox.showwarning("Remove Scenes", "No safe scene to switch to before deletion; please create one manually.")
                return

            if to_delete:
                if messagebox.askyesno("Confirm", f"Remove {len(to_delete)} scenes created by the app?"):
                    # Switch away before deletion
                    if safe_scene:
                        try:
                            self.obs_client.set_current_program_scene(safe_scene)
                        except Exception:
                            pass

                    # Remove one by one
                    removed = 0
                    for name in to_delete:
                        try:
                            # v5 supports DeleteScene/RemoveScene; obsws-python exposes remove_scene
                            self.obs_client.remove_scene(name)
                            removed += 1
                        except Exception as e:
                            print(f"Remove failed for {name}: {e}")

                    self.status_var.set(f"Removed {removed} app scenes")
                    messagebox.showinfo("Remove Scenes", f"Removed {removed} scenes.")
            else:
                messagebox.showinfo("Remove Scenes", "No app-created scenes found.")
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
        # If OBS connected, (re)build the Fillers_Scene
        if self.obs_client:
            self.ensure_fillers_scene()

    def clear_fillers(self):
        self.fillers = []
        self.status_var.set("Fillers cleared")

    def ensure_fillers_scene(self):
        """Create/refresh Fillers_Scene using VLC playlist if possible, else first file loop."""
        try:
            # Create scene
            try:
                self.obs_client.create_scene("Fillers_Scene")
            except Exception:
                pass

            # Remove any prior filler input if present
            # We'll (re)create a single input "Fillers_Playlist"
            try:
                # If it exists, remove it before recreating
                self.obs_client.remove_input("Fillers_Playlist")
            except Exception:
                pass

            if len(self.fillers) > 1:
                # VLC playlist input
                playlist = [{"value": os.path.abspath(p).replace("\\", "/"), "hidden": False, "selected": True}
                            for p in self.fillers]
                input_settings = {
                    "playlist": playlist,
                    "loop": True,
                    "shuffle": False,
                    "playback_behavior": "always_play"  # keep playing even if not visible; will still be restarted on activate
                }
                self.obs_client.create_input(
                    "Fillers_Scene",
                    "Fillers_Playlist",
                    "vlc_source",
                    input_settings,
                    True
                )
            else:
                # Single media loop via ffmpeg_source
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
                self.obs_client.create_input(
                    "Fillers_Scene",
                    "Fillers_Playlist",
                    "ffmpeg_source",
                    input_settings,
                    True
                )

            self.scene_to_input["Fillers_Scene"] = "Fillers_Playlist"
            self.status_var.set("Fillers_Scene ready")
        except Exception as e:
            messagebox.showerror("Fillers", f"Could not create fillers scene:\n{e}")

    def play_fillers_if_needed(self):
        if not self.obs_client:
            return
        if not self.fillers:
            self.fillers_active = False
            self.live_status_label.configure(text="Nothing is playing")
            return
        # Ensure filler scene exists
        self.ensure_fillers_scene()
        try:
            self.obs_client.set_current_program_scene("Fillers_Scene")
            # Restart fillers playlist to ensure visible playback
            inp = self.scene_to_input.get("Fillers_Scene")
            if inp:
                self.obs_client.trigger_media_input_action(
                    inp, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
                )
            self.fillers_active = True
            self.live_status_label.configure(text="Fillers are playing", foreground="#ffcc66")
        except Exception as e:
            print(f"Filler playback error: {e}")

    # ---------- Broadcast control ----------
    def start_broadcast(self):
        if not self.obs_client:
            messagebox.showwarning("Broadcast Error", "Connect to OBS first.")
            return
        if not self.videos:
            # No schedule -> play fillers if available
            self.broadcasting = False
            self.play_fillers_if_needed()
            return

        self.broadcasting = True
        self.fillers_active = False
        self.broadcast_start_time = time.time()
        start_seconds = self.time_to_seconds(self.start_time_var.get())
        self.manual_time_offset = start_seconds
        self.current_video_index = -1

        self.broadcast_thread = threading.Thread(target=self.broadcast_controller, daemon=True)
        self.broadcast_thread.start()

        # UI
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.skip_btn.configure(state='normal')
        self.remove_btn.configure(state='disabled')

        # Immediately start first video (no need to press Skip)
        try:
            self.switch_to_video(0)
            self.current_video_index = 0
        except Exception as e:
            print(f"Immediate start error: {e}")

        self.live_status_label.configure(text="🔴 BROADCASTING LIVE", foreground="#ff6666")
        self.status_var.set(f"🔴 Live broadcast started from {self.start_time_var.get()}")

    def stop_broadcast(self):
        self.broadcasting = False
        if self.broadcast_thread:
            self.broadcast_thread.join(timeout=1)

        # After stopping, if fillers exist, switch to fillers
        self.play_fillers_if_needed()

        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self.skip_btn.configure(state='disabled')
        self.remove_btn.configure(state='normal')

        self.current_video_index = -1
        self.update_timeline()
        self.status_var.set("Broadcast stopped")

    def broadcast_controller(self):
        while self.broadcasting:
            try:
                current_time = time.time()
                elapsed = (current_time - self.broadcast_start_time) + self.manual_time_offset
                target_index = self.get_video_at_time(elapsed)

                if target_index != self.current_video_index and target_index >= 0:
                    self.switch_to_video(target_index)
                    self.current_video_index = target_index

                time.sleep(0.5)
            except Exception as e:
                print(f"Broadcast controller error: {e}")
                time.sleep(1)

    def get_video_at_time(self, elapsed_seconds):
        current_time = 0
        for i, video in enumerate(self.videos):
            video_end = current_time + video['duration']
            if current_time <= elapsed_seconds < video_end:
                return i
            current_time = video_end
        return -1

    def switch_to_video(self, video_index):
        """Switch Program scene and explicitly restart its media input."""
        try:
            if 0 <= video_index < len(self.videos):
                base = os.path.splitext(self.videos[video_index]['filename'])[0]
                scene_name = f"Video_{video_index+1:03d}_{self._sanitize_name(base, 32)}"

                # Switch Program scene
                self.obs_client.set_current_program_scene(scene_name)

                # Restart media to ensure playback in Program (works reliably in Studio Mode)
                input_name = self.scene_to_input.get(scene_name)
                if input_name:
                    self.obs_client.trigger_media_input_action(
                        input_name,
                        "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
                    )
                # Update status
                filename = self.videos[video_index]['filename']
                self.live_status_label.configure(text=f"🔴 NOW: {filename}", foreground="#ff6666")
                self.fillers_active = False
        except Exception as e:
            print(f"Error switching/starting media: {e}")

    def skip_to_next(self):
        if not self.broadcasting:
            return
        current_time = time.time()
        elapsed = (current_time - self.broadcast_start_time) + self.manual_time_offset
        next_index = self.get_video_at_time(elapsed) + 1
        if next_index < len(self.videos):
            target_time = sum(video['duration'] for video in self.videos[:next_index])
            adjustment = target_time - elapsed
            self.manual_time_offset += adjustment
        else:
            # End reached -> play fillers if available
            self.stop_broadcast()

    def jump_to_video(self):
        selection = self.tree.selection()
        if not selection:
            return
        if not self.broadcasting:
            self.start_broadcast()
        index = self.tree.index(selection[0])
        target_time = sum(video['duration'] for video in self.videos[:index])
        current_time = time.time()
        elapsed = (current_time - self.broadcast_start_time) + self.manual_time_offset
        adjustment = target_time - elapsed
        self.manual_time_offset += adjustment

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
            # If now empty, auto-switch to fillers if available
            if self.obs_client and self.fillers:
                self.play_fillers_if_needed()

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

        start_seconds = self.time_to_seconds(self.start_time_var.get())
        schedule = {
            "videos": [],
            "start_time": self.start_time_var.get(),
            "total_duration": sum(v['duration'] for v in self.videos)
        }

        current_time = start_seconds
        for i, video in enumerate(self.videos):
            schedule["videos"].append({
                "index": i,
                "filename": video["filename"],
                "filepath": os.path.abspath(video["filepath"]),
                "duration": float(video["duration"]),
                "start_time": int(current_time),
                "start_formatted": self.format_duration(current_time),
                "end_formatted": self.format_duration(current_time + video["duration"]),
                "scene_name": f"Video_{i+1:03d}_{self._sanitize_name(os.path.splitext(video['filename'])[0], 32)}"
            })
            current_time += video["duration"]

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(schedule, f, indent=2)
            messagebox.showinfo("Success", f"Schedule exported!\n\n{filepath}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not write file:\n{e}")

    # ---------- File/time UI ----------
    def update_current_video_indicator(self, elapsed_seconds):
        current_index = self.get_video_at_time(elapsed_seconds) if self.broadcasting else -1
        for child in self.tree.get_children():
            self.tree.set(child, 'status', '')
        if 0 <= current_index < len(self.tree.get_children()):
            current_item = self.tree.get_children()[current_index]
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

        # Immediate total duration display as soon as videos are added
        self.update_timeline()

    # ---------- Timeline ----------
    def update_timeline(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        start_seconds = self.time_to_seconds(self.start_time_var.get())
        current_time = start_seconds

        for i, video in enumerate(self.videos):
            start_time = self.format_duration(current_time)
            end_time = self.format_duration(current_time + video['duration'])
            duration_str = self.format_duration(video['duration'])
            status = '▶' if i == self.current_video_index else ''
            self.tree.insert('', 'end', values=(status, video['filename'], duration_str, start_time, end_time))
            current_time += video['duration']

        total_duration = current_time - start_seconds
        total_str = self.format_duration(total_duration)
        end_time_str = self.format_duration(current_time)
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
    try:
        root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    except Exception:
        root = tk.Tk()

    app = PlaylistScheduler(root)
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f"+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()
