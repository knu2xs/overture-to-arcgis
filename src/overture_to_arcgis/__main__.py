from importlib.util import find_spec
import json
import logging
from pathlib import Path
import shutil
from typing import Union

import arcpy
import pandas as pd

from overture_to_arcgis.utils.__main__ import convert_complex_columns_to_strings

from .utils import (
    get_all_overture_types,
    get_logger,
    validate_bounding_box,
    get_temp_gdb,
    get_record_batches,
    table_to_features,
    table_to_spatially_enabled_dataframe,
    get_geometry_column,
)

# configure module logging
logger = get_logger(
    logger_name="overture_to_arcgis", level="DEBUG", add_stream_handler=False
)


def get_spatially_enabled_dataframe(
    overture_type: str,
    bbox: tuple[float, float, float, float],
    connect_timeout: int = None,
    request_timeout: int = None,
) -> pd.DataFrame:
    """
    Retrieve data from Overture Maps as an
    [ArcGIS spatially enabled Pandas DataFrame](https://developers.arcgis.com/python/latest/guide/introduction-to-the-spatially-enabled-dataframe/).

    !!! note

        To see available overture types, use `arcgis_overture.utils.get_all_overture_types()`.

    Args:
        overture_type: Overture feature type to retrieve.
        bbox: Bounding box to filter the data. Format: (minx, miny, maxx, maxy).
        connect_timeout: Optional timeout in seconds for establishing a connection to the Overture Maps service.
        request_timeout: Optional timeout in seconds for waiting for a response from the Overture Maps service.

    Returns:
        A spatially enabled pandas DataFrame containing the requested Overture Maps data.
    """
    # validate the overture type
    available_types = get_all_overture_types()
    if overture_type not in available_types:
        raise ValueError(
            f"Invalid overture type: {overture_type}. Valid types are: {available_types}"
        )

    # validate the bounding box
    bbox = validate_bounding_box(bbox)

    # get the record batch generator
    batches = get_record_batches(overture_type, bbox, connect_timeout, request_timeout)

    # initialize the dataframe and geometry column name
    df = None

    # iterate the batches
    for idx, batch in enumerate(batches):

        # if the batch has any rows and the dataframe is not yet initialized
        if batch.num_rows > 0 and df is None:

            # create the initial dataframe
            df = table_to_spatially_enabled_dataframe(batch)

            # save the geometry column name
            geom_col = df.spatial.name

        elif batch.num_rows > 0:
            # get the batch as a spatially enabled dataframe
            tmb_df = table_to_spatially_enabled_dataframe(batch)

            # append the batch dataframe to the main dataframe
            df = pd.concat([df, tmb_df], ignore_index=True)

    # if data found, perform post processing
    if isinstance(df, pd.DataFrame):
        # set the geometry column using the ArcGIS GeoAccessor to get a Spatially Enabled DataFrame
        df.spatial.set_geometry(geom_col, sr=4326, inplace=True)

        # reset the index so it makes sense after concatenation
        df.reset_index(drop=True, inplace=True)

        # log the number of rows fetched
        df_cnt = df.shape[0]
        logger.debug(
            f"Fetched {df_cnt} rows of '{overture_type}' data from Overture Maps."
        )

    # if no data found, log a warning and create an empty dataframe to return
    else:
        df = pd.DataFrame()
        logger.warning(
            f"No '{overture_type}' data found for the specified bounding box: {bbox}"
        )

    return df


def get_features(
    output_feature_class: Union[str, Path],
    overture_type: str,
    bbox: tuple[float, float, float, float],
    connect_timeout: int = None,
    request_timeout: int = None,
) -> Path:
    """
    Retrieve data from Overture Maps and save it as an ArcGIS Feature Class.

    Args:
        output_feature_class: Path to the output feature class.
        overture_type: Overture feature type to retrieve.
        bbox: Bounding box to filter the data. Format: (minx, miny, maxx, maxy).
        connect_timeout: Optional timeout in seconds for establishing a connection to the AWS S3.
        request_timeout: Optional timeout in seconds for waiting for a response from the AWS S3.

    Returns:
        Path to the created feature class.
    """
    # ensure arcpy is available
    if find_spec('arcpy') is None:
        raise EnvironmentError("ArcPy is required for get_as_feature_class.")

    # validate the bounding box
    bbox = validate_bounding_box(bbox)

    # get a temporary geodatabase to hold the batch feature classes
    tmp_gdb = get_temp_gdb()

    # list to hold the feature classes
    fc_list = []

    # get the record batch generator
    batches = get_record_batches(overture_type, bbox, connect_timeout, request_timeout)

    # iterate through the record batches to see if we have any data
    for btch_idx, batch in enumerate(batches):
        # warn of no data found for the batch
        if batch.num_rows == 0:
            logger.warning(
                f"No '{overture_type}' data found for the specified bounding box: {bbox}. No temporary feature "
                f"class will be created for this batch."
            )

        # if there is data to work with, process it
        else:
            # report progress
            if logger.level <= logging.DEBUG:
                tbl_cnt = batch.num_rows
                logger.debug(
                    f"In batch {btch_idx:,} fetched {tbl_cnt:,} rows of '{overture_type}' data from Overture Maps."
                )

            # create the temporary feature class path
            tmp_fc = tmp_gdb / f"overture_{overture_type}_{btch_idx:04d}"

            # convert the batch to a feature class
            table_to_features(batch, output_features=tmp_fc)

            # add the feature class to the list if there is data to work with
            fc_list.append(str(tmp_fc))

    # merge the feature classes into a single feature class if any data was found
    if len(fc_list) > 0:
        arcpy.management.Merge(fc_list, str(output_feature_class))
    else:
        logger.warning("No data found for the specified bounding box. No output feature class created.")

    # cleanup temporary data - remove temporary geodatabase using arcpy to avoid any locks
    arcpy.management.Delete(str(tmp_gdb))

    return output_feature_class
