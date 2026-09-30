"""Altair publication styling and fixed-width vector exports."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import vl_convert as vlc

BLUE = "#0072B2"
FONT = "DejaVu Serif"
DOUBLE_COLUMN_MM = 180


def paper_style(chart):
    return (
        chart.configure(background="white", font=FONT, padding=8)
        .configure_view(stroke=None)
        .configure_axis(
            labelFont=FONT,
            titleFont=FONT,
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
            labelFont=FONT,
            titleFont=FONT,
            labelFontSize=10,
            titleFontSize=11,
            titleFontWeight="normal",
            gradientThickness=10,
        )
        .configure_title(font=FONT, fontSize=12, anchor="start", offset=10)
    )


def save_figure(chart, stem, dpi=600, width_mm=DOUBLE_COLUMN_MM):
    """Save the Altair spec and SVG/PDF/PNG at an exact physical width."""
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
    stem.with_suffix(".svg").write_text(svg)
    # vl-convert exports unitless SVG dimensions as points (72 per inch).
    render_svg = svg.replace(f'width="{width_mm}mm"', f'width="{width_mm / 25.4 * 72}"', 1)
    render_svg = render_svg.replace(
        f'height="{height_mm}mm"', f'height="{height_mm / 25.4 * 72}"', 1
    )
    stem.with_suffix(".pdf").write_bytes(vlc.svg_to_pdf(render_svg))
    stem.with_suffix(".png").write_bytes(vlc.svg_to_png(render_svg, ppi=dpi))
    return {"width_mm": width_mm, "height_mm": height_mm, "dpi": dpi}
