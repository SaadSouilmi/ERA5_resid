"""Map the European country selection and the available ERA5 footprint."""

import altair as alt
import cartopy
from cartopy.io import shapereader
from shapely import orient_polygons
from shapely.geometry import box, mapping

from py.paths import NotebookFiguresDirectory as notebook_figures_dir
from py.publication import PaperStyle as paper_style

LABELS = [
    ("Iceland", -19, 65),
    ("Norway", 9, 64),
    ("Sweden", 17, 62.5),
    ("Finland", 27, 65),
    ("Denmark", 10, 56),
    ("UK", -3, 55),
    ("Ireland", -8, 53),
    ("France", 2, 46.5),
    ("Spain", -3, 40),
    ("Germany", 10, 51),
    ("Poland", 19, 52),
    ("Italy", 12, 42.5),
    ("Romania", 25, 45.5),
    ("Ukraine", 32, 49),
    ("Greece", 23, 38.5),
    ("Russia", 49, 60),
    ("Türkiye", 34, 39),
    ("Morocco", -7, 29),
    ("Algeria", 2, 29),
    ("Tunisia", 10, 32),
    ("Greenland", -35, 74),
]


def geographic_selection_map(country_codes, bounds):
    west, south, east, north = bounds
    viewport = box(-40, 25, 65, 80)
    coverage = box(west, south, east, north)
    cartopy.config["data_dir"] = notebook_figures_dir / "preprocessing_walkthrough/.cartopy"
    countries_file = shapereader.natural_earth("50m", "cultural", "admin_0_countries")
    categories = ["European area inside ERA5", "European area outside ERA5", "Other countries"]
    features, selected_features = [], []
    for record in shapereader.Reader(countries_file).records():
        geometry = record.geometry.intersection(viewport)
        if geometry.is_empty:
            continue
        european = record.attributes["ISO_A2_EH"] in country_codes
        properties = {
            "country": record.attributes["NAME_EN"],
            "selection": categories[1] if european else categories[2],
        }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(orient_polygons(geometry, exterior_cw=True)),
            }
        )
        if european:
            selected = geometry.intersection(coverage)
            if not selected.is_empty:
                selected_features.append(
                    {
                        "type": "Feature",
                        "properties": {**properties, "selection": categories[0]},
                        "geometry": mapping(orient_polygons(selected, exterior_cw=True)),
                    }
                )

    countries = (
        alt.Chart(alt.Data(values=features + selected_features))
        .mark_geoshape(
            stroke="white",
            strokeWidth=0.55,
            clip=True,
        )
        .encode(
            color=alt.Color(
                "properties.selection:N",
                scale=alt.Scale(
                    domain=categories,
                    range=["#6baed6", "#dcecf5", "#e2e2e2"],
                ),
                legend=alt.Legend(title=None, orient="top", columns=3, labelLimit=240),
            ),
            tooltip=[
                alt.Tooltip("properties.country:N", title="Country"),
                alt.Tooltip("properties.selection:N", title="Geographic selection"),
            ],
        )
    )
    boundary = alt.Chart(
        alt.Data(
            values=[
                {
                    "type": "Feature",
                    "geometry": mapping(coverage.boundary.segmentize(1)),
                    "properties": {},
                }
            ]
        )
    ).mark_geoshape(fill=None, stroke="#c46b00", strokeWidth=2, strokeDash=[7, 4], clip=True)
    labels = (
        alt.Chart(
            alt.Data(
                values=[{"country": name, "lon": lon, "lat": lat} for name, lon, lat in LABELS]
            )
        )
        .mark_text(fontSize=12, color="#172c3b", clip=True)
        .encode(
            longitude="lon:Q",
            latitude="lat:Q",
            text="country:N",
        )
    )
    graticule = alt.Chart(alt.graticule(step=[10, 10])).mark_geoshape(
        stroke="#cad5dd",
        strokeWidth=0.45,
        clip=True,
    )
    fit = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "MultiPoint",
            "coordinates": [[lon, lat] for lon in range(-40, 66, 5) for lat in (25, 80)],
        },
    }
    return paper_style(
        alt.layer(graticule, countries, boundary, labels)
        .project(
            type="conicConformal", parallels=[35, 65], rotate=[-12, 0, 0], center=[0, 53], fit=fit
        )
        .properties(
            width=950,
            height=680,
            view=alt.ViewConfig(fill="#f4f8fb", stroke=None),
            title=alt.TitleParams(
                "European study area within the ERA5 coverage",
                subtitle=[
                    "Blue: eligible European land. Orange dashed line: ERA5 extract.",
                    "Country outlines: Natural Earth (1:50 million).",
                ],
            ),
        )
    )
