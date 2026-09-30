import json
import struct
import tempfile
from pathlib import Path
from xml.etree import ElementTree

import altair as alt
import polars as pl
from pypdf import PdfReader

from py import paper_charts
from py.paths import FIGURES
from py.publication import paper_style, save_figure
from py.scripts.build_paper_figures import add_bounds

from .check import Expect, ExpectClose, ExpectEqual, Run


def HeatmapBoundsUseObservedExtrema():
    Summary = pl.DataFrame(
        {
            "bin_x": ["(-inf, 2]", "(2, inf]"],
            "bin_y": ["(-inf, 5]", "(5, inf]"],
            "residual": [1.0, 2.0],
        }
    )
    Frame = pl.DataFrame({"elevation": [-10, 12], "wind": [1.0, 9.0]})
    Bounded = add_bounds(Summary, Frame, "elevation", "wind")
    ExpectEqual(Bounded["x_lo"].to_list(), [-10.0, 2.0])
    ExpectEqual(Bounded["x_hi"].to_list(), [2.0, 12.0])
    ExpectEqual(Bounded["y_lo"].to_list(), [1.0, 5.0])
    ExpectEqual(Bounded["y_hi"].to_list(), [5.0, 9.0])
    Expect(Bounded.select(Summary.columns).equals(Summary), "adding bounds changed estimates")


def ExportsKeepPhysicalSizeAndEditableText():
    Chart = paper_style(
        alt.Chart(alt.Data(values=[{"x": 1, "y": 2}, {"x": 2, "y": 3}]))
        .mark_line()
        .encode(x="x:Q", y="y:Q")
        .properties(width=160, height=90)
    )
    with tempfile.TemporaryDirectory() as Directory:
        Stem = Path(Directory) / "figure"
        save_figure(Chart, Stem, width_mm=90, dpi=300)
        Page = PdfReader(Stem.with_suffix(".pdf")).pages[0]
        ExpectClose(float(Page.mediabox.width) * 25.4 / 72, 90, AbsTol=1e-4)
        Svg = ElementTree.parse(Stem.with_suffix(".svg"))
        ExpectEqual(Svg.getroot().attrib["width"], "90mm")
        Expect(bool(Svg.findall(".//{http://www.w3.org/2000/svg}text")), "SVG text is not editable")
        Png = Stem.with_suffix(".png").read_bytes()
        Width, Height = struct.unpack(">II", Png[16:24])
        Expect(abs(Width - 90 / 25.4 * 300) < 2, "wrong PNG width at 300 dpi")
        Expect(Height > 0, "empty PNG")
        Offset = 8
        FoundResolution = False
        while Offset < len(Png):
            Length = struct.unpack(">I", Png[Offset : Offset + 4])[0]
            if Png[Offset + 4 : Offset + 8] == b"pHYs":
                X, Y, Unit = struct.unpack(">IIB", Png[Offset + 8 : Offset + 8 + Length])
                ExpectClose(X * 0.0254, 300, AbsTol=0.02)
                ExpectEqual(X, Y)
                ExpectEqual(Unit, 1)
                FoundResolution = True
            Offset += Length + 12
        Expect(FoundResolution, "PNG has no physical resolution metadata")
        Spec = json.loads(Stem.with_suffix(".vl.json").read_text())
        Expect("vega-lite" in Spec["$schema"], "missing Vega-Lite specification")


def SavedTablesRenderWithoutRawData():
    Tables = FIGURES / "tables"
    for Builder in (
        paper_charts.covariates,
        paper_charts.urbanization,
        paper_charts.interactions,
        paper_charts.station_map,
    ):
        Chart = paper_style(Builder(Tables))
        Expect(bool(Chart.to_dict()), f"{Builder.__name__} produced an empty specification")


def CovariateFigureRetainsResidualAxisLabels():
    Chart = paper_style(paper_charts.covariates(FIGURES / "tables"))
    with tempfile.TemporaryDirectory() as Directory:
        Stem = Path(Directory) / "covariates"
        save_figure(Chart, Stem, dpi=72)
        Svg = ElementTree.parse(Stem.with_suffix(".svg"))
        Labels = [Node.text for Node in Svg.findall(".//{http://www.w3.org/2000/svg}text")]
        ExpectEqual(Labels.count("Mean residual (°C)"), 2)


def HeatmapExportsHaveStableCellOrder():
    Tables = FIGURES / "tables"
    First = paper_charts.interactions(Tables).to_dict()
    for _ in range(3):
        ExpectEqual(paper_charts.interactions(Tables).to_dict(), First)


def Main():
    Run(HeatmapBoundsUseObservedExtrema)
    Run(ExportsKeepPhysicalSizeAndEditableText)
    Run(SavedTablesRenderWithoutRawData)
    Run(CovariateFigureRetainsResidualAxisLabels)
    Run(HeatmapExportsHaveStableCellOrder)
