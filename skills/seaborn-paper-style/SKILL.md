---
name: seaborn-paper-style
description: Create or restyle scientific figures using Saad's saved palettes, including STIX/SciencePlots percentile box plots and the original Seaborn paper style. Use for the saved plotting style, independently of the CRandom HTML blog.
---

# Seaborn paper style

Reproduce the user's plotting style with the bundled [plot_style.py](scripts/plot_style.py). It contains the exact palettes from the original snippet and the later approved typography and appearance. Use Seaborn for plotting and Matplotlib for precise axes and annotations. This skill is independent of the blog template.

## Start here

For box-and-whisker or interval-whisker plots, read [references/percentile-box-plots.md](references/percentile-box-plots.md) and use [scientific_style.py](scripts/scientific_style.py). It uses SciencePlots, STIX serif text and faint horizontal grids. Restrict this variant to whisker plots; do not apply its thin rounded translucent boxes or serif typography to bar charts, histograms or ordinary curves. Preserve their original styling, and keep red/green (`#BE6274`, `#347F74`) for two-series comparisons. Preserve the approved DEGURBA plot in this project.

The remaining instructions describe the original sans-serif variant.

Copy `scripts/plot_style.py` beside the new plotting script. Call `paper_style()` before creating figures and `save_figure(fig, output_stem)` after adding every label and legend. The helper owns the theme; do not apply another Seaborn theme afterward.

Use `uv` for Python execution and dependencies. A standalone plotting script can declare:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8,<4", "seaborn>=0.13.2,<0.14"]
# ///
```

Run it with `uv run plot.py`. Add dependencies the new script imports directly, such as NumPy or pandas, to its metadata.

The bundled [preview.py](scripts/preview.py) is a runnable example with explicitly synthetic data. Run `uv run scripts/preview.py --output build/style-preview` from this skill directory to export a PNG and PDF. Replace its example data and labels for real work. Use [style-preview.png](assets/style-preview.png) as a visual reference for the captured colors and typography.

## Exact palettes

Preserve both mapping keys and hex values when the corresponding model or alpha levels appear. The model name uses an en dash in `Black–Scholes`.

| Model | Hex |
| --- | --- |
| Oracle | `#347F74` |
| Heston | `#BE6274` |
| Black–Scholes | `#3E6FAD` |

| Alpha | Hex |
| --- | --- |
| 0.55 | `#26776C` |
| 0.65 | `#AD5069` |
| 0.75 | `#6A56A0` |
| 0.95 | `#A86C1A` |

The helper exposes `MODEL_COLORS`, `ALPHA_COLORS`, and the general categorical sequence `COLORS`:

```text
#347F74  #BE6274  #3E6FAD  #6A56A0  #A86C1A  #60748C
```

Use `#D18A32` as an orange accent when needed. For another subject, map its actual category names to the categorical sequence; do not relabel unrelated data with the original model names. Keep mappings consistent across panels, legends, and figures.

Pass dictionaries explicitly through `palette=` and preserve order through `hue_order=`. For numeric alpha levels, use the exact dictionary and `hue_order=list(ALPHA_COLORS)` so categorical choices remain stable. The default Matplotlib color cycle is the three model colors; `paper_style(palette=COLORS)` selects the six-color sequence instead.

## Captured appearance

The original sans-serif variant uses **no SciencePlots, no grid, and DejaVu Sans**. The newer serif variant is documented above; select it when requested rather than mixing the two themes.

| Element | Value |
| --- | --- |
| Figure, axes, export background | White |
| Font / math | DejaVu Sans / `dejavusans` |
| Base / axes labels / titles / legend | 11 / 12 / 14 / 10 pt |
| Text and axes labels | `#23312F` |
| Tick text | `#44524F` |
| Axis edges | `#687370`, 0.6 pt |
| Spines | Left and bottom only |
| Ticks | Outward, length 3 pt; no top/right or minor ticks |
| Lines | 1.45 pt |
| Markers | Size 4.6 pt, edge width 0.9 pt |
| Legend | No frame |
| Text weight | Regular; 0.18 pt same-color stroke on export |
| Export | PDF vector; PNG at 300 dpi; tight bounding box; SVG only when explicitly requested |

Use a single-panel size near `(6.5, 3.4)` inches with constrained layout; adapt dimensions to content. Use restrained labels and annotations. The export helper draws the figure before adding text strokes, so generated ticks are included, and replaces its stroke effect on repeated saves rather than accumulating it.

## Plotting patterns

For already computed curves, avoid Seaborn's default aggregation and inferred confidence bands. A minimal pattern with white-filled markers is:

```python
import matplotlib.pyplot as plt
import seaborn as sns
from plot_style import MODEL_COLORS, paper_style, save_figure

paper_style()
fig, ax = plt.subplots(figsize=(6.5, 3.4), layout="constrained")
for model, color in MODEL_COLORS.items():
    sns.lineplot(
        data=df[df["model"] == model], x="x", y="value", ax=ax,
        color=color, label=model, estimator=None, errorbar=None,
        marker="o", markerfacecolor="white", markeredgecolor=color,
    )
ax.set(xlabel="X (units)", ylabel="Value (units)")
ax.legend()
save_figure(fig, "build/figure")
```

For vertical bars, use explicit category/hue mappings and `saturation=1` to retain the exact hex colors. Use `hue="category", legend=False, dodge=False` when each bar has a distinct color. The captured bar width is 0.62 with 0.4 pt edges matching each bar's fill. The preview demonstrates this mapping.

Choose uncertainty from the supplied data and request. Use `errorbar=None` for precomputed values without uncertainty; do not silently turn supplied standard deviations into confidence intervals. For supplied intervals, draw them explicitly with `ax.errorbar`: 0.9 pt whiskers, 2.4 pt caps, and color `#44524F`. For raw repeated observations, select the intended interval explicitly and label it correctly.

Do not highlight zero by default. Fit ranges to the plotted values and uncertainty with modest padding; count and total bars keep their zero baseline. PDP panels use explicit major grids (`ax.grid(True, axis="both")`) and fit their y-ranges to the full confidence band.

Seaborn's [lineplot documentation](https://seaborn.pydata.org/generated/seaborn.lineplot.html) describes aggregation and uncertainty; its [barplot documentation](https://seaborn.pydata.org/generated/seaborn.barplot.html) documents saturation and categorical hue mappings.

## Delivery and checks

Deliver the plotting script, its local helper, and requested figure exports. `save_figure` accepts an output stem without an extension and creates parent directories. Keep numerical data and user-defined output paths in their intended project locations.

Check actual colors, category order, labels and units, uncertainty meaning, absent grids, regular text weight, and unclipped legends. Render and inspect the PNG after changing the helper or layout, and check the requested vector exports exist. Do not copy the demo's synthetic numbers into a factual result. Do not change the user's data, calculations, blog, or publishing configuration merely to apply this style.
