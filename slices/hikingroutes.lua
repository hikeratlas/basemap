-- OSM hiking route relations (export/hiking-routes.lua), from
-- hiking-routes.geojsonl via the "hiking_route" layer in hikingroutes.json,
-- for hikeratlas/routes' check of its routes against known hikes. Built into
-- layers/<ns>/hikingroutes.pmtiles, which tile-join leaves out of the map:
-- only routes reads it. Nothing comes from the PBF itself.
node_keys = {}
way_keys = {}
function node_function() end
function way_function() end
