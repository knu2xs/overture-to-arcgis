import os
from pathlib import Path
from typing import Optional, Union

import arcpy

from ._arcgis_access import add_boolean_access_restrictions_fields
from ._arcgis_features import (
    split_into_level_features,
    split_into_subclass_features,
    split_segments_at_connectors,
)
from ._arcgis_fields import add_primary_name
from ._core import slugify
from ._logging import get_logger

# configure module logging
logger = get_logger(logger_name="overture_to_arcgis.utils._arcgis_routing", level="DEBUG", add_stream_handler=False)


# constants

# Restrictions coefficients for walking network routing — numeric impedance multipliers.
IMPEDANCE_TYPE_COEFFICIENTS_WALK = {
    'subtype': {
        'rail': 2,             
        'water': -1            
    },
    'class': {
        'bridleway': 1.1,      
        'cycleway': 0.8,       
        'footway': 0.7,        
        'living_street': 0.7,  
        'motorway': 2,         
        'path': 0.7,           
        'pedestrian': 0.7,     
        'primary': 1.5,          
        'secondary': 1.2,        
    }
}


def add_impedance_column(
    edge_features: Union[str, Path, arcpy._mp.Layer],
    modality_prefix: Optional[str] = "walk",
    ) -> Union[Path, arcpy._mp.Layer]:
    """
    Add impedance columns to the edge features for routing.

    Args:
        edge_features: The input line feature layer or feature class.
        modality_prefix: The prefix for the impedance field.

    Returns:
        Path or layer reference to the updated edge features.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(edge_features, Path):
        edge_features = str(edge_features)

    # ensure the input features exist
    if not arcpy.Exists(edge_features):
        raise FileNotFoundError("Cannot access the path for the input features.")
    
    # ensure the modality prefix is valid for the field name
    modality_prefix = slugify(modality_prefix)
    
    # ensure the subtype and class fields exist
    fields = [f.name for f in arcpy.ListFields(edge_features)]
    if "subtype" not in fields or "class" not in fields:
        raise ValueError("The input features must have 'subtype' and 'class' fields.")

    # type fields necessary to be in the schema
    type_fields = ('class', 'subtype')
    
    # add the impedance field if it does not exist
    impedance_field = f"{modality_prefix}_impedance"
    if impedance_field not in fields:
        arcpy.management.AddField(
            in_table=edge_features,
            field_name=impedance_field,
            field_type="FLOAT",
        )
        logger.info(f"Added field '{impedance_field}' to edge features.")
    else:
        logger.info(f"Field '{impedance_field}' already exists in edge features.")

    # update the impedance fields based on the IMPEDANCE_TYPE_COEFFICIENTS_WALK dictionary
    with arcpy.da.UpdateCursor(
        edge_features,
        type_fields + (impedance_field,)
    ) as cursor:
        
        # iterate through the rows
        for row in cursor:

            # get the type values
            type_values = {
                'class': row[0],
                'subtype': row[1],
            }

            # reset restriction value
            row[2] = None

            # set restriction values based on the type values
            for type_field, type_value in type_values.items():

                # check if there are restrictions for this type field and value
                if type_value in IMPEDANCE_TYPE_COEFFICIENTS_WALK[type_field]:

                    # get the restrictions for this type value
                    restriction = IMPEDANCE_TYPE_COEFFICIENTS_WALK[type_field][type_value]

                    # set the restriction value in the row
                    row[2] = restriction

                # provide a default restriction value if none is set
                if row[2] is None:
                    row[2] = 1.0

            cursor.updateRow(row)

    # make sure edge features are a path to return if path is a string
    if isinstance(edge_features, str):
        edge_features = Path(edge_features)

    return edge_features


def create_network_dataset(
    segment_features: Union[str, Path, arcpy._mp.Layer],
    connector_features: Union[str, Path, arcpy._mp.Layer],
    geodatabase: Union[str, Path],
    feature_dataset_name: Optional[str] = "overture_transportation",
    network_dataset_name: Optional[str] = "overture_network",
) -> Path:
    """
    Create a network dataset from the input features.

    Args:
        segment_features: The input line feature layer or feature class.
        connector_features: Point feature layer or feature class for connector features.
        geodatabase: The output geodatabase to create the network dataset in.
        feature_dataset_name: The name of the feature dataset to create the network dataset in.
        network_dataset_name: The name of the network dataset to create.

    Returns:
        Path to the created network dataset.
    """
    # function constant
    NETWORK_WALK_PATH = Path(__file__).parent.parent / "assets" / "walk_network.xml"

    # ensure network walk path exists
    if not NETWORK_WALK_PATH.exists():
        err_msg = f"Network walk path does not exist: {NETWORK_WALK_PATH}"
        logger.error(err_msg)
        raise FileNotFoundError(err_msg)

    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(segment_features, Path):
        segment_features = str(segment_features)

    # if the segment features is a layer, get the data source path
    if isinstance(segment_features, arcpy._mp.Layer):
        segment_features = segment_features.dataSource

    # ensure the input features exist
    if not arcpy.Exists(segment_features):
        err_msg = f"Cannot access the path for the input features: {segment_features}"
        logger.error(err_msg)
        raise FileNotFoundError(err_msg)

    # if the connector features are a path, convert to string - arcpy cannot handle Path objects
    if isinstance(connector_features, Path):
        connector_features = str(connector_features)

    # if the connector features are a layer, get the data source path
    if isinstance(connector_features, arcpy._mp.Layer):
        connector_features = connector_features.dataSource

    # ensure the connector features exist
    if not arcpy.Exists(connector_features):
        err_msg = f"Cannot access the path for the connector features: {connector_features}"
        logger.error(err_msg)
        raise FileNotFoundError(err_msg)

    # if the geodatabase is a Path, convert to string
    if isinstance(geodatabase, Path):
        geodatabase = str(geodatabase)

    # if the geodatabase does not exist, create it
    if not arcpy.Exists(geodatabase):
        arcpy.management.CreateFileGDB(
            out_folder=os.path.dirname(geodatabase),
            out_name=os.path.basename(geodatabase),
        )
        logger.info(f"Created geodatabase at '{geodatabase}'.")
    else:
        logger.info(f"Using existing geodatabase at '{geodatabase}'.")

    # if the feature dataset does not exist, create it
    feature_dataset_path = os.path.join(geodatabase, feature_dataset_name)
    if not arcpy.Exists(feature_dataset_path):
        # get the spatial reference from the input features
        spatial_ref = arcpy.Describe(segment_features).spatialReference

        arcpy.management.CreateFeatureDataset(
            out_dataset_path=geodatabase,
            out_name=feature_dataset_name,
            spatial_reference=spatial_ref,
        )

        logger.info(f"Created feature dataset '{feature_dataset_name}' in geodatabase.")

    else:
        logger.info(
            f"Using existing feature dataset '{feature_dataset_name}' in geodatabase."
        )

    # copy segment features into the feature dataset, overwriting any previous run's data
    segments_in_dataset = os.path.join(feature_dataset_path, "segments")
    if arcpy.Exists(segments_in_dataset):
        arcpy.management.Delete(segments_in_dataset)
        logger.info(f"Deleted existing segment features from feature dataset '{feature_dataset_name}'.")
    arcpy.management.CopyFeatures(segment_features, segments_in_dataset)
    logger.info(f"Copied segment features '{segment_features}' to feature dataset '{feature_dataset_name}'.")

    # copy connector features into the feature dataset, overwriting any previous run's data
    if connector_features is not None:
        connector_features_in_dataset = os.path.join(feature_dataset_path, "connectors")
        if arcpy.Exists(connector_features_in_dataset):
            arcpy.management.Delete(connector_features_in_dataset)
            logger.info(f"Deleted existing connector features from feature dataset '{feature_dataset_name}'.")
        arcpy.management.CopyFeatures(connector_features, connector_features_in_dataset)
        logger.info(f"Copied connector features '{connector_features}' to feature dataset '{feature_dataset_name}'.")

    # if the primary name column is not in the segment features, add and populate
    if "primary_name" not in [f.name for f in arcpy.ListFields(segments_in_dataset)]:
        logger.info(f"Adding and populating 'primary_name' field in segment features '{segments_in_dataset}'.")
        add_primary_name(segments_in_dataset)
    else:
        logger.info(f"Primary name field already exists in segment features '{segments_in_dataset}'.")

    # split into segments by subclass rules
    logger.info(f"Splitting segment features '{segments_in_dataset}' into segments by subclass rules.")
    split_into_subclass_features(segments_in_dataset, remove_original_field=True)

    # split segments into subsegments by level rules
    logger.info(f"Splitting segment features '{segments_in_dataset}' into subsegments by level (z-index) rules.")
    split_into_level_features(segments_in_dataset, remove_original_field=True)

    # split the segment features at the connector points
    logger.info(f"Splitting segment features '{segments_in_dataset}' at connector points '{connector_features_in_dataset}'.")
    split_segments_at_connectors(segments_in_dataset, connector_features_in_dataset, delete_connectors_field=True)

    # add boolean access restriction fields
    logger.info(f"Adding boolean access restriction fields.")
    add_boolean_access_restrictions_fields(segments_in_dataset, remove_original_field=True)

    # ensure the walk-prohibition field always exists for the network dataset template
    _FOOT_ACCESS_FIELD = "access_denied_when_mode_foot"
    if _FOOT_ACCESS_FIELD not in [f.name for f in arcpy.ListFields(segments_in_dataset)]:
        arcpy.management.AddField(
            in_table=segments_in_dataset,
            field_name=_FOOT_ACCESS_FIELD,
            field_type="SHORT",
        )
        logger.debug(f"Added missing field '{_FOOT_ACCESS_FIELD}' as SHORT to segment features.")
    else:
        logger.debug(f"Field '{_FOOT_ACCESS_FIELD}' already exists in segment features.")

    # add walk impedance column
    logger.info(f"Adding walk impedance column to segment features '{segments_in_dataset}'.")
    add_impedance_column(segments_in_dataset, modality_prefix="walk")

    # ensure the network template XML file has a valid XML declaration
    with open(NETWORK_WALK_PATH, "r", encoding="utf-8") as f:
        first_line = f.readline()
    if not first_line.strip().startswith("<?xml"):
        logger.warning("Network template XML missing declaration. Prepending XML declaration.")
        with open(NETWORK_WALK_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        with open(NETWORK_WALK_PATH, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n' + content)

    # delete existing network dataset before recreating to avoid conflicts on re-runs
    network_dataset_path = os.path.join(feature_dataset_path, network_dataset_name)
    if arcpy.Exists(network_dataset_path):
        arcpy.management.Delete(network_dataset_path)
        logger.info(f"Deleted existing network dataset '{network_dataset_name}' before recreating.")

    # create the network dataset
    logger.info(f"Creating network dataset '{network_dataset_name}' in feature dataset '{feature_dataset_path}'.")
    network_dataset = arcpy.na.CreateNetworkDatasetFromTemplate(
        network_dataset_template=str(NETWORK_WALK_PATH), 
        output_feature_dataset=feature_dataset_path,
    )[0]

    # build the network so it is ready to use
    logger.info('Building network dataset.')
    arcpy.na.BuildNetwork(network_dataset)

    return Path(network_dataset)
