"""Decode prepared character streams, without loading the entire corpus into RAM."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--documents', type=int, default=3)
    args = parser.parse_args()
    chars = json.loads(Path(__file__).with_name('manifest.json').read_text(encoding='utf-8'))['alphabet']
    lookup = bytes(ord(c) for c in chars)
    table = bytes.maketrans(bytes(range(len(chars))), lookup)
    if args.output:
        if args.output.resolve() == args.input.resolve():
            parser.error('Input and output must be different files.')
        with args.input.open('rb') as source, args.output.open('wb') as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                if max(chunk) >= len(chars):
                    raise ValueError('Invalid character-token ID')
                target.write(chunk.translate(table))
    else:
        if args.documents < 1:
            parser.error('--documents must be positive')
        import numpy as np
        starts = np.load(args.input.with_name(args.input.stem + '_docs.npy'), allow_pickle=False)
        end = int(starts[args.documents]) if args.documents < len(starts) else args.input.stat().st_size
        with args.input.open('rb') as source:
            data = source.read(end)
        if data and max(data) >= len(chars):
            raise ValueError('Invalid character-token ID')
        print(data.translate(table).decode('ascii'))


if __name__ == '__main__':
    main()
