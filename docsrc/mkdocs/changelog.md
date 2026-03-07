---
title: Changelog
---
# Changelog

## Unreleased

### New Features

#### Create Network Dataset Tool

A new **Create Network Dataset** geoprocessing tool builds a walk-optimised network dataset from
Overture Maps transportation data (segment and connector features). The tool can either accept
pre-downloaded features or download them directly from Overture Maps for a given extent.

The tool orchestrates the full network preparation pipeline in a single step:

1. Split segments by subclass rules.
2. Split segments by level (z-index) rules.
3. Split segments at connector points.
4. Add boolean access restriction fields.
5. Calculate walk impedance values.
6. Create and build the network dataset from an XML template.

#### Walk Impedance Column

The renamed **Add Walk Impedance Column** tool (previously *Add Walk Restrictions Column*)
calculates a `walk_impedance` cost multiplier for each segment based on its road `class` and
`subtype`. Impedance coefficients have been recalibrated to produce more realistic walking route
preferences (e.g. footways = 0.7, motorways = 2.0).

#### Optional Field Cleanup After Processing

Several processing functions now accept an optional parameter to remove the source field after
processing is complete:

| Function | New Parameter |
|---|---|
| `add_boolean_access_restrictions_fields` | `remove_original_field` |
| `split_into_subclass_features` | `remove_original_field` |
| `split_into_level_features` | `remove_original_field` |
| `split_segments_at_connectors` | `delete_connectors_field` |

This is particularly useful when preparing features for a network dataset, where the original
JSON-encoded rule fields are no longer needed.

### Changes

- **GetOvertureFeatures simplified** — Post-processing parameters (split at connectors,
  split into subsegments/levels, add walk restrictions) have been removed from the
  `GetOvertureFeatures` tool to keep it focused on data retrieval. These operations are now
  handled by the dedicated `CreateNetworkDataset` tool or the individual standalone tools.
- **`add_restrictions_column` renamed to `add_impedance_column`** — The function, field name
  (`walk_impedance`), and constant dictionary have been updated to better reflect the
  impedance-based routing semantics.
- **Impedance coefficients recalibrated** — Walking impedance multipliers have been adjusted
  for more realistic route preferences.
- **Logger configuration improved** — The ArcGIS Python Toolbox logger now sets
  `add_stream_handler=False` and `propagate=False` to prevent duplicate log messages when
  running tools inside ArcGIS Pro.

### Bug Fixes

- **Null geometry guard in `split_into_level_features`** — Features with null geometry are now
  skipped with a warning instead of causing an unhandled error during the update cursor loop.
