#!/usr/bin/env python3
"""Usage: bin/tilemaker-phases.py LOG [TELEMETRY.jsonl ...] > phases.json

Where a tilemaker run spent its time (#210), from its output as
bin/timestamp-lines.py logged it: reading GeoJSON and shapefiles, scanning
the PBF, reading its nodes, ways and relations, collecting tiles and writing
them. With the telemetry action's samples (.github/actions/telemetry), each
phase also gets the CPU it used (user + system time over all of the
runner's cores), the share of time the CPUs waited on I/O, and the peak
memory in use.
"""
import json, re, sys

# tilemaker reads the PBF's nodes, then ways, then relations; each pass ends
# with a "Block i/n (N ms)" line. With a sharded --store, the ways and
# relations are read again for each shard.
PASS_NAMES = ['nodes', 'ways', 'relations']


def phases(lines):
    out = []
    def add(name, start, end, **extra):
        out.append(dict(name=name, start=start, end=end, seconds=round((end - start) / 1000, 1), **extra))

    loading = None
    pbf_passes = 0
    writing = None
    tiles = None
    for t, text in lines:
        if text.startswith(('Reading GeoJSON', 'Reading shapefile')) and loading is None:
            loading = t
        elif text.startswith('Reading .pbf'):
            if loading is not None:
                add('read GeoJSON/shapefiles', loading, t)
                loading = None
        elif (m := re.search(r'\(Scanning for (ways used in relations|nodes used in ways)[^)]*\)\s*\((\d+) ms\)', text)):
            name = 'scan relations' if m[1].startswith('ways') else 'scan ways'
            add(name, t - int(m[2]), t)
        elif (m := re.search(r'Block \d+/(\d+) \((\d+) ms\)', text)):
            name = PASS_NAMES[pbf_passes] if pbf_passes < len(PASS_NAMES) else f'PBF pass {pbf_passes + 1}'
            add(name, t - int(m[2]), t, blocks=int(m[1]))
            pbf_passes += 1
        elif (m := re.search(r'collecting tiles: (\d+)ms', text)):
            add('collect tiles', t - int(m[1]), t)
        elif (m := re.search(r'writing tile \d+ of (\d+)', text)):
            if writing is None:
                writing = t
            tiles = int(m[1])
        elif text.startswith(('Closing pmtiles file', 'Filled the tileset')) and writing is not None:
            add('write tiles', writing, t, tiles=tiles)
            writing = None
    return out


def resources(samples, start, end):
    """CPU busy (user + system) and iowait shares, in %, and peak memory in
    use, in GiB, between two times."""
    inside = [s for s in samples if start <= s['t'] <= end]
    if len(inside) < 2:
        return {}
    a, b = inside[0]['cpu'], inside[-1]['cpu']
    d = {k: b.get(k, 0) - a.get(k, 0) for k in ('user', 'system', 'idle', 'iowait', 'steal')}
    total = sum(d.values())
    out = {}
    if total > 0:
        out['cpu'] = round(100 * (d['user'] + d['system']) / total)
        out['iowait'] = round(100 * d['iowait'] / total)
    mem = [s['mem']['used'] for s in inside if 'mem' in s]
    if mem:
        out['mem_gib'] = round(max(mem) / 2**30, 1)
    return out


def main(log, *telemetry):
    lines = []
    for row in open(log, errors='replace'):
        t, _, text = row.rstrip('\n').partition('\t')
        if t.isdigit():
            lines.append((int(t), text))
    result = phases(lines)
    samples = []
    for path in telemetry:
        for row in open(path):
            try:
                samples.append(json.loads(row))
            except ValueError:
                pass
    samples.sort(key=lambda s: s['t'])
    for p in result:
        p.update(resources(samples, p['start'], p['end']))
    json.dump({'phases': result}, sys.stdout, indent=1)
    print()


if __name__ == '__main__':
    main(*sys.argv[1:])
