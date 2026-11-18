"""Seaborn-compatible paper plotting style and export helpers."""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import seaborn as sns
from cycler import cycler
from matplotlib.text import Text

INK = "#23312F"
MUTED = "#44524F"
MODEL_COLORS = {
    "Oracle": "#347F74",
    "Heston": "#BE6274",
    "Black–Scholes": "#3E6FAD",
}
ALPHA_COLORS = {
    0.55: "#26776C",
    0.65: "#AD5069",
    0.75: "#6A56A0",
    0.95: "#A86C1A",
}
COLORS = ["#347F74", "#BE6274", "#3E6FAD", "#6A56A0", "#A86C1A", "#60748C"]
ORANGE = "#D18A32"

PAPER_STYLE = {
    "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "mathtext.fontset": "dejavusans",
    "font.size": 11, "axes.labelsize": 12, "axes.titlesize": 14,
    "legend.fontsize": 10, "legend.title_fontsize": 10, "text.color": INK, "axes.labelcolor": INK,
    "font.weight": "normal", "axes.labelweight": "normal", "axes.titleweight": "normal",
    "axes.edgecolor": "#687370", "axes.linewidth": .6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "axes.prop_cycle": cycler(color=list(MODEL_COLORS.values())),
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.direction": "out", "ytick.direction": "out",
    "xtick.top": False, "ytick.right": False, "xtick.minor.visible": False, "ytick.minor.visible": False,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "axes.grid": False, "axes.grid.axis": "both", "axes.grid.which": "major",
    "grid.color": "#DDE3E1", "grid.linewidth": .5, "grid.linestyle": "-",
    "lines.linewidth": 1.45, "lines.markersize": 4.6, "lines.markeredgewidth": .9,
    "legend.frameon": False, "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "savefig.dpi": 300, "savefig.bbox": "tight",
    "pdf.fonttype": 42, "ps.fonttype": 42,
}


def paper_style(palette=None):
    """Apply the paper style, optionally using a Seaborn-compatible palette."""
    chosen = MODEL_COLORS if palette is None else palette
    colors = list(chosen.values()) if isinstance(chosen, dict) else sns.color_palette(chosen)
    plt.rcdefaults()
    sns.set_theme(style="white", context="paper", palette=colors, rc=PAPER_STYLE)
    plt.rcParams.update(PAPER_STYLE)
    plt.rcParams["axes.prop_cycle"] = cycler(color=colors)
    plt.rcParams["xtick.labelsize"] = 11
    plt.rcParams["ytick.labelsize"] = 11


def save_figure(fig, output):
    """Save SVG, PNG, and PDF files using output as a suffix-free stem."""
    stem = Path(output)
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    for text in fig.findobj(match=Text):
        text.set_path_effects([pe.withStroke(linewidth=.18, foreground=text.get_color())])
    paths = [stem.with_suffix("." + ext) for ext in ("svg", "png", "pdf")]
    for path in paths:
        fig.savefig(path)
    return paths
