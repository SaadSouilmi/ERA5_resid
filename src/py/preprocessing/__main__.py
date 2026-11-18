"""Run station selection, grid matching, hourly maxima and the final sample export."""

import argparse

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.build_monthly_era5_pairs import main as build_monthly_era5_pairs
from py.preprocessing.build_station_cache import main as build_station_cache
from py.preprocessing.export_clean_station_sample import main as export_clean_station_sample
from py.preprocessing.match_era5_grid import main as match_era5_grid
from py.preprocessing.select_station_observations import main as select_station_observations


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not (DATA_DIRECTORY / "station_data.parquet").exists():
        build_station_cache()
    select_station_observations()
    match_era5_grid()
    build_monthly_era5_pairs()
    export_clean_station_sample()


if __name__ == "__main__":
    main()
