import pytest
import arcpy
from pathlib import Path
from overture_to_arcgis.utils._arcgis_features import split_into_level_features


@pytest.fixture
def test_fc(tmp_gdb):
    """Create a temporary polyline feature class with a level_rules field."""
    fc_path = tmp_gdb / "test_fc"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="test_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )
    arcpy.management.AddField(str(fc_path), "level_rules", "TEXT", field_length=500)
    arcpy.management.AddField(str(fc_path), "id", "LONG")
    return str(fc_path)


def insert_polyline(fc, points, level_rules, oid):
    """Insert a polyline with level_rules and id."""
    array = arcpy.Array([arcpy.Point(*pt) for pt in points])
    polyline = arcpy.Polyline(array)
    with arcpy.da.InsertCursor(fc, ["SHAPE@", "level_rules", "id"]) as cursor:
        cursor.insertRow([polyline, level_rules, oid])


def test_level_entire_geometry(test_fc):
    """Test level assignment with a single rule for the entire geometry."""
    rules = '[{"value": 1, "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert 1 in values
    assert len(values) == 1


def test_level_negative_value(test_fc):
    """Test level assignment with a negative z_index value."""
    rules = '[{"value": -1, "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert -1 in values
    assert len(values) == 1


def test_level_split_subsegments(test_fc):
    """Test splitting into two subsegments by level fraction."""
    rules = '[{"value": 1, "between": [0.5, 1.0]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 2)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert 1 in values
    assert None in values
    assert len(values) == 2


def test_level_multiple_rules(test_fc):
    """Test splitting with multiple level rules and an interior gap."""
    rules = (
        '[{"value": -1, "between": [0.0, 0.3]}, '
        '{"value": 1, "between": [0.7, 1.0]}]'
    )
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 3)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # expect three features: 0-30% z_index=-1, 30-70% gap (None), 70-100% z_index=1
    assert -1 in values
    assert 1 in values
    assert None in values
    assert len(values) == 3


def test_no_level_rules(test_fc):
    """Test feature with no level_rules (should not split or update)."""
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], None, 4)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert all(v is None for v in values)


def test_missing_level_rules_field(tmp_gdb):
    """Test error raised if level_rules field is missing."""
    fc_path = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="missing_field_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]
    with pytest.raises(ValueError, match="level_rules"):
        split_into_level_features(fc_path)


def test_output_features_copies_and_splits(test_fc, tmp_gdb):
    """Test that providing output_features copies data and splits the copy."""
    rules = '[{"value": 1, "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)

    output_fc = str(tmp_gdb / "output_fc")
    result = split_into_level_features(test_fc, output_features=output_fc)

    # return value is the output path
    assert result == output_fc
    assert arcpy.Exists(output_fc)

    # the output has the split result
    with arcpy.da.SearchCursor(output_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert 1 in values

    # original input is unchanged — it should still have exactly 1 feature
    original_count = int(arcpy.management.GetCount(test_fc)[0])
    assert original_count == 1


def test_output_features_returns_none_when_not_specified(test_fc):
    """Test that the return value is None when output_features is not provided."""
    rules = '[{"value": 1, "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)

    result = split_into_level_features(test_fc)
    assert result is None


def test_level_trailing_gap(test_fc):
    """Test that a trailing gap (rule ends before 1.0) produces an extra segment."""
    rules = '[{"value": 1, "between": [0.0, 0.5]}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 10)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # expect two features: 0-50% z_index=1, 50-100% None
    assert 1 in values
    assert None in values
    assert len(values) == 2


def test_level_leading_interior_trailing_gaps(test_fc):
    """Test a rule that has leading, interior, and trailing gaps."""
    rules = (
        '[{"value": -1, "between": [0.2, 0.4]}, '
        '{"value": 1, "between": [0.6, 0.8]}]'
    )
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 12)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # expect 5 features:
    #   0-20% gap, 20-40% z_index=-1, 40-60% gap, 60-80% z_index=1, 80-100% gap
    assert -1 in values
    assert 1 in values
    assert values.count(None) == 3
    assert len(values) == 5


def test_output_features_rollback_on_missing_field(tmp_gdb):
    """Test rollback deletes output when the source field is missing."""
    input_fc = arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="no_rules_fc",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )[0]

    output_fc = str(tmp_gdb / "should_not_exist")

    with pytest.raises(ValueError, match="level_rules"):
        split_into_level_features(input_fc, output_features=output_fc)

    # the output should have been cleaned up
    assert not arcpy.Exists(output_fc)


def test_z_index_field_already_exists_succeeds(test_fc):
    """Test that the function succeeds when z_index field already exists."""
    arcpy.management.AddField(test_fc, "z_index", "LONG")
    rules = '[{"value": 1, "between": null}]'
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 1)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    assert 1 in values
    assert len(values) == 1


def test_presplit_single_rule(tmp_gdb):
    """Test pre-split features (same id) with a level rule spanning one sub-segment."""
    fc_path = str(tmp_gdb / "presplit_single")
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="presplit_single",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )
    arcpy.management.AddField(fc_path, "level_rules", "TEXT", field_length=500)
    arcpy.management.AddField(fc_path, "id", "LONG")

    # Two features sharing id=1 that together form the original segment.
    # Feature A covers roughly [0.0, 0.5] and Feature B covers [0.5, 1.0].
    # Rule: z_index=1 covers [0.0, 0.5] of the original.
    rules = '[{"value": 1, "between": [0.0, 0.5]}]'
    insert_polyline(fc_path, [(-122.0, 47.0), (-122.005, 47.005)], rules, 1)
    insert_polyline(fc_path, [(-122.005, 47.005), (-122.01, 47.01)], rules, 1)

    split_into_level_features(fc_path)

    with arcpy.da.SearchCursor(fc_path, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # Feature A (0-50%) -> entirely z_index=1 (update in place)
    # Feature B (50-100%) -> entirely gap (None) (update in place)
    assert 1 in values
    assert None in values
    assert len(values) == 2


def test_presplit_rule_spans_boundary(tmp_gdb):
    """Test pre-split features where a level rule boundary falls inside a sub-segment."""
    fc_path = str(tmp_gdb / "presplit_boundary")
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="presplit_boundary",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )
    arcpy.management.AddField(fc_path, "level_rules", "TEXT", field_length=500)
    arcpy.management.AddField(fc_path, "id", "LONG")

    # Two equal-length features sharing id=1, each covering ~50% of the original.
    # Rule: z_index=1 [0.0, 0.75] — spans across the 50% split point.
    rules = '[{"value": 1, "between": [0.0, 0.75]}]'
    insert_polyline(fc_path, [(-122.0, 47.0), (-122.005, 47.005)], rules, 1)
    insert_polyline(fc_path, [(-122.005, 47.005), (-122.01, 47.01)], rules, 1)

    split_into_level_features(fc_path)

    with arcpy.da.SearchCursor(fc_path, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # Feature A (0-50%) -> entirely z_index=1 (update in place)
    # Feature B (50-100%) -> split: 50-75% z_index=1, 75-100% gap
    assert values.count(1) == 2
    assert values.count(None) == 1
    assert len(values) == 3


def test_multiple_level_values_on_same_segment(test_fc):
    """Test multiple distinct z_index values on different portions of the same segment."""
    rules = (
        '[{"value": 1, "between": [0.0, 0.3]}, '
        '{"value": 1, "between": [0.3, 0.5]}, '
        '{"value": -1, "between": [0.5, 0.8]}, '
        '{"value": 1, "between": [0.8, 1.0]}]'
    )
    insert_polyline(test_fc, [(-122.0, 47.0), (-122.01, 47.01)], rules, 20)
    split_into_level_features(test_fc)
    with arcpy.da.SearchCursor(test_fc, ["z_index"]) as cursor:
        values = [row[0] for row in cursor]
    # 4 segments: z_index=1 (0-30%), z_index=1 (30-50%), z_index=-1 (50-80%), z_index=1 (80-100%)
    assert values.count(1) == 3
    assert values.count(-1) == 1
    assert len(values) == 4
