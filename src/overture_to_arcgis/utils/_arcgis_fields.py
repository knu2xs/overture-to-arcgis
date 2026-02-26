"""ArcGIS field enrichment utilities for Overture Maps data.

Functions for adding and populating attribute fields (names, categories,
taxonomy codes, websites, H3 indices, and trail flags) on ArcGIS feature classes
derived from Overture Maps data.
"""

import json
from importlib.util import find_spec
from pathlib import Path
from typing import Optional, Union

import arcpy

from ._core import (
    get_overture_taxonomy_category_field_max_lengths,
    get_overture_taxonomy_dataframe,
)
from ._logging import get_logger

# configure module logging
logger = get_logger(
    logger_name=Path(__file__).stem, level="DEBUG", add_stream_handler=False
)


def add_primary_name(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'primary_name' field to the input features and populate it from the 'names' column.

    Parses the JSON-encoded 'names' field and extracts the first common name entry to
    populate a new 'primary_name' text field.

    Args:
        features: The input feature layer or feature class.
    """
    # Ensure features is a string path if it's a Path or Layer
    if isinstance(features, Path):
        features = str(features)
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # get existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure source field 'names' exists
    if "names" not in field_names:
        raise ValueError("Source field 'names' does not exist in features.")

    # check if 'primary_name' field exists
    if "primary_name" not in field_names:
        arcpy.management.AddField(
            in_table=features,
            field_name="primary_name",
            field_type="TEXT",
            field_length=255,
        )

        logger.debug("Added 'primary_name' field to features.")

    # calculate 'primary_name' from 'name' field
    with arcpy.da.UpdateCursor(features, ["names", "primary_name"]) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the name value and extract primary name
            name_str = row[0]

            # set the primary name if name_value is populated
            if (
                name_str is not None
                and isinstance(name_str, str)
                and len(name_str) > 0
                and not name_str.strip() == "None"
                and not name_str.strip().lower() == "null"
            ):
                # parse the name value into a dictionary
                name_dict = json.loads(name_str)

                # extract the primary name
                primary_name = name_dict.get("primary")

                # set the primary name in the row
                row[1] = primary_name

                # update the row
                update_cursor.updateRow(row)

                logger.debug(f"Set 'primary_name' to '{primary_name}' for feature.")


def add_trail_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'trail' boolean field to the input features if it does not already exist.

    Features with a class of 'track', 'path', 'footway', 'trail' or 'cycleway' are
    flagged with a value of ``1``.

    Args:
        features: The input feature layer or feature class.
    """
    # Ensure features is a string path if it's a Path or Layer
    if isinstance(features, Path):
        features = str(features)
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # get all field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure source field 'class' exists
    if "class" not in field_names:
        raise ValueError("Source field 'class' does not exist in features.")

    # check if 'trail_field' field exists
    if "trail" not in field_names:
        # add 'trail_field' field
        arcpy.management.AddField(
            in_table=features,
            field_name="trail",
            field_type="SHORT",
        )

        logger.debug("Added 'trail_field' field to features.")

    # list of classes to search for
    trail_classes = ["track", "path", "footway", "trail", "cycleway"]

    # calculate 'trail_field' from 'attributes' field
    with arcpy.da.UpdateCursor(features, ["class", "trail"]) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the attributes value and extract trail field
            class_value = row[0]

            # set the trail field if class_value is one of trail classes
            if class_value in trail_classes:
                # set the trail field in the row
                row[1] = 1

                # update the row
                update_cursor.updateRow(row)


def add_primary_category_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'primary_category' field to the input features and populate it from the 'categories' field.

    Args:
        features: The input feature layer or feature class.
    """
    # Ensure features is a string path if it's a Path or Layer
    if isinstance(features, Path):
        features = str(features)
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # get existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure source field 'categories' exists
    if "categories" not in field_names:
        raise ValueError("Source field 'categories' does not exist in features.")

    # check if 'primary_category' field exists
    if "primary_category" not in field_names:
        # add 'primary_category' field
        arcpy.management.AddField(
            in_table=features,
            field_name="primary_category",
            field_type="TEXT",
            field_length=255,
        )

        logger.debug("Added 'primary_category' field to features.")

    # calculate 'primary_category' from 'categories' field
    with arcpy.da.UpdateCursor(
        features, ["categories", "primary_category"]
    ) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the categories value and extract primary category
            categories_value = row[0]

            # set the primary category if categories_value is valid
            if (
                categories_value is not None
                and isinstance(categories_value, str)
                and len(categories_value) > 0
                and not categories_value.strip() == "None"
                and not categories_value.strip().lower() == "null"
            ):
                # parse the categories value into a dictionary
                categories_dict = json.loads(categories_value)

                # extract the primary category
                primary_category = categories_dict.get("primary")

                # ensure the primary category is not some variation of None
                if primary_category in [None, "None", "none", ""]:
                    primary_category = None

                # set the primary category in the row
                row[1] = primary_category

                # update the row
                update_cursor.updateRow(row)


def add_alternate_category_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add an 'alternate_category' field to the input features and populate it from the 'categories' field.

    Args:
        features: The input feature layer or feature class.
    """
    # Ensure features is a string path if it's a Path or Layer
    if isinstance(features, Path):
        features = str(features)
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # check if 'alternate_category' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]

    # add 'alternate_category' field
    if "alternate_category" not in field_names:
        arcpy.management.AddField(
            in_table=features,
            field_name="alternate_category",
            field_type="TEXT",
            field_length=255,
        )
        logger.debug("Added 'alternate_category' field to features.")

    # calculate 'alternate_category' from 'categories' field
    with arcpy.da.UpdateCursor(
        features, ["categories", "alternate_category"]
    ) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the categories value and extract alternate category
            categories_value = row[0]

            # set the alternate category if categories_value is valid
            if (
                categories_value is not None
                and isinstance(categories_value, str)
                and len(categories_value) > 0
                and not categories_value.strip() == "None"
                and not categories_value.strip().lower() == "null"
            ):
                # parse the categories value into a dictionary
                categories_dict = json.loads(categories_value)

                # extract the alternate category
                alternate_category = categories_dict.get("alternate")

                # convert to string if it is a list
                if isinstance(alternate_category, list):
                    alternate_category = ", ".join(alternate_category)

                # ensure the alternate category is not some variation of None
                if alternate_category in [None, "None", "none", ""]:
                    alternate_category = None

                # set the alternate category in the row
                row[1] = alternate_category

                # update the row
                update_cursor.updateRow(row)


def add_overture_taxonomy_fields(
    features: Union[str, Path, arcpy._mp.Layer],
) -> None:
    """
    Add 'category_<n>' fields to the input features based on the Overture taxonomy.

    The category for each row is read from the ``primary`` key in the JSON-encoded
    ``categories`` field.

    !!! note
        This function attempts to read the value for the ``primary`` key from string JSON in the ``categories`` field.
        If this field does not exist, this will raise an error.

    Args:
        features: The input feature layer or feature class.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # describe the features and ensure it is point geometry
    desc = arcpy.Describe(features)
    if desc.shapeType not in ["Point", "Multipoint"]:
        raise ValueError(
            "Input features must be of point geometry type to add Overture taxonomy fields."
        )

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the 'categories' field exists
    if "categories" not in field_names:
        raise ValueError(
            "Field for category extraction, 'categories', does not exist in features."
        )

    # create a generator to extract categories from the 'categories' field
    categories_gen = (
        json.loads(row[0]).get("primary")
        for row in arcpy.da.SearchCursor(features, ["categories"])
    )

    # root name for the taxonomy fields
    root_name = "primary_category"

    # get taxonomy dataframe
    taxonomy_df = get_overture_taxonomy_dataframe()

    # get the max lengths for each category field
    max_lengths = get_overture_taxonomy_category_field_max_lengths(taxonomy_df)

    # set the index to category_code for easier lookup
    taxonomy_df.set_index("category_code", inplace=True)

    # only keep the category columns in the taxonomy dataframe
    taxonomy_df = taxonomy_df.loc[
        :, [col for col in taxonomy_df.columns if col.startswith("category_")]
    ]

    # replace category in the field names with the root name
    taxonomy_df.columns = [
        col.replace("category_", f"{root_name}_") for col in taxonomy_df.columns
    ]
    max_lengths = {
        col.replace("category_", f"{root_name}_"): max_len
        for col, max_len in max_lengths.items()
    }

    # iterate through the maximum lengths and add fields to the features
    for col, max_len in max_lengths.items():
        # add the field to the features
        arcpy.management.AddField(
            in_table=features,
            field_name=col,
            field_type="TEXT",
            field_length=max_len,
        )

        logger.info(f"Added field '{col}' with length {max_len} to features.")

    # get the intersection of rows and taxonomy columns
    col_lst = [col for col in max_lengths.keys() if col in taxonomy_df.columns]

    # add the primary category column to the list
    col_lst.insert(0, f"{root_name}_code")

    # calculate the category code fields from the categories generator
    with arcpy.da.UpdateCursor(features, col_lst) as update_cursor:
        # iterate through the rows and categories
        for row, category in zip(update_cursor, categories_gen):
            # set the category fields if category is valid
            if (
                category is not None
                and isinstance(category, str)
                and len(category) > 0
                and not category.strip() == "None"
                and not category.strip().lower() == "null"
            ):
                # get the taxonomy row for the category
                taxonomy_row = taxonomy_df.loc[category]

                # if a taxonomy row is found, set the category fields
                if not taxonomy_row.empty:

                    # hydrate the first column with the category code
                    row[0] = taxonomy_row.name

                    # populate the rest of the values with values from the taxonomy row
                    for idx, col in enumerate(col_lst[1:]):
                        row[idx + 1] = taxonomy_row.loc[col]

                    # update the row
                    update_cursor.updateRow(row)


def add_website_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'website' field to the input features and populate it from the 'contact_info' field.

    Args:
        features: The input feature layer or feature class.
    """
    # Ensure features is a string path if it's a Path or Layer
    if isinstance(features, Path):
        features = str(features)
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # check if 'website' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if "website" not in field_names:
        # add 'website' field
        arcpy.management.AddField(
            in_table=features,
            field_name="website",
            field_type="TEXT",
            field_length=255,
        )

        logger.debug("Added 'website' field to features.")

    # calculate 'website' from 'websites' field
    with arcpy.da.UpdateCursor(features, ["websites", "website"]) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the websites value and extract website
            website_value = row[0]

            # set the website if website_value is valid
            if (
                website_value is not None
                and isinstance(website_value, str)
                and len(website_value) > 0
                and not website_value.strip() == "None"
                and not website_value.strip().lower() == "null"
            ):
                # parse the website value into a list
                website_lst = json.loads(website_value)

                # extract the first website from the list
                if isinstance(website_lst, list) and len(website_lst) > 0:
                    website = website_lst[0]

                    # only use the website if it is less than 255 characters
                    if (
                        isinstance(website, str)
                        and website.lower().strip() != "none"
                        and 0 < len(website) <= 255
                    ):
                        row[1] = website

                        # update the row
                        update_cursor.updateRow(row)

                    else:
                        logger.warning(
                            f"Website exceeds 255 characters and will not be set for the feature: '{website}'"
                        )


def add_h3_indices(
    features: Union[str, Path, arcpy._mp.Layer],
    resolution: int = 9,
    h3_field: Optional[str] = None,
) -> None:
    """
    Add an H3 index field to the input features based on their geometry.

    Args:
        features: The input feature layer or feature class.
        resolution: The H3 resolution to use for indexing.
        h3_field: The name of the H3 index field to add.
    """
    if find_spec("h3") is None:
        raise ImportError(
            "The 'h3' library is not installed. Please install it to use this function."
        )

    import h3

    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # validate resolution
    if not isinstance(resolution, int) or not (0 <= resolution <= 15):
        raise ValueError(
            "Invalid H3 resolution. Please choose a resolution between 0 and 15."
        )

    # if h3_field is None, set to default
    if h3_field is None:
        h3_field = f"h3_{resolution:02d}"

    # check if h3_field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if h3_field not in field_names:
        # add h3_field
        arcpy.management.AddField(
            in_table=features,
            field_name=h3_field,
            field_type="TEXT",
            field_length=20,
        )

        logger.debug(f"Added '{h3_field}' field to features.")

    # calculate H3 indices from geometry
    with arcpy.da.UpdateCursor(features, ["SHAPE@XY", h3_field]) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # get the geometry coordinates
            x, y = row[0]

            # get the H3 index for the centroid
            h3_index = h3.latlng_to_cell(y, x, resolution)

            # set the H3 index in the row
            row[1] = h3_index

            # update the row
            update_cursor.updateRow(row)
