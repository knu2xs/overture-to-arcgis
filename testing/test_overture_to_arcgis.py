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

# small test extent area...Black Hills just outside of Olympia, WA
test_extent = (-122.9972, 47.0068, -122.9422, 47.0446)


@pytest.fixture(scope="session")
def test_sedf():
    """Fixture to provide a spatially enabled dataframe for tests"""
    return overture_to_arcgis.get_spatially_enabled_dataframe("segment", test_extent)


@pytest.fixture(scope="session")
def test_count(test_sedf):
    """Fixture to provide the count of features in the test spatially enabled dataframe"""
    return len(test_sedf.index)


def test_get_spatially_enabled_dataframe():
    """Test fetching segments (transportation data) data for a small area"""
    df = overture_to_arcgis.get_spatially_enabled_dataframe("segment", test_extent)

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


def test_get_features(tmp_gdb: Path):
    """Test fetching segments (transportation data) data for a small area, and saving to a feature class"""
    out_fc = tmp_gdb / "segments"

    res_fc = overture_to_arcgis.get_features(
        out_fc, overture_type="segment", bbox=test_extent
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
