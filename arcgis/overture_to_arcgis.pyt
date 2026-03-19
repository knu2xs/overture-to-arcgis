# -*- coding: utf-8 -*-
__version__ = "0.3.3"
__author__ = "Joel McCune (https://github.com/knu2xs)"
__license__ = "Apache 2.0"

import importlib.util
from pathlib import Path
import shutil
import sys
from tempfile import mkdtemp

import arcpy


def find_pkg_source(package_name) -> Path:
    """Helper to find relative package name"""
    # get the path to the current directory
    file_dir = Path(__file__).parent

    # try to find the package in progressively higher levels
    for idx in range(4):
        tmp_pth = file_dir / "src" / package_name
        if tmp_pth.exists():
            return tmp_pth.parent
        else:
            file_dir = file_dir.parent

    # if nothing fund, nothing returned
    return None


# always prefer local source so the PYT uses the latest code during development
src_dir = find_pkg_source("overture_to_arcgis")
if src_dir is not None:
    sys.path.insert(0, str(src_dir))

# include custom code
import overture_to_arcgis

# add logger for the module
logger = overture_to_arcgis.utils.get_logger(level="INFO", logger_name="overture_to_arcgis", add_arcpy_handler=True, add_stream_handler=False, propagate=False)


class Toolbox:
    def __init__(self):
        self.label = "Overture to ArcGIS"
        self.alias = "overture_to_arcgis"

        # List of tool classes associated with this toolbox
        self.tools = [
            GetOvertureFeatures,
            AddLayersForUniqueValues,
            AddPrimaryNameField,
            AddTrailField,
            AddPrimaryCategoryField,
            AddAlternateCategoryField,
            AddWebsiteField,
            AddOvertureTaxonomyCodeFields,
            AddBooleanAccessRestrictionsFields,
            SplitSegmentsIntoSubclassFeatures,
            SplitSegmentsIntoLevelFeatures,
            SplitSegmentsAtConnectors,
            AddWalkImpedanceColumn,
            CreateNetworkDataset
        ]

        # add H3 index field tool only if h3 is available
        if overture_to_arcgis.utils.has_h3:
            self.tools.append(AddH3IndexField)


class GetOvertureFeatures:
    def __init__(self):
        self.label = "Get Overture Features"
        self.description = (
            "Get Overture data as features."
        )

    def getParameterInfo(self):

        # create a parameter to set the extent interactively using a dynamic features set
        extent = arcpy.Parameter(
            displayName="Extent",
            name="extent",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Required",
            direction="Input"
        )

        # limit the feature set to a rectangular polygon
        # extent.featureSet.geometryType = "Polygon"
        # extent.featureSet.spatialReference = arcpy.SpatialReference(4326)  #

        # create a parameter to get the output feature class path
        out_fc = arcpy.Parameter(
            displayName="Output Feature Class",
            name="out_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )

        # create a parameter to set the overture type
        overture_type = arcpy.Parameter(
            displayName="Overture Type",
            name="overture_type",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        overture_type.filter.type = "ValueList"
        overture_type.filter.list = overture_to_arcgis.utils.get_all_overture_types()
        overture_type.value = "segment"

        # --- Post Processing parameters ---

        # boolean to add a primary_name field parsed from the names column
        add_primary_name = arcpy.Parameter(
            displayName="Add Primary Name",
            name="add_primary_name",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Post Processing"
        )
        add_primary_name.value = False

        # boolean to add a primary_category field parsed from the categories column
        add_primary_category = arcpy.Parameter(
            displayName="Add Primary Category",
            name="add_primary_category",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
            category="Post Processing"
        )
        add_primary_category.value = False

        params = [extent, out_fc, overture_type, add_primary_name, add_primary_category]

        return params

    # Overture types whose schema includes a 'names' field
    _TYPES_WITH_NAMES = {
        "building", "building_part", "division", "division_area",
        "infrastructure", "land", "land_use", "place", "segment", "water",
    }

    # Overture types whose schema includes a 'categories' field
    _TYPES_WITH_CATEGORIES = {"place"}

    def updateParameters(self, parameters):
        """Show post processing parameters only for applicable types."""
        overture_type = parameters[2]
        add_primary_name = parameters[3]
        add_primary_category = parameters[4]

        selected_type = overture_type.valueAsText

        # --- primary name: only for types with a 'names' field ---
        has_names = selected_type in self._TYPES_WITH_NAMES
        add_primary_name.enabled = has_names
        if not has_names:
            add_primary_name.value = False

        # --- primary category: only for types with a 'categories' field ---
        has_categories = selected_type in self._TYPES_WITH_CATEGORIES
        add_primary_category.enabled = has_categories
        if not has_categories:
            add_primary_category.value = False

        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        extent_features = parameters[0].value
        out_fc = Path(parameters[1].valueAsText)
        overture_type = parameters[2].valueAsText
        add_primary_name = parameters[3].value
        add_primary_category = parameters[4].value
        
        # describe the extent features
        desc = arcpy.Describe(extent_features)

        # get the extent and spatial reference of the features
        extent = desc.extent
        spatial_reference = desc.spatialReference

        # if the spatial reference is not WGS84, project the extent to WGS84
        if spatial_reference.factoryCode != 4326:
            logger.info("Projecting extent to WGS84 (EPSG:4326).")
            projected_extent = extent.projectAs(arcpy.SpatialReference(4326))
            bbox = (projected_extent.XMin, projected_extent.YMin, projected_extent.XMax, projected_extent.YMax)
        else:
            bbox = (extent.XMin, extent.YMin, extent.XMax, extent.YMax)

        logger.info(f"Retrieving '{overture_type}' features for extent: {bbox}.")

        # get features and write to output feature class
        overture_to_arcgis.get_features(out_fc, bbox=bbox, overture_type=overture_type)

        # create feature layers for input selection features and output overture features
        ext_lyr = arcpy.management.MakeFeatureLayer(extent_features)[0]
        ovm_lyr = arcpy.management.MakeFeatureLayer(str(out_fc))[0]

        # select features in the overture layer that intersect the input extent features
        arcpy.management.SelectLayerByLocation(ovm_lyr, "INTERSECT", ext_lyr, selection_type="NEW_SELECTION", invert_spatial_relationship=True)

        # delete features not intersecting the input extent features
        arcpy.management.DeleteFeatures(ovm_lyr)

        # --- Post Processing ---

        # add primary name field if requested
        if add_primary_name:
            field_names = [f.name for f in arcpy.ListFields(str(out_fc))]
            if "names" in field_names:
                logger.info("Adding primary_name field from names column.")
                overture_to_arcgis.utils.add_primary_name(str(out_fc))
            else:
                logger.warning("Skipping primary_name — 'names' field not found in features.")

        # add primary category field if requested
        if add_primary_category:
            field_names = [f.name for f in arcpy.ListFields(str(out_fc))]
            if "categories" in field_names:
                logger.info("Adding primary_category field from categories column.")
                overture_to_arcgis.utils.add_primary_category_field(str(out_fc))
            else:
                logger.warning("Skipping primary_category — 'categories' field not found in features.")

        return out_fc


class AddLayersForUniqueValues:
    """Tool adding a layer for each unique value in a specified field."""
    def __init__(self):
        self.label = "Add Layers for Unique Values"
        self.description = (
            "Add a layer for each unique value in a specified field."
        )
        self.category = "Utilities"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_layer = arcpy.Parameter(
            displayName="Input Layer",
            name="input_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # create a parameter to set the field name
        field_name = arcpy.Parameter(
            displayName="Field Name",
            name="field_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )

        # second parameter depends on the first
        field_name.parameterDependencies = [input_layer.name]

        params = [input_layer, field_name]

        return params
    
    def updateParameters(self, parameters):

        # unpack parameters to local variables
        input_layer, field_name = parameters

        if input_layer.altered and input_layer.value:
            # Layer is selected, populate field list
            field_names = [f.name for f in arcpy.ListFields(input_layer.valueAsText)
                        if f.type not in ('Geometry', 'OID')]
            field_name.filter.list = field_names
        else:
            # Layer is cleared, reset the second parameter
            field_name.filter.list = []
            field_name.value = None
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_layer = parameters[0].value
        field_name = parameters[1].valueAsText

        # get the current project and map
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        current_map = aprx.activeMap

        # get layers from unique values
        layers = overture_to_arcgis.utils.get_layers_for_unique_values(input_layer, field_name=field_name, arcgis_map=current_map)

        return

class AddPrimaryNameField:
    """Tool to add a 'primary_name' field to a feature class."""
    def __init__(self):
        self.label = "Add Primary Name Field"
        self.description = (
            "Add a 'primary_name' field to a feature class if it does not already exist."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].value

        # add primary name field
        overture_to_arcgis.utils.add_primary_name(input_features)

        return
    
class AddTrailField:
    """Tool to add a 'trail' field to a feature class."""
    def __init__(self):
        self.label = "Add Trail Field (Segments)"
        self.description = (
            "Add a 'trail' field to a feature class if it does not already exist."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        # add trail field
        overture_to_arcgis.utils.add_trail_field(input_features)

        return
    
    
class AddPrimaryCategoryField:
    """Tool to add a 'primary_category' field to a feature class."""
    def __init__(self):
        self.label = "Add Primary Category Field"
        self.description = (
            "Add a 'primary_category' field to a feature class if it does not already exist."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        # add primary category field
        overture_to_arcgis.utils.add_primary_category_field(input_features)

        return
    

class AddAlternateCategoryField:
    """Tool to add a 'alternate_category' field to a feature class."""
    def __init__(self):
        self.label = "Add Alternate Category Field"
        self.description = (
            "Add a 'alternate_category' field to a feature class if it does not already exist."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        # add alternate category field
        overture_to_arcgis.utils.add_alternate_category_field(input_features)

        return


class AddWebsiteField:
    """Tool to add a 'website' field to a feature class."""
    def __init__(self):
        self.label = "Add Website Field"
        self.description = (
            "Add a 'website' field to a feature class if it does not already exist."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        # add website field
        overture_to_arcgis.utils.add_website_field(input_features)

        return


class AddOvertureTaxonomyCodeFields:
    """Tool to add Overture taxonomy code fields to a feature class."""
    def __init__(self):
        self.label = "Add Overture Taxonomy Code Fields (Places)"
        self.description = (
            "Add Overture taxonomy code fields to a feature class based on the primary category."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params
    
    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].value

        # add overture taxonomy code fields
        overture_to_arcgis.utils.add_overture_taxonomy_fields(input_features)

        return
    

class AddH3IndexField:
    """Tool to add H3 index field to a feature class."""
    def __init__(self):
        self.label = "Add H3 Index Field"
        self.description = (
            "Add an H3 index field to a feature class based on geometry."
        )
        self.category = "Utilities"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # create a parameter to set the H3 resolution
        h3_resolution = arcpy.Parameter(
            displayName="H3 Resolution (0-15)",
            name="h3_resolution",
            datatype="GPLong",
            parameterType="Required",
            direction="Input"
        )
        h3_resolution.filter.type = "Range"
        h3_resolution.filter.list = [0, 15]
        h3_resolution.value = 9

        params = [input_features, h3_resolution]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText
        h3_resolution = int(parameters[1].valueAsText)

        # add H3 index field
        overture_to_arcgis.utils.add_h3_indices(input_features, resolution=h3_resolution)

        return
    

class AddBooleanAccessRestrictionsFields:
    """Tool to add boolean access restrictions fields to a feature class."""
    def __init__(self):
        self.label = "Add Boolean Access Restriction Fields (Segments)"
        self.description = (
            "Add a boolean access restrictions fields to a feature class based on access_restrictions."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        logger.debug(f"Input features: {input_features}")

        # add boolean access restrictions field
        overture_to_arcgis.utils.add_boolean_access_restrictions_fields(input_features)

        return


class SplitSegmentsIntoSubclassFeatures:
    """Tool to split segment features into subclass features based on subclass_rules."""
    def __init__(self):
        self.label = "Split Segments into Subclass Features"
        self.description = (
            "Split segment features into subsegments based on the 'subclass_rules' field. "
            "For each rule, a new feature is created for the specified geometry fraction with "
            "the 'subclass' field populated accordingly. Original features with splits are "
            "replaced by the new subsegment features."
        )
        self.category = "Utilities"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # filter to only line feature layers
        input_features.filter.list = ["Polyline"]

        # optional output feature class
        output_features = arcpy.Parameter(
            displayName="Output Features",
            name="output_features",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Output"
        )

        params = [input_features, output_features]

        return params

    def updateMessages(self, parameters):
        """Validate that the input features contain the required 'subclass_rules' field."""
        input_features = parameters[0]

        if input_features.altered and input_features.value:
            field_names = [f.name for f in arcpy.ListFields(input_features.valueAsText)]
            if "subclass_rules" not in field_names:
                input_features.setErrorMessage(
                    "Input features must contain a 'subclass_rules' field."
                )

        return

    def execute(self, parameters, messages):
        """Split features into subclass subsegments using the subclass_rules field."""

        # retrieve input features from parameters
        input_features = parameters[0].valueAsText
        output_features = parameters[1].valueAsText

        # split features into subclass features
        overture_to_arcgis.utils.split_into_subclass_features(
            input_features, output_features=output_features
        )

        return


class SplitSegmentsAtConnectors:
    """Tool to split segment polylines at connector points."""
    def __init__(self):
        self.label = "Split Segments at Connectors"
        self.description = (
            "Split segment polylines at connector points defined in the 'connectors' field. "
            "Each segment is split into sub-segments between consecutive connector positions, "
            "producing one new polyline feature per pair of adjacent connectors. "
            "Features with fewer than three connectors (start and end only) are left untouched."
        )
        self.category = "Utilities"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # filter to only line feature layers
        input_features.filter.list = ["Polyline"]

        # connector point features
        connector_features = arcpy.Parameter(
            displayName="Connector Features",
            name="connector_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # filter to only point feature layers
        connector_features.filter.list = ["Point"]

        # optional output feature class
        output_features = arcpy.Parameter(
            displayName="Output Features",
            name="output_features",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Output"
        )

        params = [input_features, connector_features, output_features]

        return params

    def updateMessages(self, parameters):
        """Validate that the input features contain the required fields."""
        input_features = parameters[0]
        connector_features = parameters[1]

        if input_features.altered and input_features.value:
            field_names = [f.name for f in arcpy.ListFields(input_features.valueAsText)]
            if "connectors" not in field_names:
                input_features.setErrorMessage(
                    "Input features must contain a 'connectors' field."
                )

        if connector_features.altered and connector_features.value:
            field_names = [f.name for f in arcpy.ListFields(connector_features.valueAsText)]
            if "id" not in field_names:
                connector_features.setErrorMessage(
                    "Connector features must contain an 'id' field."
                )

        return

    def execute(self, parameters, messages):
        """Split segment polylines at connector points."""

        # retrieve input features from parameters
        input_features = parameters[0].valueAsText
        connector_features = parameters[1].valueAsText
        output_features = parameters[2].valueAsText

        # split segments at connector points
        overture_to_arcgis.utils.split_segments_at_connectors(
            input_features,
            connector_features=connector_features,
            output_features=output_features,
        )

        return


class SplitSegmentsIntoLevelFeatures:
    """Tool to split segment features into level features based on level_rules."""
    def __init__(self):
        self.label = "Split Segments into Level Features"
        self.description = (
            "Split segment features into subsegments based on the 'level_rules' field. "
            "For each rule, a new feature is created for the specified geometry fraction with "
            "the 'z_index' field populated with the integer level value. Original features "
            "with splits are replaced by the new level-based subsegment features."
        )
        self.category = "Utilities"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # filter to only line feature layers
        input_features.filter.list = ["Polyline"]

        # optional output feature class
        output_features = arcpy.Parameter(
            displayName="Output Features",
            name="output_features",
            datatype="DEFeatureClass",
            parameterType="Optional",
            direction="Output"
        )

        params = [input_features, output_features]

        return params

    def updateMessages(self, parameters):
        """Validate that the input features contain the required 'level_rules' field."""
        input_features = parameters[0]

        if input_features.altered and input_features.value:
            field_names = [f.name for f in arcpy.ListFields(input_features.valueAsText)]
            if "level_rules" not in field_names:
                input_features.setErrorMessage(
                    "Input features must contain a 'level_rules' field."
                )

        return

    def execute(self, parameters, messages):
        """Split features into level subsegments using the level_rules field."""

        # retrieve input features from parameters
        input_features = parameters[0].valueAsText
        output_features = parameters[1].valueAsText

        # split features into level features
        overture_to_arcgis.utils.split_into_level_features(
            input_features, output_features=output_features
        )

        return


class AddWalkImpedanceColumn:
    """Tool to add walk impedance column to a feature class."""
    def __init__(self):
        self.label = "Add Walk Impedance Column (Segments)"
        self.description = (
            "Add walk impedance column to a feature class to using features for walk network routing."
        )
        self.category = "Add Parsed Fields"

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        params = [input_features]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].valueAsText

        # add walk impedance column
        overture_to_arcgis.utils.add_impedance_column(input_features, modality_prefix="walk")

        return


class CreateNetworkDataset:
    """Tool to create a network dataset from Overture segment and connector features."""
    def __init__(self):
        self.label = "Create Network Dataset"
        self.description = (
            "Create a network dataset from Overture segment (edge) and connector features. "
            "Performs subclass splitting, level splitting, connector splitting, access restriction "
            "field creation, and walk impedance calculation before building the network dataset."
        )
        # self.category = "Utilities"

    def getParameterInfo(self):

        # option to download data from Overture Maps
        download_data = arcpy.Parameter(
            displayName="Download Data",
            name="download_data",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input"
        )
        download_data.value = False

        # extent for downloading data
        extent = arcpy.Parameter(
            displayName="Extent",
            name="extent",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Optional",
            direction="Input"
        )

        # input segment features
        segment_features = arcpy.Parameter(
            displayName="Segment Features",
            name="segment_features",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input"
        )
        segment_features.filter.list = ["Polyline"]

        # input connector point features
        connector_features = arcpy.Parameter(
            displayName="Connector Features",
            name="connector_features",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input"
        )
        connector_features.filter.list = ["Point"]

        # output geodatabase
        geodatabase = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="geodatabase",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )
        geodatabase.filter.list = ["Local Database"]

        # feature dataset name
        feature_dataset_name = arcpy.Parameter(
            displayName="Feature Dataset Name",
            name="feature_dataset_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )
        feature_dataset_name.value = "overture_transportation"

        # network dataset name
        network_dataset_name = arcpy.Parameter(
            displayName="Network Dataset Name",
            name="network_dataset_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )
        network_dataset_name.value = "overture_network"

        params = [download_data, extent, segment_features, connector_features, geodatabase, feature_dataset_name, network_dataset_name]

        return params

    def updateParameters(self, parameters):
        """Toggle parameter availability based on download data selection."""
        download_data = parameters[0].value

        if download_data:
            parameters[1].enabled = True    # extent
            parameters[2].enabled = False   # segment_features
            parameters[3].enabled = False   # connector_features
        else:
            parameters[1].enabled = False   # extent
            parameters[2].enabled = True    # segment_features
            parameters[3].enabled = True    # connector_features

        return

    def updateMessages(self, parameters):
        """Validate parameters based on download data selection."""
        download_data = parameters[0].value

        if download_data:
            if not parameters[1].valueAsText:
                parameters[1].setErrorMessage("Extent is required when downloading data.")
        else:
            if not parameters[2].valueAsText:
                parameters[2].setErrorMessage("Segment Features is required when not downloading data.")
            if not parameters[3].valueAsText:
                parameters[3].setErrorMessage("Connector Features is required when not downloading data.")

        return

    def execute(self, parameters, messages):
        """Create a network dataset from edge and connector features."""
        # retrieve parameters
        download_data = parameters[0].value
        geodatabase = parameters[4].valueAsText
        feature_dataset_name = parameters[5].valueAsText or "overture_transportation"
        network_dataset_name = parameters[6].valueAsText or "overture_network"

        # variable for the temporary directory, so can be correctly handled in finally block below
        temp_dir = None

        try:
            if download_data:
                extent_features = parameters[1].value
                desc = arcpy.Describe(extent_features)
                extent = desc.extent
                spatial_reference = desc.spatialReference

                if spatial_reference.factoryCode != 4326:
                    logger.info("Projecting extent to WGS84 (EPSG:4326).")
                    projected_extent = extent.projectAs(arcpy.SpatialReference(4326))
                    bbox = (projected_extent.XMin, projected_extent.YMin, projected_extent.XMax, projected_extent.YMax)
                else:
                    bbox = (extent.XMin, extent.YMin, extent.XMax, extent.YMax)
                logger.info(f"Retrieving Overture features for extent: {bbox}.")

                # create temp directory and geodatabase for downloaded data
                temp_dir = mkdtemp()
                temp_gdb_name = "overture_temp.gdb"
                arcpy.management.CreateFileGDB(temp_dir, temp_gdb_name)
                temp_gdb = str(Path(temp_dir) / temp_gdb_name)

                logger.info(f"Downloading segment features.")
                segment_fc = str(Path(temp_gdb) / "segments")
                overture_to_arcgis.get_features(segment_fc, bbox=bbox, overture_type="segment")

                logger.info(f"Downloading connector features.")
                connector_fc = str(Path(temp_gdb) / "connectors")
                overture_to_arcgis.get_features(connector_fc, bbox=bbox, overture_type="connector")

                # remove features outside the extent geometry
                ext_lyr = arcpy.management.MakeFeatureLayer(extent_features)[0]

                seg_lyr = arcpy.management.MakeFeatureLayer(segment_fc)[0]
                arcpy.management.SelectLayerByLocation(seg_lyr, "INTERSECT", ext_lyr, selection_type="NEW_SELECTION", invert_spatial_relationship=True)
                arcpy.management.DeleteFeatures(seg_lyr)

                con_lyr = arcpy.management.MakeFeatureLayer(connector_fc)[0]
                arcpy.management.SelectLayerByLocation(con_lyr, "INTERSECT", ext_lyr, selection_type="NEW_SELECTION", invert_spatial_relationship=True)
                arcpy.management.DeleteFeatures(con_lyr)

                segment_features = segment_fc
                connector_features = connector_fc
            else:
                segment_features = parameters[2].valueAsText
                connector_features = parameters[3].valueAsText

            logger.info(f"Creating network dataset '{network_dataset_name}' in '{geodatabase}'.")

            # create the network dataset
            result = overture_to_arcgis.utils.create_network_dataset(
                segment_features=segment_features,
                connector_features=connector_features,
                geodatabase=geodatabase,
                feature_dataset_name=feature_dataset_name,
                network_dataset_name=network_dataset_name,
            )

            logger.info(f"Network dataset created at '{result}'.")

            # get the current map document, and add the network to it
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                current_map = aprx.activeMap
                if current_map is not None:
                    current_map.addDataFromPath(result)
                    logger.info("Network dataset added to the current map.")
                else:
                    logger.warning("No active map found; network dataset was not added to a map.")
            except Exception:
                logger.warning("Could not add network dataset to a map (not running inside ArcGIS Pro).")

        finally:
            if temp_dir is not None:
                logger.info(f"Cleaning up temporary directory '{temp_dir}'.")
                shutil.rmtree(temp_dir, ignore_errors=True)

        return