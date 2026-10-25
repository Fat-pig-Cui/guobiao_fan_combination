"""Portable native basis scorer build, protocol and witness decoding."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from calc_fan import BANS
from native_backend import decode, physical_key
from rules import FANS, PROFILE

ROOT = Path(__file__).resolve().parent
RECORD = struct.Struct('<44s9B86s')
SOURCES = ('native/basis_scorer.hpp', 'native/basis_census.cpp',
           'native/structure_enumerator.cpp', 'basis_backend.py', 'rules.py',
           'calc_fan.py', 'decompose.py', 'reachability.py', 'context_expansion.py')


def fingerprint():
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES}


def build():
    directory = ROOT/'build-basis'
    directory.mkdir(exist_ok=True)
    exe = directory/('mcr_basis_census.exe' if os.name == 'nt' else 'mcr_basis_census')
    stamp = directory/'source.sha256'
    digest = hashlib.sha256(json.dumps(fingerprint(), sort_keys=True).encode()).hexdigest()
    if exe.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return exe
    compiler = next((shutil.which(c) for c in ('clang++', 'g++') if shutil.which(c)), None)
    if compiler:
        subprocess.run([compiler, '-O3', '-std=c++17', '-Wall', '-Wextra',
                        str(ROOT/'native/basis_census.cpp'), '-o', str(exe)], check=True)
    else:
        if not shutil.which('cmake'):
            raise RuntimeError('Install a C++17 compiler or Visual Studio Build Tools and CMake')
        subprocess.run(['cmake', '-S', str(ROOT/'native/basis'), '-B', str(directory)], check=True)
        subprocess.run(['cmake', '--build', str(directory), '--config', 'Release'], check=True)
        built = next((p for p in (directory/'Release'/exe.name, exe) if p.exists()), None)
        if built is None:
            raise RuntimeError('CMake did not produce the basis executable')
        if built != exe:
            shutil.copy2(built, exe)
    stamp.write_text(digest+'\n', encoding='ascii')
    return exe


def write_rules(path):
    lines = ['MCRRULE1', ' '.join(str(FANS[i]['value']) for i in range(8000, 8086))]
    for i in range(8000, 8086):
        bans = BANS.get(i, ())
        lines.append(' '.join(map(str, (len(bans), *(f-8000 for f in bans)))))
    Path(path).write_text('\n'.join(lines)+'\n', encoding='ascii')


def key_bytes(key, policy, closed, method):
    f = bytearray(86)
    for i, count in key:
        f[i-8000] = count
    return bytes(f)+bytes((policy == 'canonical', bool(closed), method == 'tsumo'))


def write_known(path, rows):
    with Path(path).open('wb') as stream:
        stream.write(b'MCRK0001')
        for key, policy, closed, method in rows:
            stream.write(key_bytes(json.loads(key) if isinstance(key, str) else key,
                                   policy, closed, method))


def read_observations(path):
    with Path(path).open('rb') as stream:
        if stream.read(8) != b'MCRB0001':
            raise ValueError('Invalid basis observation magic')
        while True:
            raw = stream.read(RECORD.size)
            if not raw:
                return
            if len(raw) != RECORD.size:
                raise ValueError('Truncated basis observation')
            physical, method, source, opening, wall, external, seat, rnd, closed, policy, fans = RECORD.unpack(raw)
            data = decode(physical)
            data.update(profile=PROFILE, method='tsumo' if method else 'ron',
                        seat_wind=f'{seat-26}z', round_wind=f'{rnd-26}z',
                        context={'draw_source':('normal', 'kan_replacement', 'kakan_ron')[source],
                                 'opening':('none', 'heaven', 'earth', 'human')[opening],
                                 'wall_empty':bool(wall),
                                 'visible_before_win': [physical[34]]*external})
            key = [[8000+i, n] for i,n in enumerate(fans) if n]
            yield {'key':key, 'policy':'canonical' if policy else 'all_optimal',
                   'closed':bool(closed), 'method':data['method'],
                   'total':sum(FANS[f]['value']*n for f,n in key), 'input':data}


def batch(directory, *, family='standard', tiles=range(34), include_melds=True,
          after=-1, max_bases=128, seconds=0, left_begin=0, left_end=None,
          known=None, input_path=None, all_results=False, physical_output=None, max_fan=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    executable = build()
    rules = directory/'rules.txt'
    write_rules(rules)
    output = directory/'observations.bin'
    command = [str(executable), '--rules', str(rules), '--output', str(output),
               '--family', family, '--tile-mask', str(sum(1 << t for t in set(tiles))),
               '--after', str(after), '--max-bases', str(max_bases),
               '--seconds', str(seconds), '--left-begin', str(left_begin)]
    if left_end is not None:
        command += ['--left-end', str(left_end)]
    if max_fan is not None:
        command += ['--max-fan', str(max_fan)]
    if not include_melds:
        command.append('--concealed-only')
    if known is not None:
        command += ['--known', str(known)]
    if input_path is not None:
        command += ['--input', str(input_path)]
    if physical_output is not None:
        command += ['--physical-output',str(physical_output)]
    if all_results:
        command.append('--all-results')
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout), list(read_observations(output))


if __name__ == '__main__':
    print(build())
