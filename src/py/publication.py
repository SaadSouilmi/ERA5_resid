"""Publication styling and fixed-width Altair and Plotly exports."""

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


def SaveFigure(Chart, Stem, Dpi=600, WidthMm=DoubleColumnMm, Formats=("png", "pdf")):
    """Save the Altair spec and PNG/PDF at an exact physical width."""
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


async def ExportNotebookPlotlyFigure(Figure, Notebook, Name, Dpi=600, WidthMm=DoubleColumnMm):
    import tempfile as Tempfile

    import kaleido as Kaleido
    import plotly as Plotly

    from py.paths import NotebookFiguresDirectory

    Stem = NotebookFiguresDirectory / Notebook / Name
    Stem.parent.mkdir(parents=True, exist_ok=True)
    Width, Height = Figure.layout.width, Figure.layout.height
    PixelRatio = WidthMm / 25.4 * Dpi / Width
    with Tempfile.TemporaryDirectory(prefix="era5-plotly-") as Temporary:
        Script = Path(Plotly.__file__).parent / "package_data/plotly.min.js"
        if max(Width, Height) * PixelRatio > 4096:
            # MapLibre's default canvas cap silently downsamples high-resolution exports.
            Javascript = Script.read_text()
            Default = "maxCanvasSize:[4096,4096]"
            if Javascript.count(Default) != 1:
                raise ValueError(
                    "Plotly's MapLibre canvas option changed; review high-resolution export"
                )
            Script = Path(Temporary) / "plotly.js"
            Script.write_text(Javascript.replace(Default, "maxCanvasSize:[8192,8192]"))
        async with Kaleido.Kaleido(
            plotlyjs=Script,
            mathjax=False,
            headers={"X-Requested-With": "ERA5_resid/Plotly"},
            timeout=300,
        ) as Renderer:
            # Kaleido's image scale alone does not increase MapLibre's canvas resolution.
            for Tab in Renderer.tabs.values():
                await Tab.send_command(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": Width,
                        "height": Height,
                        "deviceScaleFactor": PixelRatio,
                        "mobile": False,
                    },
                )
            Svg = (await Renderer.calc_fig(Figure, opts={"format": "svg", "scale": 1})).decode()
    Root = Et.fromstring(Svg)
    # Convert at the target size; resizing Chrome's PDF can distort its colourbar pattern.
    Svg = Svg.replace(f'width="{Root.attrib["width"]}"', f'width="{WidthMm / 25.4 * 72}"', 1)
    Svg = Svg.replace(
        f'height="{Root.attrib["height"]}"', f'height="{WidthMm / 25.4 * 72 * Height / Width}"', 1
    )
    Stem.with_suffix(".pdf").write_bytes(Vlc.svg_to_pdf(Svg))
    Figure.write_json(Stem.with_suffix(".plotly.json"), pretty=True)
    Stem.with_suffix(".vl.json").unlink(missing_ok=True)
    print(f"Saved {Stem.with_suffix('.pdf')}")
    return Figure
