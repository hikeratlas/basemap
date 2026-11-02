// Stops the sampler and writes a report to the job summary: the runner, a
// one-row usage table, a waterfall of the job's steps with each step's usage,
// and charts of CPU, memory, disk and network with the steps shaded in. The
// same numbers, plus every sample as CSV, go to the log.

const fs = require('fs');
const os = require('os');
const { execSync } = require('child_process');
const { sample } = require('./sample');

const MAX_POINTS = 120;
const BAND = '#e5e7eb'; // shading for every other step
const LINES = ['#2563eb', '#dc2626', '#16a34a'];
const GIB = 1024 ** 3;

const f1 = (n) => n.toFixed(1);
const f0 = (n) => n.toFixed(0);
const gb = (n) => (n / 1e9).toFixed(2);

// The job's name (with matrix values) and its steps' times, from the API.
// Needs `actions: read`; without it the report just has no waterfall.
async function jobInfo() {
  const { GITHUB_API_URL, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, RUNNER_NAME } = process.env;
  const token = process.env.INPUT_TOKEN;
  if (!token || !GITHUB_RUN_ID) return null;
  try {
    for (let page = 1; page <= 5; page++) {
      const url = `${GITHUB_API_URL}/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/attempts/${GITHUB_RUN_ATTEMPT || 1}/jobs?per_page=100&page=${page}`;
      const res = await fetch(url, {
        headers: { authorization: `Bearer ${token}`, accept: 'application/vnd.github+json' },
        signal: AbortSignal.timeout(10000),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const { jobs } = await res.json();
      const job = jobs.find((j) => j.runner_name === RUNNER_NAME && j.status !== 'completed');
      if (job) return job;
      if (jobs.length < 100) break;
    }
    throw new Error(`no running job on runner ${RUNNER_NAME}`);
  } catch (e) {
    console.log(`::warning::Telemetry: couldn't read the job's steps (${e.message}); is \`actions: read\` granted?`);
    return null;
  }
}

async function runnerLine(last) {
  let vm = '';
  try {
    const res = await fetch('http://169.254.169.254/metadata/instance/compute?api-version=2021-02-01', {
      headers: { Metadata: 'true' },
      signal: AbortSignal.timeout(2000),
    });
    const c = await res.json();
    vm = `${c.vmSize} (${c.location})`;
  } catch (e) {
    // not on Azure, or no metadata service
  }
  let cpu = '';
  try {
    cpu = (execSync('lscpu', { encoding: 'utf8' }).match(/^Model name:\s*(.+)$/m) || [])[1] || '';
  } catch (e) {
    // no lscpu
  }
  const meminfo = fs.readFileSync('/proc/meminfo', 'utf8');
  const swapKb = Number((meminfo.match(/^SwapTotal:\s+(\d+)/m) || [0, 0])[1]);
  return [
    [process.env.ImageOS, process.env.ImageVersion].filter(Boolean).join(' '),
    vm,
    `${cpu ? cpu + ' × ' : ''}${os.cpus().length} vCPUs`,
    `${f1(last.mem.total / GIB)} GiB RAM`,
    `${f1((swapKb * 1024) / GIB)} GiB swap`,
    ...Object.entries(last.fs).map(([m, f]) => `${m} ${f0(f.size / GIB)} GiB`),
  ].filter(Boolean).join(' · ');
}

// Mermaid task names can't contain : or #
const taskName = (s) => s.replace(/[:#;]/g, ' ').replace(/\s+/g, ' ').trim();

async function main() {
  const pid = Number(process.env.STATE_pid);
  if (pid) {
    try { process.kill(pid); } catch (e) { /* already gone */ }
  }

  let samples = [];
  try {
    samples = fs.readFileSync(process.env.STATE_file, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  } catch (e) {
    console.log(`No samples (${e.message}).`);
  }
  samples.push(sample());
  if (samples.length < 2) {
    console.log('Not enough samples for a report.');
    return;
  }
  const first = samples[0], last = samples[samples.length - 1];
  const mounts = Object.keys(last.fs);

  // One point per interval between consecutive samples.
  const points = [];
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i];
    const dt = (b.t - a.t) / 1000;
    if (dt <= 0) continue;
    const d = (k) => b.cpu[k] - a.cpu[k];
    const ticks = d('user') + d('system') + d('iowait') + d('idle') + d('steal') || 1;
    points.push({
      t: (a.t + b.t) / 2,
      dt,
      busy: (100 * (d('user') + d('system'))) / ticks,
      iowait: (100 * d('iowait')) / ticks,
      mem: b.mem.used / GIB,
      swap: b.mem.swap / GIB,
      read: b.disk.read - a.disk.read,
      write: b.disk.written - a.disk.written,
      rx: b.net.rx - a.net.rx,
      tx: b.net.tx - a.net.tx,
      free: Object.fromEntries(Object.entries(b.fs).map(([p, f]) => [p, f.free / GIB])),
    });
  }

  const stats = (ps) => {
    const secs = ps.reduce((s, p) => s + p.dt, 0) || 1;
    const sum = (k) => ps.reduce((s, p) => s + p[k], 0);
    return {
      busy: ps.reduce((s, p) => s + p.busy * p.dt, 0) / secs,
      busyPeak: Math.max(...ps.map((p) => p.busy)),
      iowait: ps.reduce((s, p) => s + p.iowait * p.dt, 0) / secs,
      mem: Math.max(...ps.map((p) => p.mem)),
      swap: Math.max(...ps.map((p) => p.swap)),
      read: sum('read'), write: sum('write'), rx: sum('rx'), tx: sum('tx'),
      readPeak: Math.max(...ps.map((p) => p.read / p.dt)) / 1e6,
      writePeak: Math.max(...ps.map((p) => p.write / p.dt)) / 1e6,
      rxPeak: Math.max(...ps.map((p) => p.rx / p.dt)) / 1e6,
      free: Object.fromEntries(mounts.map((m) => [m, Math.min(...ps.map((p) => p.free[m] ?? Infinity))])),
    };
  };
  const all = stats(points);
  const minutes = (last.t - first.t) / 60000;

  const job = await jobInfo();
  const title = job ? job.name : process.env.GITHUB_JOB || 'job';
  const steps = (job ? job.steps : [])
    .filter((s) => s.started_at && s.completed_at)
    .map((s, i) => ({
      n: i + 1,
      name: s.name,
      start: Date.parse(s.started_at),
      // the API rounds to the second; make every step at least 1 s long
      end: Math.max(Date.parse(s.completed_at), Date.parse(s.started_at) + 1000),
      conclusion: s.conclusion,
    }));
  // The step running at time t: the last one to start by then. Steps run one
  // after another, and the API rounds their times to the second.
  const stepAt = (t) => {
    let found = null;
    for (const s of steps) if (s.start <= t && t < s.end + 1000) found = s;
    return found;
  };

  const out = [];
  out.push(`### Resource usage: ${title}`, '', await runnerLine(last), '');
  out.push(
    '| Duration | CPU avg / peak | iowait | Memory peak | Swap | Disk read / written | Network in / out | Free disk (min) |',
    '|---|---|---|---|---|---|---|---|',
    `| ${f1(minutes)} min | ${f0(all.busy)}% / ${f0(all.busyPeak)}% | ${f0(all.iowait)}% | ${f1(all.mem)} / ${f1(last.mem.total / GIB)} GiB | ${f1(all.swap)} GiB | ${gb(all.read)} / ${gb(all.write)} GB | ${gb(all.rx)} / ${gb(all.tx)} GB | ${mounts.map((m) => `${m} ${f1(all.free[m])} GiB`).join(', ')} |`,
    '',
  );

  // Waterfall of the steps, with each step's usage.
  if (steps.length) {
    const longJob = (steps[steps.length - 1].end - steps[0].start) > 3600 * 1000;
    out.push(
      '```mermaid',
      'gantt',
      '  dateFormat x',
      `  axisFormat ${longJob ? '%H:%M' : '%H:%M:%S'}`,
      '  section Steps',
      ...steps.map((s) => `  ${s.n}. ${taskName(s.name)} :${s.conclusion === 'failure' ? 'crit, ' : ''}s${s.n}, ${s.start}, ${s.end}`),
      '```',
      '',
      '| # | Step | Duration | CPU avg | Memory peak | Disk read / written | Network in |',
      '|---|---|---|---|---|---|---|',
    );
    for (const s of steps) {
      const ps = points.filter((p) => stepAt(p.t) === s);
      const secs = (s.end - s.start) / 1000;
      const dur = secs >= 90 ? `${f1(secs / 60)} min` : `${f0(secs)} s`;
      if (!ps.length) {
        out.push(`| ${s.n} | ${s.name} | ${dur} | | | | |`);
        continue;
      }
      const st = stats(ps);
      out.push(`| ${s.n} | ${s.name} | ${dur} | ${f0(st.busy)}% | ${f1(st.mem)} GiB | ${gb(st.read)} / ${gb(st.write)} GB | ${gb(st.rx)} GB |`);
    }
    out.push('');
  }

  // Charts: average neighbouring intervals so each has at most MAX_POINTS points.
  const per = Math.ceil(points.length / MAX_POINTS);
  const buckets = [];
  for (let i = 0; i < points.length; i += per) buckets.push(points.slice(i, i + per));
  const series = (f, combine) => buckets.map((b) => combine(b.map(f)));
  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const peak = (xs) => Math.max(...xs);
  const low = (xs) => Math.min(...xs);
  const rate = (k) => (b) => b.reduce((s, p) => s + p[k], 0) / b.reduce((s, p) => s + p.dt, 0) / 1e6;
  // 1 for buckets in odd-numbered steps: drawn as bars, they shade every other step.
  const shade = buckets.map((b) => {
    const s = stepAt(b[Math.floor(b.length / 2)].t);
    return s && s.n % 2 === 1 ? 1 : 0;
  });

  const chart = (title, yLabel, lines, yMax) => {
    // Round the top up to two significant digits, and use that same number for
    // the axis and the shading bars, so the bars reach the top of the chart.
    const raw = yMax ?? Math.max(1, ...lines.flat()) * 1.05;
    const unit = 10 ** (Math.floor(Math.log10(raw)) - 1);
    const top = Number((Math.ceil(raw / unit - 1e-9) * unit).toPrecision(2));
    const fmt = (v) => v.toFixed(2);
    return [
      '```mermaid',
      `%%{init: {"xyChart": {"width": 900, "height": 240}, "themeVariables": {"xyChart": {"plotColorPalette": "${[...(steps.length ? [BAND] : []), ...LINES].join(', ')}"}}}}%%`,
      'xychart-beta',
      `  title "${title}"`,
      `  x-axis "minutes" 0 --> ${f1(Math.max(minutes, 0.1))}`,
      `  y-axis "${yLabel}" 0 --> ${top}`,
      ...(steps.length ? [`  bar [${shade.map((v) => fmt(v * top)).join(', ')}]`] : []),
      ...lines.map((l) => `  line [${l.map(fmt).join(', ')}]`),
      '```',
    ].join('\n');
  };

  if (steps.length) out.push('Shaded bands mark the odd-numbered steps above.', '');
  const colors = ['blue', 'red', 'green'];
  out.push(
    chart('CPU %: busy (blue), iowait (red)', '%', [series((p) => p.busy, mean), series((p) => p.iowait, mean)], 100),
    chart('Memory GiB: used (blue), swap (red)', 'GiB', [series((p) => p.mem, peak), series((p) => p.swap, peak)], last.mem.total / GIB),
    chart('Disk MB/s: read (blue), written (red)', 'MB/s', [buckets.map(rate('read')), buckets.map(rate('write'))]),
    chart('Network MB/s: in (blue), out (red)', 'MB/s', [buckets.map(rate('rx')), buckets.map(rate('tx'))]),
    chart(
      `Free disk GiB: ${mounts.map((m, i) => `${m} (${colors[i]})`).join(', ')}`,
      'GiB',
      mounts.map((m) => series((p) => p.free[m] ?? 0, low)),
    ),
    '',
  );

  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, out.join('\n') + '\n');

  // The log gets the tables and every sample.
  let inChart = false;
  const text = out.join('\n').split('\n').filter((l) => {
    if (l.startsWith('```')) { inChart = !inChart; return false; }
    return !inChart && l !== 'Shaded bands mark the odd-numbered steps above.';
  });
  console.log(text.join('\n'));
  console.log('::group::Samples (CSV)');
  console.log(['time', 'step', 'cpu_busy_pct', 'cpu_iowait_pct', 'mem_gib', 'swap_gib', 'disk_read_mbs', 'disk_write_mbs', 'net_rx_mbs', 'net_tx_mbs', ...mounts.map((m) => `free_gib_${m}`)].join(','));
  for (const p of points) {
    const s = stepAt(p.t);
    console.log([new Date(p.t).toISOString(), s ? s.n : '', p.busy, p.iowait, p.mem, p.swap, p.read / p.dt / 1e6, p.write / p.dt / 1e6, p.rx / p.dt / 1e6, p.tx / p.dt / 1e6, ...mounts.map((m) => p.free[m] ?? '')]
      .map((v) => (typeof v === 'number' ? Number(v.toFixed(2)) : v)).join(','));
  }
  console.log('::endgroup::');
}

main().catch((e) => {
  // Telemetry must never fail the job.
  console.log(`::warning::Telemetry report failed: ${e.stack || e}`);
});
