import pytest
import arcpy
from pathlib import Path
from overture_to_arcgis.utils._arcgis_features import split_into_subclass_features


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


def test_output_features_copies_and_splits(test_fc, tmp_gdb):
    """Test that providing output_features copies data and splits the copy."""
    rules = '[{"value": "driveway", "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)

    output_fc = str(tmp_gdb / "output_fc")
    result = split_into_subclass_features(test_fc, output_features=output_fc)

    # return value is the output path
    assert result == output_fc
    assert arcpy.Exists(output_fc)

    # the output has the split result
    with arcpy.da.SearchCursor(output_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert "driveway" in values

    # original input is unchanged — it should still have exactly 1 feature and no subclass field added
    original_count = int(arcpy.management.GetCount(test_fc)[0])
    assert original_count == 1


def test_output_features_subsegments(test_fc, tmp_gdb):
    """Test output_features with subsegment splitting."""
    rules = '[{"value": "driveway", "between": [0.5, 1.0]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 2)

    output_fc = str(tmp_gdb / "output_subseg")
    split_into_subclass_features(test_fc, output_features=output_fc)

    with arcpy.da.SearchCursor(output_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    assert "driveway" in values
    assert len(values) == 2

    # original unchanged
    assert int(arcpy.management.GetCount(test_fc)[0]) == 1


def test_output_features_returns_none_when_not_specified(test_fc):
    """Test that the return value is None when output_features is not provided."""
    rules = '[{"value": "driveway", "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)

    result = split_into_subclass_features(test_fc)
    assert result is None


def test_split_trailing_gap(test_fc):
    """Test that a trailing gap (rule ends before 1.0) produces an extra segment."""
    rules = '[{"value": "driveway", "between": [0.0, 0.5]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 10)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    # expect two features: 0-50% driveway, 50-100% no subclass
    assert "driveway" in values
    assert len(values) == 2


def test_split_interior_gap(test_fc):
    """Test that an interior gap between rules produces a gap segment."""
    rules = (
        '[{"value": "driveway", "between": [0.0, 0.3]}, '
        '{"value": "alley", "between": [0.6, 1.0]}]'
    )
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 11)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    # expect three features: 0-30% driveway, 30-60% no subclass, 60-100% alley
    assert "driveway" in values
    assert "alley" in values
    assert values.count(None) == 1
    assert len(values) == 3


def test_split_leading_interior_trailing_gaps(test_fc):
    """Test a rule that has leading, interior, and trailing gaps."""
    rules = (
        '[{"value": "driveway", "between": [0.2, 0.4]}, '
        '{"value": "alley", "between": [0.6, 0.8]}]'
    )
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 12)
    split_into_subclass_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["subclass"]) as cursor:
        values = [row[0] for row in cursor]
    # expect 5 features:
    #   0-20% gap, 20-40% driveway, 40-60% gap, 60-80% alley, 80-100% gap
    assert "driveway" in values
    assert "alley" in values
    assert values.count(None) == 3
    assert len(values) == 5


def test_output_features_rollback_on_missing_field(tmp_gdb):
    """Test rollback deletes output when the source field is missing."""
    # create an input FC *without* subclass_rules
    input_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_rules_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]

    output_fc = str(tmp_gdb / "should_not_exist")

    with pytest.raises(ValueError, match="subclass_rules"):
        split_into_subclass_features(input_fc, output_features=output_fc)

    # the output should have been cleaned up
    assert not arcpy.Exists(output_fc)
