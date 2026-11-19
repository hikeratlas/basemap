# route=hiking prevalence: Canada, US, mainland France

Exploratory analysis for a Hiker Atlas dev blog post (November 2026). Not
part of the basemap build.

## Inputs

Each area's `small` filtered PBF from R2, as mirror-pbfs.yml publishes it
(`pbfs/filtered/<area>/small.zstd.pbf`), converted for pyosmium:

    pbf-filter recompress --zlib small.zstd.pbf small.osm.pbf

and QRank's `qrank.db` (`bin/fetch-qrank`) for park fame. The results here
were made from the PBFs of 14 November (Canada, US) and 19 November 2026
(France); later mirrors replace those PBFs.

## Steps

    pip install osmium geopandas pyarrow shapely
    python3 -I extract.py canada.small.osm.pbf out/canada     # ~2 min; US ~15 min
    python3 -I fix_admin.py us.small.osm.pbf out/us 1116270    # Alaska
    python3 -I fix_admin.py france.small.osm.pbf out/france 3792876   # Grand Est
    python3 -I analyze.py out/canada CA                        # also US, FR

`analyze.py` reads `qrank.db` from `QRANK_DB` in the script.
Definitions are in its docstring.

## Results

`results/<area>/`: `summary.json`, and `states.csv`, `parks.csv`,
`routes.csv`. `page/` is the findings page (`index.html` with `__DATA__`
replaced by `data.json`).
