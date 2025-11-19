import math

slope_categories = {
    -1: {
        "description": "steep downhill",
        "slope_range": (-1.0, -0.03),
    },
    0: {
        "description": "moderate downhill",
        "slope_range": (-0.03, 0.0),
    },
    1: {
        "description": "flat",
        "slope_range": (0.0, 0.02),
    },
    2: {
        "description": "gentle uphill",
        "slope_range": (0.02, 0.05),
    },
    3: {
        "description": "moderate uphill",
        "slope_range": (0.05, 0.08),
    },
    4: {
        "description": "steep uphill",
        "slope_range": (0.08, 0.1),
    },
    5: {
        "description": "very steep uphill",
        "slope_range": (0.1, 0.15),
    },
    6: {
        "description": r"15 to 20% grade",
        "slope_range": (0.15, 0.2),
    },
    7: {
        "description": r"20 to 25% grade",
        "slope_range": (0.2, None),
    },
    8: {
        "description": r"25 to 30% grade",
        "slope_range": (0.25, 0.3),
    },
    9: {
        "description": r"30 to 35% grade",
        "slope_range": (0.3, 0.35),
    },
    10: {
        "description": r"35 to 40% grade",
        "slope_range": (0.35, 0.4),
    },
    11: {
        "description": r"40 to 45% grade",
        "slope_range": (0.4, 0.45),
    },
    12: {
        "description": r"45 to 50% grade",
        "slope_range": (0.45, 0.5),
    },
    13: {
        "description": r"50% grade and above",
        "slope_range": (0.5, None),
    },
}


def get_tobler_friction_coefficient(slope: float) -> float:
    """
    Get the coefficient of friction based on Tobler's hiking function. This function models walking speed as a function of slope,
    where a slope of -0.05 (5% downhill) yields the maximum walking speed. The coefficient is normalized such that a value of 1
    represents walking speed on flat ground, and values less than 1 represent slower walking speeds on uphill slopes.

    Args:
        slope (float): The slope (rise/run), e.g., elevation change divided by horizontal distance.

    Returns:
        float: Coefficient of friction (normalized walking efficiency).
    """
    baseline_speed = 5.04  # km/h at slope = 0
    speed = 6 * math.exp(-3.5 * abs(slope + 0.05))
    coeff = speed / baseline_speed
    return coeff


def get_cycle_friction_coefficient(slope: float) -> float:
    """
    Get the coefficient of friction for cycling based on slope where a 10% grade is perceived to be twice as hard as flat ground,
    but a gentle downhill (0-2%) makes cycling easier. For slopes between 0% and 2% uphill, the coefficient remains at 1. A coefficient
    greater than 1 indicates downhill cycling, flat is 1, and less than 1 indicates uphill cycling.

    !!! note:
        This is a simplified model where the coefficient decreases linearly with slope.

    Args:
        slope (float): The slope (rise/run), e.g., elevation change divided by horizontal distance.

    Returns:
        float: Coefficient of friction (normalized cycling efficiency).
    """
    if slope < 0:
        # Downhill cycling
        coeff = 1 + min(abs(slope) * 5, 0.5)  # Cap the benefit at 0.5
    elif 0 <= slope <= 0.02:
        # Flat to gentle uphill
        coeff = 1.0
    else:
        # Uphill cycling
        coeff = 1 - slope * 5
    return coeff


# def get_slope_segments(geometry):
#     """
#     Split the geometry into 100m segments and calculate the slope for each segment using the ArcGIS Python API calling the
#     Esri REST geometry service to get elevation for all start and end nodes. Based on binning slopes, if two adjacent
#     segments fall into the same slope bin, they are merged into a single segment. The final output is a list of segments
#     with their associated slopes.
#     Args:
#         geometry: An arcpy Polyline geometry object.
#     Returns:
#         list[tuple[arcpy.Polyline, float]]: A list of tuples where each tuple contains a segment geometry and its slope.
#     """
#     import arcpy
#     from overture_to_arcgis.utils._elevation import get_elevations_for_points

#     segment_length = 100  # meters
#     total_length = geometry.length
#     segments = []

#     # Create points at every 100m interval along the polyline
#     distances = list(range(0, int(total_length), segment_length))
#     if distances[-1] != int(total_length):
#         distances.append(int(total_length))

#     points = [geometry.positionAlongLine(d) for d in distances]
#     elevations = get_elevations_for_points(points)

#     # Create segments and calculate slopes
#     for i in range(len(points) - 1):
#         start_point = points[i]
#         end_point = points[i + 1]
#         start_elev = elevations[i]
#         end_elev = elevations[i + 1]

#         horiz_dist = start_point.distanceTo(end_point)
#         vert_dist = end_elev - start_elev
#         slope = vert_dist / horiz_dist if horiz_dist != 0 else 0

#         segment_geom = arcpy.Polyline(arcpy.Array([start_point, end_point]), geometry.spatialReference)
#         segments.append((segment_geom, slope))

#     # Merge segments with similar slopes
#     merged_segments = []
#     if segments:
#         current_segment, current_slope = segments[0]
#         for seg_geom, seg_slope in segments[1:]:
#             if (current_slope >= 0 and seg_slope >= 0 and abs(current_slope - seg_slope) < 0.01) or \
#                (current_slope < 0 and seg_slope < 0 and abs(current_slope - seg_slope) < 0.01):
#                 # Merge segments
#                 current_segment = arcpy.Polyline(arcpy.Array([current_segment.firstPoint, seg_geom.lastPoint]), geometry.spatialReference)
#                 current_slope = (current_slope + seg_slope) / 2  # Average slope
#             else:
#                 merged_segments.append((current_segment, current_slope))
#                 current_segment, current_slope = seg_geom, seg_slope
#     merged_segments.append((current_segment, current_slope))
#     return merged_segments
