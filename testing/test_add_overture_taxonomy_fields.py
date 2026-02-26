"""
Test suite for add_overture_taxonomy_fields in overture_to_arcgis.utils._arcgis
"""
import pytest
import arcpy
import json
from pathlib import Path
from overture_to_arcgis.utils._arcgis_fields import add_overture_taxonomy_fields


def test_add_overture_taxonomy_fields_primary(features_small_places):
    """
    Test add_overture_taxonomy_fields with primary category from 'categories' field.
    """
    # Run function
    add_overture_taxonomy_fields(features_small_places)

    # Check fields exist
    field_names_obs = [f.name for f in arcpy.ListFields(features_small_places)]
    field_names_expected = ['primary_category_code'] + [f'primary_category_{i:02d}' for i in range(1, 6)]

    # Check fields exist
    for field_expected in field_names_expected:
        assert field_expected in field_names_obs

    # Check values
    with arcpy.da.SearchCursor(
        str(features_small_places), field_names_obs
    ) as cursor:
        
        for row in cursor:

            # ensure row is not all nulls
            primary_category_code = row[field_names_obs.index('primary_category_code')]

            assert primary_category_code is not None

            assert any(
                row[field_names_obs.index(f'primary_category_{i:02d}')] is not None
                for i in range(1, 6)
            )

            assert any(val is not None or val != 'null' for val in row)