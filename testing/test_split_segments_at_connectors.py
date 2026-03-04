import json

import pytest
import arcpy
from pathlib import Path

from overture_to_arcgis.utils._arcgis_features import split_segments_at_connectors


SR = arcpy.SpatialReference(4326)


@pytest.fixture
def test_fc(tmp_gdb):
    """Create a temporary polyline feature class with a connectors field."""
    fc_path = tmp_gdb / "test_connectors_fc"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="test_connectors_fc",
        geometry_type="POLYLINE",
        spatial_reference=SR,
    )
    arcpy.management.AddField(str(fc_path), "connectors", "TEXT", field_length=2000)
    arcpy.management.AddField(str(fc_path), "id", "TEXT", field_length=100)
    return str(fc_path)


@pytest.fixture
def connector_fc(tmp_gdb):
    """Create a temporary point feature class with an id field for connectors."""
    fc_path = tmp_gdb / "test_connector_pts"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="test_connector_pts",
        geometry_type="POINT",
        spatial_reference=SR,
    )
    arcpy.management.AddField(str(fc_path), "id", "TEXT", field_length=200)
    return str(fc_path)


def insert_polyline(fc, points, connectors_json, feature_id):
    """Insert a polyline with a connectors JSON string and an id field."""
    array = arcpy.Array([arcpy.Point(*pt) for pt in points])
    polyline = arcpy.Polyline(array, SR)
    with arcpy.da.InsertCursor(fc, ["SHAPE@", "connectors", "id"]) as cursor:
        cursor.insertRow([polyline, connectors_json, feature_id])


def insert_connector_point(fc, x, y, connector_id):
    """Insert a connector point with an id field."""
    point = arcpy.PointGeometry(arcpy.Point(x, y), SR)
    with arcpy.da.InsertCursor(fc, ["SHAPE@", "id"]) as cursor:
        cursor.insertRow([point, connector_id])


# ------------------------------------------------------------------
# Basic functionality
# ------------------------------------------------------------------

def test_no_split_when_only_start_and_end(test_fc, connector_fc):
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
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_split_at_one_interior_connector(test_fc, connector_fc):
    """Three connectors should produce two sub-segments."""
    connectors = json.dumps([
        {"connector_id": "a", "at": 0.0},
        {"connector_id": "mid", "at": 0.5},
        {"connector_id": "b", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg2",
    )
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.005, 47.005, "mid")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 2


def test_split_at_multiple_interior_connectors(test_fc, connector_fc):
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
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.0025, 47.0025, "m1")
    insert_connector_point(connector_fc, -122.0075, 47.0075, "m2")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 3


def test_attributes_preserved(test_fc, connector_fc):
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
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.005, 47.005, "mid")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    split_segments_at_connectors(test_fc, connector_fc)

    with arcpy.da.SearchCursor(test_fc, ["id"]) as cursor:
        ids = [row[0] for row in cursor]
    assert all(v == "keep_me" for v in ids)
    assert len(ids) == 2


# ------------------------------------------------------------------
# Edge cases / skip conditions
# ------------------------------------------------------------------

def test_null_connectors_left_untouched(test_fc, connector_fc):
    """Features with null connectors should remain unchanged."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        None,
        "seg_null",
    )
    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_empty_string_connectors_left_untouched(test_fc, connector_fc):
    """Features with empty connectors string should remain unchanged."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        "",
        "seg_empty",
    )
    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_invalid_json_left_untouched(test_fc, connector_fc):
    """Features with unparseable JSON in connectors should be skipped."""
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        "not-valid-json",
        "seg_bad_json",
    )
    split_segments_at_connectors(test_fc, connector_fc)
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_mixed_features_partial_split(test_fc, connector_fc):
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
            {"connector_id": "c", "at": 0.0},
            {"connector_id": "d", "at": 0.5},
            {"connector_id": "e", "at": 1.0},
        ]),
        "will_split",
    )
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")
    insert_connector_point(connector_fc, -122.02, 47.02, "c")
    insert_connector_point(connector_fc, -122.025, 47.025, "d")
    insert_connector_point(connector_fc, -122.03, 47.03, "e")

    split_segments_at_connectors(test_fc, connector_fc)
    # 1 untouched + 2 from split = 3
    assert int(arcpy.management.GetCount(test_fc)[0]) == 3


# ------------------------------------------------------------------
# Missing field validation
# ------------------------------------------------------------------

def test_missing_connectors_field_raises(tmp_gdb, connector_fc):
    """ValueError raised when the connectors field is absent."""
    fc_path = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_connectors_fc",
        geometry_type="POLYLINE",
        spatial_reference=SR,
    )[0]
    with pytest.raises(ValueError, match="connectors"):
        split_segments_at_connectors(fc_path, connector_fc)


def test_missing_connector_id_field_raises(tmp_gdb, test_fc):
    """ValueError raised when the connector features lack an 'id' field."""
    bad_conn_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_id_connector_fc",
        geometry_type="POINT",
        spatial_reference=SR,
    )[0]
    with pytest.raises(ValueError, match="id"):
        split_segments_at_connectors(test_fc, bad_conn_fc)


# ------------------------------------------------------------------
# output_features parameter
# ------------------------------------------------------------------

def test_output_features_copies_and_splits(test_fc, connector_fc, tmp_gdb):
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
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.005, 47.005, "mid")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    output_fc = str(tmp_gdb / "output_connectors")
    result = split_segments_at_connectors(
        test_fc, connector_fc, output_features=output_fc
    )

    assert result == output_fc
    assert arcpy.Exists(output_fc)

    # output has the split features
    assert int(arcpy.management.GetCount(output_fc)[0]) == 2

    # original is unchanged
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_output_features_returns_none_when_not_specified(test_fc, connector_fc):
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
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.005, 47.005, "mid")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")

    result = split_segments_at_connectors(test_fc, connector_fc)
    assert result is None


def test_output_features_rollback_on_missing_field(tmp_gdb, connector_fc):
    """Rollback should delete the output when field validation fails."""
    input_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_conn_field_fc",
        geometry_type="POLYLINE",
        spatial_reference=SR,
    )[0]

    output_fc = str(tmp_gdb / "should_not_exist")

    with pytest.raises(ValueError, match="connectors"):
        split_segments_at_connectors(
            input_fc, connector_fc, output_features=output_fc
        )

    assert not arcpy.Exists(output_fc)


# ------------------------------------------------------------------
# Connector geometry not found
# ------------------------------------------------------------------

def test_missing_connector_geometry_skipped(test_fc, connector_fc):
    """Segments referencing connector IDs not in the point FC are skipped."""
    connectors = json.dumps([
        {"connector_id": "exists_start", "at": 0.0},
        {"connector_id": "does_not_exist", "at": 0.5},
        {"connector_id": "exists_end", "at": 1.0},
    ])
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        connectors,
        "seg_missing",
    )
    # only insert start and end — interior connector is missing
    insert_connector_point(connector_fc, -122.0, 47.0, "exists_start")
    insert_connector_point(connector_fc, -122.01, 47.01, "exists_end")

    split_segments_at_connectors(test_fc, connector_fc)
    # only 2 resolved points → no interior split → feature untouched
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


# ------------------------------------------------------------------
# Only related connectors are used per segment
# ------------------------------------------------------------------

def test_only_related_connectors_used(test_fc, connector_fc):
    """Each segment should only be split by its own listed connectors."""
    # segment 1 references connectors a, mid1, b
    insert_polyline(
        test_fc,
        [(-122.0, 47.0), (-122.01, 47.01)],
        json.dumps([
            {"connector_id": "a", "at": 0.0},
            {"connector_id": "mid1", "at": 0.5},
            {"connector_id": "b", "at": 1.0},
        ]),
        "seg1",
    )
    # segment 2 references connectors c, d only (no interior → no split)
    insert_polyline(
        test_fc,
        [(-122.02, 47.02), (-122.03, 47.03)],
        json.dumps([
            {"connector_id": "c", "at": 0.0},
            {"connector_id": "d", "at": 1.0},
        ]),
        "seg2",
    )
    # add all connector points — including mid1 which is near seg2
    insert_connector_point(connector_fc, -122.0, 47.0, "a")
    insert_connector_point(connector_fc, -122.005, 47.005, "mid1")
    insert_connector_point(connector_fc, -122.01, 47.01, "b")
    insert_connector_point(connector_fc, -122.02, 47.02, "c")
    insert_connector_point(connector_fc, -122.03, 47.03, "d")

    split_segments_at_connectors(test_fc, connector_fc)
    # seg1 splits into 2, seg2 stays as 1 → total 3
    assert int(arcpy.management.GetCount(test_fc)[0]) == 3

    # verify seg2 was not split even though mid1 point exists nearby
    with arcpy.da.SearchCursor(test_fc, ["id"]) as cursor:
        id_counts = {}
        for row in cursor:
            id_counts[row[0]] = id_counts.get(row[0], 0) + 1
    assert id_counts["seg1"] == 2
    assert id_counts["seg2"] == 1
