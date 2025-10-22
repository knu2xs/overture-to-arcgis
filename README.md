# Overture to ArcGIS

Utility for easily getting data from Overture into ArcGIS Pro.

## Getting Started

1 - Clone this repo.

2 - Create an environment with the requirements.
    
```
        > make env
```

3 - Try it out!

``` python
from arcgis_overture import get_spatially_enabled_dataframe

extent = (-119.911,48.3852,-119.8784,48.4028)

df = get_spatially_enabled_dataframe('places', extent)
```