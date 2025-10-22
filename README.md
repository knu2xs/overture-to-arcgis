# Overture to ArcGIS

<!--start-->
Utility for easily getting data from Overture into ArcGIS Pro.

## Getting Started

1 - Clone this repo.

2 - Create an environment with the requirements.
    
```
        > make env
```

3 - Try it out!

There is a toolbox file for use within ArcGIS Pro at `./arcgis/overture_to_arcgis.pyt`. Use the `Make Overture Feature Class` tool to create a feature class from Overture data.

You can also use this utility directly from Python. Here is an example of getting a spatially enabled dataframe for places within a given extent.

``` python
from arcgis_overture import get_spatially_enabled_dataframe

extent = (-119.911,48.3852,-119.8784,48.4028)

df = get_spatially_enabled_dataframe('places', extent)
```

!!! note
    All extents must be in the format `(xmin, ymin, xmax, ymax)` and use WGS84 decimal degrees coordinates.

<!--end-->