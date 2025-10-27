from importlib.util import find_spec
import json
from pathlib import Path
from cachetools import cachedmethod
from geomet import wkb, esri
import tempfile
from typing import Optional, Tuple, Generator, Union
from warnings import warn

from arcgis.geometry import Geometry
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs

from ._logging import get_logger

# create a logger for this module
logger = get_logger(logger_name="overture_to_arcgis.utils.__main__", level="DEBUG", add_stream_handler=False)

# provide variable indicating if arcpy is available
has_arcpy: bool = find_spec("arcpy") is not None

# provide variable indicating if pandas is available
has_pandas: bool = find_spec("pandas") is not None

# provide variable indicating if PySpark is available
has_pyarrow: bool = find_spec("pyarrow") is not None

# provide variable indicating if h3 is available
has_h3: bool = find_spec("h3") is not None


def slugify(value: str) -> str:
    """Convert a string to a slug format."""
    value = value.lower()
    value = value.replace('.', "_")  # helps with decimals for maximum heights
    value = value.replace(" ", "_")
    value = "".join(char for char in value if char.isalnum() or char == "_")
    return value


def get_temp_dir() -> Path:
    """Get a temporary directory path."""
    temp_dir = Path(tempfile.gettempdir())
    return temp_dir


def get_temp_gdb() -> Path:
    """Get a temporary File Geodatabase path."""
    tmp_dir = get_temp_dir()
    tmp_gdb = tmp_dir / "tmp_data.gdb"
    if not tmp_gdb.exists():
        if has_arcpy:
            import arcpy

            arcpy.management.CreateFileGDB(str(tmp_dir), tmp_gdb.name)
        else:
            raise EnvironmentError("arcpy is required to create a File Geodatabase.")
    return tmp_gdb


def validate_bounding_box(
    bbox: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Validate the bounding box coordinates."""
    # ensure four numeric values are provided
    if len(bbox) != 4:
        raise ValueError(
            "Bounding box must be a tuple of four values: (minx, miny, maxx, maxy)."
        )

    # ensure all coordinates are numeric, and if so convert to float
    if not all(isinstance(coord, (int, float)) for coord in bbox):
        raise ValueError(
            "All coordinates in the bounding box must be numeric (int or float)."
        )
    else:
        bbox = tuple(float(coord) for coord in bbox)

    # ensure minx < maxx and miny < maxy
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError(
            "Invalid bounding box coordinates: ensure that minx < maxx and miny < maxy."
        )

    # ensure coordinates are within valid ranges
    if not (
        -180.0 <= bbox[0] <= 180.0
        and -90.0 <= bbox[1] <= 90.0
        and -180.0 <= bbox[2] <= 180.0
        and -90.0 <= bbox[3] <= 90.0
    ):
        raise ValueError(
            "Bounding box coordinates must be within valid ranges: minx/maxx [-180, 180], miny/maxy [-90, 90]."
        )

    # If all checks pass, the bounding box is valid
    return bbox


def get_release_list(s3: Optional[fs.S3FileSystem] = None) -> list[str]:
    """
    Returns a list of all available Overture dataset releases.

    Args:
        s3: Optional pre-configured S3 filesystem. If not provided, an anonymous
            S3 filesystem will be created.
    """
    # create S3 filesystem if not provided
    if s3 is None:
        s3 = fs.S3FileSystem(anonymous=True, region="us-west-2")

    # create fileselector
    selector = fs.FileSelector(
        base_dir="overturemaps-us-west-2/release/", recursive=False
    )

    # get the most current releases from S3 as FileInfo objects
    file_infos = s3.get_file_info(selector)

    # extract the directory names from the FileInfo objects
    directories = [
        info.path for info in file_infos if info.type == fs.FileType.Directory
    ]

    # get the directory names only (last part of the path)
    releases = [dir_path.split("/")[-1] for dir_path in directories]

    # for each of the releases, ensure the releas has data (can happen if new release is still being loaded)
    releases = [rel for rel in releases if len(get_themes(rel, s3)) >= 5]

    logger.debug(f"Available releases: {releases}")

    return releases


def get_current_release() -> str:
    """
    Returns the most current Overture dataset release string.

    Returns:
        Most current release string.
    """
    # retrieve the list of releases
    releases = get_release_list()

    # make sure there is at least one release
    if not releases:
        raise RuntimeError("No Overture dataset releases found.")

    # get the most current release by sorting the list
    current_release = sorted(releases)[-1]

    logger.debug(f"Current release: {current_release}")

    return current_release


def get_themes(
    release: Optional[str] = None, s3: Optional[fs.S3FileSystem] = None
) -> list[str]:
    """
    Returns a list of all available Overture dataset themes for a given release.

    Args:
        release: Optional release version. If not provided, the most current
            release will be used.
        s3: Optional pre-configured S3 filesystem. If not provided, an anonymous
            S3 filesystem will be created.
    """
    # if no release provided, get the most current one
    if release is None:
        release = get_current_release()

    # create S3 filesystem if not provided
    if s3 is None:
        s3 = fs.S3FileSystem(anonymous=True, region="us-west-2")

    # create fileselector
    selector = fs.FileSelector(
        base_dir=f"overturemaps-us-west-2/release/{release}/", recursive=False
    )

    # get the themes from S3 as FileInfo objects
    file_infos = s3.get_file_info(selector)

    # extract the directory names from the FileInfo objects
    directories = [
        info.path for info in file_infos if info.type == fs.FileType.Directory
    ]

    # get the directory names only (last part of the path)
    themes = [dir_path.split("=")[-1] for dir_path in directories]

    logger.debug(f"Available themes for release {release}: {themes}")

    return themes


def get_type_theme_map(
    release: Optional[str] = None, s3: Optional[fs.S3FileSystem] = None
) -> dict[str, str]:
    """
    Returns the mapping of overture types to themes.

    Returns:
        Dictionary mapping overture types to themes.
    """
    # initialize dictionary
    type_theme_map = {}

    # if no release provided, get the most current one
    if release is None:
        release = get_current_release()

    # create S3 filesystem if not provided
    if s3 is None:
        s3 = fs.S3FileSystem(anonymous=True, region="us-west-2")

    # get the themes for the release
    themes = get_themes(release=release, s3=s3)

    # iterate through the themes and get the types for each
    for theme in themes:
        # create fileselector for the theme
        selector = fs.FileSelector(
            base_dir=f"overturemaps-us-west-2/release/{release}/theme={theme}/",
            recursive=False,
        )

        # get the types from S3 as FileInfo objects
        file_infos = s3.get_file_info(selector)

        # extract the directory names from the FileInfo objects
        directories = [
            info.path for info in file_infos if info.type == fs.FileType.Directory
        ]

        # get the directory names only (last part of the path)
        types = [dir_path.split("=")[-1] for dir_path in directories]

        # add the types to the mapping
        for overture_type in types:
            type_theme_map[overture_type] = theme

    logger.debug(f"Type theme map: {type_theme_map}")

    return type_theme_map


def get_all_overture_types(
    release: Optional[str] = None, s3: Optional[fs.S3FileSystem] = None
) -> list[str]:
    """
    Returns a list of all available Overture dataset types for a given release.

    Args:
        release: Optional release version. If not provided, the most current
            release will be used.
        s3: Optional pre-configured S3 filesystem. If not provided, an anonymous
            S3 filesystem will be created.

    Returns:
        List of available overture types for the release.
    """
    # if no release provided, get the most current one
    if release is None:
        release = get_current_release()

    # get the type theme map
    type_theme_map = get_type_theme_map(release=release, s3=s3)

    # get the types from the mapping
    types = list(type_theme_map.keys())

    logger.debug(f"Available types for release {release}: {types}")

    return types


def get_dataset_path(overture_type: str, release: Optional[str] = None) -> str:
    """
    Returns the S3 path of the Overture dataset to use.

    Args:
        overture_type: Overture feature type to load.
        release: Optional release version. If not provided, the most current
            release will be used.

    Returns:
        S3 path to the dataset.
    """
    # if no release provided, get the most current one
    if release is None:
        release = get_current_release()

    # get the overture type to theme mapping
    type_theme_map = get_type_theme_map()

    # get and validate the theme for the overture type
    theme = type_theme_map.get(overture_type)
    if theme is None:
        raise ValueError(f"Invalid overture type: {overture_type}")

    # create and return the dataset path
    pth = (
        f"overturemaps-us-west-2/release/{release}/theme={theme}/type={overture_type}/"
    )

    return pth


def convert_complex_columns_to_strings(table: pa.Table) -> pa.Table:
    """Convert complex data type columns in a PyArrow table to strings."""
    import json
    # list to hold new column values for converting back
    new_columns = []

    # iterate the columns
    for column in table.columns:
        # get the field
        field = table.schema.field(table.column_names[table.columns.index(column)])

        # if a struct, list or map (complex data types)
        if (
            pa.types.is_struct(field.type)
            or pa.types.is_list(field.type)
            or pa.types.is_map(field.type)
        ):
            # convert complex column to JSON string
            string_array = pa.array([json.dumps(value.as_py()) for value in column])
            new_columns.append(string_array)
        # if not complex, leave alone
        else:
            new_columns.append(column)

    # create a new PyArrow Table with the list of columns
    new_table = pa.table(new_columns, names=table.schema.names)
    return new_table


def get_geometry_column(table: Union[pa.Table, pa.RecordBatch]) -> str:
    """
    Get the name of the geometry column from the PyArrow Table or RecordBatch metadata.

    Args:
        table: PyArrow Table or RecordBatch with GeoArrow metadata.

    Returns:
        Name of the geometry column.
    """
    geo_meta = table.schema.metadata.get(b"geo")
    if geo_meta is None:
        raise ValueError("No geometry metadata found in the Overture Maps data.")
    geo_meta = json.loads(geo_meta.decode("utf-8"))
    geom_col = geo_meta.get("primary_column")
    if geom_col is None or geom_col not in table.column_names:
        raise ValueError(
            "No valid primary_geometry column defined in the Overture Maps metadata."
        )
    return geom_col


def convert_wkb_column_to_arcgis_geometry(wkb_series: pd.Series) -> pd.Series:
    """
    Convert a pandas Series of WKB values to ArcGIS Geometry objects.

    Args:
        wkb_series: pandas Series containing WKB values.

    Returns:
        pandas Series of ArcGIS Geometry objects.
    """
    def wkb_to_geometry(wkb_value):

        # if null value, return None
        if pd.isnull(wkb_value):
            ret_geom = None

        # otherwise, try to convert
        try:
            # convert WKB to geojson using geomet
            geojson = wkb.loads(wkb_value)

            # convert geojson to ArcGIS Geometry
            ret_geom = Geometry(geojson)
        
        # if any issues, log warning and return None
        except Exception as e:
            logger.warning(f"Failed to convert WKB to Geometry: {e}")
            ret_geom = None

        return ret_geom

    # use the apply method to convert each WKB value to Geometry
    geom_series = wkb_series.apply(wkb_to_geometry)

    return geom_series


def table_to_spatially_enabled_dataframe(
    table: Union[pa.Table, pa.RecordBatch]
) -> pd.DataFrame:
    """
    Convert a PyArrow Table or RecordBatch with GeoArrow metadata to an ArcGIS Spatially Enabled DataFrame.

    Args:
        table: PyArrow Table or RecordBatch with GeoArrow metadata.

    Returns:
        ArcGIS Spatially Enabled DataFrame.
    """
    # clean up any complex columns
    smpl_table = convert_complex_columns_to_strings(table)

    # convert table to a pandas DataFrame
    df = smpl_table.to_pandas()

    # get the geometry column from the metadata using the helper function
    geom_col = get_geometry_column(table)

    # convert the geometry column from WKB to arcgis Geometry objects
    df[geom_col] = convert_wkb_column_to_arcgis_geometry(df[geom_col])

    # set the geometry column using the ArcGIS GeoAccessor to get a Spatially Enabled DataFrame
    df.spatial.set_geometry(geom_col, sr=4326, inplace=True)

    return df


def table_to_features(
    table: Union[pa.Table, pa.RecordBatch], output_features: Union[str, Path]
) -> Path:
    """
    Convert a PyArrow Table or RecordBatch with GeoArrow metadata to an ArcGIS Feature Class.

    Args:
        table: PyArrow Table or RecordBatch with GeoArrow metadata.

    Returns:
        Path to the created feature class.
    """
    # convert the table to a spatially enabled dataframe
    df = table_to_spatially_enabled_dataframe(table)

    # save the dataframe to a feature class
    df.spatial.to_featureclass(output_features)

    return output_features


def get_record_batches(
    overture_type: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    connect_timeout: Optional[float] = None,
    request_timeout: Optional[float] = None,
) -> Generator[pa.RecordBatch, None, None]:
    """
    Return a pyarrow RecordBatchReader for the desired bounding box and S3 path.

    Args:
        overture_type: Overture feature type to load.
        bbox: Optional bounding box for data fetch (xmin, ymin, xmax, ymax).
        connect_timeout: Optional connection timeout in seconds.
        request_timeout: Optional request timeout in seconds.

    Yields:
        pa.RecordBatch: Record batches with the requested data.
    """
    # create connection to the S3 filesystem
    s3 = fs.S3FileSystem(
        anonymous=True,
        region="us-west-2",
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
    )

    # get the overture type to theme mapping
    type_theme_map = get_type_theme_map(s3=s3)

    # validate the overture type
    available_types = type_theme_map.keys()
    if overture_type not in available_types:
        raise ValueError(
            f"Invalid overture type: {overture_type}. Available types are: {list(available_types)}"
        )

    # validate the bounding box coordinates
    bbox = validate_bounding_box(bbox)

    # extract the coordinates from the bounding box and create the filter
    xmin, ymin, xmax, ymax = bbox
    dataset_filter = (
        (pc.field("bbox", "xmin") < xmax)
        & (pc.field("bbox", "xmax") > xmin)
        & (pc.field("bbox", "ymin") < ymax)
        & (pc.field("bbox", "ymax") > ymin)
    )

    # get the most current release version
    release = get_current_release()

    # create the dataset path
    s3_pth = get_dataset_path(overture_type, release)

    # create the PyArrow dataset
    dataset = ds.dataset(s3_pth, filesystem=s3)

    # get the record batches with the extent filter applied
    batches = dataset.to_batches(filter=dataset_filter)

    # iterate through the batches and yield with geoarrow metadata
    for idx, batch in enumerate(batches):
        # if this is the first batch, and it's empty, warn of no data found
        if idx == 0 and batch.num_rows == 0:
            warn(
                f"No '{overture_type}' data found for the specified bounding box: {bbox}"
            )

        # get the geometry field
        geo_fld_idx = batch.schema.get_field_index("geometry")
        geo_fld = batch.schema.field(geo_fld_idx)

        # set the geoarrow metadata on the geometry field
        geoarrow_geo_fld = geo_fld.with_metadata(
            {b"ARROW:extension:name": b"geoarrow.wkb"}
        )

        # create an updated schema with the correct metadata for the geometry field
        geoarrow_schema = batch.schema.set(geo_fld_idx, geoarrow_geo_fld)

        # replace the batch schema with the updated geoarrow schema
        batch = batch.replace_schema_metadata(geoarrow_schema.metadata)

        # yield the batch to the caller
        yield batch


def get_category_in_taxonomy(taxonomy_df: pd.DataFrame, category_code: str, taxonomy_index: int) -> str:
    """
    Get the taxonomy code at the specified index for a given category code.

    Args:
        taxonomy_df: DataFrame containing the taxonomy data.
        category_code: The category code to look up.
        taxonomy_index: The index in the taxonomy list to retrieve.
    
    Returns:
        The taxonomy code at the specified index, or None if not found.
    """
    # get the value from the dataframe
    taxonomy_res = taxonomy_df.loc[taxonomy_df['category_code'] == category_code, 'overture_taxonomy']

    # if something to work with
    if len(taxonomy_res) > 0:

        # get the list out of the result
        taxonomy_lst = taxonomy_res.iat[0]

        # pull out the code from the taxonomy at the index
        taxonomy_code = taxonomy_lst[taxonomy_index] if taxonomy_index < len(taxonomy_lst) else None

    else:
        taxonomy_code = None

    return taxonomy_code


def get_overture_taxonomy_dataframe():
    """
    Retrieve the Overture categories taxonomy as a pandas DataFrame.

    Returns:
        DataFrame containing the Overture categories taxonomy.
    """
    # Use the raw GitHub URL for the CSV file
    url = "https://raw.githubusercontent.com/OvertureMaps/schema/main/docs/schema/concepts/by-theme/places/overture_categories.csv"
    
    # Read the CSV using semicolon as delimiter
    df = pd.read_csv(url, sep=';', header=0, dtype='string')
    
    # format the column names
    df.columns = [col.strip().lower().replace(' ', '_') for col in df.columns]
    
    # Convert the 'Overture Taxonomy' column from string to actual list of strings
    df['overture_taxonomy'] = df['overture_taxonomy'].apply(lambda val: val.strip().strip('[]').split(','))
    
    # strip whitespace from each taxonomy item
    df['overture_taxonomy'] = df['overture_taxonomy'].apply(lambda lst: [item.strip() for item in lst])
    
    # get the maximum depth for category taxonomies
    df['list_length'] = df['overture_taxonomy'].str.len()
    max_lst_len = df['list_length'].max()

    # iterate into maximum depth for 
    for idx in range(max_lst_len):

        # create the name for the category
        col_nm = f'category_{idx + 1:02d}'
    
        # get the overture taxonomy value for the index corresponding to the code
        df[col_nm] = df['category_code'].apply(lambda cat_code: get_category_in_taxonomy(df, cat_code, idx))

    return df


def get_overture_taxonomy_category_field_max_lengths(df: Optional[pd.DataFrame] = None) -> dict[str, int]:
    """
    Retrieve the maximum lengths of each category field in the Overture taxonomy.

    Returns:
        Dictionary containing the maximum lengths of each category field.
    """
    # get the taxonomy dataframe if not provided
    if df is None:
        df = get_overture_taxonomy_dataframe()

    # only keep columns describing category levels
    cols = [c for c in df.columns if c.startswith('category')]

    # create dictionary to hold max lengths
    max_lengths = {}

    # iterate through the columns and get the max length
    for col in cols:
        max_len = df[col].str.len().max()
        max_lengths[col] = int(max_len) if pd.notnull(max_len) else 0

    return max_lengths
