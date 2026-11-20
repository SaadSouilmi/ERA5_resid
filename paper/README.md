# Working manuscript

`paper.tex` is the working draft. Its numerical text, selected PDFs, table snapshots
and `processing_review.json` describe the earlier release and have not yet been
reconciled with `data2/station_era5_clean.parquet`. Current results are in
[the results index](../figures/analysis/README.md). The numerical note remains an
older partial write-up.

After the queued weather and numerical rerun, use the current PDFs and CSV source
tables under `figures/analysis/` to reconcile the draft's prose, counts and
interpretations. Export `py.scripts.plot_station_map` for the current source
locations. Manuscript copying and table-export code are archived outside the
retained preprocessing/figure source scope; see [notes/CLEANUP.md](../notes/CLEANUP.md).

The retained `tables/degurba.vl.json` also supplies the approved
DEGURBA plotting style; keep it available to `py.scripts.plot_degurba`.

The referenced `downscaling.bib` is missing, so a complete LaTeX build is pending.
The supplied comparison and previous draft are preserved in the cleanup archive
listed in [notes/CLEANUP.md](../notes/CLEANUP.md).
