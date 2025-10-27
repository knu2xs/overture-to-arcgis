"""
This is a stubbed out test file designed to be used with PyTest, but can
easily be modified to support any testing framework.
"""

from pathlib import Path
import sys

import arcpy.management
import pandas as pd
import pytest

# get paths to useful resources - notably where the src directory is
self_pth = Path(__file__)
dir_test = self_pth.parent
dir_prj = dir_test.parent
dir_src = dir_prj / "src"

# insert the src directory into the path and import the project package
sys.path.insert(0, str(dir_src))
import overture_to_arcgis
from overture_to_arcgis.utils._arcgis import flatten_dict_to_bool_keys


@pytest.fixture(scope="session")
def test_sedf(extent_small):
    """Fixture to provide a spatially enabled dataframe for tests"""
    return overture_to_arcgis.get_spatially_enabled_dataframe("segment", extent_small)


@pytest.fixture(scope="session")
def test_count(test_sedf):
    """Fixture to provide the count of features in the test spatially enabled dataframe"""
    return len(test_sedf.index)


def test_get_spatially_enabled_dataframe():
    """Test fetching segments (transportation data) data for a small area"""
    # ...existing code...


def test_flatten_dict_to_bool_keys():
    """
    Test flatten_dict_to_bool_keys for nested dicts with strings and lists.
    """
    input_data = [
        {
            'access_type': 'denied',
            'when': {
                'during': None,
                'heading': 'backward',
                'using': None,
                'recognized': None,
                'mode': None,
                'vehicle': None
            },
            'between': None
        },
        {
            'access_type': 'denied',
            'when': {
                'during': None,
                'heading': None,
                'using': None,
                'recognized': None,
                'mode': ['bicycle'],
                'vehicle': None
            },
            'between': None
        }
    ]
    expected = {
        'access_denied_when_heading_backward': 1,
        'access_denied_when_mode_bicycle': 1
    }
    result = flatten_dict_to_bool_keys(input_data)
    # The function outputs all populated keys
    for k in expected:
        assert result.get(k) == 1
    # Should not include keys for None values
    assert not any('None' in key for key in result)


def test_get_spatially_enabled_dataframe_valid(extent_small: tuple[float, float, float, float]):
    """Test fetching segments (transportation data) data for a small area"""
    df = overture_to_arcgis.get_spatially_enabled_dataframe("segment", extent_small)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert df.spatial.validate()


def test_get_spatially_enabled_dataframe_invalid_type():
    extent = (-119.911, 48.3852, -119.8784, 48.4028)
    with pytest.raises(ValueError, match="Invalid overture type"):
        overture_to_arcgis.get_spatially_enabled_dataframe("not_a_type", extent)


def test_get_spatially_enabled_dataframe_bbox_length():
    bad_bbox = (-119.911, 48.3852, -119.8784)  # Only 3 values
    with pytest.raises(ValueError, match="Bounding box must be a tuple of four values"):
        overture_to_arcgis.get_spatially_enabled_dataframe("segment", bad_bbox)


def test_get_spatially_enabled_dataframe_bbox_non_numeric():
    bad_bbox = (-119.911, 48.3852, "foo", 48.4028)
    with pytest.raises(
        ValueError, match="All coordinates in the bounding box must be numeric"
    ):
        overture_to_arcgis.get_spatially_enabled_dataframe("segment", bad_bbox)


def test_get_spatially_enabled_dataframe_bbox_invalid_order():
    bad_bbox = (-119.8784, 48.3852, -119.911, 48.4028)  # minx > maxx
    with pytest.raises(ValueError, match="Invalid bounding box coordinates"):
        overture_to_arcgis.get_spatially_enabled_dataframe("segment", bad_bbox)


def test_get_release_list():
    """Test fetching the list of available Overture Maps releases"""
    releases = overture_to_arcgis.utils.__main__.get_release_list()

    assert isinstance(releases, list)
    assert len(releases) > 0
    assert all(isinstance(release, str) for release in releases)


def test_get_type_theme_map():
    """Test fetching the overture type to theme mapping"""
    type_theme_map = overture_to_arcgis.utils.__main__.get_type_theme_map()

    assert isinstance(type_theme_map, dict)
    assert len(type_theme_map) > 0
    assert all(
        isinstance(k, str) and isinstance(v, str) for k, v in type_theme_map.items()
    )


def test_get_features(tmp_gdb: Path, extent_small: tuple[float, float, float, float]):
    """Test fetching segments (transportation data) data for a small area, and saving to a feature class"""
    out_fc = tmp_gdb / "segments"

    res_fc = overture_to_arcgis.get_features(
        out_fc, overture_type="segment", bbox=extent_small
    )

    # features exist
    assert arcpy.Exists(str(out_fc))

    # expected columns are included
    expected_fields = [
        "id",
        "bbox",
        "version",
        "sources",
        "subtype",
        "class",
        "names",
        "connectors",
        "routes",
        "subclass_rules",
        "access_restrictions",
        "level_rules",
        "destinations",
        "prohibited_transitions",
        "road_surface",
        "road_flags",
        "speed_limits",
        "width_rules",
        "subclass",
        "rail_flags",
    ]
    actual_fields = [c.name for c in arcpy.ListFields(res_fc)]
    missing_fields = set(expected_fields).difference(actual_fields)
    assert len(missing_fields) == 0

    # features are retrieved
    assert int(arcpy.management.GetCount(str(res_fc)).getOutput(0)) > 0

    # correct geometry type
    assert arcpy.Describe(str(res_fc)).shapeType == "Polyline"


def test_get_features_invalid_type(tmp_gdb: Path, extent_small: tuple[float, float, float, float]):
    """Test fetching features with an invalid overture type"""
    out_fc = tmp_gdb / "invalid_type"

    with pytest.raises(ValueError, match="Invalid overture type"):
        overture_to_arcgis.get_features(
            out_fc, overture_type="not_a_type", bbox=extent_small
        )

def test_get_features_no_data(tmp_gdb: Path, extent_small: tuple[float, float, float, float]):
    """Test fetching features for an area with no data"""
    out_fc = tmp_gdb / "no_data"

    # Use an extent likely to have no data (e.g., middle of the ocean)
    no_data_extent = (-140.0, 0.0, -139.9, 0.1)

    res_fc = overture_to_arcgis.get_features(
        out_fc, overture_type="segment", bbox=no_data_extent
    )

    # features exist
    assert arcpy.Exists(str(out_fc))

    # features are retrieved
    assert int(arcpy.management.GetCount(str(res_fc)).getOutput(0)) == 0


def test_get_features_invalid_bbox(tmp_gdb: Path):
    """Test fetching features with an invalid bounding box"""
    out_fc = tmp_gdb / "invalid_bbox"
    bad_bbox = (-119.911, 48.3852, -119.8784)  # Only 3 values

    with pytest.raises(ValueError, match="Bounding box must be a tuple of four values"):
        overture_to_arcgis.get_features(
            out_fc, overture_type="segment", bbox=bad_bbox
        )


def test_get_features_bbox_non_numeric(tmp_gdb: Path):
    """Test fetching features with a non-numeric bounding box"""
    out_fc = tmp_gdb / "non_numeric_bbox"
    bad_bbox = (-119.911, 48.3852, "foo", 48.4028)

    with pytest.raises(
        ValueError, match="All coordinates in the bounding box must be numeric"
    ):
        overture_to_arcgis.get_features(
            out_fc, overture_type="segment", bbox=bad_bbox
        )


def test_get_features_bbox_invalid_order(tmp_gdb: Path):
    """Test fetching features with an invalid bounding box coordinate order"""
    out_fc = tmp_gdb / "invalid_order_bbox"
    bad_bbox = (-119.8784, 48.3852, -119.911, 48.4028)  # minx > maxx

    with pytest.raises(ValueError, match="Invalid bounding box coordinates"):
        overture_to_arcgis.get_features(
            out_fc, overture_type="segment", bbox=bad_bbox
        )


def test_add_boolean_access_restrictions_fields(tmp_gdb: Path, test_count: int):
    """Test adding boolean access restrictions fields to a feature class"""
    # First, create a feature class with test data
    input_fc = tmp_gdb / "access_restrictions"
    arcpy.management.CreateFeatureclass(
        out_path=str(tmp_gdb),
        out_name="access_restrictions",
        geometry_type="POLYLINE",
        spatial_reference=4326,
    )

    # Add a field to hold access restrictions data
    arcpy.management.AddField(
        in_table=str(input_fc),
        field_name="access_restrictions",
        field_type="TEXT",
        field_length=500,
    )

    # Insert test data into the feature class
    with arcpy.da.InsertCursor(
        str(input_fc), ["SHAPE@", "access_restrictions"]
    ) as cursor:
        for i in range(test_count):
            # Create a simple line geometry
            array = arcpy.Array(
                [arcpy.Point(-122.99 + i * 0.001, 47.00 + i * 0.001), arcpy.Point(-122.98 + i * 0.001, 47.01 + i * 0.001)]
            )
            polyline = arcpy.Polyline(array)
            # Example access restrictions data
            access_data = '{"access_type": "denied", "when": {"heading": "backward"}}'
            cursor.insertRow([polyline, access_data])

    # Now, test the function to add boolean access restrictions fields
    overture_to_arcgis.utils.add_boolean_access_restrictions_fields(str(input_fc))

    # Verify that new fields were added
    expected_fields = [
        "access_denied_when_heading_backward",
    ]
    actual_fields = [c.name for c in arcpy.ListFields(str(input_fc))]
    for field in expected_fields:
        assert field in actual_fields

    # Verify that the fields have correct values
    with arcpy.da.SearchCursor(
        str(input_fc), expected_fields
    ) as cursor:
        for row in cursor:
            for value in row:
                assert value == 1
