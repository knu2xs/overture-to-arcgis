---
title: ArcGIS Toolbox
---
# ArcGIS Toolbox Tools

The `overture_to_arcgis.pyt` Python Toolbox provides geoprocessing tools for use inside
**ArcGIS Pro**. The toolbox is located at `arcgis/overture_to_arcgis.pyt`.

## Data Retrieval

### Get Overture Features

Download features from Overture Maps for a given extent and save them to a feature class.
Supports all Overture feature types (place, segment, connector, building, etc.).

**Optional post-processing:**

- Add a `primary_name` text field parsed from the `names` JSON column.
- Add a `primary_category` text field parsed from the `categories` JSON column.

## Network Analysis

### Create Network Dataset

Build a walk-optimised network dataset from Overture segment and connector features.

**Modes of operation:**

- **Download data** — Provide a polygon extent and the tool downloads segment and connector
  features directly from Overture Maps.
- **Use existing features** — Point the tool at pre-downloaded segment (polyline) and connector
  (point) feature layers.

The tool performs the following steps automatically:

1. Copy features into a feature dataset.
2. Add `primary_name` field to segments.
3. Split segments by subclass rules.
4. Split segments by level (z-index) rules.
5. Split segments at connector points.
6. Add boolean access restriction fields.
7. Calculate `walk_impedance` values.
8. Create the network dataset from an XML template and build it.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| Download Data | Boolean | Whether to download data from Overture Maps. |
| Extent | Feature Set | Polygon extent for downloading (required when downloading). |
| Segment Features | Feature Layer (Polyline) | Pre-downloaded segments (required when not downloading). |
| Connector Features | Feature Layer (Point) | Pre-downloaded connectors (required when not downloading). |
| Output Geodatabase | Workspace | File geodatabase for the network dataset. |
| Feature Dataset Name | String | Name of the feature dataset (default: `overture_transportation`). |
| Network Dataset Name | String | Name of the network dataset (default: `overture_network`). |

## Add Parsed Fields

### Add Primary Name Field

Parse the `names` JSON column and add a `primary_name` text field containing the default name.

### Add Primary Category Field

Parse the `categories` JSON column and add a `primary_category` text field.

### Add Overture Taxonomy Code Fields

Parse category codes from the Overture taxonomy into separate fields.

### Add Boolean Access Restrictions Fields

Parse the `access_restrictions` JSON column into individual boolean fields for each access
mode (e.g. `access_denied_when_mode_foot`, `access_denied_when_mode_car`).

### Add Walk Impedance Column (Segments)

Calculate a `walk_impedance` cost multiplier for segment features based on road `class` and
`subtype`. Values below 1.0 prefer the segment for walking; values above 1.0 penalise it.

### Add Website Field

Parse the `websites` JSON column and add a `website` text field.

### Add H3 Index Field

Add an H3 spatial index field to features (requires the `h3` package).

## Segment Processing

### Add Subclasses

Split segment polylines into sub-features based on the `subclass_rules` JSON field.

### Split Segments into Level Features

Split segment polylines by `level_rules` and populate a `z_index` field.

### Split Segments at Connectors

Split segment polylines at connector point locations listed in the `connectors` field.
