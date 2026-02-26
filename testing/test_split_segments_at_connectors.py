import json

import pytest
import arcpy
from pathlib import Path

from overture_to_arcgis.utils._arcgis_features import split_segments_at_connectors


@pytest.fixture
def test_fc(tmp_gdb):
    """Create a temporary polyline feature class with a connectors field."""
    fc_path = tmp_gdb / "test_connectors_fc"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="test_connectors_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )
    arcpy.management.AddField(str(fc_path), "connectors", "TEXT", field_length=2000)
    arcpy.management.AddField(str(fc_path), "id", "TEXT", field_length=100)
    return str(fc_path)


def insert_polyline(fc, points, connectors_json, feature_id):
    """Insert a polyline with a connectors JSON string and an id field."""
    array = arcpy.Array([arcpy.Point(*pt) for pt in points])
    polyline = arcpy.Polyline(array, arcpy.SpatialReference(4326))
    with arcpy.da.InsertCursor(fc, ["SHAPE@", "connectors", "id"]) as cursor:
        cursor.insertRow([polyline, connectors_json, feature_id])


# ------------------------------------------------------------------
# Basic functionality
# ------------------------------------------------------------------

def test_no_split_when_only_start_and_end(test_fc):
    """Two connectors (start + end) means no interior split is needed."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg1",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_split_at_one_interior_connector(test_fc):
    """Three connectors should produce two sub-segments."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "mid", "at": 0.4},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg2",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 2


def test_split_at_multiple_interior_connectors(test_fc):
    """Four connectors should produce three sub-segments."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "m1", "at": 0.25},
        {"connector_id": "m2", "at": 0.75},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg3",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 3


def test_attributes_preserved(test_fc):
    """Attributes from the original feature are carried to sub-segments."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "mid", "at": 0.5},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "keep_me",
    )
    split_segments_at_connectors(test_fc)

    with arcpy.da.SearchCursor(test_fc, ["id"]) as cursor:
        ids = [row[0] for row in cursor]
    assert all(v == "keep_me" for v in ids)
    assert len(ids) == 2


# ------------------------------------------------------------------
# Edge cases / skip conditions
# ------------------------------------------------------------------

def test_null_connectors_left_untouched(test_fc):
    """Features with null connectors should remain unchanged."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        None,
        "seg_null",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_empty_string_connectors_left_untouched(test_fc):
    """Features with empty connectors string should remain unchanged."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        "",
        "seg_empty",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_invalid_json_left_untouched(test_fc):
    """Features with unparseable JSON in connectors should be skipped."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        "not-valid-json",
        "seg_bad_json",
    )
    split_segments_at_connectors(test_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_mixed_features_partial_split(test_fc):
    """Only features with >=3 connectors are split; others are kept."""
    # feature 1: two connectors -> no split
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        json.dumps([
            {"connector_id": "a", "at": 0.0},
            {"connector_id": "b", "at": 1.0},
        ]),
        "no_split",
    )
    # feature 2: three connectors -> split into 2
    insert_polyline(
        test_fc,
        [(-122.02, 47.02), (-122.03, 47.03)],
        json.dumps([
            {"connector_id": "a", "at": 0.0},
            {"connector_id": "mid", "at": 0.5},
            {"connector_id": "b", "at": 1.0},
        ]),
        "will_split",
    )
    split_segments_at_connectors(test_fc)
    # 1 untouched + 2 from split = 3
    assert int(arcpy.management.GetCount(test_fc)[0]) == 3


# ------------------------------------------------------------------
# Missing field validation
# ------------------------------------------------------------------

def test_missing_connectors_field_raises(tmp_gdb):
    """ValueError raised when the connectors field is absent."""
    fc_path = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_connectors_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]
    with pytest.raises(ValueError, match="connectors"):
        split_segments_at_connectors(fc_path)


# ------------------------------------------------------------------
# output_features parameter
# ------------------------------------------------------------------

def test_output_features_copies_and_splits(test_fc, tmp_gdb):
    """Providing output_features should copy data, split the copy, and leave the original untouched."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "mid", "at": 0.5},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg_copy",
    )

    output_fc = str(tmp_gdb / "output_connectors")
    result = split_segments_at_connectors(test_fc, output_features=output_fc)

    assert result == output_fc
    assert arcpy.Exists(output_fc)

    # output has the split features
    assert int(arcpy.management.GetCount(output_fc)[0]) == 2

    # original is unchanged
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_output_features_returns_none_when_not_specified(test_fc):
    """Return value should be None when output_features is not given."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "mid", "at": 0.5},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg_inplace",
    )
    result = split_segments_at_connectors(test_fc)
    assert result is None


def test_output_features_rollback_on_missing_field(tmp_gdb):
    """Rollback should delete the output when field validation fails."""
    input_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_conn_field_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]

    output_fc = str(tmp_gdb / "should_not_exist")

    with pytest.raises(ValueError, match="connectors"):
        split_segments_at_connectors(input_fc, output_features=output_fc)

    assert not arcpy.Exists(output_fc)


# ------------------------------------------------------------------
# Duplicate fractions
# ------------------------------------------------------------------

def test_duplicate_fractions_deduplicated(test_fc):
    """Duplicate 'at' values should be deduplicated so no zero-length segments are created."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "dup", "at": 0.5},
        {"connector_id": "dup2", "at": 0.5},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg_dup",
    )
    split_segments_at_connectors(test_fc)
    # deduplication means only 2 unique fractions boundaries -> 2 segments
    assert int(arcpy.management.GetCount(test_fc)[0]) == 2
