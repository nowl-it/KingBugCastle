#!/usr/bin/env python3
"""
Shared Tkinter GUI engine for extracting KGC art assets from Unity bundles.

Used by extract_treasures_gui.py and extract_legacies_gui.py. Each entry
script supplies an ExtractConfig (title, asset-type definitions, default
bundle dir) and calls run(config).

Workflow in the GUI:
  1. pick the source bundle dir (aa/Android of a converted build)
  2. tick which image types to pull
  3. "Quet / Demo" -> loads the needed bundles, finds matches, shows a
     thumbnail grid (each with a checkbox so you can deselect individual
     assets before export)
  4. pick an export dir, "Export da chon" writes the ticked PNGs full-res
"""

import os
import re
import glob
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import UnityPy
from PIL import Image, ImageTk


# ---- default bundle dir: newest converted build under unity/ -----------------

def _default_bundle_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)  # ~/Code/kgc
    pat = os.path.join(root, "unity", "*", "*", "temp", "extracted_assets",
                       "assets", "aa", "Android")
    cands = sorted(glob.glob(pat))
    return cands[-1] if cands else os.getcwd()


class AssetType:
    """One selectable image type."""
    def __init__(self, key, label, name_regex, bundle_keywords):
        self.key = key
        self.label = label
        self.regex = re.compile(name_regex)
        self.bundle_keywords = bundle_keywords  # filename substrings to load


class ExtractConfig:
    def __init__(self, title, types, default_dir=None, default_export=None):
        self.title = title
        self.types = types  # list[AssetType]
        self.default_dir = default_dir or _default_bundle_dir()
        self.default_export = default_export or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "reports", "assets", "extracted")


# ---- bundle loading / scanning ----------------------------------------------

class Engine:
    def __init__(self, config):
        self.config = config
        self._env_cache = {}

    def _bundle_files(self, bundle_dir, selected_types):
        keywords = set()
        for t in selected_types:
            keywords.update(t.bundle_keywords)
        files = []
        for kw in keywords:
            files += glob.glob(os.path.join(bundle_dir, f"*{kw}*.bundle"))
        return sorted(set(files))

    def _load_env(self, files):
        key = frozenset(files)
        if key not in self._env_cache:
            self._env_cache[key] = UnityPy.load(*files)
        return self._env_cache[key]

    def scan(self, bundle_dir, selected_types, progress_cb=None):
        """Return list of dicts: {name, type, image(PIL)}."""
        files = self._bundle_files(bundle_dir, selected_types)
        if not files:
            raise RuntimeError("Khong tim thay bundle phu hop trong: " + bundle_dir)
        if progress_cb:
            progress_cb(f"Dang nap {len(files)} bundle...")
        env = self._load_env(files)

        # name -> (AssetType, obj) ; prefer Sprite over Texture2D for same name
        picked = {}
        objs = [o for o in env.objects if o.type.name in ("Sprite", "Texture2D")]
        total = len(objs)
        for i, o in enumerate(objs):
            if progress_cb and i % 500 == 0:
                progress_cb(f"Quet asset {i}/{total}...")
            try:
                d = o.read()
                name = getattr(d, "m_Name", "") or ""
            except Exception:
                continue
            if not name:
                continue
            mt = None
            for t in selected_types:
                if t.regex.fullmatch(name):
                    mt = t
                    break
            if mt is None:
                continue
            prev = picked.get(name)
            if prev is None or (o.type.name == "Sprite" and prev[1].type.name != "Sprite"):
                picked[name] = (mt, o)

        results = []
        names = sorted(picked)
        for i, name in enumerate(names):
            if progress_cb and i % 25 == 0:
                progress_cb(f"Giai ma anh {i}/{len(names)}...")
            mt, o = picked[name]
            try:
                img = o.read().image
                if img is None:
                    continue
                results.append({"name": name, "type": mt.label,
                                "image": img.convert("RGBA")})
            except Exception:
                continue
        if progress_cb:
            progress_cb(f"Tim thay {len(results)} asset.")
        return results


# ---- GUI ---------------------------------------------------------------------

class App:
    THUMB = 110

    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.engine = Engine(config)
        self.results = []
        self.item_vars = []      # list[(tk.BooleanVar, result)]
        self._thumb_refs = []    # keep PhotoImage refs

        root.title(config.title)
        root.geometry("1000x720")

        self._build_controls()
        self._build_preview()
        self._build_statusbar()

    def _build_controls(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        # source dir
        ttk.Label(top, text="Thu muc bundle (aa/Android):").grid(row=0, column=0, sticky="w")
        self.src_var = tk.StringVar(value=self.config.default_dir)
        ttk.Entry(top, textvariable=self.src_var, width=80).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(top, text="Chon...", command=self._pick_src).grid(row=0, column=2)

        # export dir
        ttk.Label(top, text="Thu muc export:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.out_var = tk.StringVar(value=self.config.default_export)
        ttk.Entry(top, textvariable=self.out_var, width=80).grid(row=1, column=1, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(top, text="Chon...", command=self._pick_out).grid(row=1, column=2, pady=(6, 0))

        top.columnconfigure(1, weight=1)

        # type checkboxes
        types_box = ttk.LabelFrame(self.root, text="Loai anh", padding=8)
        types_box.pack(fill="x", padx=10)
        self.type_vars = {}
        for i, t in enumerate(self.config.types):
            v = tk.BooleanVar(value=True)
            self.type_vars[t.key] = v
            ttk.Checkbutton(types_box, text=t.label, variable=v).grid(
                row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)

        # action buttons
        actions = ttk.Frame(self.root, padding=(10, 6))
        actions.pack(fill="x")
        self.scan_btn = ttk.Button(actions, text="Quet / Demo", command=self._on_scan)
        self.scan_btn.pack(side="left")
        ttk.Button(actions, text="Chon tat ca", command=lambda: self._set_all(True)).pack(side="left", padx=6)
        ttk.Button(actions, text="Bo chon tat ca", command=lambda: self._set_all(False)).pack(side="left")
        self.export_btn = ttk.Button(actions, text="Export da chon", command=self._on_export, state="disabled")
        self.export_btn.pack(side="left", padx=12)

    def _build_preview(self):
        wrap = ttk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=10, pady=6)
        self.canvas = tk.Canvas(wrap, background="#1c1f2a", highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(fill="x")
        self.status = tk.StringVar(value="San sang.")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.pbar = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.pbar.pack(side="right")

    # -- dir pickers --
    def _pick_src(self):
        d = filedialog.askdirectory(initialdir=self.src_var.get() or os.getcwd())
        if d:
            self.src_var.set(d)

    def _pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or os.getcwd())
        if d:
            self.out_var.set(d)

    def _set_status(self, msg):
        self.status.set(msg)

    def _selected_types(self):
        return [t for t in self.config.types if self.type_vars[t.key].get()]

    # -- scan --
    def _on_scan(self):
        types = self._selected_types()
        if not types:
            messagebox.showwarning(self.config.title, "Chon it nhat 1 loai anh.")
            return
        src = self.src_var.get()
        if not os.path.isdir(src):
            messagebox.showerror(self.config.title, "Thu muc bundle khong ton tai.")
            return
        self.scan_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.pbar.start(12)
        threading.Thread(target=self._scan_worker, args=(src, types), daemon=True).start()

    def _scan_worker(self, src, types):
        try:
            res = self.engine.scan(src, types,
                                   progress_cb=lambda m: self.root.after(0, self._set_status, m))
            self.root.after(0, self._scan_done, res)
        except Exception as e:
            traceback.print_exc()
            self.root.after(0, self._scan_error, str(e))

    def _scan_error(self, msg):
        self.pbar.stop()
        self.scan_btn.config(state="normal")
        self._set_status("Loi: " + msg)
        messagebox.showerror(self.config.title, msg)

    def _scan_done(self, results):
        self.pbar.stop()
        self.scan_btn.config(state="normal")
        self.results = results
        self._render_grid()
        self.export_btn.config(state=("normal" if results else "disabled"))
        self._set_status(f"Demo {len(results)} asset. Bo tick cai khong muon roi Export.")

    def _render_grid(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.item_vars = []
        self._thumb_refs = []
        cols = 7
        for idx, r in enumerate(self.results):
            cell = ttk.Frame(self.grid_frame, padding=4)
            cell.grid(row=idx // cols, column=idx % cols, sticky="n")
            thumb = r["image"].copy()
            thumb.thumbnail((self.THUMB, self.THUMB), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_refs.append(photo)
            tk.Label(cell, image=photo, background="#0e1016").pack()
            var = tk.BooleanVar(value=True)
            self.item_vars.append((var, r))
            w, h = r["image"].size
            ttk.Checkbutton(cell, text=f"{r['name']}\n{w}x{h}", variable=var).pack()

    def _set_all(self, val):
        for var, _ in self.item_vars:
            var.set(val)

    # -- export --
    def _on_export(self):
        out = self.out_var.get()
        chosen = [r for var, r in self.item_vars if var.get()]
        if not chosen:
            messagebox.showwarning(self.config.title, "Chua tick asset nao.")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except Exception as e:
            messagebox.showerror(self.config.title, "Khong tao duoc thu muc export: " + str(e))
            return
        self.export_btn.config(state="disabled")
        self.pbar.start(12)
        threading.Thread(target=self._export_worker, args=(out, chosen), daemon=True).start()

    def _export_worker(self, out, chosen):
        ok = 0
        for i, r in enumerate(chosen):
            try:
                r["image"].save(os.path.join(out, r["name"] + ".png"))
                ok += 1
            except Exception:
                traceback.print_exc()
            if i % 10 == 0:
                self.root.after(0, self._set_status, f"Export {i}/{len(chosen)}...")
        self.root.after(0, self._export_done, ok, len(chosen), out)

    def _export_done(self, ok, total, out):
        self.pbar.stop()
        self.export_btn.config(state="normal")
        self._set_status(f"Xong: {ok}/{total} anh -> {out}")
        messagebox.showinfo(self.config.title, f"Da export {ok}/{total} anh vao:\n{out}")


def run(config):
    root = tk.Tk()
    App(root, config)
    root.mainloop()
