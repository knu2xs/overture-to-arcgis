import pytest
from arcgis.features import elevation
from arcgis.features import FeatureSet
from arcgis.gis import GIS


@pytest.fixture(scope="session")
def gis():
    # gis object using locally configured profile
    gis = GIS(profile="bateam")
    return gis


@pytest.fixture(scope="session")
def line_feature_set():
    # create minimal FeatureSet with a single polyline feature
    esri_json = {
        "features": [
            {
                "geometry": {
                    "paths": [[[-122.9043002, 47.04709], [-122.9042782, 47.0469306]]],
                    "spatialReference": {"wkid": 4326, "latestWkid": 4326},
                },
                "attributes": {
                    "id": "c68827ce-f713-47e6-ab0c-b1191d85d211",
                    "OBJECTID": 1,
                },
            },
            {
                "geometry": {
                    "paths": [
                        [
                            [-122.9040824, 47.0464511],
                            [-122.9040767, 47.0464191],
                            [-122.9040562, 47.0463035],
                        ]
                    ],
                    "spatialReference": {"wkid": 4326, "latestWkid": 4326},
                },
                "attributes": {
                    "id": "2709812c-ee91-4188-82fa-bb96ccdf7096",
                    "OBJECTID": 2,
                },
            },
        ],
        "objectIdFieldName": "OBJECTID",
        "displayFieldName": "OBJECTID",
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "geometryType": "esriGeometryPolyline",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID"},
            {"name": "id", "type": "esriFieldTypeString", "alias": "id", "length": 36},
            {"name": "geometry", "type": "esriFieldTypeGeometry", "alias": "geometry"},
        ],
    }

    # Minimal input FeatureSet
    input_fs = FeatureSet.from_dict(esri_json)
    return input_fs


def test_profile(gis, line_feature_set):
    result = elevation.profile(
        input_line_features=line_feature_set,
        gis=gis,
        maximum_sample_distance=100,
        maximum_sample_distance_units="meters",
        future=False,
    )
    assert isinstance(result, FeatureSet)

def test_sample(gis, line_feature_set):
    result = elevation.summarize_elevation(
        input_features=line_feature_set,
        gis=gis,
        dem_resolution='FINEST',
        include_slope_aspect=True,
        future=False,
    )
    assert isinstance(result, FeatureSet)
