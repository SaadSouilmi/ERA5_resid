"""Fixed-width Altair and Plotly exports used by the current figures."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import vl_convert as vlc

FONT = "DejaVu Serif"
DOUBLE_COLUMN_MM = 180


def save_figure(chart, stem, dpi=600, width_mm=DOUBLE_COLUMN_MM, formats=("png", "pdf")):
    """Save the Altair spec and PNG/PDF at an exact physical width."""
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    spec = chart.to_dict()
    stem.with_suffix(".vl.json").write_text(json.dumps(spec, indent=2) + "\n")
    svg = vlc.vegalite_to_svg(spec)
    root = ET.fromstring(svg)
    _, _, width, height = map(float, root.attrib["viewBox"].split())
    height_mm = width_mm * height / width
    # Preserve the viewBox while setting physical dimensions for all formats.
    svg = svg.replace(f'width="{root.attrib["width"]}"', f'width="{width_mm}mm"', 1)
    svg = svg.replace(f'height="{root.attrib["height"]}"', f'height="{height_mm}mm"', 1)
    if "svg" in formats:
        stem.with_suffix(".svg").write_text(svg)
    # vl-convert exports unitless SVG dimensions as points (72 per inch).
    render_svg = svg.replace(f'width="{width_mm}mm"', f'width="{width_mm / 25.4 * 72}"', 1)
    render_svg = render_svg.replace(
        f'height="{height_mm}mm"', f'height="{height_mm / 25.4 * 72}"', 1
    )
    if "pdf" in formats:
        stem.with_suffix(".pdf").write_bytes(vlc.svg_to_pdf(render_svg))
    if "png" in formats:
        stem.with_suffix(".png").write_bytes(vlc.svg_to_png(render_svg, ppi=dpi))
    return {"width_mm": width_mm, "height_mm": height_mm, "dpi": dpi}


async def export_analysis_plotly_figure(figure, group, name, dpi=600, width_mm=DOUBLE_COLUMN_MM):
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
    root = ET.fromstring(svg)
    # Convert at the target size; resizing Chrome's PDF can distort its colourbar pattern.
    svg = svg.replace(f'width="{root.attrib["width"]}"', f'width="{width_mm / 25.4 * 72}"', 1)
    svg = svg.replace(
        f'height="{root.attrib["height"]}"', f'height="{width_mm / 25.4 * 72 * height / width}"', 1
    )
    stem.with_suffix(".pdf").write_bytes(vlc.svg_to_pdf(svg))
    figure.write_json(stem.with_suffix(".plotly.json"), pretty=True)
    stem.with_suffix(".vl.json").unlink(missing_ok=True)
    print(f"Saved {stem.with_suffix('.pdf')}")
    return figure
