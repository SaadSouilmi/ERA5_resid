"""Observed Sentinel-2 NDVI in the existing 80 m cells and meteorological seasons."""

import hashlib as Hashlib
import json as Json
import math as Math
import os as Os
import threading as Threading
import time as Time
import xml.etree.ElementTree as Et
from datetime import (
    date as Date,
    datetime as Datetime,
    timedelta as Timedelta,
    timezone as Timezone,
)
from urllib.parse import urlencode as Urlencode, urlsplit as Urlsplit
from urllib.request import Request, urlopen as Urlopen

import numpy as Np
import rasterio as Rasterio
from pyproj import Transformer
from rasterio.windows import Window

Catalog = "https://planetarycomputer.microsoft.com/api/stac/v1"
Tokens = {}
TokenLock = Threading.Lock()


def WriteJson(File, Value):
    Temporary = File.with_suffix(f".{Os.getpid()}.{Threading.get_ident()}.tmp")
    Temporary.write_text(Json.dumps(Value, indent=2, allow_nan=False) + "\n")
    Temporary.replace(File)


def ReadBytes(Url):
    for Attempt in range(3):
        try:
            with Urlopen(
                Request(Url, headers={"User-Agent": "ERA5-NDVI-research"}), timeout=30
            ) as Response:
                return Response.read()
        except Exception:
            if Attempt == 2:
                raise
            Time.sleep(1 + Attempt)


def ReadJson(Url):
    return Json.loads(ReadBytes(Url))


def Sign(Url):
    Parts = Urlsplit(Url)
    Account = Parts.hostname.split(".")[0]
    Container = Parts.path.strip("/").split("/")[0]
    Key = (Account, Container)
    with TokenLock:
        Cached = Tokens.get(Key)
        if Cached is None or Cached[0] < Time.time() + 300:
            Data = ReadJson(
                f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{Account}/{Container}"
            )
            Expiry = Datetime.fromisoformat(Data["msft:expiry"].replace("Z", "+00:00")).timestamp()
            Tokens[Key] = (Expiry, Data["token"])
        Token = Tokens[Key][1]
    return Url + "?" + Token.lstrip("?")


def SeasonStart(Day):
    Month = 12 if Day.month in (1, 2, 12) else Day.month // 3 * 3
    return Date(Day.year - (Day.month < 3), Month, 1)


def AddMonths(Day, Count):
    Index = Day.year * 12 + Day.month - 1 + Count
    return Date(Index // 12, Index % 12 + 1, 1)


def CellBounds(Lon, Lat, Transform):
    X, Y = Transformer.from_crs(4326, 3035, always_xy=True).transform(Lon, Lat)
    Column, Row = ~Transform * (X, Y)
    Left, Top = Transform * (Math.floor(Column), Math.floor(Row))
    return Left, Top - 80, Left + 80, Top


def CatalogItems(Source, Start, End, Directory):
    File = Directory / f"catalog_{Source['SOUID']}_{Start}_{End}.json"
    if File.exists():
        return Json.loads(File.read_text())
    Lon, Lat = Source["source_lon"], Source["source_lat"]
    Query = Urlencode(
        {
            "collections": "sentinel-2-l2a",
            "bbox": f"{Lon - 0.00001},{Lat - 0.00001},{Lon + 0.00001},{Lat + 0.00001}",
            "datetime": f"{Start}T00:00:00Z/{End - Timedelta(days=1)}T23:59:59Z",
            "limit": 1000,
        }
    )
    Url = Catalog + "/search?" + Query
    Items = []
    while Url:
        Page = ReadJson(Url)
        for Item in Page.get("features", []):
            Items.append(
                {
                    "id": Item["id"],
                    "properties": Item["properties"],
                    "assets": {
                        Name: Item["assets"][Name]
                        for Name in ["B04", "B08", "SCL", "product-metadata"]
                    },
                }
            )
        Url = next((Link["href"] for Link in Page.get("links", []) if Link["rel"] == "next"), None)
    Items = sorted(Items, key=lambda Item: Item["id"])
    WriteJson(File, Items)
    return Items


def ReflectanceParameters(Item, Directory):
    File = Directory / (Item["id"] + ".xml")
    if not File.exists():
        Payload = ReadBytes(Sign(Item["assets"]["product-metadata"]["href"]))
        Et.fromstring(Payload)
        Temporary = File.with_suffix(f".{Os.getpid()}.{Threading.get_ident()}.tmp")
        Temporary.write_bytes(Payload)
        Temporary.replace(File)
    Root = Et.fromstring(File.read_bytes())
    Quantification = None
    Offsets = {}
    for Node in Root.iter():
        Name = Node.tag.split("}")[-1]
        if Name == "BOA_QUANTIFICATION_VALUE":
            Quantification = float(Node.text)
        elif Name == "BOA_ADD_OFFSET":
            Offsets[int(Node.attrib["band_id"])] = float(Node.text)
    Baseline = float(Item["properties"]["s2:processing_baseline"])
    if Quantification is None or not Math.isfinite(Quantification) or Quantification <= 0:
        raise ValueError("Missing positive reflectance quantification")
    if Baseline >= 4 and not {3, 7}.issubset(Offsets):
        raise ValueError("Missing post-baseline-04 reflectance offsets")
    if not Math.isfinite(Baseline) or not all(Math.isfinite(Value) for Value in Offsets.values()):
        raise ValueError("Nonfinite reflectance metadata")
    return Quantification, Offsets.get(3, 0.0), Offsets.get(7, 0.0)


def PixelNdvi(RedDn, NirDn, Classes, Footprint, Quantification, RedOffset, NirOffset):
    Red = (RedDn.astype(float) + RedOffset) / Quantification
    Nir = (NirDn.astype(float) + NirOffset) / Quantification
    Valid = Footprint & Np.isin(Classes, [4, 5, 6]) & (RedDn > 0) & (NirDn > 0)
    Valid &= (Red >= 0) & (Nir >= 0) & ((Nir + Red) > 0)
    Values = Np.full(Red.shape, Np.nan)
    Values[Valid] = (Nir[Valid] - Red[Valid]) / (Nir[Valid] + Red[Valid])
    return Values, Valid


def SceneValue(Item, Bounds, Directory):
    CellKey = Hashlib.sha256(Json.dumps(Bounds).encode()).hexdigest()[:16]
    File = Directory / "scene_values" / f"{Item['id']}_{CellKey}.json"
    if File.exists():
        return Json.loads(File.read_text())
    Assets = Item["assets"]
    Crs = Item["properties"]["proj:epsg"]
    Project = Transformer.from_crs(3035, Crs, always_xy=True)
    Left, Bottom, Right, Top = Bounds
    Xs, Ys = Project.transform([Left, Right, Right, Left], [Bottom, Bottom, Top, Top])
    with Rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_TIMEOUT="30",
        GDAL_HTTP_MAX_RETRY="1",
        GDAL_HTTP_RETRY_DELAY="1",
    ):
        with Rasterio.open(Sign(Assets["B04"]["href"])) as RedRaster:
            Rows, Columns = Rasterio.transform.rowcol(RedRaster.transform, Xs, Ys)
            Row0, Col0 = max(0, min(Rows)), max(0, min(Columns))
            Row1, Col1 = (
                min(RedRaster.height, max(Rows) + 1),
                min(RedRaster.width, max(Columns) + 1),
            )
            if Row1 <= Row0 or Col1 <= Col0:
                return {"id": Item["id"], "valid_fraction": 0.0, "ndvi": None}
            WindowValue = Window(Col0, Row0, Col1 - Col0, Row1 - Row0)
            RedDn = RedRaster.read(1, window=WindowValue)
            Transform = RedRaster.transform
            GridRows, GridCols = Np.meshgrid(
                Np.arange(Row0, Row1), Np.arange(Col0, Col1), indexing="ij"
            )
            PixelXs = Transform.c + (GridCols + 0.5) * Transform.a
            PixelYs = Transform.f + (GridRows + 0.5) * Transform.e
        CellXs, CellYs = Transformer.from_crs(Crs, 3035, always_xy=True).transform(PixelXs, PixelYs)
        Footprint = (CellXs >= Left) & (CellXs < Right) & (CellYs >= Bottom) & (CellYs < Top)
        with Rasterio.open(Sign(Assets["SCL"]["href"])) as Quality:
            QRows, QCols = Rasterio.transform.rowcol(
                Quality.transform, PixelXs.ravel(), PixelYs.ravel()
            )
            QRows, QCols = Np.asarray(QRows), Np.asarray(QCols)
            if (
                (QRows < 0).any()
                or (QCols < 0).any()
                or (QRows >= Quality.height).any()
                or (QCols >= Quality.width).any()
            ):
                return {"id": Item["id"], "valid_fraction": 0.0, "ndvi": None}
            QRow, QCol = QRows.min(), QCols.min()
            ClassesRaw = Quality.read(
                1,
                window=Window(
                    int(QCol), int(QRow), int(QCols.max() - QCol + 1), int(QRows.max() - QRow + 1)
                ),
            )
            Classes = ClassesRaw[QRows - QRow, QCols - QCol].reshape(RedDn.shape)
        Clear = Footprint & Np.isin(Classes, [4, 5, 6])
        if Footprint.sum() < 50 or Clear.sum() / Footprint.sum() < 0.75:
            Result = {
                "id": Item["id"],
                "valid_fraction": float(Clear.sum() / max(1, Footprint.sum())),
                "ndvi": None,
            }
        else:
            with Rasterio.open(Sign(Assets["B08"]["href"])) as NirRaster:
                if NirRaster.transform != Transform or NirRaster.crs.to_epsg() != Crs:
                    raise ValueError("Red and near-infrared grids differ")
                NirDn = NirRaster.read(1, window=WindowValue)
            Quantification, RedOffset, NirOffset = ReflectanceParameters(
                Item, Directory / "product_metadata"
            )
            Values, Valid = PixelNdvi(
                RedDn, NirDn, Classes, Footprint, Quantification, RedOffset, NirOffset
            )
            Fraction = float(Valid.sum() / Footprint.sum())
            Result = {
                "id": Item["id"],
                "valid_fraction": Fraction,
                "ndvi": float(Np.nanmean(Values)) if Fraction >= 0.75 else None,
                "quantification": Quantification,
                "red_offset": RedOffset,
                "nir_offset": NirOffset,
                "valid_pixels": int(Valid.sum()),
                "footprint_pixels": int(Footprint.sum()),
            }
    Result["acquisition_date"] = Item["properties"]["datetime"][:10]
    WriteJson(File, Result)
    return Result


def FetchSeason(Source, Start, Directory, Transform, PerMonth=2, MaxAttempts=16):
    End = AddMonths(Start, 3)
    File = Directory / "seasons" / f"{Source['SOUID']}_{Start}.json"
    if File.exists():
        return Json.loads(File.read_text())
    Items = CatalogItems(Source, Start, End, Directory / "catalog")
    Bounds = CellBounds(Source["source_lon"], Source["source_lat"], Transform)
    Accepted, Attempts, Errors = [], 0, []
    Monthly = []
    for Offset in range(3):
        Month = AddMonths(Start, Offset).isoformat()[:7]
        Candidates = sorted(
            [Item for Item in Items if Item["properties"]["datetime"].startswith(Month)],
            key=lambda Item: (Item["properties"].get("eo:cloud_cover", 100), Item["id"]),
        )
        Dates, Values = set(), []
        for Item in Candidates[:MaxAttempts]:
            Day = Item["properties"]["datetime"][:10]
            if Day in Dates:
                continue
            Attempts += 1
            try:
                Result = SceneValue(Item, Bounds, Directory)
            except Exception as Error:
                Errors.append({"id": Item["id"], "error_type": type(Error).__name__})
                continue
            if Result["ndvi"] is not None:
                Dates.add(Day)
                Accepted.append(Result)
                Values.append(Result["ndvi"])
                if len(Values) >= PerMonth:
                    break
        if Values:
            Monthly.append(
                {"month": Month, "ndvi": float(Np.median(Values)), "observations": len(Values)}
            )
    Qualified = len(Monthly) == 3 and len(Accepted) >= 3
    Result = {
        "SOUID": Source["SOUID"],
        "source_lat": Source["source_lat"],
        "source_lon": Source["source_lon"],
        "season_start": Start.isoformat(),
        "season_end": End.isoformat(),
        "ndvi_observed": float(Np.mean([Row["ndvi"] for Row in Monthly])) if Qualified else None,
        "status": "observed_season" if Qualified else "insufficient_month_coverage",
        "valid_dates": len(Accepted),
        "valid_months": len(Monthly),
        "attempted_scenes": Attempts,
        "catalog_scenes": len(Items),
        "monthly": Monthly,
        "accepted_scenes": Accepted,
        "errors": Errors,
        "cell_bounds_epsg3035": Bounds,
        "retrieved_utc": Datetime.now(Timezone.utc).isoformat(),
    }
    WriteJson(File, Result)
    return Result
