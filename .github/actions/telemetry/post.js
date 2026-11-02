// Stops the sampler and writes CPU, memory, disk and network charts to the job
// summary, plus the same numbers to the log (where the API can fetch them).

const fs = require('fs');
const os = require('os');
const { sample } = require('./sample');

const MAX_POINTS = 120;
const COLORS = '#2563eb, #dc2626, #16a34a';
const GIB = 1024 ** 3;

function main() {
  const pid = Number(process.env.STATE_pid);
  const file = process.env.STATE_file;
  if (pid) {
    try { process.kill(pid); } catch (e) { /* already gone */ }
  }

  let samples = [];
  try {
    samples = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  } catch (e) {
    console.log(`No samples (${e.message}).`);
  }
  samples.push(sample());
  if (samples.length < 2) {
    console.log('Not enough samples for a report.');
    return;
  }

  // One point per interval between consecutive samples.
  const points = [];
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i];
    const dt = (b.t - a.t) / 1000;
    if (dt <= 0) continue;
    const d = (k) => b.cpu[k] - a.cpu[k];
    const ticks = d('user') + d('system') + d('iowait') + d('idle') + d('steal') || 1;
    points.push({
      min: (b.t - samples[0].t) / 60000,
      dt,
      busy: (100 * (d('user') + d('system'))) / ticks,
      iowait: (100 * d('iowait')) / ticks,
      mem: b.mem.used / GIB,
      swap: b.mem.swap / GIB,
      read: (b.disk.read - a.disk.read) / dt / 1e6,
      write: (b.disk.written - a.disk.written) / dt / 1e6,
      rx: (b.net.rx - a.net.rx) / dt / 1e6,
      tx: (b.net.tx - a.net.tx) / dt / 1e6,
      free: Object.fromEntries(Object.entries(b.fs).map(([p, f]) => [p, f.free / GIB])),
    });
  }

  const first = samples[0], last = samples[samples.length - 1];
  const minutes = (last.t - first.t) / 60000;
  const max = (k) => Math.max(...points.map((p) => p[k]));
  const avg = (k) => points.reduce((s, p) => s + p[k] * p.dt, 0) / points.reduce((s, p) => s + p.dt, 0);
  const mounts = Object.keys(last.fs);
  const minFree = (m) => Math.min(...points.map((p) => p.free[m] ?? Infinity));
  const gb = (n) => (n / 1e9).toFixed(2);

  const rows = [
    ['Duration', `${minutes.toFixed(1)} min`],
    ['CPUs', `${os.cpus().length}`],
    ['CPU busy (user+system)', `${avg('busy').toFixed(0)}% average, ${max('busy').toFixed(0)}% peak`],
    ['CPU iowait', `${avg('iowait').toFixed(1)}% average, ${max('iowait').toFixed(0)}% peak`],
    ['Memory used', `${max('mem').toFixed(1)} GiB peak of ${(last.mem.total / GIB).toFixed(1)} GiB`],
    ['Swap used', `${max('swap').toFixed(1)} GiB peak`],
    ['Disk read', `${gb(last.disk.read - first.disk.read)} GB, ${max('read').toFixed(0)} MB/s peak`],
    ['Disk written', `${gb(last.disk.written - first.disk.written)} GB, ${max('write').toFixed(0)} MB/s peak`],
    ['Network received', `${gb(last.net.rx - first.net.rx)} GB, ${max('rx').toFixed(0)} MB/s peak`],
    ['Network sent', `${gb(last.net.tx - first.net.tx)} GB, ${max('tx').toFixed(0)} MB/s peak`],
    ...mounts.map((m) => [`Free disk on ${m}`, `${minFree(m).toFixed(1)} GiB minimum of ${(last.fs[m].size / GIB).toFixed(0)} GiB`]),
  ];

  // Average neighbouring intervals so each chart has at most MAX_POINTS points.
  const per = Math.ceil(points.length / MAX_POINTS);
  const buckets = [];
  for (let i = 0; i < points.length; i += per) buckets.push(points.slice(i, i + per));
  const series = (f, combine) => buckets.map((b) => combine(b.map(f)));
  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const peak = (xs) => Math.max(...xs);
  const low = (xs) => Math.min(...xs);

  const chart = (title, yLabel, lines, yMax) => {
    const top = yMax ?? Math.max(1, ...lines.flatMap((l) => l)) * 1.05;
    return [
      '```mermaid',
      `%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "${COLORS}"}}}}%%`,
      'xychart-beta',
      `  title "${title}"`,
      `  x-axis "minutes" 0 --> ${Math.max(minutes, 0.1).toFixed(1)}`,
      `  y-axis "${yLabel}" 0 --> ${top.toFixed(top < 10 ? 1 : 0)}`,
      ...lines.map((l) => `  line [${l.map((v) => v.toFixed(2)).join(', ')}]`),
      '```',
    ].join('\n');
  };

  const freeColors = ['blue', 'red', 'green'];
  const summary = [
    `### Resource usage: ${process.env.GITHUB_JOB || 'job'}`,
    '',
    '| | |',
    '|---|---|',
    ...rows.map(([k, v]) => `| ${k} | ${v} |`),
    '',
    chart('CPU %: busy (blue), iowait (red)', '%', [series((p) => p.busy, mean), series((p) => p.iowait, mean)], 100),
    chart('Memory GiB: used (blue), swap (red)', 'GiB', [series((p) => p.mem, peak), series((p) => p.swap, peak)], last.mem.total / GIB),
    chart('Disk MB/s: read (blue), written (red)', 'MB/s', [series((p) => p.read, mean), series((p) => p.write, mean)]),
    chart('Network MB/s: received (blue), sent (red)', 'MB/s', [series((p) => p.rx, mean), series((p) => p.tx, mean)]),
    chart(
      `Free disk GiB: ${mounts.map((m, i) => `${m} (${freeColors[i]})`).join(', ')}`,
      'GiB',
      mounts.map((m) => series((p) => p.free[m] ?? 0, low)),
    ),
    '',
  ].join('\n');

  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');

  for (const [k, v] of rows) console.log(`${k}: ${v}`);
  console.log('::group::Samples (CSV)');
  console.log(['minute', 'cpu_busy_pct', 'cpu_iowait_pct', 'mem_gib', 'swap_gib', 'disk_read_mbs', 'disk_write_mbs', 'net_rx_mbs', 'net_tx_mbs', ...mounts.map((m) => `free_gib_${m}`)].join(','));
  for (const p of points) {
    console.log([p.min, p.busy, p.iowait, p.mem, p.swap, p.read, p.write, p.rx, p.tx, ...mounts.map((m) => p.free[m] ?? '')]
      .map((v) => (typeof v === 'number' ? Number(v.toFixed(2)) : v)).join(','));
  }
  console.log('::endgroup::');
}

try {
  main();
} catch (e) {
  // Telemetry must never fail the job.
  console.log(`::warning::Telemetry report failed: ${e.stack || e}`);
}
