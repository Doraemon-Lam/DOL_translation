"""Compile local JSON dictionaries. Standard library only; no network requests."""
import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

MAGIC = b'DOLTXT1\0'

def load(paths, variants=False):
    result = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('A dictionary must be a JSON object')
        for source, target in data.items():
            if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
                raise ValueError('Entries must contain nonempty strings')
            if any(ord(c) < 32 and c not in '\r\n' for c in source + target):
                raise ValueError('Only CR and LF control characters are supported')
            if len(source.encode('utf-16-le')) > 8192 or len(target.encode('utf-16-le')) > 8192:
                raise ValueError('Entry exceeds 4096 UTF-16 code units')
            result[source] = target
    if variants:
        for source, target in list(result.items()):
            if source.startswith('：'):
                result.setdefault(source[1:], target[1:] if target.startswith('：') else target)
            else:
                result.setdefault('：' + source, '：' + target)
    return result

def encode(entries):
    data = bytearray(MAGIC + struct.pack('<I', len(entries)))
    for source, target in sorted(entries.items()):
        a, b = source.encode('utf-16-le'), target.encode('utf-16-le')
        data += struct.pack('<II', len(a)//2, len(b)//2) + a + b
    return bytes(data)

def decode(data):
    if len(data) < 12 or data[:8] != MAGIC:
        raise ValueError('Invalid dictionary header')
    count, = struct.unpack_from('<I', data, 8)
    if count > 100000:
        raise ValueError('Too many entries')
    cursor, result = 12, {}
    for _ in range(count):
        if cursor + 8 > len(data):
            raise ValueError('Truncated entry')
        a, b = struct.unpack_from('<II', data, cursor)
        cursor += 8
        if not a or not b or a > 4096 or b > 4096 or cursor + 2*(a+b) > len(data):
            raise ValueError('Invalid entry length')
        source = data[cursor:cursor+2*a].decode('utf-16-le'); cursor += 2*a
        target = data[cursor:cursor+2*b].decode('utf-16-le'); cursor += 2*b
        if '\0' in source+target or source in result:
            raise ValueError('Duplicate source or embedded NUL')
        result[source] = target
    if cursor != len(data):
        raise ValueError('Unexpected trailing bytes')
    return result

def compile_dictionary(paths, output, digest_header=None, variants=False, overlay=False):
    entries = load(paths, variants)
    data = encode(entries)
    if overlay and (len(data) > 1024*1024 or len(entries) > 10000):
        raise ValueError('Overlay exceeds 1 MiB / 10000 entry limit')
    if decode(data) != entries:
        raise AssertionError('Roundtrip mismatch')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + '.pending')
    with temp.open('wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temp.replace(output)
    digest = hashlib.sha256(data).digest()
    if digest_header:
        Path(digest_header).write_text('static const unsigned char dictionaryDigest[32]={' + ','.join('0x%02x' % b for b in digest) + '};\n', encoding='ascii')
    return {'entries': len(entries), 'bytes': len(data), 'sha256': digest.hex()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--digest-header', type=Path)
    parser.add_argument('--variants', action='store_true')
    parser.add_argument('--overlay', action='store_true')
    args = parser.parse_args()
    print(json.dumps(compile_dictionary(args.input, args.output, args.digest_header, args.variants, args.overlay), indent=2))

if __name__ == '__main__':
    main()
