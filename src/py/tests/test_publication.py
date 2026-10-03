import json as Json
import struct as Struct
import tempfile as Tempfile
from pathlib import Path
from xml.etree import ElementTree

import altair as Alt
import polars as Pl
from pypdf import PdfReader

from py import paper_charts as PaperCharts
from py.paths import FiguresDirectory
from py.publication import PaperStyle, SaveFigure
from py.scripts.build_paper_figures import AddBounds, AnalysisFrame, FeatureFrame

from .check import Expect, ExpectClose, ExpectEqual, Run


def HeatmapBoundsUseObservedExtrema():
    Summary = Pl.DataFrame(
        {
            "bin_x": ["(-inf, 2]", "(2, inf]"],
            "bin_y": ["(-inf, 5]", "(5, inf]"],
            "residual": [1.0, 2.0],
        }
    )
    Frame = Pl.DataFrame({"elevation": [-10, 12], "wind": [1.0, 9.0]})
    Bounded = AddBounds(Summary, Frame, "elevation", "wind")
    ExpectEqual(Bounded["x_lo"].to_list(), [-10.0, 2.0])
    ExpectEqual(Bounded["x_hi"].to_list(), [2.0, 12.0])
    ExpectEqual(Bounded["y_lo"].to_list(), [1.0, 5.0])
    ExpectEqual(Bounded["y_hi"].to_list(), [5.0, 9.0])
    Expect(Bounded.select(Summary.columns).equals(Summary), "adding bounds changed estimates")


def MissingCovariatesDoNotChangeTemperatureSample():
    Frame = Pl.DataFrame(
        {
            "station_celsius": [20.0, 22.0, 24.0],
            "era5_celsius": [19.0, 20.0, 21.0],
            "residual": [1.0, 2.0, 3.0],
            "lat": [50.0] * 3,
            "lon": [10.0] * 3,
            "ndvi": [0.4, None, 0.6],
            "elevation": [100, 200, None],
            "source_note": [None, None, None],
        }
    )
    Clean = AnalysisFrame(Frame)
    ExpectEqual(len(Clean), 3)
    ExpectEqual(FeatureFrame(Clean, ["station_celsius"])["residual"].to_list(), [1.0, 2.0, 3.0])
    ExpectEqual(FeatureFrame(Clean, ["ndvi"])["residual"].to_list(), [1.0, 3.0])
    ExpectEqual(FeatureFrame(Clean, ["elevation"])["residual"].to_list(), [1.0, 2.0])


def ExportsKeepPhysicalSizeAndEditableText():
    Chart = PaperStyle(
        Alt.Chart(Alt.Data(values=[{"x": 1, "y": 2}, {"x": 2, "y": 3}]))
        .mark_line()
        .encode(x="x:Q", y="y:Q")
        .properties(width=160, height=90)
    )
    with Tempfile.TemporaryDirectory() as Directory:
        Stem = Path(Directory) / "figure"
        SaveFigure(Chart, Stem, WidthMm=90, Dpi=300)
        Page = PdfReader(Stem.with_suffix(".pdf")).pages[0]
        ExpectClose(float(Page.mediabox.width) * 25.4 / 72, 90, AbsTol=1e-4)
        Svg = ElementTree.parse(Stem.with_suffix(".svg"))
        ExpectEqual(Svg.getroot().attrib["width"], "90mm")
        Expect(bool(Svg.findall(".//{http://www.w3.org/2000/svg}text")), "SVG text is not editable")
        Png = Stem.with_suffix(".png").read_bytes()
        Width, Height = Struct.unpack(">II", Png[16:24])
        Expect(abs(Width - 90 / 25.4 * 300) < 2, "wrong PNG width at 300 dpi")
        Expect(Height > 0, "empty PNG")
        Offset = 8
        FoundResolution = False
        while Offset < len(Png):
            Length = Struct.unpack(">I", Png[Offset : Offset + 4])[0]
            if Png[Offset + 4 : Offset + 8] == b"pHYs":
                X, Y, Unit = Struct.unpack(">IIB", Png[Offset + 8 : Offset + 8 + Length])
                ExpectClose(X * 0.0254, 300, AbsTol=0.02)
                ExpectEqual(X, Y)
                ExpectEqual(Unit, 1)
                FoundResolution = True
            Offset += Length + 12
        Expect(FoundResolution, "PNG has no physical resolution metadata")
        Spec = Json.loads(Stem.with_suffix(".vl.json").read_text())
        Expect("vega-lite" in Spec["$schema"], "missing Vega-Lite specification")


def SavedTablesRenderWithoutRawData():
    Tables = FiguresDirectory / "tables"
    for Builder in (
        PaperCharts.Covariates,
        PaperCharts.Urbanization,
        PaperCharts.Interactions,
        PaperCharts.StationMap,
    ):
        Chart = PaperStyle(Builder(Tables))
        Expect(bool(Chart.to_dict()), f"{Builder.__name__} produced an empty specification")


def CovariateFigureRetainsResidualAxisLabels():
    Chart = PaperStyle(PaperCharts.Covariates(FiguresDirectory / "tables"))
    with Tempfile.TemporaryDirectory() as Directory:
        Stem = Path(Directory) / "covariates"
        SaveFigure(Chart, Stem, Dpi=72)
        Svg = ElementTree.parse(Stem.with_suffix(".svg"))
        Labels = [Node.text for Node in Svg.findall(".//{http://www.w3.org/2000/svg}text")]
        ExpectEqual(Labels.count("Mean residual (°C)"), 2)


def HeatmapExportsHaveStableCellOrder():
    Tables = FiguresDirectory / "tables"
    First = PaperCharts.Interactions(Tables).to_dict()
    for _ in range(3):
        ExpectEqual(PaperCharts.Interactions(Tables).to_dict(), First)


def Main():
    Run(MissingCovariatesDoNotChangeTemperatureSample)
    Run(HeatmapBoundsUseObservedExtrema)
    Run(ExportsKeepPhysicalSizeAndEditableText)
    Run(SavedTablesRenderWithoutRawData)
    Run(CovariateFigureRetainsResidualAxisLabels)
    Run(HeatmapExportsHaveStableCellOrder)
