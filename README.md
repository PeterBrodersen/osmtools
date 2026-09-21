# OpenStreetMap Tools
These OpenStreetMap tools have been created to support the [OpenStreetMap Etymology](https://github.com/PeterBrodersen/osmetymology/tree/generic) project.

## OpenStreetMap Etymology
OpenStreetMap is a freely available map resource. Wikidata is a freely available structured data resource.

OpenStreetMap uses tags such as [`name:etymology:wikidata`](https://wiki.openstreetmap.org/wiki/Key:name:etymology:wikidata) to link to Wikidata items. Using these items it is possible to show maps based on different topics such as country, gender, profession and so on.

## OSM Etymology Project
The [OpenStreetMap Etymology](https://github.com/PeterBrodersen/osmetymology/tree/generic) project is a resource to fetch, aggregate and display etymology data for an area (city, country, etc.).

Check out live versions for the project:
* [Denmark](https://navne.findvej.dk/)
* [Paris](https://noms.findvej.dk/)
* [Berlin](https://berlin.etymology.findvej.dk/)
* [London](https://london.etymology.findvej.dk/)

# Tools
A couple of different tools are available here to help adding data to Wikidata, enriching OSM files with gender information, and so on.

## [Wikidata Auto](www/wikidata_auto.html)
Static HTML interface to add new items (places and persons) to Wikidata.

These items are mostly focused around Denmark. It supports fetching information from OpenStreetMap based on node/way/relation id, making it faster to import OpenStreetMap data to Wikidata.

The page creates QuickStatements to be used for the [QuickStatements](https://quickstatements.toolforge.org/) interface.

* [Live version](https://osmtools.findvej.dk/wikidata_auto.html)

If an item is created from an OpenStreetMap object it is recommended to add the new item back to the OpenStreetMap object as a `wikidata` object. This can be done with the [OWL Map](https://map.osm.wikidata.link/).

Shortcut to the specific item for OWL Map, e.g. for Wikidata item `Q12334493`:
```
https://map.osm.wikidata.link/item/Q12334493
```

## [Add tags to OSM file](tools/osm_add_tags.py)
Run `osm_add_tags.py` to enrich an existing OSM file (e.g. a .PBF file) with gender tags or descriptions.

This requires a local database and import for the same OSM file, usually created with the [OpenStreetMap Etymology](https://github.com/PeterBrodersen/osmetymology/tree/generic) project.

## [Create routing files that ignores roads based on gender](tools/restrictions/start.sh)
For use with [OSRM - Open Source Routing Machine](https://project-osrm.org/). This requires an OSM file that has been enriched with gender tags.

(To-do: more information about how to run the service as well as rolling out local [OSRM instances](https://github.com/Project-OSRM/osrm-backend) and [frontends](https://github.com/Project-OSRM/osrm-frontend).)

## [Find Wikidata "Named after" matches for OpenStreetMap roads](tools/wikidatamatch/match_wikidata_street_names.py)
Compare Wikidata roads to OpenStreetMap roads and find possible `name:etymology:wikidata` candidates.

Find Wikidata roads with [P138](https://www.wikidata.org/wiki/Property:P138) ("named after") in an administrative territorial entity (e.g. [Q5245991](https://www.wikidata.org/wiki/Q5245991) for Oslo Municipality) and compare it with a similar extraction for an OpenStreetMap file, e.g. a .pbf file.

Run the command with the Wikidata item and the local .pbf file. You might want to add languages for Wikidata as well.

Example:

```bash
./match_wikidata_street_names.py Q5245991 oslo.osm.pbf
```

### Extract municipality from country file:

If you have an area file with all the administrative boundaries and want to create a .pbf file for a single administrative area you can use `ogr2ogr` to create a boundary file for the administrative area and afterwards `osmium` to create the final .pbf dataset for that area.

Example: `norge_kommuner.fgb` is a boundary file. We want to fetch the municipality with `navn` set to `Oslo` and use that boundary to fetch all the OpenStreetMap data from `norway-latest.osm.pbf`:

```bash
ogr2ogr -f GeoJSON oslo.geojson norge_kommuner.fgb -where "navn = 'Oslo'" 
osmium extract -p oslo.geojson norway-latest.osm.pbf -o oslo.osm.pbf --overwrite -s smart
```

Run the command without arguments for help.

## [Find Wikidata items with OpenStreetMap references](tools/wikidata_etymology_to_osm.py).
OpenStreetMap objects might refer to Wikidata items using the `wikidata` tag.

These Wikidata items might already have a property value for [what the item is named after](https://www.wikidata.org/wiki/Property:P138).

This script uses an OSM file to fetch objects and requests all items from Wikidata using the [SPARQL interface](https://query.wikidata.org/).

## [Statistics for `name:etymology:wikidata` per country](tools/stats/count_per_area.py)
Simple script to generate JSON and CSV files with statistics to find countries with the most objects with the etymology tag. Requires no input file.

This script uses data from [GeoFabrik](https://download.geofabrik.de/) and performs about 550 API requests.

## [Statistics for user contributions](tools/get_etymology_contributors.py)
Script to find who contibuted with etymology tags. Requires OSM file.

This script fetches the history data for every OSM object in the OSM file that has `name:etymology:wikidata` present. This method might not be completely exact as it is based on individual objects with the related quirks (objects might have been deleted or split, subtracting from or adding to the count).

# LLM
Full disclosure: Some of the code has been created with the help of Copilot.
