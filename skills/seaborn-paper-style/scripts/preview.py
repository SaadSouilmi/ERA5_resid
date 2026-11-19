# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib>=3.8,<4",
#   "numpy>=1.24",
#   "seaborn>=0.13.2,<0.14",
# ]
# ///
"""Create a deterministic, synthetic preview of the paper plotting style."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

from plot_style import ALPHA_COLORS, MODEL_COLORS, paper_style, save_figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/style-preview"),
                        help="suffix-free output stem (writes PNG and PDF)")
    args = parser.parse_args()

    paper_style()
    x = np.linspace(0, 1, 9)
    fig, (line_ax, bar_ax) = plt.subplots(1, 2, figsize=(9.2, 3.8), layout="constrained")

    for index, (name, color) in enumerate(MODEL_COLORS.items()):
        y = 0.25 + index * 0.18 + 0.12 * np.sin(2 * np.pi * x + index * 0.45)
        sns.lineplot(x=x, y=y, ax=line_ax, color=color, label=name, estimator=None,
                     errorbar=None, marker="o", markerfacecolor="white",
                     markeredgecolor=color)
    line_ax.set(title="Model palette", xlabel="Synthetic x", ylabel="Synthetic response")
    line_ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.25), ncols=3,
                   handlelength=1.4, handletextpad=0.5, columnspacing=0.8)

    labels = [f"{alpha:.2f}" for alpha in ALPHA_COLORS]
    values = [0.43, 0.58, 0.51, 0.66]
    palette = dict(zip(labels, ALPHA_COLORS.values()))
    sns.barplot(x=labels, y=values, hue=labels, order=labels, hue_order=labels,
                palette=palette, legend=False, dodge=False, saturation=1,
                errorbar=None, width=0.62, linewidth=0.4, ax=bar_ax)
    for patch in bar_ax.patches:
        patch.set_edgecolor(patch.get_facecolor())
    bar_ax.set(title="Alpha palette", xlabel="Alpha", ylabel="Synthetic value")

    fig.suptitle("Style demo · synthetic data")
    save_figure(fig, args.output)
    plt.close(fig)


if __name__ == "__main__":
    main()
