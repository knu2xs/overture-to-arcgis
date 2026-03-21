# Changelog

## Unreleased

### Breaking Changes

- **`AddWalkImpedanceColumn` toolbox tool removed** — The `AddWalkImpedanceColumn` ArcGIS Pro toolbox tool has been removed and replaced by `AddImpedanceColumn`. Any `.aprx` project or ArcGIS Catalog reference to `AddWalkImpedanceColumn` will no longer resolve. Update references to use `AddImpedanceColumn` instead, selecting `"walk"` as the modality.

- **`add_impedance_column` requires explicit `modality_prefix`** — The `modality_prefix` parameter of `add_impedance_column()` no longer has a default value. Callers that previously relied on the `"walk"` default must now pass `modality_prefix="walk"` explicitly:

  ```python
  # Before (no longer works)
  add_impedance_column(edge_features)

  # After
  add_impedance_column(edge_features, modality_prefix="walk")
  ```

### New Features

- **`bike_impedance` column** — `add_impedance_column()` now supports `modality_prefix="bike"`, adding a `bike_impedance` field populated from `IMPEDANCE_TYPE_COEFFICIENTS_BIKE`.

- **`modalities` parameter on `create_network_dataset()`** — The function now accepts an optional `modalities` list (default `["walk", "bike"]`). Both `walk_impedance` and `bike_impedance` are added to segment features by default. Pass `modalities=["walk"]` to restrict to walk-only as before.

- **`AddImpedanceColumn` toolbox tool** — New ArcGIS Pro toolbox tool replacing `AddWalkImpedanceColumn`. Features a modality combo-box (predefined options: walk, bike; custom names supported) and an editable coefficient table that pre-populates when a predefined modality is selected.

- **`SUPPORTED_MODALITIES`** — New public constant (`list[str]`) exported from `overture_to_arcgis.utils._arcgis_routing` listing all registered modality names.

- **`_IMPEDANCE_REGISTRY`** — New private module-level dict mapping modality name → coefficient table, serving as the single source of truth for impedance lookups.
