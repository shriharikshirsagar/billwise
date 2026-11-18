"""Billwise "Parliamentary Blue & Green" theme - the single source of colours,
fonts and styled building blocks for every screen (and the PDF palette).
"""
import os

APP_NAME = "billwise"
TAGLINE = "Smart billing, easy to remember."

COLORS = {
    "navy": "#0B3452",        # primary navy - sidebar, headings
    "blue": "#0F5986",        # broadcast blue - top bar, primary buttons
    "ice": "#D8E5F7",         # main background
    "green": "#16856D",       # accent, success, active navigation
    "white": "#FFFFFF",       # content panels
    "text": "#142B3D",        # primary text
    "muted": "#6B8298",       # secondary text
    "red": "#B42318",         # destructive actions only
    "amber": "#C77700",       # low-stock warnings
    # complementary tints derived from the palette above
    "navy_hover": "#14476B",  # sidebar hover (between navy and broadcast blue)
    "line": "#B9CCE4",        # hairlines, input borders
    "ice_soft": "#EEF4FC",    # alternate table rows
    "navy_line": "#1E4F73",   # dividers on navy
    "muted_on_navy": "#8FA9C2",  # secondary text on navy
    "mint": "#7FD1B9",        # green tint for accents on dark surfaces
    "blue_deep": "#0D4D74",   # end stop of the top-bar gradient
}

# Filled in by init_fonts() once a Tk root exists.
FONTS = {}
_IMAGES = []  # keeps PhotoImage references alive (Tk drops unreferenced images)


def keep(image):
    _IMAGES.append(image)
    return image


def _pick(families, *candidates):
    for c in candidates:
        if c in families:
            return c
    return "Arial" if "Arial" in families else "TkDefaultFont"


def init_fonts(root):
    import tkinter.font as tkfont
    fam = set(tkfont.families(root))
    heading = _pick(fam, "Roboto Condensed SemiBold", "Roboto Condensed", "Segoe UI Semibold",
                    "Segoe UI", "Arial")
    heading_bold = _pick(fam, "Roboto Condensed", "Segoe UI", "Arial")
    body = _pick(fam, "Segoe UI", "Arial")
    semi = _pick(fam, "Segoe UI Semibold", "Segoe UI", "Arial")
    icons = "Segoe MDL2 Assets" if "Segoe MDL2 Assets" in fam else None
    FONTS.update({
        "brand": (heading_bold, 22, "bold"),
        "h1": (heading, 18, "bold"),
        "h2": (heading, 14, "bold"),
        "h3": (heading, 12, "bold"),
        "body": (body, 10),
        "caps": (semi, 8),
        "body_bold": (semi, 10),
        "small": (body, 9),
        "label": (semi, 10),
        "button": (semi, 10),
        "nav": (semi, 11),
        "metric": (heading_bold, 17, "bold"),
        "mono": ("Consolas" if "Consolas" in fam else "Courier New", 10),
        "icon_family": icons,
        "families": {"heading": heading, "body": body, "semi": semi},
    })
    return FONTS


def font(name):
    return FONTS.get(name, ("Arial", 10))


# Segoe MDL2 Assets glyphs (Windows 10+). Text fallback when unavailable.
ICONS = {
    "dashboard": ("\uE80F", "\u2302"), "billing": ("\uE7BF", "\u20B9"),
    "inventory": ("\uE7B8", "\u25A4"), "employees": ("\uE716", "\u263A"),
    "invoices": ("\uE8A5", "\u2630"), "analytics": ("\uE9D9", "\u2197"),
    "reports": ("\uE9F9", "\u2261"), "customers": ("\uE77B", "\u263B"),
    "suppliers": ("\uE806", "\u2692"), "settings": ("\uE713", "\u2699"),
    "logout": ("\uE7E8", "\u23FB"), "search": ("\uE721", "\u2315"),
    "stock": ("\uE81E", "\u21C5"), "exit": ("\uE711", "\u2715"),
}


def icon(name):
    glyph, fallback = ICONS.get(name, ("", ""))
    return glyph if FONTS.get("icon_family") else fallback


def register_theme(style):
    """Register and activate the one Billwise ttkbootstrap theme."""
    from ttkbootstrap.style import ThemeDefinition
    c = COLORS
    if "billwise" not in style.theme_names():
        style.register_theme(ThemeDefinition(
            name="billwise", themetype="light",
            colors={
                "primary": c["blue"], "secondary": c["navy"], "success": c["green"],
                "info": c["blue"], "warning": c["amber"], "danger": c["red"],
                "light": c["ice"], "dark": c["text"], "bg": c["ice"], "fg": c["text"],
                "selectbg": c["blue"], "selectfg": c["white"], "border": c["line"],
                "inputfg": c["text"], "inputbg": c["white"], "active": c["ice"],
            }))
    style.theme_use("billwise")
    _configure_styles(style)


def _configure_styles(style):
    c = COLORS
    f = font
    style.configure(".", font=f("body"))
    style.configure("TButton", font=f("button"), padding=(14, 7))
    style.configure("TLabel", background=c["ice"], foreground=c["text"])
    style.configure("TFrame", background=c["ice"])
    # White content cards
    style.configure("Card.TFrame", background=c["white"])
    style.configure("Card.TLabel", background=c["white"], foreground=c["text"], font=f("body"))
    style.configure("CardTitle.TLabel", background=c["white"], foreground=c["navy"], font=f("h2"))
    style.configure("CardMuted.TLabel", background=c["white"], foreground=c["muted"], font=f("small"))
    style.configure("CardCaps.TLabel", background=c["white"], foreground=c["muted"], font=f("caps"))
    # Navy "receipt" panel used for the bill summary
    style.configure("Receipt.TFrame", background=c["navy"])
    style.configure("Receipt.TLabel", background=c["navy"], foreground=c["ice"], font=f("body"))
    style.configure("ReceiptValue.TLabel", background=c["navy"], foreground=c["white"], font=f("body_bold"))
    style.configure("ReceiptCaps.TLabel", background=c["navy"], foreground=c["mint"], font=f("caps"))
    style.configure("ReceiptTotal.TLabel", background=c["navy"], foreground=c["white"],
                    font=(FONTS["families"]["heading"], 24, "bold"))
    style.configure("CardField.TLabel", background=c["white"], foreground=c["text"], font=f("label"))
    style.configure("Metric.TLabel", background=c["white"], foreground=c["navy"], font=f("metric"))
    style.configure("MetricAmber.TLabel", background=c["white"], foreground=c["amber"], font=f("metric"))
    style.configure("MetricGreen.TLabel", background=c["white"], foreground=c["green"], font=f("metric"))
    style.configure("PageTitle.TLabel", background=c["ice"], foreground=c["navy"], font=f("h1"))
    style.configure("PageSub.TLabel", background=c["ice"], foreground=c["muted"], font=f("body"))
    style.configure("Total.TLabel", background=c["white"], foreground=c["navy"], font=f("h1"))
    style.configure("Amber.TLabel", background=c["white"], foreground=c["amber"], font=f("label"))
    style.configure("Green.TLabel", background=c["white"], foreground=c["green"], font=f("label"))
    style.configure("Error.TLabel", background=c["white"], foreground=c["red"], font=f("label"))
    style.configure("Card.TCheckbutton", background=c["white"], foreground=c["text"])
    style.configure("Card.TRadiobutton", background=c["white"], foreground=c["text"])
    style.configure("Treeview", rowheight=28, font=f("body"), background=c["white"],
                    fieldbackground=c["white"], foreground=c["text"], bordercolor=c["line"])
    style.configure("Treeview.Heading", font=f("label"), background=c["navy"],
                    foreground=c["white"], relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", c["blue"])])
    style.map("Treeview", background=[("selected", c["blue"])],
              foreground=[("selected", c["white"])])


def style_tree(tree):
    """Row tags used by every table."""
    tree.tag_configure("odd", background=COLORS["white"])
    tree.tag_configure("even", background=COLORS["ice_soft"])
    tree.tag_configure("low", foreground=COLORS["amber"], font=font("body_bold"))
    tree.tag_configure("cancelled", foreground=COLORS["muted"])


# ---------------------------------------------------------------- images
def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def gradient(width, height, start, end, horizontal=True, persist=True):
    """Pillow gradient as a PhotoImage. persist=True keeps a global reference;
    callers that redraw often keep their own reference instead."""
    from PIL import Image, ImageTk
    width, height = max(1, int(width)), max(1, int(height))
    a, b = _hex(start), _hex(end)
    steps = width if horizontal else height
    strip = Image.new("RGB", (steps, 1))
    px = strip.load()
    for i in range(steps):
        t = i / max(1, steps - 1)
        px[i, 0] = tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))
    if horizontal:
        img = strip.resize((width, height))
    else:
        img = strip.resize((height, 1)).rotate(-90, expand=True).resize((width, height))
    photo = ImageTk.PhotoImage(img)
    return keep(photo) if persist else photo


def logo_image(size=44):
    """Simple generated 'bw' monogram (no external assets needed)."""
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 4, fill=COLORS["green"])
    fnt = None
    for path in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.exists(path):
            fnt = ImageFont.truetype(path, int(s * 0.46))
            break
    fnt = fnt or ImageFont.load_default()
    box = d.textbbox((0, 0), "bw", font=fnt)
    d.text(((s - (box[2] - box[0])) / 2 - box[0], (s - (box[3] - box[1])) / 2 - box[1]),
           "bw", font=fnt, fill=COLORS["white"])
    return keep(ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS)))
