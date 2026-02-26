"""ArcGIS feature-level operations for Overture Maps data.

Functions for creating layers from unique values, splitting features into
subclass segments, removing rail features, and converting feature classes
to ArcGIS FeatureSets (including batched conversion).
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional, Union, Generator

from arcgis.features import FeatureSet
import arcpy

from ._core import get_tmp_gdb
from ._logging import get_logger

# configure module logging
logger = get_logger(
    logger_name=Path(__file__).stem, level="DEBUG", add_stream_handler=False
)


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


def split_into_subclass_features(
    features: Union[str, Path, arcpy._mp.Layer],
    output_features: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """
    Split features into subsegments based on the definition in the 'subclass_rules' field.

    When ``output_features`` is provided the input data is first copied to the
    specified location and the split is performed on the copy.  If the process
    fails, the newly created output dataset is deleted so the caller never sees
    a half-processed result.

    ``` python
    # Example subclass_rules values:
    # 1. [{"value": "driveway", "between": null}]
    #    -> same geometry with 'subclass' field populated with 'driveway'
    # 2. [{"value": "driveway", "between": [0.772783061, 1.0]}]
    #    -> two features: 0-77.28% with null subclass, 77.28-100% with 'driveway'
    # 3. [{"value": "driveway", "between": [0.0, 0.5]}, {"value": "alley", "between": [0.5, 1.0]}]
    #    -> two subsegments with 'subclass' field populated accordingly
    ```

    Args:
        features: The input feature layer or feature class.
        output_features: Optional path to an output feature class.  When
            supplied, the input features are copied here before splitting
            and the original data is left untouched.

    Returns:
        The path to the output feature class when ``output_features`` is
        provided, otherwise ``None`` (in-place modification).

    Raises:
        ValueError: If the required ``subclass_rules`` field is missing.

    !!! warning
        When ``output_features`` is *not* provided this function modifies
        the input features in place by adding new features and deleting the
        original ones.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # make sure features is a path string if a layer is provided - this avoids schema lock issues with AddField
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # ------------------------------------------------------------------
    # If an output location was requested, copy the features there first
    # and redirect all subsequent operations to the copy.
    # ------------------------------------------------------------------
    if output_features is not None:
        if isinstance(output_features, Path):
            output_features = str(output_features)

        logger.debug(f"Copying features to output location: {output_features}")
        arcpy.management.CopyFeatures(features, output_features)

        # from here on, operate on the copy
        features = output_features

    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the necessary source field exists
    subclass_rules_field = "subclass_rules"
    if subclass_rules_field not in field_names:
        # roll back the copy if it was created before the validation error
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.debug(
                "Rolled back output feature class after validation failure."
            )
        raise ValueError(
            f"Source field '{subclass_rules_field}' does not exist in features. This is necessary to split features "
            f"into subclasses."
        )

    try:
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

        logger.debug("Deleted original split features.")

        # delete the temporary file geodatabase
        shutil.rmtree(tmp_gdb, ignore_errors=True)

        logger.debug("Deleted temporary file geodatabase.")

        # log the final counts
        logger.info(
            f"Added {add_cnt:,} new subclass features, updated {update_cnt:,} existing features, and deleted "
            f"{len(del_oid_lst):,} original features."
        )

    except Exception:
        # if output_features was requested, roll back by deleting the copy
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.error(
                "Split failed — rolled back by deleting the output feature class."
            )
        raise

    return output_features


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


def get_featureset_from_features(
    features: Union[str, Path, arcpy._mp.Layer],
) -> FeatureSet:
    """
    Convert an ArcPy feature layer or feature class to an ArcGIS FeatureSet.

    Args:
        features: The input feature layer or feature class.

    Returns:
        ArcGIS FeatureSet loaded from the input features.
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
