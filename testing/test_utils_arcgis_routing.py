from pathlib import Path
import pytest

from overture_to_arcgis.utils import _arcgis_routing


def test_add_impedance_column_walk(
    features_small_segments: Path,
):
    """Test the add_walk_impedance_column function."""
    _arcgis_routing.add_impedance_column(
        edge_features=features_small_segments,
        modality_prefix="walk",
    )

    import arcpy
    from arcgis.features import GeoAccessor

    # get a dataframe to interrogate
    df = GeoAccessor.from_featureclass(features_small_segments)

    # ensure the walk impedance column exists
    assert "walk_impedance" in df.columns

    # ensure not all values are null
    assert df["walk_impedance"].notnull().any()

    # ensure some values are greater than zero
    assert (df["walk_impedance"] > 0).any()