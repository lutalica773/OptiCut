from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Tuple

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
        return "Posodobitev je blokirana zaradi varnosti (HTTPS/validacija)."
    if isinstance(err, ChecksumError):
        return "Prenesena posodobitev ni prestala verifikacije (SHA256)."
    if isinstance(err, DownloadError):
        return "Prenos ni uspel. Preverite internet povezavo in poskusite znova."
    if isinstance(err, NetworkError):
        return "Ni mogoče preveriti posodobitev (ni internet povezave)."
    if isinstance(err, UpdateError):
        return str(err) or "Napaka pri posodabljanju."
    return "Nepričakovana napaka."


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_NAME} v{VERSION}")
        self.minsize(720, 520)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TButton", padding=(10, 8))
        style.configure("Primary.TButton", padding=(14, 10), font=("Segoe UI", 10, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Hint.TLabel", foreground="#6B7280")
        style.configure("Status.TLabel", font=("Segoe UI", 10))

        root = ttk.Frame(self, padding=18)
        root.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"v{VERSION}", style="Hint.TLabel").grid(row=0, column=1, sticky="e")

        self.var_width = tk.StringVar(value="600")
        self.var_height = tk.StringVar(value="800")
        self.var_depth = tk.StringVar(value="350")
        self.var_thickness = tk.StringVar(value="19")
        self.var_shelves = tk.StringVar(value="1")

        self.var_carcass_material = tk.StringVar(value=CARCASS_MATERIAL_DEFAULT)
        self.var_back_material = tk.StringVar(value=BACK_MATERIAL_DEFAULT)

        content = ttk.Frame(root)
        content.grid(row=1, column=0, sticky="n")
        root.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)

        input_panel = ttk.LabelFrame(content, text="Input", padding=14)
        input_panel.grid(row=0, column=0, sticky="ew")
        input_panel.grid_columnconfigure(1, weight=1)

        def add_labeled_entry(r: int, label: str, var: tk.StringVar, suffix: str = "mm") -> None:
            ttk.Label(input_panel, text=label).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 10))
            ttk.Entry(input_panel, textvariable=var, width=18).grid(row=r, column=1, sticky="w", pady=6)
            ttk.Label(input_panel, text=suffix, style="Hint.TLabel").grid(row=r, column=2, sticky="w", pady=6, padx=(8, 0))

        add_labeled_entry(0, "Width", self.var_width)
        add_labeled_entry(1, "Height", self.var_height)
        add_labeled_entry(2, "Depth", self.var_depth)
        add_labeled_entry(3, "Thickness", self.var_thickness)

        ttk.Label(input_panel, text="Shelves").grid(row=4, column=0, sticky="w", pady=6, padx=(0, 10))
        ttk.Spinbox(input_panel, from_=0, to=MAX_SHELVES, textvariable=self.var_shelves, width=16).grid(
            row=4, column=1, sticky="w", pady=6
        )
        ttk.Label(input_panel, text="pcs", style="Hint.TLabel").grid(row=4, column=2, sticky="w", pady=6, padx=(8, 0))

        ttk.Label(input_panel, text="Carcass material").grid(row=5, column=0, sticky="w", pady=6, padx=(0, 10))
        ttk.Combobox(
            input_panel,
            textvariable=self.var_carcass_material,
            values=CARCASS_MATERIAL_OPTIONS,
            state="readonly",
            width=18,
        ).grid(row=5, column=1, sticky="w", pady=6)

        ttk.Label(input_panel, text="Back material").grid(row=6, column=0, sticky="w", pady=6, padx=(0, 10))
        ttk.Combobox(
            input_panel,
            textvariable=self.var_back_material,
            values=BACK_MATERIAL_OPTIONS,
            state="readonly",
            width=18,
        ).grid(row=6, column=1, sticky="w", pady=6)

        actions = ttk.LabelFrame(content, text="Actions", padding=14)
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        actions.grid_columnconfigure(0, weight=1)
        ttk.Button(actions, text="Generate Excel", style="Primary.TButton", command=self.on_generate).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(actions, text=f"Overmeasure +{OVERMEASURE_MM} mm | Kerf {KERF_MM} mm", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )

        status_panel = ttk.LabelFrame(content, text="Status", padding=14)
        status_panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        status_panel.grid_columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(status_panel, textvariable=self.status_var, style="Status.TLabel", wraplength=560)
        self.status_label.grid(row=0, column=0, sticky="w")

        self.after(350, self.check_updates_startup)

    def _parse_int(self, label: str, value: str) -> int:
        try:
            return int(str(value).strip())
        except ValueError as e:
            raise ValidationError([f"{label} mora biti celo število (mm)."]) from e

    def on_generate(self) -> None:
        try:
            cabinet = Cabinet(
                width=self._parse_int("Širina", self.var_width.get()),
                height=self._parse_int("Višina", self.var_height.get()),
                depth=self._parse_int("Globina", self.var_depth.get()),
                thickness=self._parse_int("Debelina", self.var_thickness.get()),
            )
            shelves_count = self._parse_int("Število polic", self.var_shelves.get())

            validate(cabinet, shelves_count)
            elements = calculate_elements(cabinet, shelves_count)
            summary = calculate_materials(cabinet, shelves_count, elements)

            file_path = filedialog.asksaveasfilename(
                title="Shrani Excel",
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not file_path:
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
            messagebox.showinfo("OK", "Excel created.")

        except ValidationError as e:
            msg = "\n".join(e.messages)
            self._set_status(msg, ok=False)
            messagebox.showerror("Error (validation)", msg)
        except Exception as e:
            self._set_status(str(e), ok=False)
            messagebox.showerror("Error", str(e))

    def _set_status(self, text: str, ok: bool) -> None:
        self.status_var.set(text.strip() if text else "")
        color = "#065F46" if ok else "#991B1B"
        try:
            self.status_label.configure(foreground=color)
        except tk.TclError:
            pass

    def check_updates_startup(self) -> None:
        manifest = UPDATE_MANIFEST_URL.strip()
        if not manifest:
            return

        def worker() -> None:
            try:
                info = check_for_update(manifest, VERSION)
            except Exception:
                # startup check is silent by default
                return

            if not info:
                return

            def prompt() -> None:
                if not messagebox.askyesno("Update", f"Nova verzija je na voljo ({info.version}). Želite posodobiti?"):
                    return
                self._download_and_install(info)

            self.after(0, prompt)

        threading.Thread(target=worker, daemon=True).start()

    def _download_and_install(self, info) -> None:
        if not _can_auto_update():
            messagebox.showwarning("Update", "Auto-update je podprt samo v paketirani Windows .exe verziji.")
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
        dlg.title("Posodabljanje...")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        lbl = ttk.Label(frame, text="Prenašanje posodobitve...")
        lbl.grid(row=0, column=0, sticky="w")

        bar = ttk.Progressbar(frame, mode="determinate", length=360)
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
            lbl.configure(text=f"Prenašanje posodobitve... {_format_percent(done, total)}")
        else:
            if str(bar["mode"]) != "indeterminate":
                bar.configure(mode="indeterminate")
                bar.start(10)
            lbl.configure(text="Prenašanje posodobitve...")

    def _exit_for_update(self) -> None:
        try:
            self.destroy()
        finally:
            os._exit(0)


def main() -> None:
    app = App()
    app.mainloop()
