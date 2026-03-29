from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional, Tuple

from config import (
    APP_NAME,
    BACK_MATERIAL_DEFAULT,
    BACK_MATERIAL_OPTIONS,
    CARCASS_MATERIAL_DEFAULT,
    CARCASS_MATERIAL_OPTIONS,
    KERF_MM,
    MAX_SHELVES,
    OVERMEASURE_MM,
    UPDATE_MANIFEST_URL,
    VERSION,
)
from excel import export_excel
from logic import Cabinet, ValidationError, calculate_elements, calculate_materials, validate
from updater import (
    ChecksumError,
    DownloadError,
    NetworkError,
    SecurityError,
    UpdateError,
    check_for_update,
    download_update,
    run_updater,
    verify_checksum,
)


def _can_auto_update() -> bool:
    try:
        import sys

        return bool(getattr(sys, "frozen", False)) and sys.executable.lower().endswith(".exe")
    except Exception:
        return False


def _format_percent(done: int, total: int) -> str:
    if total <= 0:
        return ""
    pct = int((done / total) * 100)
    pct = max(0, min(100, pct))
    return f"{pct}%"


def _user_friendly_error(err: Exception) -> str:
    if isinstance(err, SecurityError):
        return "Update blocked for security reasons (HTTPS/validation)."
    if isinstance(err, ChecksumError):
        return "Downloaded update failed verification (SHA256 checksum mismatch)."
    if isinstance(err, DownloadError):
        return "Download failed. Check your connection and try again."
    if isinstance(err, NetworkError):
        return "Unable to check for updates (no internet)."
    if isinstance(err, UpdateError):
        return str(err) or "Update error."
    return "Unexpected error."


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_NAME} v{VERSION}")
        self.minsize(920, 560)

        self._apply_styles()
        self._set_window_icon()

        self._entries: Dict[str, ttk.Entry] = {}
        self._build_ui()
        self._bind_shortcuts()

        self.after(600, self.check_updates_startup)

    def _apply_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TButton", padding=(10, 8))
        style.configure("Primary.TButton", padding=(14, 11), font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("SubHeader.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", foreground="#6B7280")
        style.configure("Status.TLabel", font=("Segoe UI", 10))
        style.configure("Card.TFrame", padding=16)
        style.configure("Toolbar.TFrame", padding=(14, 12))
        style.configure("Statusbar.TFrame", padding=(14, 8))

    def _set_window_icon(self) -> None:
        try:
            import sys

            base_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
            icon_path = os.path.join(base_dir, "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        toolbar = ttk.Frame(root, style="Toolbar.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        toolbar.grid_columnconfigure(2, weight=1)

        ttk.Label(toolbar, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text=f"v{VERSION}", style="Hint.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_updates = ttk.Button(toolbar, text="Check updates", command=self.check_updates_startup)
        self.btn_updates.grid(row=0, column=3, sticky="e")

        content = ttk.Frame(root)
        content.grid(row=1, column=0, sticky="nsew")
        root.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        grid = ttk.Frame(content)
        grid.grid(row=0, column=0, sticky="n")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        left = ttk.Frame(grid, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)

        right = ttk.Frame(grid, style="Card.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_columnconfigure(0, weight=1)

        ttk.Label(left, text="Inputs", style="SubHeader.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        form = ttk.Frame(left)
        form.grid(row=1, column=0, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        self.var_width = tk.StringVar(value="600")
        self.var_height = tk.StringVar(value="800")
        self.var_depth = tk.StringVar(value="350")
        self.var_thickness = tk.StringVar(value="19")
        self.var_shelves = tk.StringVar(value="1")
        self.var_carcass_material = tk.StringVar(value=CARCASS_MATERIAL_DEFAULT)
        self.var_back_material = tk.StringVar(value=BACK_MATERIAL_DEFAULT)

        def add_field(r: int, label: str, var: tk.StringVar, unit: str = "mm") -> None:
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=8, padx=(0, 12))
            ent = ttk.Entry(form, textvariable=var, width=20)
            ent.grid(row=r, column=1, sticky="ew", pady=8)
            ttk.Label(form, text=unit, style="Hint.TLabel").grid(row=r, column=2, sticky="w", pady=8, padx=(10, 0))
            self._entries[label.lower()] = ent

        add_field(0, "Width (dolžina)", self.var_width)
        add_field(1, "Height (višina)", self.var_height)
        add_field(2, "Depth (globina)", self.var_depth)
        add_field(3, "Thickness (debelina)", self.var_thickness)

        ttk.Label(form, text="Shelves").grid(row=4, column=0, sticky="w", pady=8, padx=(0, 12))
        self.spin_shelves = ttk.Spinbox(form, from_=0, to=MAX_SHELVES, textvariable=self.var_shelves, width=18)
        self.spin_shelves.grid(row=4, column=1, sticky="w", pady=8)
        ttk.Label(form, text="pcs", style="Hint.TLabel").grid(row=4, column=2, sticky="w", pady=8, padx=(10, 0))

        ttk.Separator(left).grid(row=2, column=0, sticky="ew", pady=14)
        ttk.Label(left, text="Materials", style="SubHeader.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 10))

        mats = ttk.Frame(left)
        mats.grid(row=4, column=0, sticky="ew")
        mats.grid_columnconfigure(1, weight=1)

        ttk.Label(mats, text="Carcass").grid(row=0, column=0, sticky="w", pady=8, padx=(0, 12))
        ttk.Combobox(
            mats,
            textvariable=self.var_carcass_material,
            values=CARCASS_MATERIAL_OPTIONS,
            state="readonly",
            width=22,
        ).grid(row=0, column=1, sticky="w", pady=8)

        ttk.Label(mats, text="Back").grid(row=1, column=0, sticky="w", pady=8, padx=(0, 12))
        ttk.Combobox(
            mats,
            textvariable=self.var_back_material,
            values=BACK_MATERIAL_OPTIONS,
            state="readonly",
            width=22,
        ).grid(row=1, column=1, sticky="w", pady=8)

        ttk.Label(right, text="Actions", style="SubHeader.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.btn_generate = ttk.Button(right, text="Generate Excel", style="Primary.TButton", command=self.on_generate)
        self.btn_generate.grid(row=1, column=0, sticky="ew")

        ttk.Label(right, text=f"Overmeasure +{OVERMEASURE_MM} mm · Kerf {KERF_MM} mm", style="Hint.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )

        ttk.Separator(right).grid(row=3, column=0, sticky="ew", pady=14)
        ttk.Label(right, text="Status", style="SubHeader.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 10))

        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(right, textvariable=self.status_var, style="Status.TLabel", wraplength=340)
        self.status_label.grid(row=5, column=0, sticky="w")

        statusbar = ttk.Frame(root, style="Statusbar.TFrame")
        statusbar.grid(row=2, column=0, sticky="ew")
        statusbar.grid_columnconfigure(0, weight=1)
        self.statusbar_var = tk.StringVar(value="Ready.")
        ttk.Label(statusbar, textvariable=self.statusbar_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(statusbar, text="Ctrl+Enter: Generate", style="Hint.TLabel").grid(row=0, column=1, sticky="e")

        try:
            self._entries["width"].focus_set()
        except Exception:
            pass

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>", lambda _e: self.on_generate())
        self.bind("<Control-Enter>", lambda _e: self.on_generate())
        self.bind("<Control-u>", lambda _e: self.check_updates_startup())

    def _parse_int(self, label: str, value: str) -> int:
        try:
            return int(str(value).strip())
        except ValueError as e:
            raise ValidationError([f"{label} must be an integer (mm)."]) from e

    def _set_status(self, text: str, ok: bool) -> None:
        msg = (text or "").strip()
        self.status_var.set(msg)
        self.statusbar_var.set(msg)
        color = "#065F46" if ok else "#991B1B"
        try:
            self.status_label.configure(foreground=color)
        except tk.TclError:
            pass

    def on_generate(self) -> None:
        try:
            cabinet = Cabinet(
                width=self._parse_int("Width", self.var_width.get()),
                height=self._parse_int("Height", self.var_height.get()),
                depth=self._parse_int("Depth", self.var_depth.get()),
                thickness=self._parse_int("Thickness", self.var_thickness.get()),
            )
            shelves_count = self._parse_int("Shelves", self.var_shelves.get())

            validate(cabinet, shelves_count)
            elements = calculate_elements(cabinet, shelves_count)
            summary = calculate_materials(cabinet, shelves_count, elements)

            file_path = filedialog.asksaveasfilename(
                title="Save Excel",
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not file_path:
                self._set_status("Canceled.", ok=True)
                return

            export_excel(
                cabinet=cabinet,
                elements=elements,
                summary=summary,
                file_path=file_path,
                carcass_material=self.var_carcass_material.get().strip() or CARCASS_MATERIAL_DEFAULT,
                back_material=self.var_back_material.get().strip() or BACK_MATERIAL_DEFAULT,
            )

            self._set_status("Excel generated successfully.", ok=True)
            messagebox.showinfo("Success", "Excel created.")

        except ValidationError as e:
            msg = "\n".join(e.messages)
            self._set_status(msg, ok=False)
            messagebox.showerror("Validation error", msg)
        except Exception as e:
            self._set_status(str(e), ok=False)
            messagebox.showerror("Error", str(e))

    def check_updates_startup(self) -> None:
        manifest = UPDATE_MANIFEST_URL.strip()
        if not manifest:
            return

        def worker() -> None:
            try:
                info = check_for_update(manifest, VERSION)
            except Exception:
                return

            if not info:
                return

            def prompt() -> None:
                if not messagebox.askyesno("Update", f"New version available ({info.version}). Update now?"):
                    return
                self._download_and_install(info)

            self.after(0, prompt)

        threading.Thread(target=worker, daemon=True).start()

    def _download_and_install(self, info) -> None:
        if not _can_auto_update():
            messagebox.showwarning("Update", "Auto-update is supported only in the packaged Windows .exe build.")
            return

        dlg, bar, lbl = self._create_progress_dialog()
        q: "queue.Queue[Tuple[str, object]]" = queue.Queue()

        def progress_cb(done: int, total: Optional[int]) -> None:
            q.put(("progress", (done, total)))

        def worker() -> None:
            try:
                path = download_update(info, progress_cb=progress_cb)
                try:
                    verify_checksum(path, info.checksum)
                except Exception:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except OSError:
                        pass
                    raise
                q.put(("done", path))
            except Exception as e:
                q.put(("error", e))

        threading.Thread(target=worker, daemon=True).start()

        def poll() -> None:
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "progress":
                        done, total = payload  # type: ignore[misc]
                        self._update_progress(bar, lbl, int(done), int(total) if total else None)
                    elif kind == "error":
                        try:
                            dlg.destroy()
                        except Exception:
                            pass
                        messagebox.showerror("Update", _user_friendly_error(payload))  # type: ignore[arg-type]
                        return
                    elif kind == "done":
                        try:
                            dlg.destroy()
                        except Exception:
                            pass
                        try:
                            run_updater(str(payload))
                        except Exception as e:
                            messagebox.showerror("Update", _user_friendly_error(e))
                            return
                        self._exit_for_update()
                        return
            except queue.Empty:
                self.after(80, poll)

        poll()

    def _create_progress_dialog(self) -> Tuple[tk.Toplevel, ttk.Progressbar, ttk.Label]:
        dlg = tk.Toplevel(self)
        dlg.title("Updating...")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        lbl = ttk.Label(frame, text="Downloading update...")
        lbl.grid(row=0, column=0, sticky="w")

        bar = ttk.Progressbar(frame, mode="determinate", length=380)
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        dlg.update_idletasks()
        return dlg, bar, lbl

    def _update_progress(self, bar: ttk.Progressbar, lbl: ttk.Label, done: int, total: Optional[int]) -> None:
        if total and total > 0:
            if str(bar["mode"]) != "determinate":
                bar.stop()
                bar.configure(mode="determinate")
            bar.configure(maximum=total)
            bar["value"] = done
            lbl.configure(text=f"Downloading update... {_format_percent(done, total)}")
        else:
            if str(bar["mode"]) != "indeterminate":
                bar.configure(mode="indeterminate")
                bar.start(10)
            lbl.configure(text="Downloading update...")

    def _exit_for_update(self) -> None:
        try:
            self.destroy()
        finally:
            os._exit(0)


def main() -> None:
    app = App()
    app.mainloop()

