#!/usr/bin/env python3
"""Usage: COMMAND | bin/timestamp-lines.py LOG

Copies stdin to stdout unchanged, and writes each line of it to LOG as
"<epoch ms>\t<line>", for bin/tilemaker-phases.py. A line ends at a newline
or a carriage return, as tilemaker's progress lines do.
"""
import sys, time

def main(path):
    with open(path, 'w') as log:
        buf = b''
        while True:
            chunk = sys.stdin.buffer.read1(65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            buf += chunk
            now = int(time.time() * 1000)
            *lines, buf = buf.replace(b'\r', b'\n').split(b'\n')
            for line in lines:
                if line.strip():
                    log.write(f'{now}\t{line.decode(errors="replace").strip()}\n')
            log.flush()
        if buf.strip():
            log.write(f'{int(time.time() * 1000)}\t{buf.decode(errors="replace").strip()}\n')

if __name__ == '__main__':
    main(sys.argv[1])
