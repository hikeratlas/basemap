#!/usr/bin/env python3
"""Keeps a "Build progress" check run up to date while a build runs (#210).

Every minute until the run's other jobs have finished, it renders their
status and durations, next to the previous comparable build's (same
namespace and mode), and the tilemaker jobs' phase timings
(bin/tilemaker-phases.py, uploaded as phases-* artifacts), into a check run
on the build's commit.

With HISTORY=true, it also keeps a comment for the build on the "Build
history" issue, for a running record of build times.

Environment: GH_TOKEN (checks: write, actions: read, and issues: write for
HISTORY), GITHUB_REPOSITORY, GITHUB_RUN_ID, SHA, NAMESPACE, MODE, HISTORY.
"""
import io, json, os, signal, sys, time, traceback, urllib.error, urllib.request, zipfile
from datetime import datetime, timedelta, timezone

API = 'https://api.github.com'
REPO = os.environ['GITHUB_REPOSITORY']
RUN = int(os.environ['GITHUB_RUN_ID'])
SHA = os.environ['SHA']
NAMESPACE = os.environ['NAMESPACE']
MODE = os.environ['MODE']
SELF = os.environ.get('SELF_JOB', 'progress')
CHECK = 'Build progress'
# Whether to keep a comment on the "Build history" issue (manual north-america builds).
HISTORY = os.environ.get('HISTORY') == 'true'
TOKEN = os.environ['GH_TOKEN']
# Where the check run's id is kept, so the workflow's cleanup step (--close)
# can complete the check if this process is killed.
CHECK_ID_FILE = os.path.join(os.environ.get('RUNNER_TEMP', '/tmp'), 'build-progress-check-id')


class NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Artifact downloads redirect to blob storage, which rejects (401) the
    GitHub token urllib would otherwise forward."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header('Authorization')
        return new


OPENER = urllib.request.build_opener(NoAuthOnRedirect)


def request(method, path, body=None, raw=False):
    url = path if path.startswith('http') else API + path
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json'})
        try:
            with OPENER.open(req, timeout=60) as r:
                payload = r.read()
                return payload if raw else (json.loads(payload) if payload else None)
        except (urllib.error.URLError, TimeoutError) as e:
            client_error = isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code != 429
            if attempt == 3 or client_error:
                raise
            print(f'{method} {url}: {e}; retrying', file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def jobs(run):
    out, page = [], 1
    while True:
        r = request('GET', f'/repos/{REPO}/actions/runs/{run}/jobs?per_page=100&page={page}')
        # Skip this job, and the check run it creates: the jobs API lists
        # that too, and it can't finish before this script does.
        out += [j for j in r['jobs'] if j['name'] not in (SELF, CHECK)]
        if len(r['jobs']) < 100:
            return out
        page += 1


def artifacts(run):
    r = request('GET', f'/repos/{REPO}/actions/runs/{run}/artifacts?per_page=100')
    return {a['name']: a for a in r['artifacts']}


def artifact_json(artifact):
    """The single JSON file in an artifact, or None if it can't be read."""
    try:
        blob = request('GET', artifact['archive_download_url'], raw=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return json.loads(z.read(z.namelist()[0]))
    except Exception as e:
        print(f"artifact {artifact['name']}: {e}", file=sys.stderr)
        return None


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
        m = artifact_json(meta) or {}
        if m.get('namespace') == NAMESPACE and m.get('mode') == MODE:
            return candidate['id']
    return None


def t(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def minutes(secs):
    return f'{secs / 60:.0f}' if secs >= 60 else f'{secs / 60:.1f}'


def duration(j):
    if j and j.get('started_at') and j.get('completed_at'):
        return (t(j['completed_at']) - t(j['started_at'])).total_seconds()
    return None


def eta(cur, prev, t0, now):
    """When the build should finish: the previous build's length, shifted by
    how far ahead or behind the latest finished job is."""
    starts = [t(j['started_at']) for j in prev if j['started_at']]
    ends = [t(j['completed_at']) for j in prev if j['completed_at']]
    if not starts or not ends:
        return None
    pt0 = min(starts)
    prev_end = {j['name']: (t(j['completed_at']) - pt0).total_seconds() for j in prev if j['completed_at']}
    drift = 0
    finished = [j for j in cur if j['completed_at'] and j['name'] in prev_end]
    if finished:
        last = max(finished, key=lambda j: j['completed_at'])
        drift = (t(last['completed_at']) - t0).total_seconds() - prev_end[last['name']]
    return t0 + timedelta(seconds=(max(ends) - pt0).total_seconds() + drift)


def job_table(cur, prev, now):
    t0 = min(t(j['started_at']) for j in cur if j['started_at'])
    by_name = {j['name']: j for j in prev}
    rows, gantt, done = [], [], 0
    for j in sorted(cur, key=lambda j: j['started_at'] or 'z'):
        if j['conclusion'] == 'skipped':
            continue
        start, end = t(j['started_at']), t(j['completed_at'])
        dur = ((end or now) - start).total_seconds() if start else 0
        pdur = duration(by_name.get(j['name']))
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
    ends = [t(j['completed_at']) for j in cur if j['completed_at']]
    running = any(j['status'] != 'completed' for j in cur)
    elapsed = ((now if running or not ends else max(ends)) - t0).total_seconds()
    pt = None
    if prev:
        ps = [t(j['started_at']) for j in prev if j['started_at']]
        pe = [t(j['completed_at']) for j in prev if j['completed_at']]
        if ps and pe:
            pt = (max(pe) - min(ps)).total_seconds()
    total = sum(1 for j in cur if j['conclusion'] != 'skipped')
    title = f'{done} of {total} jobs done, {minutes(elapsed)} min'
    if running and (when := eta(cur, prev, t0, now)):
        left = max(0, (when - now).total_seconds())
        title += f', ~{minutes(left)} min left (ETA {when:%H:%M} UTC)'
    if pt:
        title += f' (previous build: {minutes(pt)} min)'
    summary = '\n'.join([
        '| Job | Status | Start (min) | Time (min) | Previous (min) |', '|---|---|---|---|---|', *rows, '',
        '```mermaid', 'gantt', '    dateFormat X', '    axisFormat %M min', *gantt, '```'])
    return title, summary


def phase_tables(phases, prev_phases):
    """One table per tilemaker run (phases-* artifacts)."""
    text = []
    for name in sorted(phases):
        prevp = {p['name']: p for p in prev_phases.get(name, {}).get('phases', [])}
        text += [f'#### {name}', '',
                 '| Phase | Time (s) | Previous (s) | CPU | iowait | Memory (GiB) |', '|---|---|---|---|---|---|']
        for p in phases[name]['phases']:
            q = prevp.get(p['name'])
            extra = ', '.join(f'{k} {p[k]:,}' for k in ('blocks', 'tiles') if k in p)
            pct = lambda k: f'{p[k]}%' if k in p else ''
            text.append(f"| {p['name']}{' (' + extra + ')' if extra else ''} | {p['seconds']:,} | "
                        f"{q['seconds'] if q else ''} | {pct('cpu')} | {pct('iowait')} | {p.get('mem_gib', '')} |")
        text.append('')
    return text


# The routes curate jobs' steps worth timing, by their names in routes.yml.
ROUTES_STEPS = [('download', 'Fetch the layers routes reads, and QRank'),
                ('curate', 'Curate'), ('upload', "Upload the shard's routes")]


def routes_tables(cur, prev, summaries, prev_summaries):
    """Per routes shard: download, curate and upload times (from the jobs'
    steps), parks and timeouts (routes-summary-* artifacts); then the
    slowest parks over all shards."""
    shards = sorted((j for j in cur if j['name'].startswith('routes / curate')), key=lambda j: j['name'])
    if not shards:
        return []
    by_name = {j['name']: j for j in prev}

    def step_secs(job):
        out = {}
        for key, name in ROUTES_STEPS:
            step = next((s for s in (job or {}).get('steps', []) if s['name'] == name), None)
            if step and step.get('started_at') and step.get('completed_at'):
                out[key] = (t(step['completed_at']) - t(step['started_at'])).total_seconds()
        return out

    text = ['#### routes', '',
            '| Shard | Download (min) | Curate (min) | Previous curate (min) | Upload (min) | Parks | Timeouts |',
            '|---|---|---|---|---|---|---|']
    slowest = []
    for j in shards:
        shard = j['name'][j['name'].rfind('(') + 1:].rstrip(')')
        cur_s, prev_s = step_secs(j), step_secs(by_name.get(j['name']))
        summ = summaries.get(shard, {})
        slowest += summ.get('slowest', [])
        fmt = lambda d, k: minutes(d[k]) if k in d else ''
        text.append(f"| {shard} | {fmt(cur_s, 'download')} | {fmt(cur_s, 'curate')} | {fmt(prev_s, 'curate')} | "
                    f"{fmt(cur_s, 'upload')} | {summ.get('parks', '')} | {len(summ.get('timeouts', [])) if summ else ''} |")
    prev_secs = {p['id']: p['seconds'] for s in prev_summaries.values() for p in s.get('slowest', [])}
    if slowest:
        text += ['', '| Slowest parks | Time (s) | Previous (s) | Nodes | Trailheads |', '|---|---|---|---|---|']
        for p in sorted(slowest, key=lambda p: -p['seconds'])[:10]:
            text.append(f"| {p['name']} ({p['id']}){' ⏱️ timed out' if p.get('timeout') else ''} | {p['seconds']} | "
                        f"{prev_secs.get(p['id'], '')} | {p['nodes']:,} | {p['trailheads']} |")
    for shard, summ in sorted(summaries.items()):
        for line in summ.get('timeouts', []):
            text.append(f'\n⏱️ Shard {shard}: {line}')
    text.append('')
    return text


def render(cur, prev, phases, prev_phases, summaries, prev_summaries):
    now = datetime.now(timezone.utc)
    title, summary = job_table(cur, prev, now)
    text = phase_tables(phases, prev_phases) + routes_tables(cur, prev, summaries, prev_summaries)
    return title, summary[:60000], '\n'.join(text)[:60000]


def load(run, prefix, into):
    """Reads the run's artifacts named PREFIX-* that aren't in INTO yet."""
    for name, a in artifacts(run).items():
        key = name[len(prefix):]
        if name.startswith(prefix) and key not in into and not a['expired']:
            p = artifact_json(a)
            if p:
                into[key] = p
    return into


class History:
    """A comment per manual north-america build on the "Build history" issue,
    edited in place as the build runs, for a running record of build times."""
    TITLE = 'Build history'

    def __init__(self):
        self.issue = self.comment = None

    def update(self, title, summary):
        url = f'https://github.com/{REPO}/actions/runs/{RUN}'
        body = f'### [{datetime.now(timezone.utc):%Y-%m-%d} {MODE} build]({url}): {title}\n\n{summary}'
        if self.comment:
            request('PATCH', f'/repos/{REPO}/issues/comments/{self.comment}', {'body': body})
            return
        if not self.issue:
            issues = request('GET', f'/repos/{REPO}/issues?state=open&per_page=100')
            found = [i for i in issues if i['title'] == self.TITLE and 'pull_request' not in i]
            self.issue = found[0]['number'] if found else request('POST', f'/repos/{REPO}/issues', {
                'title': self.TITLE,
                'body': 'One comment per manual north-america build, with its job times, '
                        'posted by bin/build-progress.py (#210).'})['number']
        self.comment = request('POST', f'/repos/{REPO}/issues/{self.issue}/comments', {'body': body})['id']


def watch(check_id):
    prev = previous_run()
    prev_jobs = jobs(prev) if prev else []
    prev_phases = load(prev, 'phases-', {}) if prev else {}
    prev_summaries = load(prev, 'routes-summary-', {}) if prev else {}
    phases, summaries = {}, {}
    history = History() if HISTORY else None
    while True:
        cur = jobs(RUN)
        load(RUN, 'phases-', phases)
        load(RUN, 'routes-summary-', summaries)
        title, summary, text = render(cur, prev_jobs, phases, prev_phases, summaries, prev_summaries)
        finished = all(j['status'] == 'completed' for j in cur)
        body = {'output': {'title': title, 'summary': summary, 'text': text or 'No phase timings yet.'}}
        if finished:
            body.update(status='completed', conclusion='neutral')
        request('PATCH', f'/repos/{REPO}/check-runs/{check_id}', body)
        if history:
            try:
                history.update(title, summary)
            except Exception as e:
                print(f'history comment: {e}', file=sys.stderr)
        if finished:
            return
        time.sleep(60)


def close(check_id, why):
    """Completes the check run, so it never stays in progress."""
    request('PATCH', f'/repos/{REPO}/check-runs/{check_id}', {
        'status': 'completed', 'conclusion': 'neutral',
        'output': {'title': 'Progress reporting stopped', 'summary': why[-60000:]}})


def main():
    if sys.argv[1:] == ['--close']:
        # Cleanup step: the watcher was killed (timeout, cancel) or crashed
        # before it could complete the check.
        try:
            check_id = open(CHECK_ID_FILE).read().strip()
        except FileNotFoundError:
            return
        check = request('GET', f'/repos/{REPO}/check-runs/{check_id}')
        if check['status'] != 'completed':
            close(check_id, 'The progress job stopped before the build finished; see its log.')
        return

    check = request('POST', f'/repos/{REPO}/check-runs', {
        'name': CHECK, 'head_sha': SHA, 'status': 'in_progress',
        'output': {'title': 'Starting', 'summary': 'Waiting for the first jobs.'}})
    with open(CHECK_ID_FILE, 'w') as f:
        f.write(str(check['id']))

    # Turn a cancel or timeout's SIGTERM into an exception, so the check is closed.
    def on_term(signum, frame):
        raise SystemExit(f'Stopped by signal {signum}.')
    signal.signal(signal.SIGTERM, on_term)

    try:
        watch(check['id'])
    except BaseException as e:
        why = traceback.format_exc() if not isinstance(e, SystemExit) else str(e)
        print(why, file=sys.stderr)
        close(check['id'], f'Progress reporting failed; the build itself is unaffected.\n\n```\n{why}\n```')
        # Reporting is best effort: don't fail the job over it.


if __name__ == '__main__':
    main()
