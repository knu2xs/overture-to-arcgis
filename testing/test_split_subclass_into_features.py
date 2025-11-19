import pytest
import arcpy
from pathlib import Path
from overture_to_arcgis.utils._arcgis import split_into_subclass_features


@pytest.fixture
def test_fc(tmp_gdb):
    """Create a temporary polyline feature class with a subclass_rules field."""
    fc_path = tmp_gdb / "test_fc"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="test_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )
    arcpy.management.AddField(str(fc_path), "subclass_rules", "TEXT", field_length=500)
    arcpy.management.AddField(str(fc_path), "id", "LONG")
    return str(fc_path)


def insert_polyline(fc, points, subclass_rules, oid):
    """Insert a polyline with subclass_rules and id."""
    array = arcpy.Array([arcpy.Point(*pt) for pt in points])
    polyline = arcpy.Polyline(array)
    with arcpy.da.InsertCursor(fc, ["SHAPE@", "subclass_rules", "id"]) as cursor:
        cursor.insertRow([polyline, subclass_rules, oid])


def test_split_entire_geometry(test_fc):
    """Test splitting with a single rule for the entire geometry."""
    rules = '[{"value": "driveway", "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert "driveway" in values
    assert len(values) == 1


def test_split_subsegments(test_fc):
    """Test splitting into two subsegments."""
    rules = '[{"value": "driveway", "between": [0.5, 1.0]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 2)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert "driveway" in values
    assert len(values) == 2


def test_split_multiple_subsegments(test_fc):
    """Test splitting into multiple subsegments."""
    rules = '[{"value": "driveway", "between": [0.0, 0.5]}, {"value": "alley", "between": [0.5, 1.0]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 3)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert "driveway" in values
    assert "alley" in values
    assert len(values) == 2


def test_no_subclass_rules(test_fc):
    """Test feature with no subclass_rules (should not split or update)."""
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], None, 4)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert all(v is None for v in values)


def test_missing_subclass_rules_field(tmp_gdb):
    """Test error raised if subclass_rules field is missing."""
    fc_path = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="missing_field_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]
    with pytest.raises(ValueError, match="subclass_rules"):
        split_into_subclass_features(fc_path)
