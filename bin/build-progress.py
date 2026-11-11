#!/usr/bin/env python3
"""Keeps a "Build progress" check run up to date while a build runs (#210).

It renders the build's jobs (status and durations, next to the previous
comparable build's: same namespace and mode, with an ETA), the tilemaker
runs' phase timings (bin/tilemaker-phases.py) and the routes shards'
summaries (bin/routes-summary.py) into a check run on the build's commit.

No job polls: that held a runner for the whole build. Instead:

  start   (a short job after config) creates the check, finds the previous
          build and stores its data, compressed, in the check itself; and
          takes over the build's progress comment: the PR's (linked from its
          description), or for a manual north-america build (HISTORY=true)
          the "Build history" issue's, which holds the latest build's.
  update  (the last step of the main jobs) merges the job's own results
          ($RUNNER_TEMP/phases-*.json, routes-summary-*.json) into that data
          and any other job's results it's missing (from their
          artifacts), and re-renders: a few API calls.
  live    (in the background of the long jobs) puts where the job's
          tilemaker or routes run is now (phase, progress, when the phase
          should end) into the check every few minutes.
  finish  (a job after all the others, even if they failed or were
          cancelled) re-reads every artifact, in case two updates raced,
          and completes the check.

The progress comment shows all the check's page does, without the
check page's sidebar of every job on the commit (a long scroll on a
phone): the job table and what's running now, then the phase timings and
routes tables, folded. Every step that renders the check edits it too.

Environment: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, SHA; and for
start, NAMESPACE, MODE, PR, HISTORY. The token needs checks: write,
actions: read and issues: write (the comment); start and finish also
pull-requests: write (the PR's description).
"""
import base64, importlib.util, io, json, os, random, re, sys, time, traceback, urllib.error, urllib.request, zipfile, zlib
from datetime import datetime, timedelta, timezone

API = 'https://api.github.com'
REPO = os.environ['GITHUB_REPOSITORY']
RUN = int(os.environ['GITHUB_RUN_ID'])
# The run's number in the workflow, as GitHub shows it ("Build area #689").
RUN_NUMBER = os.environ.get('GITHUB_RUN_NUMBER', '')
SHA = os.environ['SHA']
TOKEN = os.environ['GH_TOKEN']
RUNNER_TEMP = os.environ.get('RUNNER_TEMP', '/tmp')
# Set from the environment by start, and from the check's data afterwards.
NAMESPACE = os.environ.get('NAMESPACE', '')
MODE = os.environ.get('MODE', '')
PR = os.environ.get('PR', '')
HISTORY = os.environ.get('HISTORY') == 'true'
# How many builds the "Build history" issue's description lists.
HISTORY_LINES = 25


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


# The job token's API budget left this hour, from the last response. It's
# 1,000 an hour for the whole repository, shared by every job of every run.
REMAINING = None
# The live loops skip their updates below this, leaving the rest for the
# jobs that need the API.
LIVE_RESERVE = 400


def request(method, path, body=None, raw=False):
    url = path if path.startswith('http') else API + path
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json'})
        try:
            with OPENER.open(req, timeout=60) as r:
                global REMAINING
                if r.headers.get('x-ratelimit-remaining', '').isdigit():
                    REMAINING = int(r.headers['x-ratelimit-remaining'])
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


def link(text, url):
    """TEXT linked to URL (a job's page), if there is one."""
    return f'[{text}]({url})' if url and text else text


def job_table(cur, prev, now):
    t0 = min((t(j['started_at']) for j in cur if j['started_at']), default=now)
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
        # Each job links to its page (its log); the previous time, to the
        # previous build's job, where its data has the link.
        p = by_name.get(j['name']) or {}
        rows.append(f"| {link(j['name'], j.get('html_url'))} | {state} | {minutes((start - t0).total_seconds()) if start else ''} | "
                    f"{minutes(dur) + flag if start else ''} | {link(minutes(pdur), p.get('html_url')) if pdur else ''} |")
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


def live_table(cur, live, phases, summaries, now):
    """Where each long run is now (#210), from the live entries the jobs'
    background loops (build-progress.py live) keep in the check's data."""
    rows = []
    now_ms = now.timestamp() * 1000
    steps = {j['name']: j.get('steps', []) for j in cur}
    for name, e in sorted(live.items()):
        shard = name[len('routes-'):] if name.startswith('routes-') else None
        finished = shard in summaries if shard is not None else name in phases
        if finished or now_ms - e.get('updated', 0) > 15 * 60 * 1000:
            continue
        eta = e.get('eta')
        if shard is not None and e.get('done'):
            # Routes' log has no times: time the shard from its Curate step.
            step = next((st for st in steps.get(f'routes / curate ({shard})', []) if st['name'] == 'Curate'), None)
            if step and step.get('started_at'):
                begun = t(step['started_at']).timestamp() * 1000
                eta = begun + (e['updated'] - begun) * e['total'] / e['done']
        progress = ''
        if e.get('total'):
            unit = '' if e['unit'] == '%' else f" {e['unit']}"
            progress = (f"{e['done']}%" if e['unit'] == '%' else
                        f"{e['done']:,} of {e['total']:,}{unit} ({100 * e['done'] // e['total']}%)")
        ends = ''
        if eta:
            ends = f"~{minutes(max(0, (eta - now_ms) / 1000))} min ({datetime.fromtimestamp(eta / 1000, timezone.utc):%H:%M} UTC)"
        rows.append(f"| {name} | {e['phase']} | {progress} | {ends} | {minutes((now_ms - e['updated']) / 1000)} min ago |")
    if not rows:
        return []
    return ['#### Running now', '', '| Run | Phase | Progress | Phase ends | Updated |', '|---|---|---|---|---|', *rows, '']


def regressions(summaries, prev_summaries):
    """The named regressions (routes' fixtures/expect/, checked by the
    routes merge job as routes-summary-regressions): a note for the title
    if any is failing, a line for the summary (with what changed since the
    previous build), and a table for the details."""
    reg = summaries.get('regressions')
    if not reg:
        return '', [], []
    rows = [r for r in reg.get('regressions', []) if r.get('status') != 'skipped']
    if not rows:
        return '', [], []
    before = {r['name']: r.get('status') for r in (prev_summaries.get('regressions') or {}).get('regressions', [])}
    failing = [r for r in rows if r['status'] == 'failing']
    newly = [r['name'] for r in failing if before.get(r['name']) == 'ok']
    fixed = [r['name'] for r in rows if r['status'] == 'ok' and before.get(r['name']) == 'failing']
    note = f" · ⚠️ {len(failing)} named regression{'s' if len(failing) != 1 else ''}" if failing else ''
    line = (f"**Named regressions:** ❌ {len(failing)} of {len(rows)} failing: "
            + ', '.join(f"{r['name']} ({r['issue']})" for r in failing)
            if failing else f"**Named regressions:** ✅ all {len(rows)} ok")
    if newly:
        line += f" · newly failing: {', '.join(newly)}"
    if fixed:
        line += f" · fixed: {', '.join(fixed)}"
    table = ['#### Named regressions', '', '| Route | Park | Issue | Status | Previous | Problems |', '|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda r: (r['status'] != 'failing', r['name'])):
        mark = '❌ failing' if r['status'] == 'failing' else '✅ ok'
        table.append(f"| {r['name']} | {r['park']} | {r['issue']} | {mark} | {before.get(r['name'], '')} | "
                     f"{'<br>'.join(p.replace('|', '/') for p in r.get('problems', []))} |")
    return note, [line, ''], table + ['']


def render(cur, prev, phases, prev_phases, summaries, prev_summaries, live=None):
    now = datetime.now(timezone.utc)
    title, summary = job_table(cur, prev, now)
    note, line, table = regressions(summaries, prev_summaries)
    title += note
    summary = '\n'.join(line + [summary])
    sections = {'live': live_table(cur, live or {}, phases, summaries, now),
                'phases': phase_tables(phases, prev_phases), 'regressions': table,
                'routes': routes_tables(cur, prev, summaries, prev_summaries)}
    text = [l for part in sections.values() for l in part]
    return title, summary[:60000], '\n'.join(text)[:60000], sections


def load(run, prefix, into):
    """Reads the run's artifacts named PREFIX-* that aren't in INTO yet."""
    for name, a in artifacts(run).items():
        key = name[len(prefix):]
        if name.startswith(prefix) and key not in into and not a['expired']:
            p = artifact_json(a)
            if p:
                into[key] = p
    return into


COMMENT_MARK = '<!-- build-progress-comment -->'
COMMENT_MAX = 65000  # GitHub's limit is 65,536 characters
BOT = 'github-actions[bot]'


def run_mark(run=RUN):
    return f'<!-- run:{run} -->'


def comments(issue):
    """The issue's (or PR's) comments, oldest first."""
    out, page = [], 1
    while True:
        r = request('GET', f'/repos/{REPO}/issues/{issue}/comments?per_page=100&page={page}')
        out += r
        if len(r) < 100:
            return out
        page += 1


def take_comment(issue, body, prune=False):
    """This build takes over the issue's (or PR's) progress comment, or adds
    one; with PRUNE, the bot's other comments there go (the "Build history"
    issue keeps one: the latest build's). Returns the meta to keep."""
    mine = [c for c in comments(issue) if (c.get('user') or {}).get('login') == BOT]
    found = next((c for c in mine if COMMENT_MARK in (c.get('body') or '')), None)
    if found:
        c = request('PATCH', f"/repos/{REPO}/issues/comments/{found['id']}", {'body': body})
    else:
        c = request('POST', f'/repos/{REPO}/issues/{issue}/comments', {'body': body})
    if prune:
        for old in mine:
            if old['id'] != c['id']:
                try:
                    request('DELETE', f"/repos/{REPO}/issues/comments/{old['id']}")
                except Exception as e:
                    print(f"deleting comment {old['id']}: {e}", file=sys.stderr)
    return {'issue': issue, 'comment': c['id'], 'comment_url': c['html_url']}


def comment_body(meta, title, summary='', sections=None):
    """The progress comment: what the check's page shows, the job table and
    what's running now first, the rest folded, within GitHub's limit."""
    url = f'https://github.com/{REPO}/actions/runs/{RUN}'
    what = (f'#{RUN_NUMBER} ' if RUN_NUMBER else '') + f"{meta.get('date', '')} {MODE} build" + ('' if HISTORY else f' of {NAMESPACE}')
    check = f" · [check]({meta['check_url']})" if meta.get('check_url') else ''
    head = f"{COMMENT_MARK}{run_mark()}\n### [{what.strip()}]({url}) ({SHA[:7]}): {title}{check}\n\n"
    body = head + summary
    sections = sections or {}
    if sections.get('live'):
        body += '\n\n' + '\n'.join(sections['live'])
    folds = [('Phase timings', 'phases'), ('Named regressions', 'regressions'), ('Routes', 'routes')]
    for label, key in folds:
        lines = sections.get(key) or []
        if not lines:
            continue
        open_, close = f'\n\n<details><summary>{label}</summary>\n\n', '\n\n</details>'
        room = COMMENT_MAX - len(body) - len(open_) - len(close) - 40
        if room < 200:
            break
        text = '\n'.join(lines)
        if len(text) > room:
            cut = text.rfind('\n', 0, room)
            text = text[:cut if cut > 0 else room] + '\n\n_(cut short: see the check)_'
        body += open_ + text + close
    return body[:COMMENT_MAX]


class History:
    """The "Build history" issue, for a running record of manual north-america
    builds' times: a line per build in the issue's description, newest first
    (the last HISTORY_LINES), and one comment, the latest build's progress."""
    TITLE = 'Build history'
    BODY = ('A line per manual north-america build, and one comment with the latest '
            "build's progress, kept by bin/build-progress.py (#210).")
    OLD_BODY = ('One comment per manual north-america build, with its job times, '
                'posted by bin/build-progress.py (#210).')
    LIST = re.compile(r'<!-- builds -->\n(.*?)<!-- /builds -->', re.S)

    def create(self, body):
        """Finds or opens the issue and takes its comment over for this build."""
        issues = request('GET', f'/repos/{REPO}/issues?state=open&per_page=100')
        found = [i for i in issues if i['title'] == self.TITLE and 'pull_request' not in i]
        issue = found[0]['number'] if found else request('POST', f'/repos/{REPO}/issues', {
            'title': self.TITLE, 'body': self.BODY})['number']
        return take_comment(issue, body, prune=True)

    @staticmethod
    def line(meta, status):
        """Puts this build's line at the top of the issue's list, replacing
        its earlier one, and keeps the newest HISTORY_LINES."""
        issue = meta.get('issue')
        if not issue:
            return
        mark = run_mark()
        url = f'https://github.com/{REPO}/actions/runs/{RUN}'
        progress = f" · [progress]({meta['check_url']})" if meta.get('check_url') else ''
        number = f'#{RUN_NUMBER} ' if RUN_NUMBER else ''
        new = f"- [{number}{meta['date']} {MODE} build]({url}): {status}{progress} {mark}"
        body = (request('GET', f'/repos/{REPO}/issues/{issue}')['body'] or '').replace(History.OLD_BODY, History.BODY)
        m = History.LIST.search(body)
        old = [History.numbered(l) for l in (m[1].splitlines() if m else []) if l.strip() and mark not in l]
        block = '<!-- builds -->\n' + '\n'.join([new] + old[:HISTORY_LINES - 1]) + '\n<!-- /builds -->'
        body = (body[:m.start()] + block + body[m.end():]) if m else f'{body.rstrip()}\n\n**Builds**, newest first:\n\n{block}\n'
        request('PATCH', f'/repos/{REPO}/issues/{issue}', {'body': body})


    OLD_LINE = re.compile(r'^- \[(?!#)(.*?)\]\(https://github\.com/[^)]*/actions/runs/(\d+)\)')

    @staticmethod
    def numbered(line):
        """A line from before lines showed the run's number, with it (one API
        call, once: the line keeps it)."""
        m = History.OLD_LINE.match(line)
        if not m:
            return line
        try:
            n = request('GET', f'/repos/{REPO}/actions/runs/{m[2]}')['run_number']
        except Exception as e:
            print(f'run {m[2]}: {e}', file=sys.stderr)
            return line
        return f'- [#{n} {m[1]}]' + line[m.end(1) + 1:]


LINK = re.compile(r'<!-- build-progress -->.*?<!-- /build-progress -->\n*', re.S)


def link_from_pr(check_id, status, start=False, comment_url=None):
    """Puts a link to this build's progress comment (or, without one, its
    check) at the top of the PR's description, replacing the previous
    build's when it starts. Later updates only touch the link while it's
    still this build's, so a superseded build's last update doesn't replace
    a newer build's link. (An edit with the job's token doesn't trigger
    workflows, so this doesn't rebuild the PR.)"""
    if not PR:
        return
    try:
        url = comment_url or f'https://github.com/{REPO}/pull/{PR}/checks?check_run_id={check_id}'
        block = f'<!-- build-progress -->{run_mark()}\n📊 **[Build progress]({url})** for {SHA[:7]}: {status}\n<!-- /build-progress -->\n\n'
        body = request('GET', f'/repos/{REPO}/pulls/{PR}')['body'] or ''
        current = LINK.search(body)
        if not start and not (current and (run_mark() in current[0] or f'check_run_id={check_id})' in current[0])):
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
    keep = ('name', 'status', 'conclusion', 'started_at', 'completed_at', 'html_url')
    out = []
    for j in jobs_:
        k = {x: j.get(x) for x in keep}
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


def finishing(cur):
    """The jobs, with the one this runs in (its last step, the update)
    shown as finished: the jobs API still has it running, so the last job to
    finish would otherwise show as running until a later job's update."""
    me = os.environ.get('RUNNER_NAME')
    for j in cur:
        if me and j.get('runner_name') == me and j['status'] != 'completed':
            failed = any(s.get('conclusion') in ('failure', 'cancelled') for s in j.get('steps', []))
            j.update(status='completed', conclusion='failure' if failed else 'success',
                     completed_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    return cur


def publish(check, data, final=False, done=False):
    """Renders DATA with the run's current jobs into the check and the
    progress comment; DONE if this is the calling job's last step."""
    cur = jobs(RUN)
    if done:
        cur = finishing(cur)
    if final:
        data.pop('live', None)
    title, summary, text, sections = render(cur, data['prev_jobs'], data['phases'], data['prev_phases'],
                                            data['summaries'], data['prev_summaries'], data.get('live'))
    if final and data.get('error'):
        title += ' (progress reporting hit an error; see the progress jobs\' logs)'
    blob = f'\n\n<!-- build-progress-data:{pack(data)} -->'
    body = {'output': {'title': title, 'summary': summary[:65000 - len(blob)] + blob,
                       'text': text or 'No phase timings yet.'}}
    if final:
        body.update(status='completed', conclusion='neutral')
    request('PATCH', f"/repos/{REPO}/check-runs/{check['id']}", body)
    comment = data['meta'].get('comment')
    if comment:
        try:
            path = f'/repos/{REPO}/issues/comments/{comment}'
            # A superseded build (a cancelled PR build's finish) leaves a
            # newer build's comment alone. Earlier stale edits are put
            # right by the newer build's next one.
            if not final or run_mark() in (request('GET', path).get('body') or ''):
                request('PATCH', path, {'body': comment_body(data['meta'], title, summary, sections)})
        except Exception as e:
            print(f'progress comment: {e}', file=sys.stderr)
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
    # The check may show up under another run of the commit, so link it
    # from this run's summary page.
    print(f"::notice title={check_name()}::{check['html_url']}", flush=True)
    data['meta']['check_url'] = check['html_url']
    first = comment_body(data['meta'], 'starting')
    if PR:
        try:
            data['meta'].update(take_comment(PR, first))
        except Exception as e:
            print(f'progress comment: {e}', file=sys.stderr)
    link_from_pr(check['id'], 'running', start=True, comment_url=data['meta'].get('comment_url'))
    if HISTORY:
        try:
            data['meta'].update(History().create(first))
            History.line(data['meta'], 'running')
        except Exception as e:
            print(f'history: {e}', file=sys.stderr)
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
    publish(check, data, done=True)


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
    link_from_pr(check['id'], title, comment_url=data['meta'].get('comment_url'))
    if HISTORY:
        try:
            History.line(data['meta'], title)
        except Exception as e:
            print(f'history: {e}', file=sys.stderr)
    write_step_summary(title, summary, text)


def live_status(kind, log):
    """Where this job's run is now, from its log so far."""
    if not os.path.exists(log):
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    script = {'tilemaker': 'tilemaker-phases.py', 'routes': 'routes-summary.py'}[kind]
    spec = importlib.util.spec_from_file_location(kind, os.path.join(here, script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if kind == 'tilemaker':
        return mod.live(mod.read_log(log), int(time.time() * 1000))
    return mod.live(open(log, errors='replace'))


def live(name, kind, log):
    """Runs in the background of a long job (.github/actions/build-progress
    with live:), putting where the job's run is into the check every 5-8
    minutes until the job ends. Jobs' loops are spread out at random, which
    keeps the API calls to 3 per job every 6.5 minutes or so, and they skip
    updates while the repository's API budget is low (LIVE_RESERVE)."""
    random.seed(f'{RUN}/{name}')
    time.sleep(random.uniform(30, 150))
    check_id = None
    while True:
        try:
            status = live_status(kind, log)
            if status:
                check = request('GET', f'/repos/{REPO}/check-runs/{check_id}') if check_id else find_check()
                if check and check['status'] == 'completed':
                    return
                if REMAINING is not None and REMAINING < LIVE_RESERVE:
                    print(f'{REMAINING} API calls left this hour; skipping this update', flush=True)
                    check = None
                data = unpack(check['output']['summary']) if check else None
                if data:
                    check_id = check['id']
                    configure(data['meta'])
                    status['updated'] = int(time.time() * 1000)
                    data.setdefault('live', {})[name] = status
                    publish(check, data)
        except Exception:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
        time.sleep(random.uniform(300, 480))


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else ''
    if step == 'live':
        live(*sys.argv[2:5])
        return
    try:
        {'start': start, 'update': update, 'finish': finish}[step]()
    except Exception:
        # Reporting is best effort: never fail a build job over it.
        print(traceback.format_exc(), file=sys.stderr)
        print(f'::warning::Build progress {step} failed; see the log.')


if __name__ == '__main__':
    main()
