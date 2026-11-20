"""STIX scientific figures and rounded 5th–95th percentile box plots."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import scienceplots  # noqa: F401
from cycler import cycler
from matplotlib.colors import to_rgba
from matplotlib.patches import PathPatch
from matplotlib.path import Path as DrawingPath

COLORS = ["#527EAC", "#BE6274", "#347F74", "#6A56A0", "#A86C1A", "#60748C"]
INK = "#23312F"


def scientific_style():
    plt.rcdefaults()
    plt.style.use(["science", "ieee", "no-latex"])
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["STIXGeneral"],
            "mathtext.fontset": "stix",
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "text.usetex": False,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": "#687370",
            "axes.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.top": False,
            "ytick.right": False,
            "xtick.minor.visible": False,
            "ytick.minor.visible": False,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "xtick.color": INK,
            "ytick.color": INK,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "grid.color": "#DDE3E1",
            "grid.linewidth": 0.5,
            "grid.alpha": 0.8,
            "axes.prop_cycle": cycler(color=COLORS),
            "lines.linewidth": 1.1,
            "lines.markersize": 4,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.06,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
        }
    )


def rounded_rectangle(ax, left, bottom, width, height, color, label=None):
    right, top = left + width, bottom + height
    rx, ry = 0.08 * width, 0.035 * height
    vertices = [
        (left + rx, bottom),
        (right - rx, bottom),
        (right, bottom),
        (right, bottom + ry),
        (right, top - ry),
        (right, top),
        (right - rx, top),
        (left + rx, top),
        (left, top),
        (left, top - ry),
        (left, bottom + ry),
        (left, bottom),
        (left + rx, bottom),
        (left + rx, bottom),
    ]
    codes = [
        DrawingPath.MOVETO,
        DrawingPath.LINETO,
        DrawingPath.CURVE3,
        DrawingPath.CURVE3,
        DrawingPath.LINETO,
        DrawingPath.CURVE3,
        DrawingPath.CURVE3,
        DrawingPath.LINETO,
        DrawingPath.CURVE3,
        DrawingPath.CURVE3,
        DrawingPath.LINETO,
        DrawingPath.CURVE3,
        DrawingPath.CURVE3,
        DrawingPath.CLOSEPOLY,
    ]
    patch = PathPatch(
        DrawingPath(vertices, codes),
        facecolor=to_rgba(color, 0.30),
        edgecolor=color,
        linewidth=0.9,
        label=label,
        zorder=2,
    )
    ax.add_patch(patch)
    return patch


def percentile_boxes(ax, samples, positions, colors, width=0.10):
    stats = []
    for values in samples:
        values = np.asarray(values, dtype=float)
        if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
            raise ValueError(
                "Box samples must be nonempty finite vectors; resolve missing values explicitly"
            )
        p05, p25, p50, p75, p95 = np.quantile(values, [0.05, 0.25, 0.50, 0.75, 0.95])
        stats.append(dict(whislo=p05, q1=p25, med=p50, q3=p75, whishi=p95))
    artists = ax.bxp(
        stats,
        positions=positions,
        widths=width,
        capwidths=width * 0.5,
        showfliers=False,
        patch_artist=True,
        manage_ticks=False,
        medianprops={"color": INK, "linewidth": 1.0, "zorder": 3},
    )
    for index, (box, values, x, color) in enumerate(
        zip(artists["boxes"], stats, positions, colors, strict=True)
    ):
        box.remove()
        rounded_rectangle(
            ax, x - width / 2, values["q1"], width, values["q3"] - values["q1"], color
        )
        for line in (
            artists["whiskers"][2 * index : 2 * index + 2]
            + artists["caps"][2 * index : 2 * index + 2]
        ):
            line.set(color=color, linewidth=0.8)
    return stats


def zero_line(ax, value=0):
    ax.axhline(value, color="#687370", linestyle=":", linewidth=0.7, zorder=1)


def top_legend(fig):
    handles, labels = [], []
    for ax in fig.axes:
        for handle, label in zip(*ax.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
        if ax.get_legend() is not None:
            ax.get_legend().remove()
    if handles:
        fig.legend(handles, labels, loc="outside upper center", ncols=min(4, len(labels)))


def save_scientific_figure(fig, output):
    stem = Path(output)
    stem.parent.mkdir(parents=True, exist_ok=True)
    paths = [stem.with_suffix(f".{extension}") for extension in ("png", "pdf", "svg")]
    for path in paths:
        fig.savefig(path, dpi=600)
    return paths
