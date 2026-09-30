# ERA5 Errors Analysis

[![View Report](https://img.shields.io/badge/View%20Report-GitHub%20Pages-blue?style=for-the-badge)](https://saadsouilmi.github.io/ERA5_resid/)

## Publication figures

Generate the main residual-analysis figures with
[Altair](https://altair-viz.github.io/) and `vl-convert`:

```bash
uv run python scripts/build_paper_figures.py
```

To change styling using the saved data, without rerunning the bootstrap:

```bash
uv run python scripts/build_paper_figures.py --from-tables
```

Outputs in `figures/paper/`:

- `01_covariates`: six panels of binned mean residuals and 95% station-bootstrap intervals.
- `02_urbanization`: mean residuals and intervals by land urbanization class.
- `03_interactions`: temperature × wind and elevation × distance-to-sea heatmaps.
- `04_station_map`: station mean residuals in a European map window.
- PDF, SVG and 600 dpi PNG for each figure, plus `all_figures.pdf` for review.
- Self-contained Vega-Lite specifications (`*.vl.json`) for reuse in Altair.
- `captions.txt`, `metadata.json` and CSV source tables in `tables/`.

The figures have a fixed 180 mm width, serif text, embedded PDF fonts, editable
SVG text and a white background. SVG text uses DejaVu Serif; install that font
when editing on another machine. Chart builders live in
`src/era5_analysis/paper_charts.py`; styling and export helpers live in
`src/era5_analysis/publication.py`. The same charts display directly in Marimo:

```python
from pathlib import Path
from era5_analysis.paper_charts import covariates
from era5_analysis.publication import paper_style, save_figure

chart = paper_style(covariates(Path("figures/paper/tables")))
save_figure(chart, "figures/paper/custom", width_mm=180)
chart
```

The input is `data2/residuals.parquet`, with the main notebook's complete-case
filter. Residual means **station minus ERA5**. Elevation plots exclude the
`−9999` missing-value code and treat `−999` as missing too. Curves show descriptive
binned means, not fitted model partial dependence. The bootstrap follows the existing analysis's
within-bin station resampling, with sorted aggregates for reproducibility.
See the generated captions for weighting, transformations and map coverage.

The map downloads Natural Earth boundaries on its first run and caches them
in `figures/paper/.cartopy/`. Clipped map geometry is saved as GeoJSON in `tables/`.
Subsequent `--from-tables` renders need neither the raw parquet nor network access.
For older tables, the first such run reads the parquet's extrema to add explicit
numeric heatmap boundaries, without recomputing estimates or intervals.
Add `--skip-map` to omit the map. Other options include `--output`, `--bins`,
`--bootstrap`, `--seed`, `--dpi`, `--width-mm` and `--min-stations` (minimum
station count in a heatmap cell). In `--from-tables` mode, `--output` locates
the existing tables and metadata; bootstrap, bin and seed settings come from
that metadata and cannot be overridden.
