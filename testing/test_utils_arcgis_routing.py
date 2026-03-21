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


def test_add_impedance_column_bike(
    features_small_segments: Path,
):
    """Test that bike_impedance field is created and populated."""
    _arcgis_routing.add_impedance_column(
        edge_features=features_small_segments,
        modality_prefix="bike",
    )

    import arcpy
    from arcgis.features import GeoAccessor

    df = GeoAccessor.from_featureclass(features_small_segments)

    assert "bike_impedance" in df.columns
    assert df["bike_impedance"].notnull().any()
    assert (df["bike_impedance"] > 0).any()


def test_add_impedance_column_bike_unknown_class(
    features_small_segments: Path,
):
    """Test that features with unrecognised class and subtype default to 1.0."""
    _arcgis_routing.add_impedance_column(
        edge_features=features_small_segments,
        modality_prefix="bike",
    )

    from arcgis.features import GeoAccessor

    df = GeoAccessor.from_featureclass(features_small_segments)

    known_classes = set(_arcgis_routing.IMPEDANCE_TYPE_COEFFICIENTS_BIKE["class"].keys())
    known_subtypes = set(_arcgis_routing.IMPEDANCE_TYPE_COEFFICIENTS_BIKE["subtype"].keys())
    df_unknown = df[
        ~df["class"].isin(known_classes) & ~df["subtype"].isin(known_subtypes)
    ]

    if df_unknown.empty:
        pytest.skip("no fully-unknown features in fixture")

    assert (df_unknown["bike_impedance"] == 1.0).all()


def test_add_impedance_column_bike_prohibited_subtype(
    features_small_segments: Path,
):
    """Test that water-subtype features receive impedance value -1.0."""
    _arcgis_routing.add_impedance_column(
        edge_features=features_small_segments,
        modality_prefix="bike",
    )

    from arcgis.features import GeoAccessor

    df = GeoAccessor.from_featureclass(features_small_segments)
    df_water = df[df["subtype"] == "water"]

    if df_water.empty:
        pytest.skip("no water-subtype features in fixture")

    assert (df_water["bike_impedance"] == -1.0).all()


def test_add_impedance_column_invalid_modality(
    features_small_segments: Path,
):
    """Test that an unknown modality_prefix raises a descriptive ValueError."""
    with pytest.raises(ValueError) as exc_info:
        _arcgis_routing.add_impedance_column(
            edge_features=features_small_segments,
            modality_prefix="car",
        )

    message = str(exc_info.value)
    assert "car" in message
    assert "Valid options:" in message
    assert "walk" in message or "bike" in message


def test_add_impedance_column_custom_coefficients(
    features_small_segments: Path,
):
    """Test that a custom coefficients dict overrides registry values."""
    _arcgis_routing.add_impedance_column(
        edge_features=features_small_segments,
        modality_prefix="walk",
        coefficients={"class": {"motorway": 99.0}, "subtype": {}},
    )

    from arcgis.features import GeoAccessor

    df = GeoAccessor.from_featureclass(features_small_segments)
    df_motorway = df[df["class"] == "motorway"]

    if df_motorway.empty:
        pytest.skip("no motorway features in fixture")

    assert (df_motorway["walk_impedance"] == 99.0).all()