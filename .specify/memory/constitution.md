<!--
SYNC IMPACT REPORT
==================
Version change: (template / 0.0.0) → 1.0.0
Bump rationale: MAJOR — first substantive fill of the constitution template;
  establishes all principles and governance from scratch.

Modified principles:
  [PRINCIPLE_1_NAME] → I. Library-First
  [PRINCIPLE_2_NAME] → II. Toolbox as Thin Wrapper
  [PRINCIPLE_3_NAME] → III. WGS84 as Canonical CRS
  [PRINCIPLE_4_NAME] → IV. ArcGIS-Native Outputs
  [PRINCIPLE_5_NAME] → V. Testable Through Python

Added sections:
  "Development Tooling" (was [SECTION_2_NAME])
  "Contribution Workflow" (was [SECTION_3_NAME])

Templates reviewed:
  ✅ .specify/templates/plan-template.md — Constitution Check gate is generic; no changes needed.
  ✅ .specify/templates/spec-template.md — No principle-specific references; no changes needed.
  ✅ .specify/templates/tasks-template.md — No principle-specific references; no changes needed.
  ✅ .github/agents/* — Agent files are generic; no CLAUDE-specific or outdated references found.

Deferred TODOs:
  TODO(RATIFICATION_DATE): Original project adoption date unknown; marked below.
-->

# Overture to ArcGIS Constitution

## Core Principles

### I. Library-First

All business logic — data retrieval, coordinate transformation, field manipulation, network
dataset construction, and spatial filtering — MUST live in the `src/overture_to_arcgis/`
Python package. The package MUST be self-contained, independently importable, and usable
from plain Python scripts or notebooks without launching ArcGIS Pro.

**Non-negotiable rules**:
- New capabilities MUST be implemented as library functions before being surfaced in the toolbox.
- Library modules MUST have a clear, single responsibility (e.g., `_arcgis_routing.py`,
  `_arcgis_fields.py`).
- The library MUST NOT depend on a running ArcGIS Pro session for unit-level logic; `arcpy`
  usage is allowed but MUST be isolatable behind fixtures in tests.

### II. Toolbox as Thin Wrapper

The ArcGIS Pro Python Toolbox (`arcgis/overture_to_arcgis.pyt`) is a UI delegation layer
only. It MUST NOT contain algorithm implementations.

**Non-negotiable rules**:
- Tool `execute` methods MUST delegate immediately to library functions
  (e.g., `overture_to_arcgis.utils.*`, `overture_to_arcgis.get_features()`).
- Parameter construction (`getParameterInfo`), conditional enabling (`updateParameters`),
  and input validation (`updateMessages`) are the only logic permitted in the toolbox.
- Temporary workspace management (e.g., `mkdtemp`, cleanup in `finally`) is acceptable in
  `execute` as infrastructure scaffolding, not business logic.

### III. WGS84 as Canonical CRS

All interactions with the Overture Maps API use WGS84 (EPSG:4326) bounding boxes in the
format `(xmin, ymin, xmax, ymax)`. Any input geometry in a different CRS MUST be fully
normalized to WGS84 before a bounding box is computed or an API call is made.

**Non-negotiable rules**:
- Point feature inputs MUST derive their extent from actual feature coordinates (via cursor),
  not from `desc.extent`, which may reflect the spatial domain rather than true data extent.
- Non-point inputs MAY use `extent.projectAs(arcpy.SpatialReference(4326))`.
- Bounding box expansion (e.g., the 1-mile buffer for point inputs) MUST be applied in
  WGS84 degree units after reprojection.
- The `validate_bounding_box` utility MUST be used when accepting bbox values at public
  library entry points.

### IV. ArcGIS-Native Outputs

All persistent feature outputs MUST be stored as ArcGIS feature classes inside file
geodatabases (`.gdb`). No GeoJSON, shapefile, or CSV files are produced as primary outputs.

**Non-negotiable rules**:
- Output paths MUST be fully qualified paths inside a geodatabase or the ArcGIS in-memory
  workspace (`"memory/..."`).
- Temporary data created during a tool run MUST be cleaned up in a `finally` block.
- Optional in-memory layers (e.g., `MakeFeatureLayer`) MUST NOT be returned as tool outputs.

### V. Testable Through Python

All library functions MUST be independently testable with `pytest` without requiring an
interactive ArcGIS Pro session. The `testing/` directory is the canonical location for all
tests.

**Non-negotiable rules**:
- Every new library function MUST have at least one corresponding test in `testing/`.
- Tests MUST use fixtures (`conftest.py`) for temporary directories and geodatabases rather
  than hardcoded paths.
- Toolbox-level behaviour (parameter enable/disable, error messages) is integration-level
  and may be tested manually; it is not required to have automated pytest coverage.

## Development Tooling

- **Language**: Python 3.9+
- **Runtime dependency**: ArcGIS Pro conda environment (provides `arcpy`, `arcgis` SDK)
- **Key runtime packages**: `pyarrow`, `pandas`, `arcgis>=2.2.0`, `geomet`, `numpy`
- **Optional**: `h3` (H3 index field support — detected at import time via `has_h3`)
- **Environment setup**: `make env` (or `make.cmd env` on Windows)
- **Testing**: `pytest` — run from the repo root after activating the ArcGIS Pro environment
- **Versioning**: Semantic versioning (`MAJOR.MINOR.PATCH`); version is the single source of
  truth in `VERSION`, mirrored in `pyproject.toml` and `src/overture_to_arcgis/__init__.py`

## Contribution Workflow

1. Create a feature branch from `main` following the pattern `###-short-description`.
2. Implement library logic first; wire the toolbox afterward.
3. Add or update tests in `testing/` to cover new library behaviour.
4. Ensure all existing tests pass before opening a pull request.
5. Constitution amendments MUST be documented in the Sync Impact Report comment and
   reflected in the version line below.

## Governance

This constitution supersedes all other informal practices or ad-hoc conventions. Any
addition of a new principle, removal of an existing one, or redefinition of a
non-negotiable rule constitutes a MAJOR version bump. Adding new guidance or sections
without changing existing rules is a MINOR bump. Clarifications and wording fixes are
PATCH bumps.

All pull request reviews MUST verify compliance with the five core principles above.
Complexity that cannot be justified against these principles MUST be simplified or deferred.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): set to original project adoption date | **Last Amended**: 2026-03-19

