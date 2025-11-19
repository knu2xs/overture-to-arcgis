"""
Test suite for get_featureset_batches in overture_to_arcgis.utils._arcgis
"""
import pytest
import arcpy
from pathlib import Path
from overture_to_arcgis.utils._arcgis import get_featureset_batches


def create_test_fc(tmp_gdb, n=10):
    """
    Helper to create a temporary feature class with n point features.
    """
    fc_path = arcpy.management.CreateFeatureclass(str(tmp_gdb), "test_fc", "POINT")[0]
    arcpy.management.AddField(fc_path, "name", "TEXT", field_length=50)
    with arcpy.da.InsertCursor(fc_path, ["name", "SHAPE@XY"]) as cursor:
        for i in range(n):
            cursor.insertRow([f"pt_{i}", (i, i)])
    return fc_path


def test_get_featureset_batches_basic(tmp_path):
    """
    Test get_featureset_batches yields correct number and size of batches.
    """
    fc = create_test_fc(tmp_path, n=7)
    batch_size = 3
    batches = list(get_featureset_batches(fc, batch_size=batch_size))
    # Should yield 3 batches: [0-2], [3-5], [6]
    assert len(batches) == 3
    # Check batch sizes
    assert batches[0].features.__len__() == 3
    assert batches[1].features.__len__() == 3
    assert batches[2].features.__len__() == 1


def test_get_featureset_batches_exact(tmp_path):
    """
    Test get_featureset_batches with batch size equal to feature count.
    """
    fc = create_test_fc(tmp_path, n=5)
    batch_size = 5
    batches = list(get_featureset_batches(fc, batch_size=batch_size))
    assert len(batches) == 1
    assert batches[0].features.__len__() == 5


def test_get_featureset_batches_large(tmp_path):
    """
    Test get_featureset_batches with batch size larger than feature count.
    """
    fc = create_test_fc(tmp_path, n=4)
    batch_size = 10
    batches = list(get_featureset_batches(fc, batch_size=batch_size))
    assert len(batches) == 1
    assert batches[0].features.__len__() == 4
