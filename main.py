"""Billwise launcher - the original entry point.

Opens the employee billing counter (employee.py) or the administration panel
(admin.py) in its own process, exactly as the original project did, but with
absolute paths and the current Python interpreter so it works from any folder.
"""
import subprocess
import sys
import tkinter as tk

import ttkbootstrap as ttk

import db
import theme
import ui
from ui import tk_plain

C = theme.COLORS
ui.setup_logging()
main = ui.create_root("Billwise", size=(1100, 660))


def Exit():
    if ui.confirm(main, "Exit", "Are you sure you want to exit?"):
        main.destroy()


main.protocol("WM_DELETE_WINDOW", Exit)


def _launch(script, label):
    path = db.app_path(script)
    err_log = db.app_path("logs", "billwise.log")
    try:
        with open(err_log, "a", encoding="utf-8") as errf:
            proc = subprocess.Popen([sys.executable, path], cwd=db.APP_DIR, stderr=errf)
    except OSError as e:
        ui.error(main, "Error", "Failed to open %s:\n%s" % (label, e))
        return
    status.set("Opening %s..." % label)
    for b in (emp_button, adm_button):
        b.configure(state="disabled")

    def check():
        code = proc.poll()
        if code is None:          # still running after the start-up window: hand over
            main.destroy()
        elif code != 0:           # crashed during start-up: say so instead of vanishing
            status.set("")
            for b in (emp_button, adm_button):
                b.configure(state="normal")
            ui.error(main, "Error", "%s closed unexpectedly (exit code %s).\n"
                     "See logs/billwise.log for details." % (label, code))
        else:
            main.destroy()
    main.after(1500, check)


def emp():
    _launch("employee.py", "Invoicing desk")


def adm():
    _launch("admin.py", "Administration")


# ---------------------------------------------------------------- layout
brand = tk_plain(tk.Canvas, main, width=440, highlightthickness=0, bg=C["navy"])
brand.pack(side="left", fill="y")


def draw_brand(event=None):
    h = max(brand.winfo_height(), 600)
    brand.delete("all")
    brand.img = theme.gradient(440, h, C["navy"], C["blue"], horizontal=False, persist=False)
    brand.create_image(0, 0, image=brand.img, anchor="nw")
    brand.create_rectangle(0, 0, 8, h, fill=C["green"], outline="")
    brand.create_image(56, h * 0.36, image=logo, anchor="w")
    brand.create_text(56, h * 0.36 + 70, text=theme.APP_NAME, anchor="w", fill=C["white"],
                      font=(theme.FONTS["families"]["heading"], 40, "bold"))
    brand.create_text(58, h * 0.36 + 120, text=theme.TAGLINE, anchor="w", fill=C["ice"],
                      font=theme.font("h3"))
    brand.create_text(58, h - 40, text="GST billing  |  Inventory  |  Reports", anchor="w",
                      fill=C["ice"], font=theme.font("small"))


logo = theme.logo_image(84)
brand.bind("<Configure>", draw_brand)

right = ttk.Frame(main, padding=48)
right.pack(side="left", fill="both", expand=True)
panel = ui.card(right, padding=36)
panel.place(relx=0.5, rely=0.5, anchor="center", width=460)
ttk.Label(panel, text="Welcome", style="CardTitle.TLabel", font=theme.font("h1")).pack(anchor="w")
ttk.Label(panel, text="Choose where you want to sign in.", style="CardMuted.TLabel").pack(
    anchor="w", pady=(4, 24))

emp_button = ttk.Button(panel, text="Invoicing desk  (Staff)", bootstyle="primary",
                        command=emp)
emp_button.pack(fill="x", ipady=10)
ttk.Label(panel, text="Create GST invoices, search and reprint bills.", style="CardMuted.TLabel"
          ).pack(anchor="w", pady=(6, 18))
adm_button = ttk.Button(panel, text="Administration  (Admin / Manager)", bootstyle="success",
                        command=adm)
adm_button.pack(fill="x", ipady=10)
ttk.Label(panel, text="Inventory, employees, invoices, analytics and reports.",
          style="CardMuted.TLabel").pack(anchor="w", pady=(6, 18))
ttk.Separator(panel).pack(fill="x", pady=8)
status = tk.StringVar()
row = ttk.Frame(panel, style="Card.TFrame")
row.pack(fill="x")
ttk.Label(row, textvariable=status, style="Green.TLabel").pack(side="left")
ttk.Button(row, text="Exit", bootstyle="secondary-outline", command=Exit).pack(side="right")

if __name__ == "__main__":
    main.mainloop()
