#!/usr/bin/env python3
"""Usage: bin/routes-summary.py LOG > summary.json

What a routes curate shard spent its time on (#210), from its log: the
slowest parks, the parks that hit --park-timeout, and routes' totals
("searching ... evaluating ...", "done in ..."). For build-area.yml's
"Build progress" check.
"""
import json, re, sys

# Name (id, or trail-id): T tiles, N nodes, D destinations (R reachable), H trailheads, ...;
# day 0.2s, ...: 5 day hikes, ... (1.3s)
PARK = re.compile(r'^(.*) \(([\w-]+)\): (\d+) tiles, (\d+) nodes, .*?, (\d+) trailheads,.*\(([\d.]+)s\)$')


def summarize(lines, top=10):
    parks, timeouts, notes = [], [], []
    for line in lines:
        line = line.rstrip('\n')
        if (m := PARK.match(line)):
            parks.append(dict(name=m[1], id=m[2], tiles=int(m[3]), nodes=int(m[4]),
                              trailheads=int(m[5]), seconds=float(m[6]),
                              timeout='(TIMEOUT' in line))
        elif line.startswith('TIMEOUT: '):
            timeouts.append(line[len('TIMEOUT: '):])
        elif line.startswith(('searching ', 'done in ', 'shard ')):
            notes.append(line)
    parks.sort(key=lambda p: -p['seconds'])
    return {
        'parks': len(parks),
        'park_seconds': round(sum(p['seconds'] for p in parks), 1),
        'slowest': parks[:top],
        'timeouts': timeouts,
        'notes': notes,
    }


def live(lines):
    """How far a shard is, from its log so far: parks curated of the shard's."""
    total = done = None
    for line in lines:
        if (m := re.match(r'shard \d+/\d+: (\d+) parks', line)):
            total, done = int(m[1]), 0
        elif total is not None and PARK.match(line.rstrip('\n')):
            done += 1
    if total is None:
        return None
    return {'phase': 'curate', 'done': done, 'total': total, 'unit': 'parks'}


if __name__ == '__main__':
    json.dump(summarize(open(sys.argv[1], errors='replace')), sys.stdout, indent=1)
    print()
