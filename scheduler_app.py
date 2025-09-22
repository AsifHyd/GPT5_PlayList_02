# filename: scheduler_app.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import subprocess
import sys
from pathlib import Path
import time
import threading
from datetime import datetime

# ---- Safe tkdnd detection ----
HAS_DND = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    try:
        _probe_root = tk.Tk()
        try:
            _probe_root.tk.eval('package require tkdnd')
            HAS_DND = True
        except Exception:
            HAS_DND = False
        _probe_root.destroy()
    except Exception:
        HAS_DND = False
except Exception:
    HAS_DND = False
# ------------------------------

import obsws_python as obs  # v5 client


def seconds_since_midnight() -> int:
    now = datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second


class PlaylistScheduler:
    PLAYER_SCENE = "Scheduler_Player"
    PLAYER_INPUT = "Scheduler_Player_Input"
    FILLERS_SCENE = "Fillers_Scene"
    FILLERS_INPUT = "Fillers_Playlist"
    LEGACY_PREFIX = "Video_"

    def __init__(self, root):
        self.root = root
        self.root.title("OBS Playlist Scheduler v2.4 - Live Broadcast Automation")
        self.root.geometry("1480x900")

        # Data
        self.videos = []              # dicts: filepath, filename, duration, absolute_time
        self.clipboard_data = []
        self.fillers = []
        self.broadcasting = False
        self.broadcast_thread = None
        self.obs_client = None
        self.current_video_index = -1
        self.fillers_active = False

        # Computed times
        self.abs_starts = []
        self.abs_ends = []
        self.total_duration = 0

        # OBS connection
        self.obs_host_var = tk.StringVar(value="127.0.0.1")
        self.obs_port_var = tk.StringVar(value="4455")
        self.obs_password_var = tk.StringVar(value="")

        # Theme
        self.bg = "#2d2d2d"; self.fg = "#e6e6e6"; self.acc = "#3b3b3b"; self.sel = "#4a4a4a"
        self.ok = "#66ff99"; self.warn = "#ffcc66"; self.err = "#ff6666"

        self.setup_ui()
        self.apply_dark_theme()
        self.setup_drag_drop()

    # ---------- Utilities ----------
    def _sanitize_name(self, name: str, max_len: int = 64) -> str:
        allowed = "-_.() []{}abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(ch if ch in allowed else "_" for ch in name)[:max_len]  [web:29]

    def recompute_schedule_times(self):
        """Compute absolute start/end using explicit absolute_time first, then pack the rest sequentially after the last timed item or the default start time."""  [web:29]
        self.abs_starts = []; self.abs_ends = []  [web:29]
        if not self.videos:
            self.total_duration = 0; return  [web:29]
        timed = [(i, v) for i, v in enumerate(self.videos) if v.get('absolute_time') is not None]  [web:29]
        untimed = [(i, v) for i, v in enumerate(self.videos) if v.get('absolute_time') is None]  [web:29]
        timed.sort(key=lambda x: x[1]['absolute_time'])  [web:29]
        sched = {}  [web:29]
        for i, v in timed:
            s = v['absolute_time']; e = s + int(v['duration']); sched[i] = (s, e)  [web:29]
        base = self.time_to_seconds(self.start_time_var.get())  [web:29]
        cur = max((e for (s, e) in sched.values()), default=base)  [web:29]
        for i, v in untimed:
            s = cur; e = s + int(v['duration']); sched[i] = (s, e); cur = e  [web:29]
        for i, v in enumerate(self.videos):
            s, e = sched.get(i, (0, int(v['duration']))); self.abs_starts.append(s); self.abs_ends.append(e)  [web:29]
        self.total_duration = (max(self.abs_ends) - min(self.abs_starts)) if self.abs_starts else 0  [web:29]

    # ---------- Theme ----------
    def apply_dark_theme(self):
        try:
            self.root.configure(bg=self.bg)  [web:29]
            style = ttk.Style()  [web:29]
            try: style.theme_use("clam")
            except tk.TclError: pass  [web:29]
            style.configure(".", background=self.bg, foreground=self.fg)  [web:29]
            style.configure("TFrame", background=self.bg)  [web:29]
            style.configure("TLabelframe", background=self.bg, foreground=self.fg)  [web:29]
            style.configure("TLabelframe.Label", background=self.bg, foreground=self.fg)  [web:29]
            style.configure("TLabel", background=self.bg, foreground=self.fg)  [web:29]
            style.configure("TButton", background=self.acc, foreground=self.fg, padding=5)  [web:29]
            style.map("TButton", background=[("active", self.sel)])  [web:29]
            style.configure("TEntry", fieldbackground=self.acc, foreground=self.fg, insertcolor=self.fg)  [web:29]
            style.configure("Treeview", background=self.acc, fieldbackground=self.acc, foreground=self.fg, rowheight=26)  [web:29]
            style.configure("Treeview.Heading", background=self.acc, foreground=self.fg)  [web:29]
            style.map("Treeview", background=[("selected", self.sel)], foreground=[("selected", self.fg)])  [web:29]
            style.configure("TScrollbar", background=self.acc, troughcolor=self.bg)  [web:29]
        except Exception:
            pass  [web:29]

    # ---------- UI ----------
    def setup_ui(self):
        main = ttk.Frame(self.root, padding="10"); main.grid(row=0, column=0, sticky="nsew")  [web:29]
        self.root.columnconfigure(0, weight=1); self.root.rowconfigure(0, weight=1)  [web:29]
        main.columnconfigure(1, weight=1); main.rowconfigure(1, weight=1)  [web:29]

        # Left scrollable column
        left_container = ttk.Frame(main); left_container.grid(row=0, column=0, rowspan=2, sticky="ns")  [web:29]
        self.left_canvas = tk.Canvas(left_container, width=380, highlightthickness=0, bg=self.bg)  [web:29]
        lscroll = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=self.left_canvas.yview)  [web:29]
        self.left_inner = ttk.Frame(self.left_canvas)  [web:29]
        self.left_inner.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))  [web:29]
        self.left_canvas.create_window((0, 0), window=self.left_inner, anchor="nw")  [web:29]
        self.left_canvas.configure(yscrollcommand=lscroll.set)  [web:29]
        self.left_canvas.grid(row=0, column=0, sticky="ns"); lscroll.grid(row=0, column=1, sticky="ns")  [web:29]

        left = ttk.LabelFrame(self.left_inner, text="Broadcast Control Center", padding="6")
        left.grid(row=0, column=0, sticky="ew"); left.columnconfigure(0, weight=1)  [web:29]

        # File ops
        ttk.Label(left, text="📁 File Management", font=('Arial', 9, 'bold')).grid(row=0, column=0, pady=(0,5), sticky="w")  [web:29]
        ttk.Button(left, text="Add Videos", command=self.add_videos).grid(row=1, column=0, pady=2, sticky="ew")  [web:29]
        ttk.Button(left, text="Add Folder", command=self.add_folder).grid(row=2, column=0, pady=2, sticky="ew")  [web:29]
        ttk.Separator(left).grid(row=3, column=0, sticky="ew", pady=5)  [web:29]

        # Schedule settings
        ttk.Label(left, text="⏰ Schedule Settings", font=('Arial', 9, 'bold')).grid(row=4, column=0, pady=(0,5), sticky="w")  [web:29]
        tf = ttk.Frame(left); tf.grid(row=5, column=0, sticky="ew", pady=2); tf.columnconfigure(1, weight=1)  [web:29]
        ttk.Label(tf, text="Default Start:").grid(row=0, column=0, padx=(0,5))  [web:29]
        self.start_time_var = tk.StringVar(value="00:00:00")  [web:29]
        ttk.Entry(tf, textvariable=self.start_time_var, width=10).grid(row=0, column=1, sticky="w")  [web:29]
        ttk.Button(left, text="⏰ Set Current Time", command=self.set_current_time).grid(row=6, column=0, pady=2, sticky="ew")  [web:29]
        ttk.Button(left, text="🕐 Set Start for Selected", command=self.set_start_for_selected).grid(row=7, column=0, pady=2, sticky="ew")  [web:29]
        ttk.Button(left, text="🚫 Clear Start for Selected", command=self.clear_start_for_selected).grid(row=8, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Separator(left).grid(row=9, column=0, sticky="ew", pady=5)  [web:29]

        # Editing
        ttk.Label(left, text="✏️ Playlist Editing", font=('Arial', 9, 'bold')).grid(row=10, column=0, pady=(0,5), sticky="w")  [web:29]
        ttk.Button(left, text="Move Up", command=self.move_up).grid(row=11, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Button(left, text="Move Down", command=self.move_down).grid(row=12, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Button(left, text="Delete Selected", command=self.delete_selected).grid(row=13, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Button(left, text="Clear All", command=self.clear_all).grid(row=14, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Separator(left).grid(row=15, column=0, sticky="ew", pady=5)  [web:29]

        # Copy/Paste
        cpf = ttk.Frame(left); cpf.grid(row=16, column=0, sticky="ew")  [web:29]
        ttk.Button(cpf, text="📋 Copy Block", command=self.copy_block).grid(row=0, column=0, padx=(0,4), sticky="ew")  [web:29]
        ttk.Button(cpf, text="📥 Paste Block", command=self.paste_block).grid(row=0, column=1, sticky="ew")  [web:29]
        cpf.columnconfigure(0, weight=1); cpf.columnconfigure(1, weight=1)  [web:29]
        ttk.Separator(left).grid(row=17, column=0, sticky="ew", pady=5)  [web:29]

        # OBS connection
        ttk.Label(left, text="🔗 OBS Connection", font=('Arial', 9, 'bold')).grid(row=18, column=0, pady=(0,5), sticky="w")  [web:29]
        cf = ttk.Frame(left); cf.grid(row=19, column=0, sticky="ew", pady=(0,4)); cf.columnconfigure(1, weight=1)  [web:29]
        ttk.Label(cf, text="Host").grid(row=0, column=0, padx=(0,5), sticky="w")  [web:29]
        ttk.Entry(cf, textvariable=self.obs_host_var, width=14).grid(row=0, column=1, sticky="ew")  [web:29]
        ttk.Label(cf, text="Port").grid(row=1, column=0, padx=(0,5), sticky="w")  [web:29]
        ttk.Entry(cf, textvariable=self.obs_port_var, width=8).grid(row=1, column=1, sticky="ew")  [web:29]
        ttk.Label(cf, text="Password").grid(row=2, column=0, padx=(0,5), sticky="w")  [web:29]
        ttk.Entry(cf, textvariable=self.obs_password_var, show="*", width=14).grid(row=2, column=1, sticky="ew")  [web:29]
        self.connect_btn = ttk.Button(left, text="Connect to OBS", command=self.connect_obs); self.connect_btn.grid(row=20, column=0, pady=2, sticky="ew")  [web:29]
        self.connection_status = ttk.Label(left, text="● Disconnected", foreground=self.err, font=('Arial', 8)); self.connection_status.grid(row=21, column=0, sticky="w")  [web:29]

        self.setup_player_btn = ttk.Button(left, text="🎬 Setup Player Scene", command=self.setup_player_scene)
        self.setup_player_btn.grid(row=22, column=0, pady=2, sticky="ew"); self.setup_player_btn.configure(state='disabled')  [web:29]
        self.remove_btn = ttk.Button(left, text="🗑 Remove Your Scenes", command=self.remove_app_scenes)
        self.remove_btn.grid(row=23, column=0, pady=2, sticky="ew"); self.remove_btn.configure(state='disabled')  [web:29]

        ttk.Separator(left).grid(row=24, column=0, sticky="ew", pady=5)  [web:29]

        # Live broadcast
        ttk.Label(left, text="🔴 Live Broadcast", font=('Arial', 9, 'bold')).grid(row=25, column=0, pady=(0,5), sticky="w")  [web:29]
        self.start_btn = ttk.Button(left, text="▶ Start Broadcasting", command=self.start_broadcast)
        self.start_btn.grid(row=26, column=0, pady=2, sticky="ew"); self.start_btn.configure(state='disabled')  [web:29]
        self.stop_btn = ttk.Button(left, text="⏹ Stop Broadcasting", command=self.stop_broadcast)
        self.stop_btn.grid(row=27, column=0, pady=2, sticky="ew"); self.stop_btn.configure(state='disabled')  [web:29]
        self.skip_btn = ttk.Button(left, text="⏭ Skip to Next", command=self.skip_to_next)
        self.skip_btn.grid(row=28, column=0, pady=1, sticky="ew"); self.skip_btn.configure(state='disabled')  [web:29]

        ttk.Separator(left).grid(row=29, column=0, sticky="ew", pady=5)  [web:29]

        # Fillers
        ttk.Label(left, text="🧩 Fillers (loop when idle)", font=('Arial', 9, 'bold')).grid(row=30, column=0, sticky="w")  [web:29]
        ttk.Button(left, text="➕ Add Fillers", command=self.add_fillers).grid(row=31, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Button(left, text="🧹 Clear Fillers", command=self.clear_fillers).grid(row=32, column=0, pady=1, sticky="ew")  [web:29]
        ttk.Separator(left).grid(row=33, column=0, sticky="ew", pady=5)  [web:29]
        ttk.Button(left, text="💾 Export Playlist", command=self.export_playlist).grid(row=34, column=0, pady=5, sticky="ew")  [web:29]

        # Right panel
        right = ttk.LabelFrame(main, text="🎬 Timeline & Live Status", padding="6")
        right.grid(row=0, column=1, rowspan=2, sticky="nsew"); right.columnconfigure(0, weight=1); right.rowconfigure(2, weight=1)  [web:29]

        sf = ttk.Frame(right); sf.grid(row=0, column=0, sticky="ew"); sf.columnconfigure(1, weight=1)  [web:29]
        ttk.Label(sf, text="🔴 STATUS:", font=('Arial', 10, 'bold')).grid(row=0, column=0, padx=(0,6))  [web:29]
        self.live_status_label = ttk.Label(sf, text="Not Broadcasting", font=('Arial', 10)); self.live_status_label.grid(row=0, column=1, sticky="w")  [web:29]
        self.time_label = ttk.Label(sf, text="", font=('Arial', 10, 'bold')); self.time_label.grid(row=0, column=2, padx=(5,0), sticky="e")  [web:29]

        self.file_time_label = ttk.Label(right, text="", font=('Arial', 10)); self.file_time_label.grid(row=1, column=0, sticky="ew", pady=(2,6))  [web:29]

        cols = ('status', 'filename', 'duration', 'start_time', 'end_time')  [web:29]
        self.tree = ttk.Treeview(right, columns=cols, show='headings', height=28, selectmode='extended')  [web:29]
        for c, w in [('status',34), ('filename',480), ('duration',90), ('start_time',100), ('end_time',100)]:
            self.tree.heading(c, text=c.replace('_',' ').title()); self.tree.column(c, width=w, anchor=tk.CENTER if c!='filename' else tk.W)  [web:29]
        scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.tree.yview)  [web:29]
        self.tree.configure(yscrollcommand=scr.set); self.tree.grid(row=2, column=0, sticky="nsew"); scr.grid(row=2, column=1, sticky="ns")  [web:29]

        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)  [web:29]
        self.context_menu.add_command(label="Jump to This Video", command=self.jump_to_video)  [web:29]
        self.context_menu.add_separator()  [web:29]
        self.context_menu.add_command(label="Set Start Time", command=self.context_set_start)  [web:29]
        self.context_menu.add_command(label="Clear Start Time", command=self.context_clear_start)  [web:29]
        self.context_menu.add_separator()  [web:29]
        self.context_menu.add_command(label="Show Properties", command=self.show_properties)  [web:29]
        self.context_menu.add_separator()  [web:29]
        self.context_menu.add_command(label="Move Up", command=self.move_up)  [web:29]
        self.context_menu.add_command(label="Move Down", command=self.move_down)  [web:29]
        self.context_menu.add_separator()  [web:29]
        self.context_menu.add_command(label="Delete", command=self.delete_selected)  [web:29]

        self.tree.bind("<Button-3>", self.show_context_menu)  [web:29]
        self.tree.bind("<Double-1>", lambda e: self.set_start_for_selected())  [web:29]

        self.status_var = tk.StringVar(value="Ready - Set start time and connect to OBS for automation")  [web:29]
        ttk.Label(main, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10,0))  [web:29]

        self.update_ui_loop()  [web:29]

    # ---------- Time helpers ----------
    def set_current_time(self):
        self.start_time_var.set(datetime.now().strftime("%H:%M:%S")); self.update_timeline()  [web:29]
        self.status_var.set(f"Default start time set to {self.start_time_var.get()}")  [web:29]

    def time_to_seconds(self, time_str):
        try:
            h, m, s = map(int, time_str.split(':')); return h*3600+m*60+s  [web:29]
        except Exception:
            return 0  [web:29]

    def format_duration(self, seconds):
        seconds = int(seconds); h=seconds//3600; m=(seconds%3600)//60; s=seconds%60; return f"{h:02d}:{m:02d}:{s:02d}"  [web:29]

    def format_time_or_auto(self, seconds, is_exact): 
        return f"★{self.format_duration(seconds)}" if is_exact else self.format_duration(seconds)  [web:29]

    # ---------- Absolute scheduling ----------
    def set_start_for_selected(self):
        sel = self.get_selected_indices()  [web:29]
        if not sel:
            messagebox.showwarning("Set Start Time","Select one or more videos first."); return  [web:29]
        t = simpledialog.askstring("Set Start Time","Time (HH:MM:SS), e.g., 10:00:00", initialvalue="10:00:00")  [web:29]
        if not t: return  [web:29]
        try:
            s = self.time_to_seconds(t)
            if s < 0 or s >= 86400: raise ValueError()  [web:29]
        except Exception:
            messagebox.showerror("Invalid","Use HH:MM:SS in 24‑hour format."); return  [web:29]
        for i in sel:
            if 0<=i<len(self.videos): self.videos[i]['absolute_time'] = s  [web:29]
        self.update_timeline(); self.status_var.set(f"Exact start {t} set for {len(sel)} item(s)")  [web:29]

    def clear_start_for_selected(self):
        sel = self.get_selected_indices()  [web:29]
        if not sel:
            messagebox.showwarning("Clear Start","Select one or more videos first."); return  [web:29]
        for i in sel:
            if 0<=i<len(self.videos): self.videos[i]['absolute_time'] = None  [web:29]
        self.update_timeline(); self.status_var.set(f"Cleared exact time for {len(sel)} item(s)")  [web:29]

    def context_set_start(self): self.set_start_for_selected()  [web:29]
    def context_clear_start(self): self.clear_start_for_selected()  [web:29]

    # ---------- DnD ----------
    def setup_drag_drop(self):
        try:
            if HAS_DND:
                self.tree.drop_target_register(DND_FILES); self.tree.dnd_bind('<<Drop>>', self.on_drop)  [web:29]
                self.root.drop_target_register(DND_FILES); self.root.dnd_bind('<<Drop>>', self.on_drop)  [web:29]
        except Exception:
            pass  [web:29]

    # ---------- UI loop ----------
    def update_ui_loop(self):
        if self.broadcasting and self.abs_starts:
            now = seconds_since_midnight(); tele = max(0, now - min(self.abs_starts))  [web:29]
            self.time_label.configure(text=f"Elapsed: {self.format_duration(tele)}")  [web:29]
        else:
            self.time_label.configure(text="")  [web:29]

        try:
            if self.obs_client:
                input_name = self.PLAYER_INPUT if self.is_player_ready() and 0<=self.current_video_index<len(self.videos) else (self.FILLERS_INPUT if self.fillers_active else None)  [web:29]
                if input_name:
                    st = self.obs_client.get_media_input_status(input_name)  [web:190]
                    data = getattr(st, "responseData", None) or {}  [web:190]
                    cur = int(data.get("mediaCursor", 0)); dur = int(data.get("mediaDuration", 0)); state = data.get("mediaState","")  [web:190]
                    ps = cur/1000 if dur>=1000 else cur; ts = dur/1000 if dur>=1000 else dur; rem = max(ts-ps,0)  [web:190]
                    if self.fillers_active: self.file_time_label.configure(text="Fillers are playing (advertisements)")  [web:29]
                    else: self.file_time_label.configure(text=f"File: {self.format_duration(ps)} / {self.format_duration(ts)}  (−{self.format_duration(rem)}) [{state}]")  [web:190]
                else:
                    self.file_time_label.configure(text="Fillers are playing (advertisements)" if self.fillers_active else "Nothing is playing")  [web:29]
        except Exception:
            pass  [web:29]

        self.root.after(1000, self.update_ui_loop)  [web:29]

    # ---------- OBS connection ----------
    def connect_obs(self):
        try:
            if self.obs_client:
                try: self.obs_client.disconnect()
                except Exception: pass  [web:29]
            host = (self.obs_host_var.get() or "127.0.0.1").strip()  [web:29]
            try: port = int((self.obs_port_var.get() or "4455").strip())
            except Exception: port = 4455  [web:29]
            password = self.obs_password_var.get()  [web:29]

            self.obs_client = obs.ReqClient(host=host, port=port, password=password, timeout=4)  [web:61]
            v = self.obs_client.get_version()  [web:61]
            self.connection_status.configure(text="● Connected", foreground=self.ok)  [web:29]
            self.connect_btn.configure(text="Disconnect", command=self.disconnect_obs)  [web:29]
            self.setup_player_btn.configure(state='normal'); self.remove_btn.configure(state='normal')  [web:29]
            if self.videos: self.start_btn.configure(state='normal')  [web:29]
            self.status_var.set(f"Connected to OBS {v.obs_version} at {host}:{port}")  [web:61]
        except Exception as e:
            messagebox.showerror("Connection Failed", f"Could not connect:\n\n{e}\n\nEnable OBS WebSocket and verify port/password.")  [web:29]
            self.disconnect_obs()  [web:29]

    def disconnect_obs(self):
        if self.broadcasting: self.stop_broadcast()  [web:29]
        if self.obs_client:
            try: self.obs_client.disconnect()
            except Exception: pass
            self.obs_client = None  [web:29]
        self.connection_status.configure(text="● Disconnected", foreground=self.err)  [web:29]
        self.connect_btn.configure(text="Connect to OBS", command=self.connect_obs)  [web:29]
        self.setup_player_btn.configure(state='disabled'); self.remove_btn.configure(state='disabled'); self.start_btn.configure(state='disabled')  [web:29]
        self.status_var.set("Disconnected from OBS")  [web:29]

    # ---------- Player scene ----------
    def setup_player_scene(self):
        if not self.obs_client:
            messagebox.showwarning("Setup Player","Connect to OBS first."); return  [web:29]
        try:
            try: self.obs_client.create_scene(self.PLAYER_SCENE)
            except Exception: pass  [web:29]
            try: self.obs_client.remove_input(self.PLAYER_INPUT)
            except Exception: pass  [web:29]
            self.obs_client.create_input(
                self.PLAYER_SCENE, self.PLAYER_INPUT, "ffmpeg_source",
                {"local_file":"", "is_local_file":True, "looping":False, "restart_on_activate":True, "clear_on_media_end":False, "close_when_inactive":False, "hardware_decode":False},
                True
            )  [web:29]
            self.status_var.set("Player scene ready")  [web:29]
            messagebox.showinfo("Player Scene","Player created. Use Start Broadcasting.")  [web:29]
        except Exception as e:
            messagebox.showerror("Player Scene", f"Error creating player:\n{e}")  [web:29]

    def is_player_ready(self):
        try: self.obs_client.get_input_settings(self.PLAYER_INPUT); return True  [web:27]
        except Exception: return False  [web:27]

    def play_item_on_player(self, idx:int):
        if not (0<=idx<len(self.videos)): return  [web:29]
        try:
            if not self.is_player_ready(): self.setup_player_scene()  [web:29]
            file_path = os.path.abspath(self.videos[idx]['filepath']).replace("\\","/")  [web:29]
            self.obs_client.set_input_settings(self.PLAYER_INPUT, {"local_file":file_path, "is_local_file":True}, True)  # overlay update [web:203]
            self.obs_client.set_current_program_scene(self.PLAYER_SCENE)  [web:29]
            self.obs_client.trigger_media_input_action(self.PLAYER_INPUT, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")  # restart [web:133]
            fn = self.videos[idx]['filename']; self.live_status_label.configure(text=f"🔴 NOW: {fn}", foreground=self.err)  [web:29]
            for ch in self.tree.get_children(): self.tree.set(ch, 'status', '')  [web:29]
            if 0<=idx<len(self.tree.get_children()): self.tree.set(self.tree.get_children()[idx], 'status', '▶')  [web:29]
        except Exception as e:
            print(f"Player error: {e}")  [web:29]

    # ---------- Fillers: add/clear + idempotent ensure ----------
    def add_fillers(self):
        files = filedialog.askopenfilenames(title="Select filler files (ads/media)",
                                            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.flac *.webm"), ("All files", "*.*")])  [web:29]
        if not files: return  [web:29]
        self.fillers = list(files)  [web:29]
        self.status_var.set(f"Fillers set: {len(self.fillers)} item(s)")  [web:29]
        if self.obs_client: self.ensure_fillers_scene()  [web:29]

    def clear_fillers(self):
        self.fillers = []  [web:29]
        self.status_var.set("Fillers cleared")  [web:29]

    def ensure_fillers_scene(self):
        if not self.obs_client: return  [web:29]
        try:
            try: self.obs_client.create_scene(self.FILLERS_SCENE)
            except Exception: pass  [web:29]

            # Reuse if exists
            try:
                li = self.obs_client.get_input_list()
                data = getattr(li, "responseData", None) or {}
                existing = {i.get("inputName") for i in data.get("inputs", []) if isinstance(i, dict)}  [web:27]
            except Exception:
                existing = set()  [web:27]

            if self.FILLERS_INPUT in existing:
                if len(self.fillers) > 1:
                    playlist = [{"value": os.path.abspath(p).replace("\\","/"), "hidden": False, "selected": True} for p in self.fillers]  [web:29]
                    self.obs_client.set_input_settings(self.FILLERS_INPUT, {"playlist": playlist, "loop": True, "shuffle": False, "playback_behavior":"always_play"}, True)  [web:52]
                else:
                    fp = os.path.abspath(self.fillers[0]).replace("\\","/")  [web:29]
                    self.obs_client.set_input_settings(self.FILLERS_INPUT, {"local_file": fp, "is_local_file": True, "looping": True, "restart_on_activate": True}, True)  [web:123]
                # Ensure present in scene
                try:
                    sl = self.obs_client.get_scene_item_list(self.FILLERS_SCENE)  [web:52]
                    di = getattr(sl, "responseData", None) or {}
                    names = [it.get("sourceName") for it in di.get("sceneItems", []) if isinstance(it, dict)]  [web:52]
                    if self.FILLERS_INPUT not in names:
                        self.obs_client.create_scene_item(self.FILLERS_SCENE, self.FILLERS_INPUT)  [web:52]
                except Exception:
                    pass  [web:52]
            else:
                if len(self.fillers) > 1:
                    playlist = [{"value": os.path.abspath(p).replace("\\","/"), "hidden": False, "selected": True} for p in self.fillers]  [web:29]
                    self.obs_client.create_input(self.FILLERS_SCENE, self.FILLERS_INPUT, "vlc_source", {"playlist": playlist, "loop": True, "shuffle": False, "playback_behavior":"always_play"}, True)  [web:29]
                else:
                    fp = os.path.abspath(self.fillers[0]).replace("\\","/")  [web:29]
                    self.obs_client.create_input(self.FILLERS_SCENE, self.FILLERS_INPUT, "ffmpeg_source", {"local_file": fp, "is_local_file": True, "looping": True, "restart_on_activate": True, "clear_on_media_end": False, "close_when_inactive": False, "hardware_decode": False}, True)  [web:29][web:123]
            self.status_var.set("Fillers ready")  [web:29]
        except Exception as e:
            print(f"Fillers setup warning: {e}")  [web:29]

    def play_fillers_if_needed(self):
        if not self.obs_client: return  [web:29]
        if not self.fillers:
            self.fillers_active = False; self.live_status_label.configure(text="Nothing is playing", foreground=self.fg); self.file_time_label.configure(text="Nothing is playing"); return  [web:29]
        self.ensure_fillers_scene()  [web:29]
        try:
            self.obs_client.set_current_program_scene(self.FILLERS_SCENE)  [web:29]
            self.obs_client.trigger_media_input_action(self.FILLERS_INPUT, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")  [web:133]
            self.fillers_active = True  [web:29]
            self.live_status_label.configure(text="Fillers are playing (advertisements)", foreground=self.warn)  [web:29]
            self.file_time_label.configure(text="Fillers are playing (advertisements)")  [web:29]
        except Exception as e:
            print(f"Filler playback error: {e}")  [web:29]

    # ---------- Broadcast control ----------
    def start_broadcast(self):
        if not self.obs_client:
            messagebox.showwarning("Broadcast Error","Connect to OBS first."); return  [web:29]
        self.recompute_schedule_times()  [web:29]
        if not self.videos: self.broadcasting=False; self.play_fillers_if_needed(); return  [web:29]
        self.broadcasting=True; self.fillers_active=False; self.current_video_index=-1  [web:29]
        self.broadcast_thread = threading.Thread(target=self.broadcast_controller, daemon=True); self.broadcast_thread.start()  [web:29]
        self.start_btn.configure(state='disabled'); self.stop_btn.configure(state='normal'); self.skip_btn.configure(state='normal'); self.remove_btn.configure(state='disabled')  [web:29]
        now = seconds_since_midnight(); idx = self.index_for_time(now)  [web:29]
        if idx is not None: self.play_item_on_player(idx); self.current_video_index=idx  [web:29]
        else: self.play_fillers_if_needed()  [web:29]
        self.live_status_label.configure(text="🔴 BROADCASTING LIVE", foreground=self.err); self.status_var.set("🔴 Live broadcast active")  [web:29]

    def stop_broadcast(self):
        self.broadcasting=False  [web:29]
        if self.broadcast_thread: self.broadcast_thread.join(timeout=1)  [web:29]
        self.play_fillers_if_needed()  [web:29]
        self.start_btn.configure(state='normal'); self.stop_btn.configure(state='disabled'); self.skip_btn.configure(state='disabled'); self.remove_btn.configure(state='normal')  [web:29]
        self.current_video_index=-1; self.update_timeline(); self.status_var.set("Broadcast stopped")  [web:29]

    def index_for_time(self, now_sod:int):
        if not self.videos or not self.abs_starts: return None  [web:29]
        for i,(s,e) in enumerate(zip(self.abs_starts, self.abs_ends)):
            if s<=now_sod<e: return i  [web:29]
        return None  [web:29]

    def broadcast_controller(self):
        while self.broadcasting:
            try:
                now = seconds_since_midnight(); target = self.index_for_time(now)  [web:29]
                if target is not None and target != self.current_video_index:
                    self.play_item_on_player(target); self.current_video_index=target; self.fillers_active=False  [web:29]
                if target is None and not self.fillers_active:
                    self.play_fillers_if_needed(); self.current_video_index=-1  [web:29]
                time.sleep(0.5)  [web:29]
            except Exception as e:
                print(f"Broadcast controller error: {e}"); time.sleep(1)  [web:29]

    def skip_to_next(self):
        if not self.broadcasting: return  [web:29]
        now = seconds_since_midnight(); next_idx=None  [web:29]
        for i,s in enumerate(self.abs_starts):
            if s>now: next_idx=i; break  [web:29]
        if next_idx is not None: self.play_item_on_player(next_idx); self.current_video_index=next_idx  [web:29]
        else: self.play_fillers_if_needed(); self.current_video_index=-1  [web:29]

    # ---------- Remove app scenes ----------
    def remove_app_scenes(self):
        if not self.obs_client:
            messagebox.showwarning("Remove Scenes","Connect to OBS first."); return  [web:29]
        try:
            sl = self.obs_client.get_scene_list(); data = getattr(sl,"responseData",None) or {}; raw = data.get("scenes", []) if isinstance(data, dict) else []  [web:27]
            scenes = [s.get("sceneName") for s in raw if isinstance(s, dict)]  [web:27]
            to_del = [n for n in scenes if n in (self.PLAYER_SCENE, self.FILLERS_SCENE) or (n.startswith(self.LEGACY_PREFIX) and len(n.split("_",2)[1])==3 and n.split("_",2)[1].isdigit())]  [web:29]
            safe = next((n for n in scenes if n not in to_del), None)  [web:29]
            if not to_del: messagebox.showinfo("Remove Scenes","No app-created scenes found."); return  [web:29]
            if not safe: messagebox.showwarning("Remove Scenes","No safe scene to switch to; create one manually."); return  [web:29]
            if messagebox.askyesno("Confirm", f"Remove {len(to_del)} app scenes?"):
                try: self.obs_client.set_current_program_scene(safe)
                except Exception: pass  [web:29]
                try: self.obs_client.set_current_preview_scene(safe)
                except Exception: pass  [web:29]
                removed=0  [web:29]
                for n in to_del:
                    try: self.obs_client.remove_scene(n); removed+=1
                    except Exception as e: print(f"Remove failed for {n}: {e}")  [web:29]
                self.status_var.set(f"Removed {removed} app scenes"); messagebox.showinfo("Remove Scenes", f"Removed {removed} scenes.")  [web:29]
        except Exception as e:
            messagebox.showerror("Remove Scenes", f"Error: {e}")  [web:29]

    # ---------- Editing ----------
    def get_selected_indices(self): return [self.tree.index(i) for i in self.tree.selection()]  [web:29]

    def move_up(self):
        idx = self.get_selected_indices(); 
        if not idx or idx[0]==0: return  [web:29]
        for i in idx: self.videos[i-1], self.videos[i] = self.videos[i], self.videos[i-1]  [web:29]
        self.update_timeline()  [web:29]

    def move_down(self):
        idx = self.get_selected_indices(); 
        if not idx or idx[-1]==len(self.videos)-1: return  [web:29]
        for i in reversed(idx): self.videos[i+1], self.videos[i] = self.videos[i], self.videos[i+1]  [web:29]
        self.update_timeline()  [web:29]

    def delete_selected(self):
        idx = self.get_selected_indices(); 
        if not idx: return  [web:29]
        if messagebox.askyesno("Confirm", f"Delete {len(idx)} videos?"):
            for i in reversed(idx): del self.videos[i]  [web:29]
            self.update_timeline()  [web:29]

    def clear_all(self):
        if self.videos and messagebox.askyesno("Clear All","Clear entire playlist?"):
            self.videos.clear(); self.update_timeline()  [web:29]
            if self.obs_client and self.fillers: self.play_fillers_if_needed()  [web:29]

    def copy_block(self):
        idx = self.get_selected_indices(); 
        if not idx: return  [web:29]
        self.clipboard_data = [self.videos[i].copy() for i in idx]; self.status_var.set(f"Copied {len(idx)} item(s)")  [web:29]

    def paste_block(self):
        if not self.clipboard_data: return  [web:29]
        idx = self.get_selected_indices(); ins = idx[-1]+1 if idx else len(self.videos)  [web:29]
        for j,v in enumerate(self.clipboard_data): self.videos.insert(ins+j, v.copy())  [web:29]
        self.update_timeline(); self.status_var.set(f"Pasted {len(self.clipboard_data)} item(s) at position {ins+1}")  [web:29]

    # ---------- Export ----------
    def export_playlist(self):
        if not self.videos: messagebox.showinfo("Export","No videos to export."); return  [web:29]
        p = filedialog.asksaveasfilename(title="Export schedule", defaultextension=".json", filetypes=[("Schedule","*.json"),("All","*.*")])  [web:29]
        if not p: return  [web:29]
        self.recompute_schedule_times()  [web:29]
        sched = {"videos":[], "start_time": self.start_time_var.get(), "total_duration": self.total_duration, "fillers":[os.path.abspath(f) for f in self.fillers]}  [web:29]
        for i,v in enumerate(self.videos):
            sched["videos"].append({"index":i,"filename":v["filename"],"filepath":os.path.abspath(v["filepath"]), "duration":float(v["duration"]), "absolute_time":v.get("absolute_time"), "start_time_abs":int(self.abs_starts[i]), "start_formatted": self.format_duration(self.abs_starts[i]), "end_formatted": self.format_duration(self.abs_ends[i]), "scene_name": self.PLAYER_SCENE, "is_exact_time": v.get("absolute_time") is not None})  [web:29]
        try:
            with open(p,"w",encoding="utf-8") as f: json.dump(sched,f,indent=2)  [web:29]
            messagebox.showinfo("Success", f"Schedule exported!\n\n{p}")  [web:29]
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not write file:\n{e}")  [web:29]

    # ---------- Add files ----------
    def add_videos(self):
        ft = [("Video files","*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm"), ("All files","*.*")]
        files = filedialog.askopenfilenames(title="Select videos", filetypes=ft)  [web:29]
        if files: self.process_files(files)  [web:29]

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select video folder")  [web:29]
        if folder:
            exts={'.mp4','.avi','.mov','.mkv','.wmv','.flv','.webm'}  [web:29]
            files=[os.path.join(folder,f) for f in os.listdir(folder) if Path(f).suffix.lower() in exts]  [web:29]
            if files: files.sort(); self.process_files(files)  [web:29]

    def process_files(self, files, insert_at=None):
        self.status_var.set("Processing videos..."); self.root.update()  [web:29]
        new=[]
        for fp in files:
            fn=os.path.basename(fp); dur=self.get_video_duration(fp)  [web:29]
            new.append({'filepath':fp, 'filename':fn, 'duration':dur, 'absolute_time':None})  [web:29]
        if insert_at is not None:
            for i,v in enumerate(new): self.videos.insert(insert_at+i, v)  [web:29]
        else: self.videos.extend(new)  [web:29]
        self.update_timeline()  [web:29]

    # ---------- Timeline ----------
    def update_timeline(self):
        self.recompute_schedule_times()  [web:29]
        for i in self.tree.get_children(): self.tree.delete(i)  [web:29]
        for i,v in enumerate(self.videos):
            st=self.format_time_or_auto(self.abs_starts[i], v.get('absolute_time') is not None)
            et=self.format_duration(self.abs_ends[i]); dur=self.format_duration(v['duration'])
            status='▶' if i==self.current_video_index else ''
            self.tree.insert('', 'end', values=(status, v['filename'], dur, st, et))  [web:29]
        if self.abs_starts and self.abs_ends:
            earliest=min(self.abs_starts); latest=max(self.abs_ends); span=self.format_duration(latest-earliest)
            exact=sum(1 for v in self.videos if v.get('absolute_time') is not None); auto=len(self.videos)-exact
            self.status_var.set(f"Schedule: {self.format_duration(earliest)} to {self.format_duration(latest)} | Span: {span} | {exact} exact, {auto} auto | {len(self.fillers)} fillers")  [web:29]
        else:
            self.status_var.set("Schedule empty")  [web:29]

    # ---------- DnD / Properties ----------
    def on_drop(self, event):
        files=self.root.tk.splitlist(event.data); vids=[]
        for f in files:
            p=f.strip('{}')
            if os.path.isfile(p) and Path(p).suffix.lower() in {'.mp4','.avi','.mov','.mkv','.wmv','.flv','.webm'}: vids.append(p)  [web:29]
        if vids: self.process_files(vids)  [web:29]

    def show_context_menu(self, event):
        try: self.context_menu.tk_popup(event.x_root, event.y_root)
        finally: self.context_menu.grab_release()  [web:29]

    def show_properties(self):
        sel=self.tree.selection()
        if sel:
            i=self.tree.index(sel[0]); v=self.videos[i]
            exact = f"Exact: {self.format_duration(v['absolute_time'])}" if v.get('absolute_time') is not None else "Auto-scheduled"
            info=f"File: {v['filename']}\nPath: {v['filepath']}\nDuration: {self.format_duration(v['duration'])}\n{exact}"
            messagebox.showinfo("Video Info", info)  [web:29]

    # ---------- Video IO ----------
    def get_video_duration(self, fp):
        try:
            ff='ffprobe' if not getattr(sys,'frozen',False) else os.path.join(sys._MEIPASS,'ffprobe.exe')  [web:29]
            r=subprocess.run([ff,'-v','quiet','-print_format','json','-show_format',fp],capture_output=True,text=True,timeout=10)  [web:29]
            if r.returncode==0:
                d=json.loads(r.stdout); return float(d['format']['duration'])  [web:29]
            else: return max(os.path.getsize(fp)/(1024*1024*2),30)  [web:29]
        except Exception: return 60  [web:29]

 
def main():
    if HAS_DND:
        try: root=TkinterDnD.Tk()  # type: ignore
        except Exception: root=tk.Tk()  [web:29]
    else: root=tk.Tk()  [web:29]
    app=PlaylistScheduler(root); root.update_idletasks()  [web:29]
    x=(root.winfo_screenwidth()//2)-(root.winfo_width()//2); y=(root.winfo_screenheight()//2)-(root.winfo_height()//2)  [web:29]
    root.geometry(f"+{x}+{y}"); root.mainloop()  [web:29]


if __name__=="__main__":
    main()  [web:29]
