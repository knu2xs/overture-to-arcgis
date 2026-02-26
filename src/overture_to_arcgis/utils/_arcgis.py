import json
import shutil
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Optional, Union, Generator

from arcgis.features import FeatureSet
import arcpy


from ._core import (
    get_overture_taxonomy_category_field_max_lengths,
    get_overture_taxonomy_dataframe,
    get_tmp_gdb,
    slugify,
)
from ._logging import get_logger

# configure module logging
logger = get_logger(logger_name=Path(__file__).stem, level="DEBUG", add_stream_handler=False)


def get_layers_for_unique_values(
    input_features: Union[arcpy._mp.Layer, str, Path],
    field_name: str,
    arcgis_map: Optional[arcpy._mp.Map] = None,
) -> list[arcpy._mp.Layer]:
    """
    Create layers from unique values in a specified field of the input features.

    Args:
        input_features: The input feature layer or feature class.
        field_name: The field name to get unique values from.
        arcgis_map: The ArcGIS map object to add the layers to.

    Returns:
        A list of ArcGIS layers created from the unique values.
    """
    # get unique values using a search cursor to generate value into a set
    unique_values = set(
        (val[0] for val in arcpy.da.SearchCursor(input_features, [field_name]))
    )

    # list to hydrate with created layers
    layers = []

    # iterate unique values
    for value in unique_values:
        # create layer name
        layer_name = f"{field_name}_{value}"

        # create definition query
        definition_query = (
            f"{field_name} = '{value}'"
            if isinstance(value, str)
            else f"{field_name} = {value}"
        )

        # use definition query to create layer object
        layer = arcpy.management.MakeFeatureLayer(
            in_features=input_features,
            out_layer=layer_name,
            where_clause=definition_query,
        )[0]

        # if the map is provided, add the layer to the map
        if arcgis_map:
            arcgis_map.addLayer(layer)
        layers.append(layer)

    return layers


def add_primary_name(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'primary_name' field to the input features if it does not already exist, and calculate from

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

    return


def add_trail_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'trail' boolean field to the input features if it does not already exist. These features
    are those with a class of 'track', 'path', 'footway', 'trail' or 'cycleway' field.

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

    return


def add_primary_category_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'primary_category' field to the input features if it does not already exist, and calculate from
    the 'categories' field.

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

    return


def add_alternate_category_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add an 'alternate_category' field to the input features if it does not already exist, and calculate from
    the 'categories' field.

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

    return


def add_overture_taxonomy_fields(
    features: Union[str, Path, arcpy._mp.Layer]
) -> None:
    """
    Add 'category_<n>' fields to the input features based on the Overture taxonomy based on the category provided for
    each row. The category for each row can be specified using the `single_category_field` parameter.

    !!! note
        This function attempts to read the value for the `primary` key from string JSON in the `categories` field.
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

    return


def add_website_field(features: Union[arcpy._mp.Layer, str, Path]) -> None:
    """
    Add a 'website' field to the input features if it does not already exist, and calculate from
    the 'contact_info' field.

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

    return


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

    return


def flatten_dict_to_bool_keys(dicts):
    """
    Takes a list of dictionaries and returns a flat dictionary with boolean values (1) for each populated value.
    Handles nested dictionaries and values that are strings or lists of strings.

    Example:
        [{'access_type': 'denied', 'when': {'heading': 'backward', 'mode': ['bicycle']}}]
        -> {'access_denied_when_heading_backward': 1, 'access_denied_when_mode_bicycle': 1}
    """
    # if the input is a string, attempt to parse it to a dict or list of dicts - using eval since input may not be strict JSON
    if isinstance(dicts, str):
        try:
            parsed = json.loads(dicts)
            dicts = parsed if isinstance(parsed, list) else [parsed]
        except Exception as e:
            logger.warning(f"Input string could not be parsed as JSON: {dicts}")

    # initialize result dictionary
    result = {}

    for d in dicts:
        if not isinstance(d, dict):
            continue  # Skip non-dict items

        # Check if 'access_type' is present in the dictionary
        access_type = d.get("access_type")
        if access_type:
            prefix = f"access_{access_type}"

            # If 'when' key exists, process its nested conditions
            when = d.get("when")
            if isinstance(when, dict):
                for k, v in when.items():
                    # If the value is a list, create a key for each item
                    if isinstance(v, list):
                        for item in v:
                            if item is not None:
                                key = f"{prefix}_when_{k}_{item}"
                                result[key] = 1  # Mark as true
                    # If the value is not None, create a key for the condition
                    elif v is not None:
                        key = f"{prefix}_when_{k}_{v}"
                        result[key] = 1
            # If 'when' is missing, just set the access_type key
            else:
                result[prefix] = 1

        # If 'access_type' is missing, flatten other keys for general use
        else:
            for k, v in d.items():
                # If the value is a dict, flatten its keys
                if isinstance(v, dict):
                    for subk, subv in v.items():
                        if isinstance(subv, list):
                            for item in subv:
                                if item is not None:
                                    key = f"{k}_{subk}_{item}"
                                    result[key] = 1
                        elif subv is not None:
                            key = f"{k}_{subk}_{subv}"
                            result[key] = 1
                # If the value is a list, create a key for each item
                elif isinstance(v, list):
                    for item in v:
                        if item is not None:
                            key = f"{k}_{item}"
                            result[key] = 1
                # If the value is not None, create a key for the condition
                elif v is not None:
                    key = f"{k}_{v}"
                    result[key] = 1
    return result


def get_boolean_access_restrictions(
    features: Union[str, Path, arcpy._mp.Layer],
    access_field: str = "access_restrictions",
) -> list[dict]:
    """
    Extract boolean access restrictions from the access_restrictions field of the input features.

    Args:
        features: The input feature layer or feature class.
        access_field: The name of the access restrictions field.

    Returns:
        A list of dictionaries containing the boolean access restrictions.
    """
    if not arcpy.Exists(features):
        raise ValueError("Input features do not exist.")

    access_restrictions = []
    with arcpy.da.SearchCursor(features, [access_field]) as cursor:
        for row in cursor:
            if row[0] is not None and isinstance(row[0], str):
                access_rest_dict = json.loads(row[0])
                if isinstance(access_rest_dict, list):
                    access_restrictions.append(flatten_dict_to_bool_keys(row[0]))

    return access_restrictions


def add_boolean_access_restrictions_fields(
    features: Union[str, Path, arcpy._mp.Layer],
    access_field: str = "access_restrictions",
) -> None:
    """
    Add boolean access restriction fields to the input features based on the access_restrictions field.

    Args:
        features: The input feature layer or feature class.
        access_field: The name of the access restrictions field.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # ensure the features exist
    if not arcpy.Exists(features):
        raise ValueError("Input features do not exist.")

    # first pass to collect all unique keys
    unique_keys = set()
    with arcpy.da.SearchCursor(features, [access_field]) as cursor:
        for row in cursor:
            if row[0] is not None:
                bool_dict = flatten_dict_to_bool_keys(row[0])
                unique_keys.update(bool_dict.keys())

    # create a list of fields to add
    add_fields = sorted([[slugify(key), "SHORT"] for key in unique_keys])

    # add fields to feature class
    arcpy.management.AddFields(features, add_fields)

    logger.info(
        "Added boolean access restriction fields to features: "
        + ", ".join([f[0] for f in add_fields])
    )

    # second pass to populate the fields
    field_names = [slugify(key) for key in unique_keys]

    with arcpy.da.UpdateCursor(features, [access_field] + field_names) as cursor:
        for row in cursor:
            bool_dict = {}
            if row[0] is not None:
                bool_dict = flatten_dict_to_bool_keys(row[0])
            for idx, key in enumerate(unique_keys):
                row[idx + 1] = bool_dict.get(key, 0)
            cursor.updateRow(row)

    return


def add_network_restriction_oneway_field(
    features: Union[str, Path, arcpy._mp.Layer],
    output_field: str = "network_restriction_oneway",
) -> None:
    """
    Create a one-way network restriction field based on the 'oneway' field in the input features.

    Args:
        features: The input feature layer or feature class.
        output_field: The name of the output one-way network restriction field.
    """
    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the necessary source field exists
    required_field = "access_denied_when_heading_backward"
    if required_field not in field_names:
        raise ValueError(
            f"Source field '{required_field}' does not exist in features. This is necessary to create the one-way "
            f"network restriction field."
        )

    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # check if output_field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if output_field not in field_names:
        # add output_field
        arcpy.management.AddField(
            in_table=features,
            field_name=output_field,
            field_type="SHORT",
        )

        logger.debug(f"Added '{output_field}' field to features.")

    # if the 'access_denied_when_heading_forward' field exists, convert those to backward by reversing geometries
    if "access_denied_when_heading_forward" in field_names:
        # use an update cursor to reverse geometries where access is denied when heading forward
        fwd_flds = [
            "access_denied_when_heading_forward",
            "access_denied_when_heading_backward",
            "SHAPE@",
        ]
        fwd_fltr = "access_denied_when_heading_forward = 1"
        fwd_cnt = 0
        with arcpy.da.UpdateCursor(
            features, field_names=fwd_flds, where_clause=fwd_fltr
        ) as update_cursor:
            # iterate through the rows
            for row in update_cursor:
                if row[0] == 1:
                    # reverse the geometry
                    row[2] = row[2].reverse()

                    # set access_denied_when_heading_backward to 1 and access_denied_when_heading_forward to 0
                    row[1] = 1
                    row[0] = 0

                    # update the row
                    update_cursor.updateRow(row)

                    # increment counter
                    fwd_cnt += 1

        logger.info(
            f"Reversed {fwd_cnt:,} geometries for features with access denied when heading forward."
        )

    else:
        logger.info(
            "'access_denied_when_heading_forward' field does not exist. Skipping geometry reversal step."
        )

    # calculate one-way network restriction from 'access_denied_when_heading_backward' field
    flds = ["access_denied_when_heading_backward", output_field]
    with arcpy.da.UpdateCursor(features, field_names=flds) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # if access_denied_when_heading_backward is 1, set output_field to 1, else 0
            row[1] = 1 if row[1] == 1 else 0

            # update the row
            update_cursor.updateRow(row)

    return


def split_into_subclass_features(features: Union[str, Path, arcpy._mp.Layer]) -> None:
    """
    Split features into subsegments based on the definition in the 'subclass_rules' field.

    Example:
        1. [{"value": "driveway", "between": null}] -> same geometry with 'subclass' field populated with 'driveway'
        2. [{"value": "driveway", "between": [0.772783061, 1.0]}] -> two features replacing the original one feature,
            the first subsegment from 0-77.2783061% with a null subclass and a second subsegment from 77.28% to 100% of
            geometry with 'subclass' field populated with 'driveway'
        3. [{"value": "driveway", "between": [0.0, 0.5]}, {"value": "alley", "between": [0.5, 1.0]}] -> two
            subsegments with 'subclass' field populated accordingly

    Args:
        features: The input feature layer or feature class.

    warning !!!
        This function modifies the input features in place by adding new features and deleting the original ones.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the necessary source field exists
    subclass_rules_field = "subclass_rules"
    if subclass_rules_field not in field_names:
        raise ValueError(
            f"Source field '{subclass_rules_field}' does not exist in features. This is necessary to split features "
            f"into subclasses."
        )

    # add subclass field if it does not exist
    if "subclass" not in field_names:
        arcpy.management.AddField(
            in_table=features,
            field_name="subclass",
            field_type="TEXT",
            field_length=50,
        )
        logger.debug("Added 'subclass' field to features.")

        # update field names list
        field_names = [f.name for f in arcpy.ListFields(features)]
    else:
        logger.debug("'subclass' field already exists in features.")

    # counters
    add_cnt = 0
    update_cnt = 0
    del_cnt = 0

    # delete oid tracker
    del_oid_lst = []

    # create a temporary feature class with the same schema to hold new features
    tmp_gdb = get_tmp_gdb()
    desc = arcpy.Describe(features)
    tmp_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name=f"temp_subclass_{uuid.uuid4().hex}",
        geometry_type=desc.shapeType,
        template=features,
        spatial_reference=desc.spatialReference,
    )[0]

    logger.debug(f"Created temporary feature class for subclass features: {tmp_fc}")

    # cursor field names not including the geometry column
    cursor_fields = [f for f in field_names if f != desc.shapeFieldName]

    # add geometry token to cursor field names
    cursor_fields = cursor_fields + ["SHAPE@"]

    # use an update cursor to read and update features
    with arcpy.da.UpdateCursor(features, cursor_fields) as update_cursor:
        # use an insert cursor to add new features to the temporary feature class
        with arcpy.da.InsertCursor(tmp_fc, cursor_fields) as insert_cursor:
            # iterate through the update_cursor rows
            for row in update_cursor:
                # get the subclass_rules as a raw string
                subclass_rules_str = row[cursor_fields.index(subclass_rules_field)]

                # only process if subclass_rules is valid
                if not (
                    subclass_rules_str is None
                    or not isinstance(subclass_rules_str, str)
                    or subclass_rules_str.strip() == "null"
                    or len(subclass_rules_str) == 0
                ):
                    # parse the subclass_rules string into a list of dictionaries
                    subclass_rules = json.loads(subclass_rules_str)

                    # process each subclass rule
                    for idx, rule in enumerate(subclass_rules):
                        # The geometry object for the current feature
                        geom = row[-1]

                        # Index of subclass field
                        subclass_idx = cursor_fields.index("subclass")

                        # Index of OID field
                        oid_idx = cursor_fields.index(desc.OIDFieldName)

                        # Extract the subclass value and the segment range (between)
                        value = rule.get("value")
                        between = rule.get("between")

                        if between is None:
                            # If 'between' is None, update the current row to set the subclass for the entire geometry
                            row[subclass_idx] = value
                            update_cursor.updateRow(row)
                            logger.debug(
                                f"Updated feature with OID {row[0]} to have subclass '{value}' for entire geometry."
                            )
                            update_cnt += 1
                        else:
                            # If this is the first rule and the segment does not start at 0, retain the original row for the initial segment
                            if idx == 0 and between[0] > 0:
                                new_row = list(row)  # Copy the original row

                                # Create a geometry subsegment from 0 to the start of 'between'
                                new_row[-1] = geom.segmentAlongLine(
                                    0.0, between[0] * geom.length
                                )
                                insert_cursor.insertRow(new_row)
                                logger.debug(
                                    f"Inserted new feature with no subclass from 0.0000 to {between[0]:.4f} fraction of geometry."
                                )
                                add_cnt += 1

                            # For the current rule, create a new row for the specified subclass and segment
                            new_row = list(row)
                            new_row[subclass_idx] = value  # Set the subclass value
                            (
                                start_frac,
                                end_frac,
                            ) = between  # Segment start and end fractions

                            # Create a geometry subsegment for the specified range
                            new_row[-1] = geom.segmentAlongLine(
                                start_frac * geom.length, end_frac * geom.length
                            )
                            insert_cursor.insertRow(new_row)
                            logger.debug(
                                f"Inserted new feature with subclass '{value}' from {start_frac:.4f} to {end_frac:.4f} fraction of geometry."
                            )
                            add_cnt += 1

                            # Mark the original feature for deletion after splitting
                            del_oid_lst.append(row[oid_idx])

    # append the new features from the temporary feature class to the original features
    arcpy.management.Append(
        inputs=tmp_fc,
        target=features,
        schema_type="NO_TEST",
    )

    logger.debug("Appended new subclass features to original features.")

    # delete the split features - deleting after appending new features to avoid data loss
    with arcpy.da.UpdateCursor(features, "OID@") as drop_cursor:
        for row in drop_cursor:
            if row[0] in del_oid_lst:
                drop_cursor.deleteRow()

    logger.debug("Appended new subclass features to original features.")

    # delete the temporary file geodatabase
    shutil.rmtree(tmp_gdb, ignore_errors=True)

    logger.debug("Deleted temporary file geodatabase.")

    # log the final counts
    logger.info(
        f"Added {add_cnt:,} new subclass features, updated {update_cnt:,} existing features, and deleted "
        f"{len(del_oid_lst):,} original features."
    )

    return


def remove_rail_features(features: Union[str, Path, arcpy._mp.Layer]) -> None:
    """
    Remove rail features from the input features based on the 'subtype' field.

    Args:
        features: The input feature layer or feature class.
    """
    subtype_field = "subtype"

    # if features is path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # ensure subtype field is in schema
    if subtype_field not in [f.name for f in arcpy.ListFields(features)]:
        raise ValueError(
            f"Field '{subtype_field}' does not exist in features. Cannot remove rail features."
        )

    # counter for deleted features
    del_cnt = 0

    # use an update cursor to delete rail features
    with arcpy.da.UpdateCursor(features, ["subtype"]) as update_cursor:
        # iterate through the rows
        for row in update_cursor:
            # check if subtype is 'rail'
            subtype = row[0]
            if (
                subtype is not None
                and isinstance(subtype, str)
                and subtype.lower() == "rail"
            ):
                # delete the row
                update_cursor.deleteRow()
                del_cnt += 1

    logger.info(f"Deleted {del_cnt:,} rail features.")

    return


def get_featureset_from_features(
    features: Union[str, Path, arcpy._mp.Layer]
) -> FeatureSet:
    """
    Convert an ArcPy feature layer or feature class to an ArcGIS FeatureSet.
    Args:
        features: The input feature layer or feature class.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # create an arcpy FeatureSet and load the features into it
    arcpy_fs = arcpy.FeatureSet()
    arcpy_fs.load(features)

    # convert the features to an arcgis FeatureSet using EsriJSON
    fs = FeatureSet.from_json(arcpy_fs.JSON)

    return fs


def get_featureset_batches(
    features: Union[str, Path, arcpy._mp.Layer],
    batch_size: int = 1000,
) -> Generator[FeatureSet, None, None]:
    """
    Split an ArcPy feature layer or feature class into batches of ArcGIS FeatureSets.

    Args:
        features: The input feature layer or feature class.
        batch_size: The number of features per batch.
    Yields:
        Generator of ArcGIS FeatureSets.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # get the total number of features
    total_features = int(arcpy.management.GetCount(features)[0])

    # get the OID field name
    oid_field_name = arcpy.Describe(features).OIDFieldName

    # get a list of all OIDs
    oid_lst = [row[0] for row in arcpy.da.SearchCursor(features, oid_field_name)]

    # iterate through the features in batches
    for start_idx in range(0, total_features, batch_size):
        # get the end index taking into consideration the total feature count
        end_idx = min(start_idx + batch_size, total_features)

        # build a where clause to select the subset features
        object_ids_to_keep = oid_lst[start_idx:end_idx]

        # build sql to select features in the batch by the OIDs
        where_clause = f"{oid_field_name} IN ({','.join(map(str, object_ids_to_keep))})"

        # create a new arcpy FeatureSet for the batch
        batch_arcpy_fs = arcpy.FeatureSet(features, where_clause)

        # convert the batch to an arcgis FeatureSet using EsriJSON
        batch_fs = FeatureSet.from_json(batch_arcpy_fs.JSON)

        yield batch_fs