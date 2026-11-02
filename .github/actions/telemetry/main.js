// Starts the background sampler; post.js stops it and writes the report.

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const interval = Number(process.env['INPUT_INTERVAL'] || '1');
const out = path.join(process.env.RUNNER_TEMP || '/tmp', `telemetry-${process.pid}.jsonl`);

const child = spawn(process.execPath, [path.join(__dirname, 'sample.js'), out, String(interval)], {
  detached: true,
  stdio: 'ignore',
});
child.unref();

// Hand the sampler's pid and output file to the post step.
fs.appendFileSync(process.env.GITHUB_STATE, `pid=${child.pid}\nfile=${out}\n`);
console.log(`Sampling CPU, memory, disk and network every ${interval}s (pid ${child.pid}).`);
