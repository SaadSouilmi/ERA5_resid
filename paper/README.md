# Working manuscript

`paper.tex` is the working draft. Its numerical text, selected PDFs, table snapshots
and `processing_review.json` describe the earlier release and have not yet been
reconciled with `data2/station_era5_clean.parquet`. Current results are in
[the numerical note](../notes/NUMERICAL_ANALYSIS.md).

After the queued weather and numerical rerun:

1. Export `py.scripts.plot_station_map` for the current source locations.
2. Run `py.scripts.build_paper_tables` and `py.scripts.sync_paper_figures`.
3. Reconcile the draft's prose, counts and interpretations with those results.

`py.scripts.sync_paper_figures --check` validates the selected sources without
copying. It requires the completed weather profiles/interactions and current
station map. The retained `tables/degurba.vl.json` also supplies the approved
DEGURBA plotting style; keep it available to `py.scripts.plot_degurba`.

The referenced `downscaling.bib` is missing, so a complete LaTeX build is pending.
The supplied comparison and previous draft are preserved in the cleanup archive
listed in [notes/CLEANUP.md](../notes/CLEANUP.md).
