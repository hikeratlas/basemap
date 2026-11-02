// Reads one sample of the runner's resource counters from /proc and statfs.
//
// Counters (CPU jiffies, disk sectors, network bytes) are cumulative; the
// report turns consecutive samples into rates.

const fs = require('fs');

function cpu() {
  // cpu  user nice system idle iowait irq softirq steal ...
  const f = fs.readFileSync('/proc/stat', 'utf8').split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
  const [user, nice, system, idle, iowait, irq, softirq, steal] = f;
  return { user: user + nice, system: system + irq + softirq, iowait, idle, steal: steal || 0 };
}

function mem() {
  const kb = {};
  for (const line of fs.readFileSync('/proc/meminfo', 'utf8').split('\n')) {
    const m = line.match(/^(\w+):\s+(\d+)/);
    if (m) kb[m[1]] = Number(m[2]);
  }
  return {
    total: kb.MemTotal * 1024,
    used: (kb.MemTotal - kb.MemAvailable) * 1024,
    swap: (kb.SwapTotal - kb.SwapFree) * 1024,
  };
}

// Whole disks only (partitions and device-mapper devices would double count).
const disks = new Set(
  fs.readdirSync('/sys/block').filter((d) => !/^(loop|ram|zram|dm-|md|sr|nbd)/.test(d)),
);

function disk() {
  let read = 0, written = 0;
  for (const line of fs.readFileSync('/proc/diskstats', 'utf8').split('\n')) {
    const f = line.trim().split(/\s+/);
    if (f.length < 10 || !disks.has(f[2])) continue;
    read += Number(f[5]) * 512;
    written += Number(f[9]) * 512;
  }
  return { read, written };
}

// An interface with a master is part of another one, whose counters already
// include its traffic: on Azure runners, accelerated networking puts a
// Mellanox VF (enP...) under eth0, so counting both doubled the traffic.
const enslaved = (name) => fs.existsSync(`/sys/class/net/${name}/master`);

function net() {
  let rx = 0, tx = 0;
  for (const line of fs.readFileSync('/proc/net/dev', 'utf8').split('\n').slice(2)) {
    const m = line.match(/^\s*([^:]+):\s*(.*)$/);
    if (!m || m[1] === 'lo' || m[1].startsWith('docker') || m[1].startsWith('veth') || m[1].startsWith('br-') || enslaved(m[1])) continue;
    const f = m[2].trim().split(/\s+/).map(Number);
    rx += f[0];
    tx += f[8];
  }
  return { rx, tx };
}

// Free space on each distinct filesystem the jobs write to.
function filesystems() {
  const seen = new Set();
  const out = {};
  for (const p of ['/', '/mnt', process.env.GITHUB_WORKSPACE].filter(Boolean)) {
    try {
      const dev = fs.statSync(p).dev;
      if (seen.has(dev)) continue;
      seen.add(dev);
      const s = fs.statfsSync(p);
      out[p] = { free: s.bavail * s.bsize, size: s.blocks * s.bsize };
    } catch (e) {
      // missing mount point
    }
  }
  return out;
}

function sample() {
  return { t: Date.now(), cpu: cpu(), mem: mem(), disk: disk(), net: net(), fs: filesystems() };
}

module.exports = { sample };

// Run as the background sampler: node sample.js OUTPUT INTERVAL_SECONDS
if (require.main === module) {
  const [out, interval] = process.argv.slice(2);
  const write = () => {
    try {
      fs.appendFileSync(out, JSON.stringify(sample()) + '\n');
    } catch (e) {
      // keep sampling; a missed sample only widens one interval
    }
  };
  write();
  setInterval(write, Number(interval) * 1000);
}
