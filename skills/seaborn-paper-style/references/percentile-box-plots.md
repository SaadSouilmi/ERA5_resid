# Serif whisker plots and percentile boxes

Use Matplotlib with SciencePlots styles `science`, `ieee`, `no-latex`, followed by STIXGeneral serif text and `mathtext.fontset = "stix"`. Run Python with `uv`. The bundled `scientific_style.py` supplies the theme, rounded boxes and exports.

Apply this variant only to box-and-whisker and interval-whisker plots. Keep the original bar, histogram, curve and heatmap appearance. Do not make bars thin, rounded or translucent merely because this style is available.

## General appearance

- White canvas, regular serif text, mathematical labels where relevant, thin left/bottom spines; hide top/right spines and minor ticks.
- For three whisker series, use blue `#527EAC`, rose `#BE6274`, teal `#347F74`. For two series, preserve the existing red/green comparison mapping (`#BE6274`, `#347F74`); `PAIR_COLORS` supplies green then rose. Extend with `#6A56A0`, `#A86C1A`, `#60748C` if necessary. Bind these to actual categories consistently; the motivating finance labels are not part of the style.
- Translucent fills (about 0.30 alpha), opaque matching outlines, dark median lines, narrow whisker caps, subtly rounded box corners.
- Linear axes and faint horizontal gridlines. Do not highlight zero or force it into the range by default. Fit the vertical range to the plotted values and intervals with modest padding. Count/total bars retain a zero baseline; ratio plots may retain a meaningful reference at one. Preserve units, transformations and axis meanings.
- Put a frameless legend above the axes, centered, in the same left-to-right order as the plotted groups. For a multi-panel figure, prefer one shared legend above the panels.
- No overall title or explanatory prose inside the figure. Short panel labels may identify different variables. Put methods and definitions in the surrounding note.

## Box-plot statistics and geometry

Each box represents the 25th–75th percentiles, with a line at the median and whiskers at the **5th and 95th percentiles**. These are percentile whiskers, not 1.5×IQR fences or confidence intervals. Compute quantiles with linear interpolation over every observation in the intended analysis sample, including flagged outcomes. Never filter by flag or trim tails merely for appearance. Handle and document missing/nonfinite values separately; hiding fliers does not remove observations from quantile calculations.

Use categorical group centers one unit apart, box width `0.10`, and offsets `[-0.17, 0, 0.17]` for three series. For a different number of series, use symmetric offsets with spacing `0.17`. A single series is centered. Do not draw individual tail observations.

Use the actual x categories, series names, outcome label and units. Do not copy α, option-premium percentages, model names or finance terminology into unrelated work.

Do not turn an existing mean/CI, total, regression coefficient or fold-range plot into a box plot as a styling edit. Those statistics do not determine quartiles. Preserve their meaning. Transfer this appearance to interval-whisker plots only; leave other chart types in their original style. A bootstrap distribution of a mean describes estimator uncertainty, not the spread of individual observations; label that distinction when requested.

## Use and exports

`scientific_style()` applies the theme. `percentile_boxes(ax, samples, positions, colors)` computes quantiles from complete finite one-dimensional samples and draws rounded boxes. It returns the computed statistics so they can be saved as a source table. Pass positions in the actual display order. Add a legend with the real category labels in that order.

`save_scientific_figure(fig, stem)` exports a 600 dpi PNG and vector SVG/PDF. The user's current PNG+SVG request authorizes SVG for this variant; follow explicit format restrictions in later requests. Do not add SVG exports to unrelated figures.

Inspect the rendered PNG at a readable size for clipped ticks, overlapping labels or legends, distorted corners and excessive whitespace. Check percentile ordering and that source tables and statistical interpretations survive a restyle. Keep the reusable helper and data provenance with the figure.

Run the explicitly synthetic [box_preview.py](../scripts/box_preview.py) with `uv run` to inspect the grouped geometry. Its category names and generated values are demonstrations, not a factual result.
