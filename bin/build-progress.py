#!/usr/bin/env python3
"""Keeps a "Build progress" check run up to date while a build runs (#210).

Every minute until the run's other jobs have finished, it renders their
status and durations, next to the previous comparable build's (same
namespace and mode), and the tilemaker jobs' phase timings
(bin/tilemaker-phases.py, uploaded as phases-* artifacts), into a check run
on the build's commit.

Environment: GH_TOKEN (checks: write, actions: read), GITHUB_REPOSITORY,
GITHUB_RUN_ID, SHA, NAMESPACE, MODE.
"""
import io, json, os, sys, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone

API = 'https://api.github.com'
REPO = os.environ['GITHUB_REPOSITORY']
RUN = int(os.environ['GITHUB_RUN_ID'])
SHA = os.environ['SHA']
NAMESPACE = os.environ['NAMESPACE']
MODE = os.environ['MODE']
SELF = os.environ.get('SELF_JOB', 'progress')
TOKEN = os.environ['GH_TOKEN']


def request(method, path, body=None, raw=False):
    url = path if path.startswith('http') else API + path
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                return payload if raw else (json.loads(payload) if payload else None)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                raise
            print(f'{method} {url}: {e}; retrying', file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def jobs(run):
    out, page = [], 1
    while True:
        r = request('GET', f'/repos/{REPO}/actions/runs/{run}/jobs?per_page=100&page={page}')
        out += r['jobs']
        if len(r['jobs']) < 100:
            return out
        page += 1


def artifacts(run):
    r = request('GET', f'/repos/{REPO}/actions/runs/{run}/artifacts?per_page=100')
    return {a['name']: a for a in r['artifacts']}


def artifact_json(artifact):
    """The single JSON file in an artifact."""
    blob = request('GET', artifact['archive_download_url'], raw=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return json.loads(z.read(z.namelist()[0]))


def previous_run():
    """The last successful run of this workflow for the same namespace and mode."""
    run = request('GET', f'/repos/{REPO}/actions/runs/{RUN}')
    wf = run['workflow_id']
    r = request('GET', f'/repos/{REPO}/actions/workflows/{wf}/runs?status=success&per_page=30')
    for candidate in r['workflow_runs']:
        if candidate['id'] == RUN:
            continue
        meta = artifacts(candidate['id']).get('build-meta')
        if not meta or meta['expired']:
            continue
        m = artifact_json(meta)
        if m.get('namespace') == NAMESPACE and m.get('mode') == MODE:
            return candidate['id']
    return None


def t(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def minutes(secs):
    return f'{secs / 60:.0f}' if secs >= 60 else f'{secs / 60:.1f}'


def render(cur, prev, phases, prev_phases):
    t0 = min(t(j['started_at']) for j in cur if j['started_at'])
    now = datetime.now(timezone.utc)
    by_name = {j['name']: j for j in prev}
    rows, gantt, done = [], [], 0
    for j in sorted(cur, key=lambda j: j['started_at'] or 'z'):
        if j['name'] == SELF or j['conclusion'] == 'skipped':
            continue
        start, end = t(j['started_at']), t(j['completed_at'])
        dur = ((end or now) - start).total_seconds() if start else 0
        p = by_name.get(j['name'])
        pdur = (t(p['completed_at']) - t(p['started_at'])).total_seconds() if p and p['completed_at'] and p['started_at'] else None
        flag = ''
        if pdur and end and dur > pdur * 1.2 and dur - pdur > 60:
            flag = ' ⚠️'
        state = j['conclusion'] or j['status']
        done += j['status'] == 'completed'
        rows.append(f"| {j['name']} | {state} | {minutes((start - t0).total_seconds()) if start else ''} | "
                    f"{minutes(dur) + flag if start else ''} | {minutes(pdur) if pdur else ''} |")
        if start:
            gantt.append(f"    {j['name'].replace(':', ' ')} :{'done' if end else 'active'}, "
                         f"{int((start - t0).total_seconds())}, {max(1, int(dur))}s")
    ends = [t(j['completed_at']) for j in cur if j['name'] != SELF and j['completed_at']]
    running = any(j['status'] != 'completed' for j in cur if j['name'] != SELF)
    elapsed = ((now if running or not ends else max(ends)) - t0).total_seconds()
    pt = None
    if prev:
        ps = [t(j['started_at']) for j in prev if j['started_at']]
        pe = [t(j['completed_at']) for j in prev if j['completed_at']]
        if ps and pe:
            pt = (max(pe) - min(ps)).total_seconds()
    total = sum(1 for j in cur if j['name'] != SELF and j['conclusion'] != 'skipped')
    title = f'{done} of {total} jobs done, {minutes(elapsed)} min' + (f' (previous build: {minutes(pt)} min)' if pt else '')
    summary = '\n'.join([
        '| Job | Status | Start (min) | Time (min) | Previous (min) |', '|---|---|---|---|---|', *rows, '',
        '```mermaid', 'gantt', '    dateFormat X', '    axisFormat %M min', *gantt, '```'])
    text = []
    for name in sorted(phases):
        prevp = {p['name']: p for p in prev_phases.get(name, {}).get('phases', [])}
        text += [f'#### {name}', '', '| Phase | Time (s) | Previous (s) | CPU |', '|---|---|---|---|']
        for p in phases[name]['phases']:
            q = prevp.get(p['name'])
            extra = ', '.join(f'{k} {p[k]:,}' for k in ('blocks', 'tiles') if k in p)
            text.append(f"| {p['name']}{' (' + extra + ')' if extra else ''} | {p['seconds']:,} | "
                        f"{q['seconds'] if q else ''} | {str(p['cpu']) + '%' if 'cpu' in p else ''} |")
        text.append('')
    return title, summary[:60000], '\n'.join(text)[:60000]


def main():
    check = request('POST', f'/repos/{REPO}/check-runs', {
        'name': 'Build progress', 'head_sha': SHA, 'status': 'in_progress',
        'output': {'title': 'Starting', 'summary': 'Waiting for the first jobs.'}})
    prev = previous_run()
    prev_jobs = jobs(prev) if prev else []
    prev_phases = {}
    if prev:
        for name, a in artifacts(prev).items():
            if name.startswith('phases-') and not a['expired']:
                prev_phases[name[len('phases-'):]] = artifact_json(a)
    phases = {}
    while True:
        cur = jobs(RUN)
        for name, a in artifacts(RUN).items():
            key = name[len('phases-'):]
            if name.startswith('phases-') and key not in phases:
                phases[key] = artifact_json(a)
        title, summary, text = render(cur, prev_jobs, phases, prev_phases)
        finished = all(j['status'] == 'completed' for j in cur if j['name'] != SELF)
        body = {'output': {'title': title, 'summary': summary, 'text': text or 'No phase timings yet.'}}
        if finished:
            body.update(status='completed', conclusion='neutral')
        request('PATCH', f"/repos/{REPO}/check-runs/{check['id']}", body)
        if finished:
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
