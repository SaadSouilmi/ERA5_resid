"""Altair publication styling and fixed-width vector exports."""

import json as Json
from pathlib import Path
from xml.etree import ElementTree as Et

import vl_convert as Vlc

Blue = "#0072B2"
Font = "DejaVu Serif"
DoubleColumnMm = 180


def PaperStyle(Chart):
    return (
        Chart.configure(background="white", font=Font, padding=8)
        .configure_view(stroke=None)
        .configure_axis(
            labelFont=Font,
            titleFont=Font,
            labelFontSize=10,
            titleFontSize=11,
            titleFontWeight="normal",
            titlePadding=10,
            labelPadding=5,
            domainColor="#444444",
            domainWidth=0.7,
            tickColor="#444444",
            tickWidth=0.7,
            tickSize=4,
            gridColor="#e5e5e5",
            gridWidth=0.5,
            labelColor="#222222",
            titleColor="#222222",
        )
        .configure_legend(
            labelFont=Font,
            titleFont=Font,
            labelFontSize=10,
            titleFontSize=11,
            titleFontWeight="normal",
            gradientThickness=10,
        )
        .configure_title(font=Font, fontSize=12, anchor="start", offset=10)
    )


def SaveFigure(Chart, Stem, Dpi=600, WidthMm=DoubleColumnMm, Formats=("svg", "pdf", "png")):
    """Save the Altair spec and SVG/PDF/PNG at an exact physical width."""
    Stem = Path(Stem)
    Stem.parent.mkdir(parents=True, exist_ok=True)
    Spec = Chart.to_dict()
    Stem.with_suffix(".vl.json").write_text(Json.dumps(Spec, indent=2) + "\n")
    Svg = Vlc.vegalite_to_svg(Spec)
    Root = Et.fromstring(Svg)
    _, _, Width, Height = map(float, Root.attrib["viewBox"].split())
    HeightMm = WidthMm * Height / Width
    # Preserve the viewBox while setting physical dimensions for all formats.
    Svg = Svg.replace(f'width="{Root.attrib["width"]}"', f'width="{WidthMm}mm"', 1)
    Svg = Svg.replace(f'height="{Root.attrib["height"]}"', f'height="{HeightMm}mm"', 1)
    if "svg" in Formats:
        Stem.with_suffix(".svg").write_text(Svg)
    # vl-convert exports unitless SVG dimensions as points (72 per inch).
    RenderSvg = Svg.replace(f'width="{WidthMm}mm"', f'width="{WidthMm / 25.4 * 72}"', 1)
    RenderSvg = RenderSvg.replace(f'height="{HeightMm}mm"', f'height="{HeightMm / 25.4 * 72}"', 1)
    if "pdf" in Formats:
        Stem.with_suffix(".pdf").write_bytes(Vlc.svg_to_pdf(RenderSvg))
    if "png" in Formats:
        Stem.with_suffix(".png").write_bytes(Vlc.svg_to_png(RenderSvg, ppi=Dpi))
    return {"width_mm": WidthMm, "height_mm": HeightMm, "dpi": Dpi}


def ExportNotebookFigure(Chart, Notebook, Name):
    from py.paths import NotebookFiguresDirectory

    Stem = NotebookFiguresDirectory / Notebook / Name
    SaveFigure(Chart, Stem, Formats=("pdf",))
    print(f"Saved {Stem.with_suffix('.pdf')}")
    return Chart
