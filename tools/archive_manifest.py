"""Write an artifact manifest for an already moved historical snapshot."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--description', default='Historical results and matching pre-change source; not a complete census')
    args = parser.parse_args()
    directory = args.directory.resolve()
    destination = directory / 'MANIFEST.json'
    rows = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or path == destination:
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
        rows.append({'path': str(path.relative_to(directory)),
                     'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    destination.write_text(json.dumps({
        'description': args.description,
        'files': rows, 'total_bytes': sum(r['bytes'] for r in rows),
    }, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'files': len(rows), 'bytes': sum(r['bytes'] for r in rows),
                      'manifest': str(destination)}))


if __name__ == '__main__':
    main()
