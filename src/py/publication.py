"""Fixed-width Altair and Plotly exports used by the current figures."""

import json as Json
from pathlib import Path
from xml.etree import ElementTree as Et

import vl_convert as Vlc

Font = "DejaVu Serif"
DoubleColumnMm = 180


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


async def export_analysis_plotly_figure(figure, group, name, dpi=600, width_mm=DoubleColumnMm):
    import tempfile

    import kaleido
    import plotly

    from py.paths import ANALYSIS_FIGURES_DIRECTORY

    stem = ANALYSIS_FIGURES_DIRECTORY / group / name
    stem.parent.mkdir(parents=True, exist_ok=True)
    width, height = figure.layout.width, figure.layout.height
    pixel_ratio = width_mm / 25.4 * dpi / width
    with tempfile.TemporaryDirectory(prefix="era5-plotly-") as temporary:
        script = Path(plotly.__file__).parent / "package_data/plotly.min.js"
        if max(width, height) * pixel_ratio > 4096:
            # MapLibre's default canvas cap silently downsamples high-resolution exports.
            javascript = script.read_text()
            default = "maxCanvasSize:[4096,4096]"
            if javascript.count(default) != 1:
                raise ValueError(
                    "Plotly's MapLibre canvas option changed; review high-resolution export"
                )
            script = Path(temporary) / "plotly.js"
            script.write_text(javascript.replace(default, "maxCanvasSize:[8192,8192]"))
        async with kaleido.Kaleido(
            plotlyjs=script,
            mathjax=False,
            headers={"X-Requested-With": "ERA5_resid/Plotly"},
            timeout=300,
        ) as renderer:
            # Kaleido's image scale alone does not increase MapLibre's canvas resolution.
            for tab in renderer.tabs.values():
                await tab.send_command(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": width,
                        "height": height,
                        "deviceScaleFactor": pixel_ratio,
                        "mobile": False,
                    },
                )
            svg = (await renderer.calc_fig(figure, opts={"format": "svg", "scale": 1})).decode()
    root = Et.fromstring(svg)
    # Convert at the target size; resizing Chrome's PDF can distort its colourbar pattern.
    svg = svg.replace(f'width="{root.attrib["width"]}"', f'width="{width_mm / 25.4 * 72}"', 1)
    svg = svg.replace(
        f'height="{root.attrib["height"]}"', f'height="{width_mm / 25.4 * 72 * height / width}"', 1
    )
    stem.with_suffix(".pdf").write_bytes(Vlc.svg_to_pdf(svg))
    figure.write_json(stem.with_suffix(".plotly.json"), pretty=True)
    stem.with_suffix(".vl.json").unlink(missing_ok=True)
    print(f"Saved {stem.with_suffix('.pdf')}")
    return figure
