"""Build the station-window temperature sample and its separate covariate tables."""

import argparse

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.analysis_covariates import build_source_elevation
from py.preprocessing.build_monthly_era5_pairs import main as build_monthly_era5_pairs
from py.preprocessing.build_station_cache import main as build_station_cache
from py.preprocessing.export_clean_station_sample import main as export_clean_station_sample
from py.preprocessing.match_era5_grid import main as match_era5_grid
from py.preprocessing.select_station_observations import main as select_station_observations
from py.preprocessing.coastal_distance import main as coastal_distance
from py.preprocessing.ndvi import main as seasonal_ndvi
from py.preprocessing.download_hourly_weather import download_weather
from py.preprocessing.hourly_weather import build_weather_covariates
from py.preprocessing.land_cover import build_land_cover


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not (DATA_DIRECTORY / "station_data.parquet").exists():
        build_station_cache()
    select_station_observations()
    match_era5_grid()
    build_monthly_era5_pairs()
    export_clean_station_sample()
    coastal_distance()
    seasonal_ndvi()
    build_source_elevation()
    build_land_cover()
    download_weather()
    build_weather_covariates()


if __name__ == "__main__":
    main()
