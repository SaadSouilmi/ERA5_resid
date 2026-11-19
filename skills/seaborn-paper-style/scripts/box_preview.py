# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.8", "numpy>=1.24", "scienceplots>=2.2"]
# ///
"""Preview the percentile-box variant with explicitly synthetic data."""

import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgba
from matplotlib.patches import Patch

from scientific_style import (
    COLORS,
    percentile_boxes,
    save_scientific_figure,
    scientific_style,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/box-style-preview")
    args = parser.parse_args()
    scientific_style()
    fig, ax = plt.subplots(figsize=(6.5, 3.6), layout="constrained")
    rng = np.random.default_rng(1337)
    samples, positions, colors = [], [], []
    for group in range(4):
        for index, offset in enumerate([-0.17, 0, 0.17]):
            samples.append(rng.normal((group - 1.5) * 0.4 + index * 0.2, 0.7, 1000))
            positions.append(group + offset)
            colors.append(COLORS[index])
    statistics = percentile_boxes(ax, samples, positions, colors)
    for values, result in zip(samples, statistics):
        expected = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
        assert np.array_equal(expected, list(result.values()))
    ax.set_xticks(range(4), ["A", "B", "C", "D"])
    ax.set(xlim=(-0.5, 3.5), xlabel="Synthetic category", ylabel="Synthetic outcome")
    handles = [
        Patch(facecolor=to_rgba(color, 0.30), edgecolor=color, label=f"Series {index + 1}")
        for index, color in enumerate(COLORS[:3])
    ]
    fig.legend(handles=handles, loc="outside upper center", ncols=3)
    save_scientific_figure(fig, args.output)
    plt.close(fig)


if __name__ == "__main__":
    main()
