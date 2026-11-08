#!/usr/bin/env python3
"""Keeps a "Build progress" check run up to date while a build runs (#210).

It renders the build's jobs (status and durations, next to the previous
comparable build's: same namespace and mode, with an ETA), the tilemaker
runs' phase timings (bin/tilemaker-phases.py) and the routes shards'
summaries (bin/routes-summary.py) into a check run on the build's commit.

No job polls: that held a runner for the whole build. Instead:

  start   (a short job after config) creates the check, finds the previous
          build and stores its data, compressed, in the check itself; links
          the check from the PR's description, or for a manual
          north-america build (HISTORY=true) from a comment on the "Build
          history" issue.
  update  (the last step of the main jobs) merges the job's own results
          ($RUNNER_TEMP/phases-*.json, routes-summary-*.json) into that data
          and any other job's results it's missing (from their
          artifacts), and re-renders: a few API calls.
  finish  (a job after all the others, even if they failed or were
          cancelled) re-reads every artifact, in case two updates raced,
          and completes the check.

Environment: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, SHA; and for
start, NAMESPACE, MODE, PR, HISTORY. The token needs checks: write and
actions: read; start and finish also pull-requests: write (PR) and
issues: write (HISTORY).
"""
import base64, io, json, os, re, sys, time, traceback, urllib.error, urllib.request, zipfile, zlib
from datetime import datetime, timedelta, timezone

API = 'https://api.github.com'
REPO = os.environ['GITHUB_REPOSITORY']
RUN = int(os.environ['GITHUB_RUN_ID'])
SHA = os.environ['SHA']
TOKEN = os.environ['GH_TOKEN']
RUNNER_TEMP = os.environ.get('RUNNER_TEMP', '/tmp')
# Set from the environment by start, and from the check's data afterwards.
NAMESPACE = os.environ.get('NAMESPACE', '')
MODE = os.environ.get('MODE', '')
PR = os.environ.get('PR', '')
HISTORY = os.environ.get('HISTORY') == 'true'


def check_name():
    # A commit can have several builds (a push's and a manual one), and
    # GitHub shows each check under whichever of the commit's runs it likes,
    # so a non-PR build names its check after its namespace.
    return 'Build progress' if PR else f'Build progress ({NAMESPACE})'


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
        # Skip the progress jobs, and the check runs builds create: the jobs
        # API lists those too.
        out += [j for j in r['jobs'] if not j['name'].startswith(('progress', 'Build progress'))]
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
    edited as the build runs, for a running record of build times."""
    TITLE = 'Build history'

    def create(self, check_url):
        issues = request('GET', f'/repos/{REPO}/issues?state=open&per_page=100')
        found = [i for i in issues if i['title'] == self.TITLE and 'pull_request' not in i]
        issue = found[0]['number'] if found else request('POST', f'/repos/{REPO}/issues', {
            'title': self.TITLE,
            'body': 'One comment per manual north-america build, with its job times, '
                    'posted by bin/build-progress.py (#210).'})['number']
        url = f'https://github.com/{REPO}/actions/runs/{RUN}'
        return request('POST', f'/repos/{REPO}/issues/{issue}/comments', {
            'body': f'### [{datetime.now(timezone.utc):%Y-%m-%d} {MODE} build]({url}): starting\n\n[Build progress]({check_url})'})['id']


LINK = re.compile(r'<!-- build-progress -->.*?<!-- /build-progress -->\n*', re.S)


def link_from_pr(check_id, status, start=False):
    """Puts a link to this build's check at the top of the PR's description,
    replacing the previous build's when it starts. Later updates only touch
    the link while it's still this build's, so a superseded build's last
    update doesn't replace a newer build's link. (An edit with the job's
    token doesn't trigger workflows, so this doesn't rebuild the PR.)"""
    if not PR:
        return
    try:
        url = f'https://github.com/{REPO}/pull/{PR}/checks?check_run_id={check_id}'
        block = f'<!-- build-progress -->\n📊 **[Build progress]({url})** for {SHA[:7]}: {status}\n<!-- /build-progress -->\n\n'
        body = request('GET', f'/repos/{REPO}/pulls/{PR}')['body'] or ''
        current = LINK.search(body)
        if not start and not (current and f'check_run_id={check_id})' in current[0]):
            return
        new = block + LINK.sub('', body, count=1)
        if new != body:
            request('PATCH', f'/repos/{REPO}/pulls/{PR}', {'body': new})
    except Exception as e:
        print(f'PR link: {e}', file=sys.stderr)


def write_step_summary(title, summary, text):
    """The final report on this run's summary page too."""
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a') as f:
            f.write(f'## {check_name()}: {title}\n\n{summary}\n\n{text}\n')


# The data the renders need, kept at the end of the check's summary.
DATA = re.compile(r'\n*<!-- build-progress-data:([A-Za-z0-9+/=]+) -->')


def pack(data):
    return base64.b64encode(zlib.compress(json.dumps(data, separators=(',', ':')).encode(), 9)).decode()


def unpack(summary):
    m = DATA.search(summary or '')
    return json.loads(zlib.decompress(base64.b64decode(m[1]))) if m else None


def slim(jobs_):
    """What renders need of a previous build's jobs."""
    keep = ('name', 'status', 'conclusion', 'started_at', 'completed_at')
    out = []
    for j in jobs_:
        k = {x: j[x] for x in keep}
        if j['name'].startswith('routes / curate'):
            k['steps'] = [{x: st[x] for x in ('name', 'started_at', 'completed_at')} for st in j.get('steps', [])]
        out.append(k)
    return out


def find_check():
    """This run's check, by its external_id."""
    page = 1
    while True:
        r = request('GET', f'/repos/{REPO}/commits/{SHA}/check-runs?filter=all&per_page=100&page={page}')
        for c in r['check_runs']:
            if c.get('external_id') == str(RUN):
                return c
        if len(r['check_runs']) < 100:
            return None
        page += 1


def configure(meta):
    global NAMESPACE, MODE, PR, HISTORY
    NAMESPACE, MODE, PR, HISTORY = meta['namespace'], meta['mode'], meta.get('pr', ''), meta.get('history', False)


def publish(check, data, final=False):
    """Renders DATA with the run's current jobs into the check."""
    cur = jobs(RUN)
    title, summary, text = render(cur, data['prev_jobs'], data['phases'], data['prev_phases'],
                                  data['summaries'], data['prev_summaries'])
    if final and data.get('error'):
        title += ' (progress reporting hit an error; see the progress jobs\' logs)'
    blob = f'\n\n<!-- build-progress-data:{pack(data)} -->'
    body = {'output': {'title': title, 'summary': summary[:65000 - len(blob)] + blob,
                       'text': text or 'No phase timings yet.'}}
    if final:
        body.update(status='completed', conclusion='neutral')
    request('PATCH', f"/repos/{REPO}/check-runs/{check['id']}", body)
    if HISTORY and data['meta'].get('comment'):
        try:
            url = f'https://github.com/{REPO}/actions/runs/{RUN}'
            request('PATCH', f"/repos/{REPO}/issues/comments/{data['meta']['comment']}", {
                'body': f"### [{data['meta']['date']} {MODE} build]({url}): {title}\n\n{summary}"})
        except Exception as e:
            print(f'history comment: {e}', file=sys.stderr)
    return title, summary, text


def local_results():
    """This job's own phase timings and routes summary."""
    found = {'phases': {}, 'summaries': {}}
    for prefix, key in (('phases-', 'phases'), ('routes-summary-', 'summaries')):
        for f in os.listdir(RUNNER_TEMP):
            if f.startswith(prefix) and f.endswith('.json'):
                try:
                    found[key][f[len(prefix):-len('.json')]] = json.load(open(os.path.join(RUNNER_TEMP, f)))
                except ValueError as e:
                    print(f'{f}: {e}', file=sys.stderr)
    return found


def start():
    prev = previous_run()
    data = {
        'meta': {'namespace': NAMESPACE, 'mode': MODE, 'pr': PR, 'history': HISTORY, 'prev': prev,
                 'date': f'{datetime.now(timezone.utc):%Y-%m-%d}'},
        'prev_jobs': slim(jobs(prev)) if prev else [],
        'prev_phases': load(prev, 'phases-', {}) if prev else {},
        'prev_summaries': load(prev, 'routes-summary-', {}) if prev else {},
        'phases': load(RUN, 'phases-', {}), 'summaries': load(RUN, 'routes-summary-', {}),
    }
    check = request('POST', f'/repos/{REPO}/check-runs', {
        'name': check_name(), 'head_sha': SHA, 'status': 'in_progress', 'external_id': str(RUN),
        'output': {'title': 'Starting', 'summary': 'Waiting for the first jobs.'}})
    link_from_pr(check['id'], 'running', start=True)
    # The check may show up under another run of the commit, so link it
    # from this run's summary page.
    print(f"::notice title={check_name()}::{check['html_url']}", flush=True)
    if HISTORY:
        try:
            data['meta']['comment'] = History().create(check['html_url'])
        except Exception as e:
            print(f'history comment: {e}', file=sys.stderr)
    publish(check, data)
    # How later builds find this one to compare with (previous_run).
    with open('build-meta.json', 'w') as f:
        json.dump({'namespace': NAMESPACE, 'mode': MODE}, f)


def update():
    check = find_check()
    if not check:
        print('No progress check for this run yet.')
        return
    data = unpack(check['output']['summary'])
    if not data:
        return
    configure(data['meta'])
    mine = local_results()
    data['phases'].update(mine['phases'])
    data['summaries'].update(mine['summaries'])
    # And any other job's results the check is missing: jobs that finished
    # before start created the check, or whose update raced with another.
    # Only the missing artifacts are downloaded.
    load(RUN, 'phases-', data['phases'])
    load(RUN, 'routes-summary-', data['summaries'])
    publish(check, data)


def finish():
    check = find_check()
    if not check:
        print('No progress check for this run.')
        return
    data = unpack(check['output']['summary']) or {}
    if not data:
        return
    configure(data['meta'])
    # Every artifact again, in case two updates raced and one was lost.
    load(RUN, 'phases-', data['phases'])
    load(RUN, 'routes-summary-', data['summaries'])
    title, summary, text = publish(check, data, final=True)
    link_from_pr(check['id'], title)
    write_step_summary(title, summary, text)


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else ''
    try:
        {'start': start, 'update': update, 'finish': finish}[step]()
    except Exception:
        # Reporting is best effort: never fail a build job over it.
        print(traceback.format_exc(), file=sys.stderr)
        print(f'::warning::Build progress {step} failed; see the log.')


if __name__ == '__main__':
    main()
