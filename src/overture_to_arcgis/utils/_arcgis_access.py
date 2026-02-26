"""ArcGIS access-restriction utilities for Overture Maps transportation data.

Functions for extracting, flattening, and applying boolean access-restriction
fields and one-way network restriction fields to ArcGIS feature classes.
"""

import json
from pathlib import Path
from typing import Union

import arcpy

from ._core import slugify
from ._logging import get_logger

# configure module logging
logger = get_logger(
    logger_name=Path(__file__).stem, level="DEBUG", add_stream_handler=False
)


def flatten_dict_to_bool_keys(dicts: Union[str, list[dict]]) -> dict[str, int]:
    """
    Flatten a list of access-restriction dictionaries into boolean presence keys.

    Takes a list of dictionaries (or a JSON string representation) and returns a flat
    dictionary with integer ``1`` values for each populated nested key path.

    ``` python
    flatten_dict_to_bool_keys(
        [{'access_type': 'denied', 'when': {'heading': 'backward', 'mode': ['bicycle']}}]
    )
    # {'access_denied_when_heading_backward': 1, 'access_denied_when_mode_bicycle': 1}
    ```

    Args:
        dicts: A list of dictionaries or a JSON string to parse.

    Returns:
        Dictionary mapping flattened key paths to ``1`` for each populated value.
    """
    # if the input is a string, attempt to parse it to a dict or list of dicts
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
