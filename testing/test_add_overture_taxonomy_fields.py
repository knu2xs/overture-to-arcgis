"""
Test suite for add_overture_taxonomy_fields in overture_to_arcgis.utils._arcgis
"""
import pytest
import arcpy
import json
from pathlib import Path
from overture_to_arcgis.utils._arcgis import add_overture_taxonomy_fields


def create_test_fc(tmp_path, fields):
    """
    Helper to create a temporary feature class with specified fields.
    """
    gdb_path = arcpy.management.CreateFileGDB(str(tmp_path), "test.gdb")[0]
    fc_path = arcpy.management.CreateFeatureclass(gdb_path, "test_fc", "POINT")[0]
    for field in fields:
        arcpy.management.AddField(fc_path, field, "TEXT", field_length=255)
    return fc_path


def test_add_overture_taxonomy_fields_primary(monkeypatch, tmp_path):
    """
    Test add_overture_taxonomy_fields with primary category from 'categories' field.
    """
    # Create test feature class
    fc = create_test_fc(tmp_path, ["categories"])
    # Insert a row with a valid primary category
    with arcpy.da.InsertCursor(fc, ["categories", "SHAPE@XY"]) as cursor:
        cursor.insertRow([json.dumps({"primary": "segment"}), (0, 0)])
    # Patch taxonomy dataframe and max lengths
    monkeypatch.setattr(
        "overture_to_arcgis.utils._arcgis.get_overture_taxonomy_dataframe",
        lambda: __import__("pandas").DataFrame(
            {
                "category_code": ["segment"],
                "category_1": ["transport"],
                "category_2": ["road"],
            }
        ),
    )
    monkeypatch.setattr(
        "overture_to_arcgis.utils._arcgis.get_overture_taxonomy_category_field_max_lengths",
        lambda df: {"category_1": 20, "category_2": 20},
    )
    # Run function
    add_overture_taxonomy_fields(fc)
    # Check fields exist
    field_names = [f.name for f in arcpy.ListFields(fc)]
    assert any("primary_category_1" in f for f in field_names)
    assert any("primary_category_2" in f for f in field_names)
    # Check values
    with arcpy.da.SearchCursor(
        fc, ["primary_category_1", "primary_category_2"]
    ) as cursor:
        for row in cursor:
            assert row[0] == "transport"
            assert row[1] == "road"


def test_add_overture_taxonomy_fields_single(monkeypatch, tmp_path):
    """
    Test add_overture_taxonomy_fields with a single category field.
    """
    # Create test feature class
    fc = create_test_fc(tmp_path, ["mycat"])
    # Insert a row with a valid category
    with arcpy.da.InsertCursor(fc, ["mycat", "SHAPE@XY"]) as cursor:
        cursor.insertRow(["segment", (1, 1)])
    # Patch taxonomy dataframe and max lengths
    monkeypatch.setattr(
        "overture_to_arcgis.utils._arcgis.get_overture_taxonomy_dataframe",
        lambda: __import__("pandas").DataFrame(
            {
                "category_code": ["segment"],
                "category_1": ["transport"],
                "category_2": ["road"],
            }
        ),
    )
    monkeypatch.setattr(
        "overture_to_arcgis.utils._arcgis.get_overture_taxonomy_category_field_max_lengths",
        lambda df: {"category_1": 20, "category_2": 20},
    )
    # Run function
    add_overture_taxonomy_fields(fc, single_category_field="mycat")
    # Check fields exist
    field_names = [f.name for f in arcpy.ListFields(fc)]
    assert any("mycat_1" in f for f in field_names)
    assert any("mycat_2" in f for f in field_names)
    # Check values
    with arcpy.da.SearchCursor(fc, ["mycat_1", "mycat_2"]) as cursor:
        for row in cursor:
            assert row[0] == "transport"
            assert row[1] == "road"
