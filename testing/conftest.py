"""
Pytest configuration file for arcgis-overture tests.

It is used to set up fixtures and configurations for running tests, 
especially when tests are spread acrsoss multiple files.
"""
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="function")
def tmp_dir():
    """Create a temporary directory for testing purposes. When the test is done, the directory and its contents are deleted."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture(scope="function")
def tmp_gdb(tmp_dir: Path):
    """Create a temporary file geodatabase for testing purposes. When the test is done, the geodatabase and its contents are deleted."""
    import arcpy

    gdb_pth: str = arcpy.management.CreateFileGDB(str(tmp_dir), "test.gdb")[0]
    yield Path(gdb_pth)


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Set up any necessary environment variables or configurations before tests run."""
    # Example: Set an environment variable
    import os

    os.environ["TEST_ENV"] = "true"
    yield
    # Teardown code can go here if needed
    del os.environ["TEST_ENV"]

@pytest.fixture(scope="session")
def extent_small():
    """Provide a small test extent area for tests."""
    # Small test extent area...downtown Olympia, WA
    return (-122.9049,47.0384,-122.8909,47.0473)


@pytest.fixture(scope="function")
def features_small(tmp_gdb: Path, extent_small: tuple[float, float, float, float]):
    """Provide a small set of test features for tests."""
    import arcpy

    fc_pth = tmp_gdb / "test_features_small"

    from overture_to_arcgis import get_features

    output_features = get_features(fc_pth, overture_type="segment", bbox=extent_small)

    yield output_features

    # remove using arcpy to avoid schema locks
    arcpy.Delete_management(fc_pth)
