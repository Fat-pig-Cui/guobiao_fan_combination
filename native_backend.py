"""Build and read the portable C++ finite-domain batch generator."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from decompose import Group, compact, parse

ROOT = Path(__file__).resolve().parent
KINDS = ('', 'chi', 'pon', 'minkan', 'ankan')
RECORD = struct.Struct('<Q34BBB8B')
MAGIC = b'MCRN0001'


def build(*, force=False):
    directory = ROOT / 'build-native'
    directory.mkdir(exist_ok=True)
    source = ROOT / 'native/structure_enumerator.cpp'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    exe = directory / ('mcr_structure_enumerator.exe' if os.name == 'nt'
                       else 'mcr_structure_enumerator')
    stamp = directory / 'source.sha256'
    if not force and exe.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return exe
    compiler = next((shutil.which(c) for c in ('clang++', 'g++') if shutil.which(c)), None)
    if compiler:
        subprocess.run([compiler, '-O3', '-std=c++17', '-Wall', '-Wextra',
                        str(source), '-o', str(exe)], check=True)
    else:
        if not shutil.which('cmake'):
            raise RuntimeError('Install a C++17 compiler; on Windows use Visual Studio Build Tools and CMake')
        subprocess.run(['cmake', '-S', str(ROOT/'native'), '-B', str(directory)], check=True)
        subprocess.run(['cmake', '--build', str(directory), '--config', 'Release'], check=True)
        candidates = (directory/'Release'/exe.name, exe)
        built = next((p for p in candidates if p.exists()), None)
        if built is None:
            raise RuntimeError('CMake completed but native executable was not found')
        if built != exe:
            shutil.copy2(built, exe)
    stamp.write_text(digest+'\n', encoding='ascii')
    return exe


def physical_key(data):
    """44-byte identity independent of decomposition and fixed-meld order."""
    counts = [0]*34
    for tile in parse(data['hand'])+parse(data['win']):
        counts[tile] += 1
    fixed = sorted((KINDS.index('minkan' if m['kind'] == 'kakan' else m['kind']),
                    min(parse(m['tiles']))) for m in data.get('melds', ()))
    slots = [v for g in fixed for v in g]+[0]*(8-2*len(fixed))
    return bytes(counts+[parse(data['win'])[0], len(fixed)]+slots)


def decode(payload):
    counts, win, nfixed = payload[:34], payload[34], payload[35]
    concealed = [t for t, n in enumerate(counts) for _ in range(n)]
    concealed.remove(win)
    fixed = [Group(KINDS[payload[36+2*i]], payload[37+2*i]) for i in range(nfixed)]
    return {'hand': compact(concealed), 'win': compact((win,)),
            'melds': [{'kind': g.kind, 'tiles': compact(g.tiles)} for g in fixed]}


def read_batch(path):
    raw = Path(path).read_bytes()
    if raw[:8] != MAGIC or (len(raw)-8) % RECORD.size:
        raise ValueError('Truncated or incompatible native batch')
    for offset in range(8, len(raw), RECORD.size):
        cursor = int.from_bytes(raw[offset:offset+8], 'little')
        yield cursor, raw[offset+8:offset+RECORD.size]


def generate_batch(executable, output, *, family='standard', tiles=range(34),
                   after=-1, max_records=4096, include_melds=True,
                   left_begin=0, left_end=None):
    mask = sum(1 << t for t in set(tiles))
    if not mask or mask >> 34 or min(tiles) < 0:
        raise ValueError('Tiles must be a nonempty subset of 0..33')
    command = [str(executable), '--output', str(output), '--family', family,
               '--tile-mask', str(mask), '--after', str(after),
               '--max-records', str(max_records), '--left-begin', str(left_begin)]
    if left_end is not None:
        command += ['--left-end', str(left_end)]
    if not include_melds:
        command.append('--concealed-only')
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


if __name__ == '__main__':
    print(build(force='--force' in sys.argv))
