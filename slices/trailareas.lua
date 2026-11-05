-- Trail areas (see bin/trail-areas.py), from trail-areas.geojsonl via the
-- "trail_area" layer in trailareas.json, for hikeratlas/routes. Built into
-- layers/<ns>/trailareas.pmtiles, which tile-join leaves out of the map: only
-- routes reads it. Nothing comes from the PBF itself.
node_keys = {}
way_keys = {}
function node_function() end
function way_function() end
