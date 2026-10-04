"""Minimal English desktop shell for PC diagnostics."""

from queue import Empty, Queue
from threading import Thread
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .sections.hardware import format_hardware
from .collectors.inventory import collect_snapshot
from .sections.overview import format_overview
from .collectors.network import collect_network_snapshot
from .sections.network import format_network
from .collectors.drivers import collect_drivers_snapshot
from .sections.drivers import format_drivers
from .reports import export_text


SECTIONS = ("Overview", "Hardware", "Drivers", "Network", "Devices", "System")
FORMATTERS = {"Overview": format_overview, "Hardware": format_hardware,
              "Drivers": format_drivers, "Network": format_network}


class SysHelperApp(tk.Tk):
    BG = "#f5f7fa"
    PANEL = "#ffffff"
    INK = "#182333"
    MUTED = "#637083"
    ACCENT = "#2463eb"
    BORDER = "#e1e6ee"

    def __init__(self):
        super().__init__()
        self.title("SysHelper")
        self.geometry("1020x680")
        self.minsize(760, 500)
        self.configure(bg=self.BG)
        self.option_add("*Font", "{Segoe UI} 10")
        self.section = "Overview"
        self.reports = {}
        self.report_times = {}
        self.nav_buttons = {}
        self.pending = set()
        self.results = Queue()
        self._configure_styles()
        self._build_layout()
        self.select_section("Overview")
        self.after(100, self._receive_results)

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Vertical.TScrollbar", background=self.BORDER,
                        troughcolor=self.PANEL, borderwidth=0, arrowsize=12)

    def _button(self, parent, text, command, primary=False):
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=self.ACCENT if primary else "#edf1f7",
            fg="white" if primary else self.INK,
            activebackground="#1d4ed8" if primary else "#e1e7f0",
            activeforeground="white" if primary else self.INK,
            padx=18, pady=10, cursor="hand2", takefocus=True,
        )

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        sidebar = tk.Frame(self, bg=self.PANEL, width=196,
                           highlightbackground=self.BORDER, highlightthickness=1)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(9, weight=1)
        tk.Label(sidebar, text="SysHelper", bg=self.PANEL, fg=self.INK,
                 font=("Segoe UI", 20, "bold"), anchor="w").grid(
                     row=0, column=0, sticky="ew", padx=22, pady=(28, 2))
        for row, name in enumerate(SECTIONS, start=2):
            button = tk.Button(sidebar, text=name, anchor="w", relief="flat",
                               bd=0, padx=16, pady=12, cursor="hand2",
                               command=lambda section=name: self.select_section(section))
            button.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[name] = button

        content = tk.Frame(self, bg=self.BG)
        content.grid(row=0, column=1, sticky="nsew", padx=28, pady=28)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        header = tk.Frame(content, bg=self.BG)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        self.heading = tk.Label(header, bg=self.BG, fg=self.INK,
                                font=("Segoe UI", 22, "bold"), anchor="w")
        self.heading.grid(row=0, column=0, sticky="ew")
        self.detail_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(header, text="Show details", variable=self.detail_mode,
                       command=self.render_report, bg=self.BG, fg=self.MUTED,
                       activebackground=self.BG, selectcolor=self.BG,
                       cursor="hand2").grid(row=0, column=1, padx=(12, 0))
        self._button(header, "Run check", self.run_check, primary=True).grid(
            row=0, column=2, padx=(12, 0))

        panel = tk.Frame(content, bg=self.PANEL,
                         highlightbackground=self.BORDER, highlightthickness=1)
        panel.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(0, weight=1)

        self.output = tk.Text(panel, bg=self.PANEL, fg=self.INK, relief="flat",
                              bd=0, font=("Consolas", 11), wrap="word",
                              padx=20, pady=10, spacing3=7, state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew", pady=(8, 16))
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=(8, 16))
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.tag_configure("status", foreground=self.MUTED)
        self.output.bind("<Control-c>", self.copy_selection)
        self.output.bind("<Control-C>", self.copy_selection)
        self.output.bind("<Control-KeyPress>", self._copy_shortcut)

        footer = tk.Frame(content, bg=self.BG)
        footer.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        self.status = tk.Label(footer, text="", bg=self.BG, fg=self.MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        save = tk.Menubutton(footer, text="Save report ▾", relief="flat", bd=0,
                            bg="#edf1f7", fg=self.INK, activebackground="#e1e7f0",
                            padx=18, pady=10, cursor="hand2", direction="above")
        menu = self.save_menu = tk.Menu(save, tearoff=False)
        menu.add_command(label="Current category", command=self.save_report)
        menu.add_command(label="All collected reports", command=lambda: self.save_report(all_reports=True))
        save.configure(menu=menu)
        save.pack(side="right")

    def select_section(self, name):
        self.section = name
        self.heading.configure(text=name)
        for section, button in self.nav_buttons.items():
            selected = section == name
            button.configure(bg="#eaf0ff" if selected else self.PANEL,
                             fg=self.ACCENT if selected else self.MUTED,
                             activebackground="#eaf0ff", activeforeground=self.ACCENT,
                             font=("Segoe UI", 10, "bold" if selected else "normal"))
        self.status.configure(text="Checking..." if name in self.pending else "")
        self.render_report()

    def render_report(self):
        report = self.reports.get(self.section)
        self.save_menu.entryconfigure(0, state="normal" if report else "disabled")
        self.save_menu.entryconfigure(1, state="normal" if self.reports else "disabled")
        if report is None:
            summary = details = "[NOT RUN]"
        else:
            summary, details = report
        text = details if self.detail_mode.get() else summary
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def run_check(self):
        if self.section in FORMATTERS:
            if self.section in self.pending:
                return
            section = self.section
            self.pending.add(section)
            self.status.configure(text="Checking...")
            Thread(target=self._collect_report, args=(section,), daemon=True).start()
            return
        self.reports[self.section] = (
            "[UNAVAILABLE] Not implemented.",
            "[UNAVAILABLE] Not implemented.",
        )
        self.render_report()
        self.status.configure(text="Check unavailable")

    def _collect_report(self, section):
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            collector = {"Network": collect_network_snapshot,
                         "Drivers": collect_drivers_snapshot}.get(section)
            data = collector() if collector else collect_snapshot(section)
            timestamp = datetime.fromisoformat(data["CollectedAt"]).isoformat(timespec="seconds")
            report = FORMATTERS[section](data)
            status = ""
        except Exception as error:
            report = ("[UNAVAILABLE] See details.",
                      f"COLLECTION ERROR\n{type(error).__name__}: {error}")
            status = "Check failed"
        self.results.put((section, report, status, timestamp))

    def _receive_results(self):
        try:
            while True:
                section, report, status, timestamp = self.results.get_nowait()
                self.pending.discard(section)
                self.reports[section] = report
                self.report_times[section] = timestamp
                if self.section == section:
                    self.render_report()
                    self.status.configure(text=status)
        except Empty:
            pass
        self.after(100, self._receive_results)

    def _copy_shortcut(self, event):
        if event.keycode == 67:
            return self.copy_selection(event)

    def copy_selection(self, event=None):
        try:
            selected = self.output.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(selected)
        return "break"

    def save_report(self, all_reports=False):
        try:
            text = export_text(self.reports, self.section, self.detail_mode.get(), all_reports,
                               order=SECTIONS, timestamps=self.report_times)
        except ValueError:
            self.status.configure(text="Run a check first")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save report", defaultextension=".txt",
            initialfile="SysHelper-all.txt" if all_reports else f"SysHelper-{self.section.lower()}.txt",
            filetypes=[("Text reports", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as report:
                report.write(text)
        except OSError as error:
            messagebox.showerror("Could not save report", str(error), parent=self)
            self.status.configure(text="Save failed")
        else:
            self.status.configure(text="Report saved")
