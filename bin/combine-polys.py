#!/usr/bin/env python3
"""Combine Osmosis .poly files into one, for osmium extract -p.

  combine-polys.py <name> <in.poly>... > out.poly

A .poly file is a name line, then sections (an id line, "lon lat" lines,
END; an id starting with "!" is a hole), then a closing END. The output
has every input's sections, renumbered so the ids stay unique, holes kept
as holes. Geofabrik publishes one per extract, e.g.
https://download.geofabrik.de/north-america/canada.poly (basemap#158).
"""
import sys


def sections(path):
    with open(path) as f:
        lines = [l.rstrip('\n') for l in f]
    out, i = [], 1  # skip the file's name line
    while i < len(lines):
        head = lines[i].strip()
        if head == 'END':  # the file's closing END
            break
        if not head:
            i += 1
            continue
        pts = []
        i += 1
        while lines[i].strip() != 'END':
            if lines[i].strip():
                pts.append(lines[i])
            i += 1
        i += 1
        out.append((head.startswith('!'), pts))
    if not out:
        sys.exit(f'{path}: no polygons')
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(sys.argv[1])
    n = 0
    for path in sys.argv[2:]:
        for hole, pts in sections(path):
            n += 1
            print(f'{"!" if hole else ""}{n}')
            print('\n'.join(pts))
            print('END')
    print('END')


main()
