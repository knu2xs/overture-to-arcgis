from importlib.util import find_spec
from pathlib import Path
import json
from typing import Optional, Union

import arcpy


from overture_to_arcgis.utils.__main__ import get_overture_taxonomy_category_field_max_lengths, get_overture_taxonomy_dataframe
from .__main__ import slugify
from ._logging import get_logger

# configure module logging
logger = get_logger(logger_name=__name__, level="DEBUG", add_stream_handler=False)


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
    # check if 'primary_name' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if "primary_name" not in field_names:
        # add 'primary_name' field
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

            # set the primary name if name_value is valid
            if (
                name_str is not None
                and isinstance(name_str, str)
                and len(name_str) > 0
                and not name_str.strip() == "None"
            ):
                # parse the name value into a dictionary
                name_dict = eval(name_str)

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
    # check if 'trail_field' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if "trail_field" not in field_names:
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
    # check if 'primary_category' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
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
    with arcpy.da.UpdateCursor(features, ["categories", "primary_category"]) as update_cursor:
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
            ):
                # parse the categories value into a dictionary
                categories_dict = eval(categories_value)

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
    # check if 'alternate_category' field exists
    field_names = [f.name for f in arcpy.ListFields(features)]
    if "alternate_category" not in field_names:
        # add 'alternate_category' field
        arcpy.management.AddField(
            in_table=features,
            field_name="alternate_category",
            field_type="TEXT",
            field_length=255,
        )

        logger.debug("Added 'alternate_category' field to features.")

    # calculate 'alternate_category' from 'categories' field
    with arcpy.da.UpdateCursor(features, ["categories", "alternate_category"]) as update_cursor:
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
            ):
                # parse the categories value into a dictionary
                categories_dict = eval(categories_value)

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


def add_overture_taxonomy_fields(features: Union[str, Path, arcpy._mp.Layer], single_category_field: Optional[str] = None) -> None:
    """
    Add 'category_<n>' fields to the input features based on the Overture taxonomy based on the category provided for each row.
    The category for each row can be specified using the `single_category_field` parameter.

    !!! note
        If a single category field is not provided, the function will attempt to read the value for the `primary` key from 
        string JSON in the `categories` field, if this field exists.

    Args:
        features: The input feature layer or feature class.
        single_category_field: The field name containing a single category.
    """
    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # if single category not provided, attempt to use the 'categories' field to extract the primary category
    if single_category_field is None:

        # ensure the 'categories' field exists
        if "categories" not in field_names:
            raise ValueError("Field for category extraction, 'categories', does not exist in features.")
        
        # create a generator to extract categories from the 'categories' field
        categories_gen = (
            eval(row[0]).get("primary")
            for row in arcpy.da.SearchCursor(features, ["categories"])
        )

        # root name for the taxonomy fields
        root_name = "primary_category"

    # if single category field is provided
    else:

        # ensure the single category field exists
        if single_category_field not in field_names:
            raise ValueError(f"Provided single category field '{single_category_field}' does not exist in features.")
        
        # create a generator to extract categories from the single category field
        categories_gen = (
            row[0]
            for row in arcpy.da.SearchCursor(features, [single_category_field])
        )

        # root name for the taxonomy fields
        root_name = slugify(single_category_field)

    # get taxonomy dataframe
    taxonomy_df = get_overture_taxonomy_dataframe()

    # get the max lengths for each category field
    max_lengths = get_overture_taxonomy_category_field_max_lengths(taxonomy_df)

    # set the index to category_code for easier lookup
    taxonomy_df.set_index("category_code", inplace=True)

    # only keep the category columns in the taxonomy dataframe
    taxonomy_df = taxonomy_df.loc[:,[col for col in taxonomy_df.columns if col.startswith("category_")]]

    # replace category in the field names with the root name
    taxonomy_df.columns = [col.replace("category_", f"{root_name}_") for col in taxonomy_df.columns]
    max_lengths = {col.replace("category_", f"{root_name}_"): max_len for col, max_len in max_lengths.items()}
    
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

    # calculate the category code fields from the categories generator
    with arcpy.da.UpdateCursor(features, list(max_lengths.keys())) as update_cursor:
        # iterate through the rows and categories
        for row, category in zip(update_cursor, categories_gen):

            # set the category fields if category is valid
            if (
                category is not None
                and isinstance(category, str)
                and len(category) > 0
                and not category.strip() == "None"
            ):
                # get the taxonomy row for the category
                taxonomy_row = taxonomy_df.loc[category]

                # if a taxonomy row is found, set the category fields
                if not taxonomy_row.empty:
                    
                    # iterate through the category fields and set their values
                    for idx, col in enumerate(max_lengths.keys()):
                        row[idx] = taxonomy_row.loc[col]

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
            ):
                # parse the website value into a list
                website_lst = eval(website_value)

                # extract the first website from the list
                if isinstance(website_lst, list) and len(website_lst) > 0:
                    website = website_lst[0]

                    # only use the website if it is less than 255 characters
                    if isinstance(website, str) and website.lower().strip() != "none" and 0 < len(website) <= 255:
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
        raise ImportError("The 'h3' library is not installed. Please install it to use this function.")

    import h3
    
    # validate resolution
    if not isinstance(resolution, int) or not (0 <= resolution <= 15):
        raise ValueError("Invalid H3 resolution. Please choose a resolution between 0 and 15.")

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
    with arcpy.da.UpdateCursor(features, ['SHAPE@XY', h3_field]) as update_cursor:
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
            continue
        # Start with the access_type value
        access_type = d.get('access_type')
        if access_type:
            prefix = f"access_{access_type}"

            # If 'when' exists, process its keys
            when = d.get('when')
            if isinstance(when, dict):
                for k, v in when.items():
                    if isinstance(v, list):
                        for item in v:
                            if item is not None:
                                key = f"{prefix}_when_{k}_{item}"
                                result[key] = 1
                    elif v is not None:
                        key = f"{prefix}_when_{k}_{v}"
                        result[key] = 1
            # If no 'when', just set the access_type key
            else:
                result[prefix] = 1
        # If no access_type, flatten other keys as fallback (legacy)
        else:
            for k, v in d.items():
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
                elif isinstance(v, list):
                    for item in v:
                        if item is not None:
                            key = f"{k}_{item}"
                            result[key] = 1
                elif v is not None:
                    key = f"{k}_{v}"
                    result[key] = 1
    return result


def get_boolean_access_restrictions(features: Union[str, Path, arcpy._mp.Layer], access_field: str = "access_restrictions") -> list[dict]:
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
                access_rest_dict = eval(row[0])
                if isinstance(access_rest_dict, list):
                    access_restrictions.append(flatten_dict_to_bool_keys(row[0]))

    return access_restrictions


def add_boolean_access_restrictions_fields(features: Union[str, Path, arcpy._mp.Layer], access_field: str = "access_restrictions") -> None:
    """
    Add boolean access restriction fields to the input features based on the access_restrictions field.

    Args:
        features: The input feature layer or feature class.
        access_field: The name of the access restrictions field.
    """
    # if features is a path, convert to string
    if isinstance(features, Path):
        features = str(features)

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
    add_fields = sorted([
        [slugify(key), "SHORT"] for key in unique_keys
    ])

    # add fields to feature class
    arcpy.management.AddFields(features, add_fields)

    logger.info('Added boolean access restriction fields to features: ' + ', '.join([f[0] for f in add_fields]))

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

