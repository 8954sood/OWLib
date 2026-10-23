"""Find acoustic variants of a confirmed voice using an existing local fingerprint cache."""

import argparse
import csv
import html
import importlib.util
import json
import pathlib
import sqlite3

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['root', 'cache', 'seed', 'ffmpeg', 'output']:
        parser.add_argument('--' + name, type=pathlib.Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('finder', pathlib.Path(__file__).with_name('find-recorded-sounds.py'))
    finder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(finder)
    recording = finder.decode(args.seed, args.ffmpeg)
    reference = finder.fingerprint(recording)
    keys = np.unique(reference[:, 0])
    with (args.root / 'index.csv').open(encoding='utf-8-sig', newline='') as stream:
        metadata = {row['path']: row for row in csv.DictReader(stream) if row['status'] == 'success' and row['type'] == '0B2'}
    results = []
    screened = 0
    verified = 0
    with sqlite3.connect(args.cache.resolve().as_uri() + '?mode=ro', uri=True) as db:
        for path, blob in db.execute("SELECT path,hashes FROM tracks WHERE error=''"):
            if path not in metadata:
                continue
            screened += 1
            hashes = np.frombuffer(blob, dtype='<u4').reshape(-1, 2)
            if len(hashes) == 0 or np.count_nonzero(np.isin(hashes[:, 0], keys)) < 8:
                continue
            alignment = finder.find_alignment(hashes, reference)
            if not alignment:
                continue
            try:
                score = finder.verify_waveform(finder.decode(args.root / path, args.ffmpeg), recording, alignment)
                verified += 1
                results.append({**metadata[path], **alignment, **score})
            except Exception as error:
                results.append({**metadata[path], 'error': str(error), 'waveform_score': 0})
    results.sort(key=lambda row: row['waveform_score'], reverse=True)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'candidates.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    with (args.output / 'candidates.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['guid', 'type', 'duration_seconds', 'waveform_score', 'path'], extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    rows = []
    for item in results[:50]:
        source = (args.root / item['path']).resolve()
        if not source.is_relative_to(args.root.resolve()):
            raise ValueError('Source leaves extraction root')
        rows.append(f'<tr><td>{html.escape(source.name)}</td><td>{item["waveform_score"]:.3f}</td><td><audio controls preload="none" src="{html.escape(source.as_uri(), quote=True)}"></audio></td></tr>')
    document = '<!doctype html><meta charset="utf-8"><title>확인 음성의 유사 후보</title><body style="background:#0b0c10;color:#eee;font:16px system-ui"><h1>확인 음성의 유사 후보</h1><p>같은 소리의 변형을 찾는 음향 비교입니다. 같은 화자·대사·용도를 보장하지 않습니다. 기준 음원 자체도 포함됩니다.</p><table>' + ''.join(rows) + '</table>'
    (args.output / 'index.html').write_text(document, encoding='utf-8')
    print(json.dumps({'voices_screened': screened, 'waveforms_verified': verified, 'top': [{k: row.get(k) for k in ['guid', 'waveform_score', 'duration_seconds']} for row in results[:12]]}), flush=True)


if __name__ == '__main__':
    main()
