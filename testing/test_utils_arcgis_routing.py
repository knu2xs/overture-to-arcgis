from pathlib import Path
import pytest

from overture_to_arcgis.utils import _arcgis_routing


def test_add_restrictions_columns_walk(
    features_small_segments: Path,
):
    """Test the add_walk_restrictions_columns function."""
    _arcgis_routing.add_restrictions_column(
        edge_features=features_small_segments,
        modality_prefix="walk",
    )

    import arcpy
    from arcgis.features import GeoAccessor

    # get a dataframe to interrogate
    df = GeoAccessor.from_featureclass(features_small_segments)

    # ensure the walk restriction column exists
    assert "walk_restrictions" in df.columns

    # ensure not all values are null
    assert df["walk_restrictions"].notnull().any()

    # ensure some values are greater than zero
    assert (df["walk_restrictions"] > 0).any()