// Re-compresses an .osm.pbf's blocks with zstd.
//
//   bun bin/pbf-zstd.ts INPUT OUTPUT [LEVEL]
//
// INPUT may be "-" for stdin, e.g. to take `osmium cat -f pbf,pbf_compression=none`
// output from a pipe. Blocks may be uncompressed, zlib or zstd (zstd blocks are
// copied as-is). The file is otherwise unchanged: same blocks, in the same
// order, with the same header (so e.g. Sort.Type_then_ID is kept).
//
// zstd blocks decompress several times faster than zlib ones, and tilemaker
// (cldellow/tilemaker's relslow-patched) reads some blocks several times. Few
// other tools read them yet: libosmium 2.22 can't.
//
// File format: https://wiki.openstreetmap.org/wiki/PBF_Format. The file is a
// sequence of (4-byte big-endian length, BlobHeader, Blob).

import { inflateSync } from "node:zlib";
import { open } from "node:fs/promises";

const [input, output, levelArg] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: bun bin/pbf-zstd.ts INPUT|- OUTPUT [LEVEL]");
  process.exit(2);
}
const level = levelArg ? Number(levelArg) : 6;

// ---- minimal protobuf ------------------------------------------------------

function readVarint(buf: Uint8Array, pos: number): [number, number] {
  let result = 0;
  let mult = 1;
  for (;;) {
    if (pos >= buf.length) throw new Error("truncated varint");
    const b = buf[pos++];
    result += (b & 0x7f) * mult;
    if (b < 0x80) return [result, pos];
    mult *= 128;
  }
}

function varint(n: number): number[] {
  const out: number[] = [];
  while (n >= 0x80) {
    out.push((n % 128) | 0x80);
    n = Math.floor(n / 128);
  }
  out.push(n);
  return out;
}

type Field = { field: number; wire: number; value: number | Uint8Array };

function* fields(buf: Uint8Array): Generator<Field> {
  let pos = 0;
  while (pos < buf.length) {
    let tag: number;
    [tag, pos] = readVarint(buf, pos);
    const field = Math.floor(tag / 8);
    const wire = tag & 7;
    if (wire === 0) {
      let v: number;
      [v, pos] = readVarint(buf, pos);
      yield { field, wire, value: v };
    } else if (wire === 2) {
      let len: number;
      [len, pos] = readVarint(buf, pos);
      if (pos + len > buf.length) throw new Error("truncated field");
      yield { field, wire, value: buf.subarray(pos, pos + len) };
      pos += len;
    } else {
      throw new Error(`unexpected wire type ${wire}`);
    }
  }
}

function bytesField(field: number, data: Uint8Array): Uint8Array[] {
  return [Uint8Array.from([...varint(field * 8 + 2), ...varint(data.length)]), data];
}

function varintField(field: number, n: number): Uint8Array {
  return Uint8Array.from([...varint(field * 8), ...varint(n)]);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let pos = 0;
  for (const p of parts) {
    out.set(p, pos);
    pos += p.length;
  }
  return out;
}

// ---- blobs -----------------------------------------------------------------

// BlobHeader: 1 type (string), 2 indexdata (bytes), 3 datasize (int32)
// Blob: 1 raw, 2 raw_size, 3 zlib_data, 4 lzma_data, 6 lz4_data, 7 zstd_data
function recompressBlob(blob: Uint8Array): Uint8Array {
  let raw: Uint8Array | undefined;
  let zstd: Uint8Array | undefined;
  let rawSize: number | undefined;
  for (const f of fields(blob)) {
    if (f.field === 1) raw = f.value as Uint8Array;
    else if (f.field === 2) rawSize = f.value as number;
    else if (f.field === 3) raw = inflateSync(f.value as Uint8Array);
    else if (f.field === 7) zstd = f.value as Uint8Array;
    else throw new Error(`unsupported blob compression (field ${f.field})`);
  }
  if (zstd) return blob;
  if (!raw) throw new Error("blob has no data");
  if (rawSize !== undefined && rawSize !== raw.length)
    throw new Error(`raw_size ${rawSize} doesn't match ${raw.length} bytes`);
  const compressed = Bun.zstdCompressSync(raw, { level });
  return concat([varintField(2, raw.length), ...bytesField(7, compressed)]);
}

function rewriteHeader(header: Uint8Array, datasize: number): Uint8Array {
  const parts: Uint8Array[] = [];
  for (const f of fields(header)) {
    if (f.field === 3) continue;
    if (f.wire !== 2) throw new Error(`unexpected BlobHeader field ${f.field}`);
    parts.push(...bytesField(f.field, f.value as Uint8Array));
  }
  parts.push(varintField(3, datasize));
  return concat(parts);
}

function blobDatasize(header: Uint8Array): number {
  for (const f of fields(header)) if (f.field === 3) return f.value as number;
  throw new Error("BlobHeader has no datasize");
}

// ---- I/O -------------------------------------------------------------------

// Reads exactly n bytes, or returns null at a clean end of input.
async function* chunks(): AsyncGenerator<Uint8Array> {
  if (input === "-") {
    for await (const c of Bun.stdin.stream()) yield c;
  } else {
    for await (const c of Bun.file(input).stream()) yield c;
  }
}

class Reader {
  private buf = new Uint8Array(0);
  private pos = 0;
  private done = false;
  constructor(private it: AsyncGenerator<Uint8Array>) {}

  async read(n: number): Promise<Uint8Array | null> {
    while (this.buf.length - this.pos < n && !this.done) {
      const next = await this.it.next();
      if (next.done) {
        this.done = true;
        break;
      }
      const rest = this.buf.subarray(this.pos);
      const merged = new Uint8Array(rest.length + next.value.length);
      merged.set(rest);
      merged.set(next.value, rest.length);
      this.buf = merged;
      this.pos = 0;
    }
    const avail = this.buf.length - this.pos;
    if (avail === 0 && this.done) return null;
    if (avail < n) throw new Error("truncated input");
    const out = this.buf.slice(this.pos, this.pos + n);
    this.pos += n;
    return out;
  }
}

const reader = new Reader(chunks());
const out = await open(output, "w");
let blocks = 0;
let inBytes = 0;
let outBytes = 0;
const start = Date.now();

for (;;) {
  const lenBytes = await reader.read(4);
  if (lenBytes === null) break;
  const headerLen = new DataView(lenBytes.buffer).getUint32(0);
  const header = (await reader.read(headerLen))!;
  const blob = (await reader.read(blobDatasize(header)))!;

  const newBlob = recompressBlob(blob);
  const newHeader = rewriteHeader(header, newBlob.length);
  const newLen = new Uint8Array(4);
  new DataView(newLen.buffer).setUint32(0, newHeader.length);
  await out.write(concat([newLen, newHeader, newBlob]));

  blocks++;
  inBytes += 4 + headerLen + blob.length;
  outBytes += 4 + newHeader.length + newBlob.length;
  if (blocks % 10000 === 0)
    console.error(`${blocks} blocks, ${(outBytes / 1e9).toFixed(2)} GB written`);
}
await out.close();

const secs = (Date.now() - start) / 1000;
console.error(
  `${blocks} blocks: ${(inBytes / 1e9).toFixed(2)} GB in, ${(outBytes / 1e9).toFixed(2)} GB out ` +
    `(zstd level ${level}) in ${secs.toFixed(1)}s`,
);
