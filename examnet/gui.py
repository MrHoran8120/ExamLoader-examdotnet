import json
import logging
import os
import queue
import threading
import tkinter as tk
import webbrowser
from collections import Counter
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import APP_NAME, DOWNLOAD_URL, LAST_VERIFIED, __version__
from .browser import EXAM_NET_URL, BrowserNotFoundError, is_cdp_available, launch_browser
from .cli import build_question_schema_text, configure_logging
from .paths import data_file, documents_dir, logs_dir
from .json_precheck import _extract_json_payload, _strip_jsonc_comments, run_json_precheck

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
POLL_MS = 100
CLIPBOARD_FILE = "clipboard_questions.json"


def extract_clipboard_json(raw_text):
    """Pull a JSON payload out of copied text (e.g. a ChatGPT reply).

    Handles ```json fences and surrounding prose. Returns (payload, error):
    error is None when the payload parses as JSON (comments allowed).
    """
    payload = _extract_json_payload(raw_text)
    if not payload:
        return "", None

    def parse_error(text):
        try:
            json.loads(_strip_jsonc_comments(text))
            return None
        except json.JSONDecodeError as e:
            return f"{e.msg} (line {e.lineno}, column {e.colno})"

    error = parse_error(payload)
    if error is None:
        return payload, None

    # Trim any chat text before the first '[' / '{' and after the last ']' / '}'.
    starts = [i for i in (payload.find("["), payload.find("{")) if i != -1]
    end = max(payload.rfind("]"), payload.rfind("}"))
    if starts and end > min(starts):
        trimmed = payload[min(starts) : end + 1]
        if parse_error(trimmed) is None:
            return trimmed, None
    return payload, error


class QueueLogHandler(logging.Handler):
    """Forwards log records from the worker thread to the GUI thread."""

    def __init__(self, event_queue):
        super().__init__()
        self.event_queue = event_queue

    def emit(self, record):
        try:
            self.event_queue.put(("log", record.levelno, self.format(record)))
        except Exception:
            self.handleError(record)


class ExamNetGui:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.worker = None
        self.stop_requested = threading.Event()

        self.json_path = tk.StringVar(value="")
        self.continue_on_error = tk.BooleanVar(value=False)
        self.bypass_precheck = tk.BooleanVar(value=False)
        self.max_attempts = tk.IntVar(value=1)
        self.log_level = tk.StringVar(value="INFO")
        self.browser_url = tk.StringVar(value="http://127.0.0.1:9222")
        self.debug_preview = tk.BooleanVar(value=False)
        self.debug_preview_ms = tk.IntVar(value=5000)
        self.debug_confirm = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose a questions JSON file, then click Start.")
        self.log_file_path = None

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_MS, self._poll_events)
        # Open Chrome straight away so the user can log in to exam.net before clicking Start.
        self.root.after(300, self._open_chrome)

    # ---------- layout ----------

    def _build(self):
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.minsize(760, 560)
        pad = {"padx": 8, "pady": 4}

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        # Questions file
        file_frame = ttk.LabelFrame(main, text="Questions file", padding=8)
        file_frame.grid(row=0, column=0, sticky="ew", **pad)
        file_frame.columnconfigure(0, weight=1)
        ttk.Entry(file_frame, textvariable=self.json_path).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(file_frame, text="Browse...", command=self._browse).grid(row=0, column=1, padx=2)
        ttk.Button(file_frame, text="Paste from clipboard", command=self._paste_from_clipboard).grid(
            row=0, column=2, padx=2
        )
        ttk.Button(file_frame, text="Validate", command=self._validate).grid(row=0, column=3, padx=2)
        ttk.Button(file_frame, text="Copy JSON schema", command=self._copy_schema).grid(row=0, column=4, padx=2)

        # Options
        opt_frame = ttk.LabelFrame(main, text="Options", padding=8)
        opt_frame.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Checkbutton(
            opt_frame, text="Continue after a failed question", variable=self.continue_on_error
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(
            opt_frame, text="Skip JSON precheck", variable=self.bypass_precheck
        ).grid(row=0, column=1, sticky="w", padx=(0, 16))
        ttk.Label(opt_frame, text="Attempts per question:").grid(row=0, column=2, sticky="e")
        ttk.Spinbox(opt_frame, from_=1, to=5, width=4, textvariable=self.max_attempts).grid(
            row=0, column=3, sticky="w", padx=(4, 16)
        )
        ttk.Label(opt_frame, text="Log level:").grid(row=0, column=4, sticky="e")
        ttk.Combobox(
            opt_frame, values=LOG_LEVELS, width=9, state="readonly", textvariable=self.log_level
        ).grid(row=0, column=5, sticky="w", padx=4)

        # Advanced / debug options, collapsed by default
        self.adv_visible = False
        self.adv_toggle = ttk.Button(opt_frame, text="Show advanced ▸", command=self._toggle_advanced)
        self.adv_toggle.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.adv_frame = ttk.Frame(opt_frame)
        ttk.Label(self.adv_frame, text="Browser debug URL:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self.adv_frame, textvariable=self.browser_url, width=28).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Checkbutton(
            self.adv_frame, text="Highlight 'Create question' before clicking (ms):", variable=self.debug_preview
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Spinbox(
            self.adv_frame, from_=0, to=30000, increment=500, width=7, textvariable=self.debug_preview_ms
        ).grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Checkbutton(
            self.adv_frame, text="Ask before each 'Create question' click", variable=self.debug_confirm
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        # Run controls
        run_frame = ttk.Frame(main)
        run_frame.grid(row=2, column=0, sticky="ew", **pad)
        run_frame.columnconfigure(2, weight=1)
        self.start_btn = ttk.Button(run_frame, text="Start", command=self._start)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_btn = ttk.Button(run_frame, text="Stop after current question", command=self._stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(0, 6))
        self.progress = ttk.Progressbar(run_frame, mode="determinate")
        self.progress.grid(row=0, column=2, sticky="ew", padx=6)
        self.chrome_btn = ttk.Button(run_frame, text="Open browser", command=self._open_chrome)
        self.chrome_btn.grid(row=0, column=3, padx=(0, 6))
        ttk.Button(run_frame, text="Open logs folder", command=self._open_logs).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(run_frame, text="About", command=self._show_about).grid(row=0, column=5)

        ttk.Label(main, textvariable=self.status, anchor="w").grid(row=3, column=0, sticky="ew", **pad)

        # Log output
        self.log_text = ScrolledText(main, height=18, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.grid(row=4, column=0, sticky="nsew", **pad)
        self.log_text.tag_configure("DEBUG", foreground="#777777")
        self.log_text.tag_configure("WARNING", foreground="#b36b00")
        self.log_text.tag_configure("ERROR", foreground="#c62828")

    def _toggle_advanced(self):
        self.adv_visible = not self.adv_visible
        if self.adv_visible:
            self.adv_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))
            self.adv_toggle.configure(text="Hide advanced ▾")
        else:
            self.adv_frame.grid_remove()
            self.adv_toggle.configure(text="Show advanced ▸")

    # ---------- helpers ----------

    def _append_log(self, levelno, text):
        tag = logging.getLevelName(levelno)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag if tag in ("DEBUG", "WARNING", "ERROR") else ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _resolved_json_path(self):
        path = self.json_path.get().strip().strip('"')
        if not path:
            messagebox.showwarning("No file", "Choose a questions JSON file first.")
            return None
        if not os.path.exists(path):
            messagebox.showerror("File not found", f"Could not find:\n{path}")
            return None
        return path

    def _set_running(self, running):
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    # ---------- actions ----------

    def _browse(self):
        initial = os.path.dirname(self.json_path.get()) or documents_dir()
        path = filedialog.askopenfilename(
            title="Choose questions JSON file",
            initialdir=initial,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.json_path.set(os.path.normpath(path))

    def _paste_from_clipboard(self):
        try:
            raw_text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard empty", "The clipboard doesn't contain any text.")
            return

        payload, error = extract_clipboard_json(raw_text)
        if not payload:
            messagebox.showwarning("Clipboard empty", "The clipboard doesn't contain any text.")
            return
        if error and not messagebox.askyesno(
            "JSON looks malformed",
            f"The clipboard text isn't valid JSON:\n{error}\n\n"
            "It may have been cut off. Save it anyway? The loader will try to recover valid questions.",
        ):
            return

        path = data_file(CLIPBOARD_FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        self.json_path.set(path)
        self.status.set(f"Saved clipboard to {CLIPBOARD_FILE}.")
        self._validate()

    def _validate(self):
        path = self._resolved_json_path()
        if not path:
            return
        from .automator import ExamNetAutomator

        log = logging.getLogger("examnet.gui")
        automator = ExamNetAutomator(json_file=path, logger=log)
        try:
            run_json_precheck(path, interactive=False, logger=log)
            questions = automator.load_questions()
            automator.validate_questions(questions)
        except Exception as e:
            self.status.set("Validation failed.")
            messagebox.showerror("Validation failed", str(e))
            return

        counts = Counter(automator.normalize_question_type(q) for q in questions)
        summary = "\n".join(f"  {qtype}: {n}" for qtype, n in sorted(counts.items()))
        self.status.set(f"Validation passed: {len(questions)} question(s).")
        messagebox.showinfo("Validation passed", f"{len(questions)} question(s) are valid:\n\n{summary}")

    def _copy_schema(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(build_question_schema_text())
        self.status.set("Example JSON schema copied to clipboard.")

    def _open_chrome(self):
        browser_url = self.browser_url.get().strip()
        self.chrome_btn.configure(state="disabled")
        self.status.set("Opening the browser...")

        def worker():
            try:
                if is_cdp_available(browser_url):
                    message = "The browser is open. Log in to exam.net and open your exam, then click Start."
                else:
                    name = launch_browser(browser_url, start_url=EXAM_NET_URL)
                    message = f"{name} opened. Log in to exam.net and open your exam, then click Start."
                self.events.put(("chrome", message, None))
            except Exception as e:
                self.events.put(("chrome", "Could not open the browser.", e))

        threading.Thread(target=worker, daemon=True).start()

    def _open_logs(self):
        os.startfile(logs_dir())

    def _show_about(self):
        about = tk.Toplevel(self.root)
        about.title(f"About {APP_NAME}")
        about.resizable(False, False)
        about.transient(self.root)
        frame = ttk.Frame(about, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text=f"Version {__version__}").pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, text=f"Last checked against Exam.net: {LAST_VERIFIED}").pack(anchor="w")
        ttk.Label(
            frame,
            text="If questions stop being created correctly, Exam.net may have changed its pages.\n"
            "Check the download page for a newer version.",
            justify="left",
        ).pack(anchor="w", pady=(10, 0))
        ttk.Label(
            frame,
            text="Independent tool, not affiliated with or endorsed by Exam.net.\nMIT License.",
            foreground="#555555",
            justify="left",
        ).pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e", pady=(14, 0))
        ttk.Button(buttons, text="Open download page", command=lambda: webbrowser.open(DOWNLOAD_URL)).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(buttons, text="Close", command=about.destroy).pack(side="left")
        about.grab_set()

    def _start(self):
        path = self._resolved_json_path()
        if not path or (self.worker and self.worker.is_alive()):
            return
        try:
            max_attempts = max(1, int(self.max_attempts.get()))
            preview_ms = max(0, int(self.debug_preview_ms.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid option", "Attempts and highlight duration must be whole numbers.")
            return

        self.log_file_path = configure_logging(self.log_level.get())
        gui_handler = QueueLogHandler(self.events)
        gui_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(gui_handler)

        self.stop_requested.clear()
        self.progress.configure(value=0, maximum=1)
        self.status.set("Starting...")
        self._set_running(True)

        options = dict(
            browser_url=self.browser_url.get().strip(),
            json_file=path,
            interactive=True,
            max_attempts=max_attempts,
            stop_on_error=not self.continue_on_error.get(),
            debug_create_preview=self.debug_preview.get(),
            debug_create_preview_ms=preview_ms,
            debug_create_confirm=self.debug_confirm.get(),
            bypass_json_precheck=self.bypass_precheck.get(),
            confirm=self._confirm_from_worker,
            should_stop=self.stop_requested.is_set,
            on_progress=lambda done, total: self.events.put(("progress", done, total)),
            pause_at_end=False,
        )
        self.worker = threading.Thread(target=self._run_worker, args=(options,), daemon=True)
        self.worker.start()

    def _run_worker(self, options):
        from .automator import ExamNetAutomator

        try:
            ExamNetAutomator(**options).run()
            self.events.put(("done", None))
        except Exception as e:
            logging.getLogger("examnet.gui").error("Run failed: %s", e)
            self.events.put(("done", e))

    def _stop(self):
        self.stop_requested.set()
        self.stop_btn.configure(state="disabled")
        self.status.set("Stopping after the current question finishes...")

    def _confirm_from_worker(self, message):
        """Called on the worker thread; blocks until the user answers a dialog on the GUI thread."""
        answered = threading.Event()
        result = {}
        self.events.put(("confirm", message, answered, result))
        answered.wait()
        return result.get("ok", False)

    # ---------- event loop ----------

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1], event[2])
                elif kind == "progress":
                    done, total = event[1], event[2]
                    self.progress.configure(maximum=max(total, 1), value=done)
                    if done < total:
                        self.status.set(f"Processing question {done + 1} of {total}...")
                elif kind == "confirm":
                    message, answered, result = event[1], event[2], event[3]
                    self.root.lift()
                    result["ok"] = messagebox.askokcancel(APP_NAME, message, parent=self.root)
                    answered.set()
                elif kind == "chrome":
                    self.chrome_btn.configure(state="normal")
                    if not (self.worker and self.worker.is_alive()):
                        self.status.set(event[1])
                    error = event[2]
                    if isinstance(error, BrowserNotFoundError):
                        messagebox.showerror("Browser not found", str(error))
                    elif error:
                        messagebox.showerror(
                            "Could not open the browser", f"{error}\n\nClick 'Open browser' to try again."
                        )
                elif kind == "done":
                    self._on_run_finished(event[1])
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _on_run_finished(self, error):
        self._set_running(False)
        for handler in list(logging.getLogger().handlers):
            if isinstance(handler, QueueLogHandler):
                logging.getLogger().removeHandler(handler)
        log_note = f"\n\nLog file: {self.log_file_path}" if self.log_file_path else ""
        if error:
            self.status.set("Run failed. See log below.")
            messagebox.showerror(
                "Run failed",
                f"{error}{log_note}\n\nYou are using version {__version__} (last checked against Exam.net "
                f"{LAST_VERIFIED}). If Exam.net has changed its pages, a newer version may fix this: see About.",
            )
        else:
            self.status.set("Run finished. The browser window stays open.")
            messagebox.showinfo("Run finished", f"Run finished. Check the log for any failures.{log_note}")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Run in progress",
                "Automation is still running. Quit anyway?\n\n"
                "The current question in exam.net may be left half-finished.",
            ):
                return
        self.root.destroy()


def main():
    root = tk.Tk()
    ExamNetGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
