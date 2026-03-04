import os
from pathlib import Path
from typing import Optional, Union

import arcpy


from ._core import slugify
from ._logging import get_logger

# configure module logging
logger = get_logger(logger_name=Path(__file__).stem, level="DEBUG", add_stream_handler=False)


# constants

# Restrictions for walking network routing — numeric impedance multipliers.
# REF: https://pro.arcgis.com/en/pro-app/latest/help/analysis/networks/restriction-attributes.htm#GUID-662D8A4E-556B-4717-9DE2-F0734023C7CF
RESTRICTIONS_WALK = {
    'subtype': {
        'rail': 5,             # 'avoid': 'high',
        'water': -1            # 'prohibited': 'true'
    },
    'class': {
        'bridleway': 1.3,      # 'avoid': 'low'
        'cycleway': 1.3,       # 'avoid': 'low'
        'footway': 0.2,        # 'prefer': 'high'
        'living_street': 0.5,  # 'prefer': 'medium'
        'motorway': 5,         # 'avoid': 'high'
        'path': 0.2,           # 'prefer': 'high',
        'pedestrian': 0.2,     # 'prefer': 'high'
        'primary': 5,          # 'avoid': 'high'
        'secondary': 2,        # 'avoid': 'medium'
    }
}


def add_restrictions_column(
    edge_features: Union[str, Path, arcpy._mp.Layer],
    modality_prefix: Optional[str] = "walk",
    ) -> Union[Path, arcpy._mp.Layer]:
    """
    Add restriction columns to the edge features for routing.

    Args:
        edge_features: The input line feature layer or feature class.
        modality_prefix: The prefix for the restriction field.

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
    
    # add the restriction field if it does not exist
    restriction_field = f"{modality_prefix}_restrictions"
    if restriction_field not in fields:
        arcpy.management.AddField(
            in_table=edge_features,
            field_name=restriction_field,
            field_type="FLOAT",
        )
        logger.info(f"Added field '{restriction_field}' to edge features.")
    else:
        logger.info(f"Field '{restriction_field}' already exists in edge features.")

    # update the restriction fields based on the RESTRICTIONS_WALK dictionary
    with arcpy.da.UpdateCursor(
        edge_features,
        type_fields + (restriction_field,)
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
                if type_value in RESTRICTIONS_WALK[type_field]:

                    # get the restrictions for this type value
                    restriction = RESTRICTIONS_WALK[type_field][type_value]

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
    edge_features: Union[str, Path, arcpy._mp.Layer],
    geodatabase: Union[str, Path],
    feature_dataset_name: str,
    network_dataset_name: str,
    travel_mode_name: Optional[str] = "Walking Distance",
) -> Path:
    """
    Create a network dataset from the input features.

    Args:
        edge_features: The input line feature layer or feature class.
        geodatabase: The output geodatabase to create the network dataset in.
        feature_dataset_name: The name of the feature dataset to create the network dataset in.
        network_dataset_name: The name of the network dataset to create.
        travel_mode_name: The name of the travel mode to use for the network dataset.

    Returns:
        Path to the created network dataset.
    """
    # if features is a path, convert to string - arcpy cannot handle Path objects
    if isinstance(edge_features, Path):
        edge_features = str(edge_features)

    # ensure the input features exist
    if not arcpy.Exists(edge_features):
        raise FileNotFoundError("Cannot access the path for the input features.")

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
        spatial_ref = arcpy.Describe(edge_features).spatialReference

        arcpy.management.CreateFeatureDataset(
            out_dataset=geodatabase,
            out_name=feature_dataset_name,
            spatial_reference=spatial_ref,
        )

        logger.info(f"Created feature dataset '{feature_dataset_name}' in geodatabase.")

    else:
        logger.info(
            f"Using existing feature dataset '{feature_dataset_name}' in geodatabase."
        )

    # create the network dataset
    output_network_dataset = arcpy.na.CreateNetworkDataset(
        feature_dataset=feature_dataset_path,
        out_name=network_dataset_name,
        source_feature_class_names=[edge_features],
        elevation_model="NO_ELEVATION"
    )[0]

    logger.info(
        f"Created network dataset '{output_network_dataset}' from features with travel mode '{travel_mode_name}'."
    )

    return Path(output_network_dataset)
