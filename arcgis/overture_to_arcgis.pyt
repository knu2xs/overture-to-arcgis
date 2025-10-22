# -*- coding: utf-8 -*-
__version__ = "0.1.0.dev1"
__author__ = "Joel McCune (https://github.com/knu2xs)"
__license__ = "Apache 2.0"

import importlib.util
from pathlib import Path
import sys

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


# account for using relative path to package
if importlib.util.find_spec("overture_to_arcgis") is None:
    src_dir = find_pkg_source("overture_to_arcgis")
    if src_dir is not None:
        sys.path.append(str(src_dir))

# include custom code
import overture_to_arcgis


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
            AddOnewayField, 
            AddPrimaryCategoryField,
            AddAlternateCategoryField,
            AddWebsiteField,
            AddOvertureTaxonomyCodeFields,
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
        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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

        # add parameter to optionally add primary name field
        add_primary_name_field = arcpy.Parameter(
            displayName="Add Primary Name Field",
            name="add_primary_name_field",
            datatype="GPBoolean",
            category="Parsing",
            parameterType="Optional",
            direction="Input"
        )
        add_primary_name_field.value = True

        params = [extent, out_fc, overture_type, add_primary_name_field]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        extent_features = parameters[0].value
        out_fc = Path(parameters[1].valueAsText)
        overture_type = parameters[2].valueAsText

        # describe the extent features
        desc = arcpy.Describe(extent_features)

        # get the extent and spatial reference of the features
        extent = desc.extent
        spatial_reference = desc.spatialReference

        # if the spatial reference is not WGS84, project the extent to WGS84
        if spatial_reference.factoryCode != 4326:
            self.logger.info("Projecting extent to WGS84 (EPSG:4326).")
            projected_extent = extent.projectAs(arcpy.SpatialReference(4326))
            bbox = (projected_extent.XMin, projected_extent.YMin, projected_extent.XMax, projected_extent.YMax)
        else:
            bbox = (extent.XMin, extent.YMin, extent.XMax, extent.YMax)

        self.logger.info(f"Retrieving '{overture_type}' features for extent: {bbox}.")

        # get features and write to output feature class
        overture_to_arcgis.get_features(out_fc, bbox=bbox, overture_type=overture_type)

        # create feature layers for input selection features and output overture features
        ext_lyr = arcpy.management.MakeFeatureLayer(extent_features)[0]
        ovm_lyr = arcpy.management.MakeFeatureLayer(str(out_fc))[0]

        # select features in the overture layer that intersect the input extent features
        arcpy.management.SelectLayerByLocation(ovm_lyr, "INTERSECT", ext_lyr, selection_type="NEW_SELECTION", invert_spatial_relationship=True)

        # delete features not intersecting the input extent features
        arcpy.management.DeleteFeatures(ovm_lyr)

        # add primary name field if specified
        if parameters[3].valueAsText.lower() == "true":
            overture_to_arcgis.utils.add_primary_name(str(out_fc))

        return out_fc


class AddLayersForUniqueValues:
    """Tool adding a layer for each unique value in a specified field."""
    def __init__(self):
        self.label = "Add Layers for Unique Values"
        self.description = (
            "Add a layer for each unique value in a specified field."
        )
        self.category = "Utilities"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
    
class AddOnewayField:
    """Tool to add a 'oneway' field to a feature class."""
    def __init__(self):
        self.label = "Add One-Way Field (Segments)"
        self.description = (
            "Add a 'oneway' field to a feature class if it does not already exist."
        )
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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

        # add oneway field
        overture_to_arcgis.utils.add_oneway_field(input_features)

        return
    
class AddPrimaryCategoryField:
    """Tool to add a 'primary_category' field to a feature class."""
    def __init__(self):
        self.label = "Add Primary Category Field"
        self.description = (
            "Add a 'primary_category' field to a feature class if it does not already exist."
        )
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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
        self.category = "Parsing"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

    def getParameterInfo(self):

        # create a parameter to set the input feature layer
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="input_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # create a parameter to set the primary category field
        primary_category_field = arcpy.Parameter(
            displayName="Primary Category Field",
            name="primary_category_field",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        primary_category_field.value = "primary_category"
        primary_category_field.filter.type = "ValueList"

        params = [input_features, primary_category_field]

        return params

    def updateParameters(self, parameters):
        """Update the tool's parameters."""
        # update the primary category field value
        input_features = parameters[0]
        primary_category_field = parameters[1]
        
        if input_features.value:
            try:
                fields = [f.name for f in arcpy.ListFields(input_features.value) if f.type.upper() == 'TEXT']
                primary_category_field.filter.list = fields
            except Exception as e:
                arcpy.AddWarning(f"Could not list fields: {e}")
        return
    
    def execute(self, parameters, messages):
        """The source code of the tool."""

        # retrieve the data directory path from parameters
        input_features = parameters[0].value
        primary_category_field = parameters[1].valueAsText

        # add overture taxonomy code fields
        overture_to_arcgis.utils.add_overture_taxonomy_fields(input_features, primary_category_field=primary_category_field)

        return
    
class AddH3IndexField:
    """Tool to add H3 index field to a feature class."""
    def __init__(self):
        self.label = "Add H3 Index Field"
        self.description = (
            "Add an H3 index field to a feature class based on geometry."
        )
        self.category = "Utilities"

        # configure logging so messages bubble up through ArcPy
        self.logger = overture_to_arcgis.utils.get_logger("INFO", logger_name=f"overture_to_arcgis.{self.__class__.__name__}", add_arcpy_handler=True)

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