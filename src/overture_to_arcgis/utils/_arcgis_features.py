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


def _chain_sub_segments(
    members: list[tuple[int, object]],
) -> list[tuple[int, object]]:
    """
    Chain polyline sub-segments into spatial order by matching endpoints.

    Given a collection of polyline sub-segments that were split from a
    single original segment, return them sorted in the order they appear
    along the original line.  Segments are linked by matching the end
    point of one segment to the start point of the next.

    Args:
        members: A list of `(OID, geometry)` tuples to chain.

    Returns:
        The input tuples reordered so that each segment's end point
        matches the next segment's start point.
    """
    # discard members with null geometry so chaining logic is safe
    members = [(oid, geom) for oid, geom in members if geom is not None]

    if len(members) <= 1:
        return members

    def _pt_key(point: object) -> tuple[float, float]:
        return (round(point.X, 8), round(point.Y, 8))

    # map each end-point to its index for quick lookup
    end_to_idx: dict[tuple[float, float], int] = {}
    for i, (_, geom) in enumerate(members):
        end_to_idx[_pt_key(geom.lastPoint)] = i

    # the first segment is the one whose start point is not any other's end point
    first_idx = 0
    for i, (_, geom) in enumerate(members):
        if _pt_key(geom.firstPoint) not in end_to_idx:
            first_idx = i
            break

    # build start-point -> index mapping
    start_to_idx: dict[tuple[float, float], int] = {}
    for i, (_, geom) in enumerate(members):
        start_to_idx[_pt_key(geom.firstPoint)] = i

    # walk the chain
    chain = [members[first_idx]]
    used: set[int] = {first_idx}
    while len(chain) < len(members):
        last_end = _pt_key(chain[-1][1].lastPoint)
        next_idx = start_to_idx.get(last_end)
        if next_idx is not None and next_idx not in used:
            chain.append(members[next_idx])
            used.add(next_idx)
        else:
            # cannot continue chaining — append remaining in original order
            for i, m in enumerate(members):
                if i not in used:
                    chain.append(m)
                    used.add(i)
            break

    return chain


def _build_segment_map(
    between_rules: list[dict],
) -> list[tuple[float, float, Optional[str]]]:
    """
    Build a segment map covering `[0.0, 1.0]` from sorted subclass rules.

    Gaps between rules and leading/trailing gaps are filled with
    `(start, end, None)` entries so the returned list forms a
    contiguous partition of `[0.0, 1.0]`.

    Args:
        between_rules: Subclass rules **already sorted** by start
            fraction.  Each dict must have `"value"` and `"between"`
            keys.

    Returns:
        A list of `(start_frac, end_frac, value)` tuples covering
        the full `[0.0, 1.0]` range.
    """
    segments: list[tuple[float, float, Optional[str]]] = []
    prev_end = 0.0
    for rule in between_rules:
        start, end = rule["between"]
        value = rule.get("value")
        if start > prev_end:
            segments.append((prev_end, start, None))
        segments.append((start, end, value))
        prev_end = end
    if prev_end < 1.0:
        segments.append((prev_end, 1.0, None))
    return segments


def _get_overlapping_pieces(
    segment_map: list[tuple[float, float, Optional[str]]],
    feat_start: float,
    feat_end: float,
    tolerance: float = 1e-9,
) -> list[tuple[float, float, Optional[str]]]:
    """
    Return portions of *segment_map* overlapping `[feat_start, feat_end]`.

    Each returned tuple is clamped to the feature's range.  Overlaps
    smaller than *tolerance* are discarded to avoid negligible sliver
    segments caused by floating-point imprecision.

    Args:
        segment_map: Full `[0.0, 1.0]` segment map produced by
            [_build_segment_map][].
        feat_start: Start fraction of the feature within the original
            segment.
        feat_end: End fraction of the feature within the original
            segment.
        tolerance: Minimum overlap width to keep.

    Returns:
        A list of `(clamped_start, clamped_end, value)` tuples.
    """
    pieces: list[tuple[float, float, Optional[str]]] = []
    for seg_start, seg_end, value in segment_map:
        overlap_start = max(seg_start, feat_start)
        overlap_end = min(seg_end, feat_end)
        if overlap_end - overlap_start > tolerance:
            pieces.append((overlap_start, overlap_end, value))
    return pieces


def split_into_subclass_features(
    features: Union[str, Path, arcpy._mp.Layer],
    output_features: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """
    Split features into subsegments based on the definition in the `subclass_rules` field.

    When `output_features` is provided the input data is first copied to the
    specified location and the split is performed on the copy.  If the process
    fails, the newly created output dataset is deleted so the caller never sees
    a half-processed result.

    !!! note
        Any gaps between rules (leading, interior, or trailing) are filled
        with segments that retain the original feature's properties but have
        a `None` subsegment value.

    !!! note
        When features share the same `id` value (e.g. after being split
        by [split_segments_at_connectors][]), the `between`
        fractions are evaluated relative to the combined original
        geometry rather than each individual sub-segment.

    !!! warning
        When `output_features` is *not* provided this function modifies
        the input features in place by adding new features and deleting the
        original ones.

    ``` python
    # Example subclass_rules values:
    # 1. [{"value": "driveway", "between": null}]
    #    -> same geometry with 'subsegment' field populated with 'driveway'
    # 2. [{"value": "driveway", "between": [0.772783061, 1.0]}]
    #    -> two features: 0-77.28% with null subsegment, 77.28-100% with 'driveway'
    # 3. [{"value": "driveway", "between": [0.0, 0.5]}, {"value": "alley", "between": [0.5, 1.0]}]
    #    -> two subsegments with 'subsegment' field populated accordingly
    # 4. [{"value": "driveway", "between": [0.0, 0.3]}, {"value": "alley", "between": [0.6, 1.0]}]
    #    -> three features: 0-30% 'driveway', 30-60% gap (original properties, no subsegment),
    #       60-100% 'alley'
    # 5. [{"value": "driveway", "between": [0.0, 0.5]}]
    #    -> two features: 0-50% 'driveway', 50-100% trailing gap (original properties,
    #       no subsegment)
    ```

    Args:
        features: The input feature layer or feature class.
        output_features: Optional path to an output feature class.  When
            supplied, the input features are copied here before splitting
            and the original data is left untouched.

    Returns:
        The path to the output feature class when `output_features` is
        provided, otherwise `None` (in-place modification).

    Raises:
        ValueError: If the required `subclass_rules` field is missing.
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

    # log the initial feature count
    initial_count = int(arcpy.management.GetCount(features)[0])
    logger.info(f"Starting split_into_subclass_features with {initial_count:,} features.")

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
        # add subsegment field if it does not already exist
        if "subsegment" not in field_names:
            arcpy.management.AddField(
                in_table=features,
                field_name="subsegment",
                field_type="TEXT",
                field_length=50,
            )
            logger.debug("Added 'subsegment' field to features.")

            # update field names list
            field_names = [f.name for f in arcpy.ListFields(features)]
        else:
            logger.debug("'subsegment' field already exists in features.")

        # describe once for OID/shape metadata
        desc = arcpy.Describe(features)

        # ------------------------------------------------------------------
        # Pre-compute fraction ranges for features that may share an 'id'
        # (e.g. after split_segments_at_connectors).  For each feature we
        # store (group_start_frac, group_end_frac) representing where that
        # feature sits within the combined original segment.
        # ------------------------------------------------------------------
        id_field = "id"
        has_id_field = id_field in field_names
        oid_frac_map: dict[int, tuple[float, float]] = {}

        if has_id_field:
            id_groups: dict[object, list[tuple[int, object]]] = {}
            with arcpy.da.SearchCursor(
                features, [desc.OIDFieldName, id_field, "SHAPE@"]
            ) as sc:
                for oid, fid, geom in sc:
                    if fid is not None:
                        if geom is not None:
                            id_groups.setdefault(fid, []).append(
                                (oid, geom)
                            )
                        else:
                            logger.debug(
                                "Skipping OID %s with null geometry "
                                "(id=%s).",
                                oid,
                                fid,
                            )
                            oid_frac_map[oid] = (0.0, 1.0)
                    else:
                        oid_frac_map[oid] = (0.0, 1.0)

            for fid, members in id_groups.items():
                if len(members) == 1:
                    oid_frac_map[members[0][0]] = (0.0, 1.0)
                else:
                    chained = _chain_sub_segments(members)
                    total_length = sum(
                        g.length for _, g in chained if g is not None
                    )
                    if total_length == 0:
                        for oid, _ in chained:
                            oid_frac_map[oid] = (0.0, 1.0)
                        continue
                    cum = 0.0
                    for oid, geom in chained:
                        start_f = cum / total_length
                        cum += geom.length
                        end_f = cum / total_length
                        oid_frac_map[oid] = (start_f, end_f)

            logger.debug(
                f"Pre-computed fraction ranges for {len(oid_frac_map):,} features "
                f"across {len(id_groups):,} id groups."
            )
        else:
            logger.debug(
                "No 'id' field found — treating each feature as an independent segment."
            )

        # counters
        add_cnt = 0
        update_cnt = 0
        del_cnt = 0

        # delete oid tracker — use a set for O(1) membership checks during deletion
        del_oid_set: set[int] = set()

        # create a temporary feature class with the same schema to hold new features
        tmp_gdb = get_tmp_gdb()
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

                        # common indices resolved once per feature
                        geom = row[-1]
                        subclass_idx = cursor_fields.index("subsegment")
                        oid_idx = cursor_fields.index(desc.OIDFieldName)

                        # sort rules by start fraction so gaps can be detected in order
                        between_rules = [
                            r for r in subclass_rules if r.get("between") is not None
                        ]
                        no_between_rules = [
                            r for r in subclass_rules if r.get("between") is None
                        ]

                        # handle rules without a 'between' range (whole-geometry assignment)
                        for rule in no_between_rules:
                            value = rule.get("value")
                            row[subclass_idx] = value
                            update_cursor.updateRow(row)
                            logger.debug(
                                f"Updated feature with OID {row[0]} to have subsegment '{value}' for entire geometry."
                            )
                            update_cnt += 1

                        # process rules that define subsegments
                        if between_rules:
                            # sort by start fraction to process in order
                            between_rules.sort(key=lambda r: r["between"][0])

                            # determine this feature's position within the
                            # original (possibly pre-split) segment
                            group_start, group_end = oid_frac_map.get(
                                row[oid_idx], (0.0, 1.0)
                            )

                            # build a full [0,1] segment map and find pieces
                            # that overlap with this feature's range
                            segment_map = _build_segment_map(between_rules)
                            pieces = _get_overlapping_pieces(
                                segment_map, group_start, group_end
                            )

                            if len(pieces) <= 1:
                                # feature falls entirely within a single
                                # segment (or gap) — update in place
                                value = pieces[0][2] if pieces else None
                                row[subclass_idx] = value
                                update_cursor.updateRow(row)
                                logger.debug(
                                    f"Updated feature OID {row[oid_idx]} with "
                                    f"subsegment '{value}' (range "
                                    f"{group_start:.4f}-{group_end:.4f})."
                                )
                                update_cnt += 1
                            else:
                                # feature spans multiple segments — split it
                                feat_range = group_end - group_start
                                for p_start, p_end, value in pieces:
                                    local_start = (
                                        (p_start - group_start) / feat_range
                                    )
                                    local_end = (
                                        (p_end - group_start) / feat_range
                                    )
                                    new_row = list(row)
                                    new_row[subclass_idx] = value
                                    new_row[-1] = geom.segmentAlongLine(
                                        local_start * geom.length,
                                        local_end * geom.length,
                                    )
                                    insert_cursor.insertRow(new_row)
                                    logger.debug(
                                        f"Inserted subsegment '{value}' "
                                        f"local {local_start:.4f}-"
                                        f"{local_end:.4f} (global "
                                        f"{p_start:.4f}-{p_end:.4f}) for "
                                        f"OID {row[oid_idx]}."
                                    )
                                    add_cnt += 1

                                # mark the original feature for deletion
                                del_oid_set.add(row[oid_idx])

        # append the new features from the temporary feature class to the original features
        arcpy.management.Append(
            inputs=tmp_fc,
            target=features,
            schema_type="NO_TEST",
        )

        logger.debug("Appended new subsegment features to original features.")

        # delete the split features - deleting after appending new features to avoid data loss
        with arcpy.da.UpdateCursor(features, "OID@") as drop_cursor:
            for row in drop_cursor:
                if row[0] in del_oid_set:
                    drop_cursor.deleteRow()

        logger.debug("Deleted original split features.")

        # delete the temporary file geodatabase
        shutil.rmtree(tmp_gdb, ignore_errors=True)

        logger.debug("Deleted temporary file geodatabase.")

        # log the final counts
        final_count = int(arcpy.management.GetCount(features)[0])
        logger.info(
            f"Added {add_cnt:,} new subsegment features, updated {update_cnt:,} existing features, and deleted "
            f"{len(del_oid_set):,} original features. Final feature count: {final_count:,}."
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


def split_into_level_features(
    features: Union[str, Path, arcpy._mp.Layer],
    output_features: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """
    Split features into subsegments based on the `level_rules` field and populate a `z_index` field.

    The `level_rules` field uses the same structure as `subclass_rules`:
    a JSON array of objects, each with an integer `value` (the vertical
    level / z-index) and an optional `between` pair of fractions
    `[start, end]` describing which portion of the geometry the value
    applies to.

    When `output_features` is provided the input data is first copied to
    the specified location and the split is performed on the copy.  If the
    process fails, the newly created output dataset is deleted so the
    caller never sees a half-processed result.

    !!! note
        Any gaps between rules (leading, interior, or trailing) are filled
        with segments that retain the original feature's properties but have
        a `None` z_index value.

    !!! note
        When features share the same `id` value (e.g. after being split
        by [split_segments_at_connectors][]), the `between`
        fractions are evaluated relative to the combined original
        geometry rather than each individual sub-segment.

    !!! warning
        When `output_features` is *not* provided this function modifies
        the input features in place by adding new features and deleting the
        original ones.

    ``` python
    # Example level_rules values:
    # 1. [{"value": 1, "between": null}]
    #    -> same geometry with 'z_index' field populated with 1
    # 2. [{"value": 1, "between": [0.5, 1.0]}]
    #    -> two features: 0-50% with null z_index, 50-100% with z_index=1
    # 3. [{"value": -1, "between": [0.0, 0.3]}, {"value": 1, "between": [0.7, 1.0]}]
    #    -> three features: 0-30% z_index=-1, 30-70% gap (null z_index),
    #       70-100% z_index=1
    ```

    Args:
        features: The input feature layer or feature class.
        output_features: Optional path to an output feature class.  When
            supplied, the input features are copied here before splitting
            and the original data is left untouched.

    Returns:
        The path to the output feature class when `output_features` is
        provided, otherwise `None` (in-place modification).

    Raises:
        ValueError: If the required `level_rules` field is missing.
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

    # log the initial feature count
    initial_count = int(arcpy.management.GetCount(features)[0])
    logger.info(
        f"Starting split_into_level_features with {initial_count:,} features."
    )

    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the necessary source field exists
    level_rules_field = "level_rules"
    if level_rules_field not in field_names:
        # roll back the copy if it was created before the validation error
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.debug(
                "Rolled back output feature class after validation failure."
            )
        raise ValueError(
            f"Source field '{level_rules_field}' does not exist in features. "
            f"This is necessary to split features by level."
        )

    try:
        # add z_index field if it does not already exist
        if "z_index" not in field_names:
            arcpy.management.AddField(
                in_table=features,
                field_name="z_index",
                field_type="LONG",
            )
            logger.debug("Added 'z_index' field to features.")

            # update field names list
            field_names = [f.name for f in arcpy.ListFields(features)]
        else:
            logger.debug("'z_index' field already exists in features.")

        # describe once for OID/shape metadata
        desc = arcpy.Describe(features)

        # ------------------------------------------------------------------
        # Pre-compute fraction ranges for features that may share an 'id'
        # (e.g. after split_segments_at_connectors).  For each feature we
        # store (group_start_frac, group_end_frac) representing where that
        # feature sits within the combined original segment.
        # ------------------------------------------------------------------
        id_field = "id"
        has_id_field = id_field in field_names
        oid_frac_map: dict[int, tuple[float, float]] = {}

        if has_id_field:
            id_groups: dict[object, list[tuple[int, object]]] = {}
            with arcpy.da.SearchCursor(
                features, [desc.OIDFieldName, id_field, "SHAPE@"]
            ) as sc:
                for oid, fid, geom in sc:
                    if fid is not None:
                        if geom is not None:
                            id_groups.setdefault(fid, []).append(
                                (oid, geom)
                            )
                        else:
                            logger.debug(
                                "Skipping OID %s with null geometry "
                                "(id=%s).",
                                oid,
                                fid,
                            )
                            oid_frac_map[oid] = (0.0, 1.0)
                    else:
                        oid_frac_map[oid] = (0.0, 1.0)

            for fid, members in id_groups.items():
                if len(members) == 1:
                    oid_frac_map[members[0][0]] = (0.0, 1.0)
                else:
                    chained = _chain_sub_segments(members)
                    total_length = sum(
                        g.length for _, g in chained if g is not None
                    )
                    if total_length == 0:
                        for oid, _ in chained:
                            oid_frac_map[oid] = (0.0, 1.0)
                        continue
                    cum = 0.0
                    for oid, geom in chained:
                        start_f = cum / total_length
                        cum += geom.length
                        end_f = cum / total_length
                        oid_frac_map[oid] = (start_f, end_f)

            logger.debug(
                f"Pre-computed fraction ranges for {len(oid_frac_map):,} features "
                f"across {len(id_groups):,} id groups."
            )
        else:
            logger.debug(
                "No 'id' field found — treating each feature as an independent segment."
            )

        # counters
        add_cnt = 0
        update_cnt = 0
        del_cnt = 0

        # delete oid tracker — use a set for O(1) membership checks during deletion
        del_oid_set: set[int] = set()

        # create a temporary feature class with the same schema to hold new features
        tmp_gdb = get_tmp_gdb()
        tmp_fc = arcpy.management.CreateFeatureclass(
            out_path=str(tmp_gdb),
            out_name=f"temp_level_{uuid.uuid4().hex}",
            geometry_type=desc.shapeType,
            template=features,
            spatial_reference=desc.spatialReference,
        )[0]

        logger.debug(f"Created temporary feature class for level features: {tmp_fc}")

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
                    # get the level_rules as a raw string
                    level_rules_str = row[cursor_fields.index(level_rules_field)]

                    # only process if level_rules is valid
                    if not (
                        level_rules_str is None
                        or not isinstance(level_rules_str, str)
                        or level_rules_str.strip() == "null"
                        or len(level_rules_str) == 0
                    ):
                        # parse the level_rules string into a list of dicts
                        level_rules = json.loads(level_rules_str)

                        # common indices resolved once per feature
                        geom = row[-1]
                        z_index_idx = cursor_fields.index("z_index")
                        oid_idx = cursor_fields.index(desc.OIDFieldName)

                        # sort rules by start fraction so gaps can be detected in order
                        between_rules = [
                            r for r in level_rules if r.get("between") is not None
                        ]
                        no_between_rules = [
                            r for r in level_rules if r.get("between") is None
                        ]

                        # handle rules without a 'between' range (whole-geometry assignment)
                        for rule in no_between_rules:
                            value = rule.get("value")
                            # ensure value is stored as int (or None)
                            row[z_index_idx] = (
                                int(value) if value is not None else None
                            )
                            update_cursor.updateRow(row)
                            logger.debug(
                                f"Updated feature with OID {row[0]} to have "
                                f"z_index={value} for entire geometry."
                            )
                            update_cnt += 1

                        # process rules that define subsegments
                        if between_rules:
                            # sort by start fraction to process in order
                            between_rules.sort(key=lambda r: r["between"][0])

                            # determine this feature's position within the
                            # original (possibly pre-split) segment
                            group_start, group_end = oid_frac_map.get(
                                row[oid_idx], (0.0, 1.0)
                            )

                            # build a full [0,1] segment map and find pieces
                            # that overlap with this feature's range
                            segment_map = _build_segment_map(between_rules)
                            pieces = _get_overlapping_pieces(
                                segment_map, group_start, group_end
                            )

                            if len(pieces) <= 1:
                                # feature falls entirely within a single
                                # segment (or gap) — update in place
                                value = pieces[0][2] if pieces else None
                                row[z_index_idx] = (
                                    int(value) if value is not None else None
                                )
                                update_cursor.updateRow(row)
                                logger.debug(
                                    f"Updated feature OID {row[oid_idx]} with "
                                    f"z_index={value} (range "
                                    f"{group_start:.4f}-{group_end:.4f})."
                                )
                                update_cnt += 1
                            else:
                                # feature spans multiple segments — split it
                                feat_range = group_end - group_start
                                for p_start, p_end, value in pieces:
                                    local_start = (
                                        (p_start - group_start) / feat_range
                                    )
                                    local_end = (
                                        (p_end - group_start) / feat_range
                                    )
                                    new_row = list(row)
                                    new_row[z_index_idx] = (
                                        int(value) if value is not None else None
                                    )
                                    new_row[-1] = geom.segmentAlongLine(
                                        local_start * geom.length,
                                        local_end * geom.length,
                                    )
                                    insert_cursor.insertRow(new_row)
                                    logger.debug(
                                        f"Inserted level segment z_index={value} "
                                        f"local {local_start:.4f}-"
                                        f"{local_end:.4f} (global "
                                        f"{p_start:.4f}-{p_end:.4f}) for "
                                        f"OID {row[oid_idx]}."
                                    )
                                    add_cnt += 1

                                # mark the original feature for deletion
                                del_oid_set.add(row[oid_idx])

        # append the new features from the temporary feature class to the original features
        arcpy.management.Append(
            inputs=tmp_fc,
            target=features,
            schema_type="NO_TEST",
        )

        logger.debug("Appended new level-split features to original features.")

        # delete the split features - deleting after appending new features to avoid data loss
        with arcpy.da.UpdateCursor(features, "OID@") as drop_cursor:
            for row in drop_cursor:
                if row[0] in del_oid_set:
                    drop_cursor.deleteRow()

        logger.debug("Deleted original split features.")

        # delete the temporary file geodatabase
        shutil.rmtree(tmp_gdb, ignore_errors=True)

        logger.debug("Deleted temporary file geodatabase.")

        # log the final counts
        final_count = int(arcpy.management.GetCount(features)[0])
        logger.info(
            f"Added {add_cnt:,} new level-split features, updated {update_cnt:,} "
            f"existing features, and deleted {len(del_oid_set):,} original features. "
            f"Final feature count: {final_count:,}."
        )

    except Exception:
        # if output_features was requested, roll back by deleting the copy
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.error(
                "Level split failed — rolled back by deleting the output feature class."
            )
        raise

    return output_features


def split_segments_at_connectors(
    features: Union[str, Path, arcpy._mp.Layer],
    connector_features: Union[str, Path, arcpy._mp.Layer],
    output_features: Optional[Union[str, Path]] = None,
    search_radius: str = "10 Meters",
) -> Optional[str]:
    """
    Split segment polylines at connector point geometries listed in the `connectors` field.

    For each segment, the `connectors` JSON field is parsed to obtain the
    list of `connector_id` values.  The corresponding point geometries are
    looked up from `connector_features` and their positions along the
    segment are computed using `queryPointAndDistance`.  The segment is
    then split into sub-segments between consecutive connector positions
    using `segmentAlongLine`.

    Only connector points explicitly referenced in a segment's
    `connectors` field are used to split that segment, ensuring unrelated
    nearby connectors do not interfere.

    When `output_features` is provided the input data is first copied to
    the specified location and all processing is performed on the copy.
    If the process fails, the newly created output dataset is deleted so
    the caller never sees a half-processed result.

    !!! note
        Features whose `connectors` field is *null*, empty, unparseable,
        or references fewer than three connector points (i.e. only start
        and end) are left untouched because no interior split is required.

    !!! note
        Connector points are snapped to the nearest position on the
        segment polyline.  Points farther than `search_radius` from
        any listed segment are logged as warnings and skipped.

    !!! warning
        When `output_features` is *not* provided this function modifies
        the input features in place by inserting new sub-segment features
        and deleting the originals that were split.

    ``` python
    # Example connectors values:
    # [{"connector_id": "abc", "at": 0.0}, {"connector_id": "def", "at": 1.0}]
    #    -> no split needed (start and end only)
    # [{"connector_id": "abc", "at": 0.0}, {"connector_id": "mid", "at": 0.4},
    #  {"connector_id": "def", "at": 1.0}]
    #    -> two features split at the "mid" connector point location
    ```

    Args:
        features: The input feature layer or feature class containing
            Overture segment polylines.
        connector_features: A point feature layer or feature class
            containing Overture connector geometries.  Must have an
            `id` field matching the `connector_id` values stored in
            each segment's `connectors` JSON.
        output_features: Optional path to an output feature class.  When
            supplied, the input features are copied here before splitting
            and the original data is left untouched.
        search_radius: Maximum distance a connector point may be from a
            segment to be considered valid.  Points farther away are
            skipped with a warning.  Accepts any linear unit string
            recognised by arcpy (e.g. ``"10 Meters"``).

    Returns:
        The path to the output feature class when `output_features` is
        provided, otherwise `None` (in-place modification).

    Raises:
        ValueError: If the required `connectors` field is missing from
            `features` or the required `id` field is missing from
            `connector_features`.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(features, Path):
        features = str(features)

    # resolve to catalog path when a layer is provided to avoid schema locks
    if isinstance(features, arcpy._mp.Layer):
        features = arcpy.Describe(features).catalogPath

    # normalise connector_features to a string path
    if isinstance(connector_features, Path):
        connector_features = str(connector_features)
    if isinstance(connector_features, arcpy._mp.Layer):
        connector_features = arcpy.Describe(connector_features).catalogPath

    # parse the search_radius into a linear unit value for distance comparison
    radius_parts = search_radius.strip().split()
    radius_value = float(radius_parts[0])

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

    # log the initial feature count
    initial_count = int(arcpy.management.GetCount(features)[0])
    logger.info(
        f"Starting split_segments_at_connectors with {initial_count:,} features."
    )

    # get a list of existing field names
    field_names = [f.name for f in arcpy.ListFields(features)]

    # ensure the connectors field exists
    connectors_field = "connectors"
    if connectors_field not in field_names:
        # roll back the copy if it was created before the validation error
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.debug(
                "Rolled back output feature class after validation failure."
            )
        raise ValueError(
            f"Source field '{connectors_field}' does not exist in features. "
            f"This is necessary to split segments at connector points."
        )

    # validate connector_features has an 'id' field
    conn_field_names = [f.name for f in arcpy.ListFields(connector_features)]
    if "id" not in conn_field_names:
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.debug(
                "Rolled back output feature class after connector validation failure."
            )
        raise ValueError(
            "Connector features must contain an 'id' field matching the "
            "'connector_id' values in the segment connectors JSON."
        )

    try:
        # ------------------------------------------------------------------
        # Build connector_id -> point geometry lookup dict (single pass).
        # ------------------------------------------------------------------
        connector_geom_map: dict[str, arcpy.Geometry] = {}
        with arcpy.da.SearchCursor(
            connector_features, ["id", "SHAPE@"]
        ) as conn_cursor:
            for conn_id, geom in conn_cursor:
                if conn_id is not None and geom is not None:
                    connector_geom_map[str(conn_id)] = geom

        logger.debug(
            f"Built connector geometry lookup with "
            f"{len(connector_geom_map):,} entries."
        )

        # counters
        add_cnt = 0
        del_oid_lst: list[int] = []

        # create a temporary feature class with the same schema to hold new features
        tmp_gdb = get_tmp_gdb()
        desc = arcpy.Describe(features)
        tmp_fc = arcpy.management.CreateFeatureclass(
            out_path=str(tmp_gdb),
            out_name=f"temp_connectors_{uuid.uuid4().hex}",
            geometry_type=desc.shapeType,
            template=features,
            spatial_reference=desc.spatialReference,
        )[0]

        logger.debug(
            f"Created temporary feature class for connector-split features: {tmp_fc}"
        )

        # build cursor field list (all fields except shape, plus SHAPE@ token)
        cursor_fields = [f for f in field_names if f != desc.shapeFieldName]
        cursor_fields = cursor_fields + ["SHAPE@"]

        # resolve field indices once
        connectors_idx = cursor_fields.index(connectors_field)
        oid_idx = cursor_fields.index(desc.OIDFieldName)

        # read + split
        with arcpy.da.UpdateCursor(features, cursor_fields) as update_cursor:
            with arcpy.da.InsertCursor(tmp_fc, cursor_fields) as insert_cursor:
                for row in update_cursor:
                    connectors_str = row[connectors_idx]

                    # skip features with no valid connectors value
                    if (
                        connectors_str is None
                        or not isinstance(connectors_str, str)
                        or connectors_str.strip() in ("", "null")
                    ):
                        continue

                    # attempt to parse the JSON
                    try:
                        connectors_list = json.loads(connectors_str)
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(
                            f"Skipping OID {row[oid_idx]}: unable to parse connectors JSON."
                        )
                        continue

                    # must be a non-empty list
                    if not isinstance(connectors_list, list) or len(connectors_list) == 0:
                        continue

                    # need at least 3 connector entries to have an interior split
                    if len(connectors_list) < 3:
                        continue

                    geom = row[-1]
                    if geom is None:
                        continue

                    line_length = geom.length
                    if line_length == 0:
                        continue

                    # ----------------------------------------------------------
                    # Resolve connector_ids to point geometries and compute
                    # their distance along the segment polyline.
                    # ----------------------------------------------------------
                    distances: list[float] = []
                    for entry in connectors_list:
                        cid = entry.get("connector_id")
                        if cid is None:
                            continue

                        pt_geom = connector_geom_map.get(str(cid))
                        if pt_geom is None:
                            logger.debug(
                                f"Connector '{cid}' referenced by OID "
                                f"{row[oid_idx]} not found in connector "
                                f"features — skipping."
                            )
                            continue

                        # queryPointAndDistance returns:
                        # (point_on_line, distance_along, distance_from, right_side)
                        result = geom.queryPointAndDistance(pt_geom)
                        distance_along = result[1]
                        distance_from_line = result[2]

                        # skip if the connector is too far from the segment
                        if distance_from_line > radius_value:
                            logger.warning(
                                f"Connector '{cid}' is {distance_from_line:.2f} "
                                f"units from OID {row[oid_idx]} (exceeds "
                                f"search_radius={search_radius}) — skipping."
                            )
                            continue

                        distances.append(distance_along)

                    # deduplicate and sort distances
                    unique_distances = sorted(set(
                        round(d, 8) for d in distances
                    ))

                    # need at least 3 unique positions to produce interior splits
                    if len(unique_distances) < 3:
                        continue

                    # create one sub-segment for each consecutive pair of distances
                    for i in range(len(unique_distances) - 1):
                        start_dist = unique_distances[i]
                        end_dist = unique_distances[i + 1]

                        new_row = list(row)
                        new_row[-1] = geom.segmentAlongLine(
                            start_dist,
                            end_dist,
                        )
                        insert_cursor.insertRow(new_row)
                        logger.debug(
                            f"Inserted connector sub-segment from "
                            f"{start_dist:.2f} to {end_dist:.2f} for "
                            f"OID {row[oid_idx]}."
                        )
                        add_cnt += 1

                    # mark the original feature for deletion
                    del_oid_lst.append(row[oid_idx])

        # append the new features from the temporary feature class into the target
        arcpy.management.Append(
            inputs=tmp_fc,
            target=features,
            schema_type="NO_TEST",
        )
        logger.debug("Appended connector-split features to target features.")

        # delete the original features that were split
        del_oid_set = set(del_oid_lst)
        with arcpy.da.UpdateCursor(features, "OID@") as drop_cursor:
            for row in drop_cursor:
                if row[0] in del_oid_set:
                    drop_cursor.deleteRow()

        logger.debug("Deleted original features that were split at connectors.")

        # clean up temporary geodatabase
        shutil.rmtree(tmp_gdb, ignore_errors=True)
        logger.debug("Deleted temporary file geodatabase.")

        # log final counts
        final_count = int(arcpy.management.GetCount(features)[0])
        logger.info(
            f"Added {add_cnt:,} connector-split sub-segments and deleted "
            f"{len(del_oid_lst):,} original features. "
            f"Final feature count: {final_count:,}."
        )

    except Exception:
        # roll back output copy on failure
        if output_features is not None and arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
            logger.error(
                "Split at connectors failed — rolled back by deleting the output feature class."
            )
        raise

    return output_features


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
