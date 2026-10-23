"""Match recorded game audio against extracted resources locally; requires NumPy and FFmpeg."""

import argparse
import concurrent.futures
import csv
import json
import html
import pathlib
import sqlite3
import subprocess
import time

import numpy as np

RATE = 8000
HOP = 256
FFT = 1024
VERSION = 'landmarks-v1'
_REFERENCE_CACHE = (None, None, None)


def decode(path, ffmpeg):
    result = subprocess.run(
        [str(ffmpeg), '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path),
         '-vn', '-ac', '1', '-ar', str(RATE), '-f', 'f32le', 'pipe:1'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[:2000])
    return np.frombuffer(result.stdout, dtype='<f4').copy()


def fingerprint(samples):
    if len(samples) < FFT or np.max(np.abs(samples)) < 1e-6:
        return np.empty((0, 2), dtype='<u4')
    frames = np.lib.stride_tricks.sliding_window_view(samples, FFT)[::HOP]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(FFT), axis=1)).astype(np.float32)
    spectrum[:, :8] = 0
    local = spectrum.copy()
    for shift in range(1, 4):
        local[:, shift:] = np.maximum(local[:, shift:], spectrum[:, :-shift])
        local[:, :-shift] = np.maximum(local[:, :-shift], spectrum[:, shift:])
    peaks = (spectrum >= local) & (spectrum > max(float(spectrum.max()) * 0.003, 1e-6))
    candidates = np.where(peaks, spectrum, -1)
    points = []
    for start in range(0, len(frames), 2):
        block = candidates[start:start + 2]
        index = int(np.argmax(block))
        row, freq = np.unravel_index(index, block.shape)
        if block[row, freq] > 0:
            points.append((start + row, freq // 2))
    hashes = []
    for i, (anchor_time, anchor_frequency) in enumerate(points):
        for target_time, target_frequency in points[i + 1:i + 7]:
            delta = target_time - anchor_time
            if 2 <= delta <= 40:
                key = (anchor_frequency << 16) | (target_frequency << 8) | delta
                hashes.append((key, anchor_time))
    return np.asarray(hashes, dtype='<u4').reshape(-1, 2)


def find_alignment(candidate, reference):
    global _REFERENCE_CACHE
    if len(candidate) == 0 or len(reference) == 0:
        return None
    if _REFERENCE_CACHE[0] is not reference:
        ordered = reference[np.argsort(reference[:, 0])]
        keys, starts = np.unique(ordered[:, 0], return_index=True)
        ends = np.append(starts[1:], len(ordered))
        groups = {int(key): ordered[start:end, 1].astype(np.int64)
                  for key, start, end in zip(keys, starts, ends)}
        _REFERENCE_CACHE = (reference, keys, groups)
    reference_keys, reference_groups = _REFERENCE_CACHE[1:]
    candidate = candidate[np.argsort(candidate[:, 0])]
    candidate_keys, starts = np.unique(candidate[:, 0], return_index=True)
    ends = np.append(starts[1:], len(candidate))
    common_indices = np.flatnonzero(np.isin(candidate_keys, reference_keys, assume_unique=True))
    if len(common_indices) < 6:
        return None
    votes = []
    for index in common_indices:
        track_times = candidate[starts[index]:ends[index], 1].astype(np.int64)
        recording_times = reference_groups[int(candidate_keys[index])]
        if len(track_times) * len(recording_times) > 500:
            continue
        votes.append((recording_times[:, None] - track_times[None, :]).ravel())
    if not votes:
        return None
    votes = np.concatenate(votes)
    offsets, counts = np.unique(votes // 3, return_counts=True)
    best = int(np.argmax(counts))
    offset = int(offsets[best]) * 3
    coherent = int(np.count_nonzero(np.abs(votes - offset - 1) <= 3))
    if coherent < 8:
        return None
    return {
        'landmark_votes': coherent,
        'reference_seconds': max(0.0, (offset + 1) * HOP / RATE),
        'offset_seconds': (offset + 1) * HOP / RATE,
        'hash_coverage': min(1.0, coherent / max(1, len(candidate))),
    }


def verify_waveform(samples, recording, alignment):
    offset = int(alignment['offset_seconds'] * RATE)
    first = max(0, -offset)
    last = min(len(samples), len(recording) - offset)
    width = min(RATE, last - first)
    if width < 128:
        return {'waveform_score': 0.0}
    region = samples[first:last].astype(np.float64)
    energy = np.concatenate(([0.0], np.cumsum(region * region)))
    start = first + int(np.argmax(energy[width:] - energy[:-width]))
    template = samples[start:start + width].astype(np.float64)
    template -= template.mean()
    expected = offset + start
    window_start = max(0, expected - RATE // 3)
    window_end = min(len(recording), expected + width + RATE // 3)
    window = recording[window_start:window_end].astype(np.float64)
    if len(window) < width or np.sum(template * template) < 1e-12:
        return {'waveform_score': 0.0}
    length = 1 << (len(window) + width - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(window, length) * np.conj(np.fft.rfft(template, length)), length)[:len(window) - width + 1]
    sums = np.concatenate(([0.0], np.cumsum(window)))
    squares = np.concatenate(([0.0], np.cumsum(window * window)))
    variance = squares[width:] - squares[:-width] - (sums[width:] - sums[:-width]) ** 2 / width
    normalized = np.abs(correlation) / np.sqrt(np.maximum(variance * np.sum(template * template), 1e-20))
    best = int(np.argmax(normalized))
    return {'waveform_score': float(min(1.0, normalized[best])),
            'matched_reference_seconds': (window_start + best) / RATE,
            'matched_source_seconds': start / RATE,
            'reference_seconds': max(0.0, (window_start + best - start) / RATE)}


def open_cache(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS tracks (path TEXT PRIMARY KEY, signature TEXT, hashes BLOB, error TEXT)')
    return db


def build_cache(rows, root, db, ffmpeg, workers):
    cached = dict(db.execute("SELECT path,signature FROM tracks WHERE error=''"))
    pending = []
    for row in rows:
        source = root / row['path']
        stat = source.stat()
        signature = f'{VERSION}:{stat.st_size}:{stat.st_mtime_ns}'
        if cached.get(row['path']) != signature:
            pending.append((row['path'], signature))
    print(f'Cache: {len(rows) - len(pending)} ready, {len(pending)} to analyze', flush=True)

    def work(item):
        relative, signature = item
        try:
            hashes = fingerprint(decode(root / relative, ffmpeg))
            return relative, signature, hashes.tobytes(), ''
        except Exception as error:
            return relative, signature, b'', str(error)

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for count, result in enumerate(pool.map(work, pending), 1):
            db.execute('INSERT OR REPLACE INTO tracks VALUES (?,?,?,?)', result)
            if count % 100 == 0 or count == len(pending):
                db.commit()
                print(f'Analyzed {count}/{len(pending)} in {time.monotonic() - started:.0f}s', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--ffmpeg', type=pathlib.Path, required=True)
    parser.add_argument('--reference', type=pathlib.Path)
    parser.add_argument('--output', type=pathlib.Path)
    parser.add_argument('--include-voice', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, default=0, help='Diagnostic subset only; 0 means all')
    parser.add_argument('--cached-only', action='store_true', help='Search existing cache without decoding uncached files; partial result if cache is incomplete')
    args = parser.parse_args()
    root = args.root.resolve()
    with (root / 'index.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['status'] == 'success'
                and (args.include_voice or row['type'] != '0B2')]
    if args.limit:
        rows = rows[:args.limit]
    output = (args.output or root / 'recording-matches').resolve()
    output.mkdir(parents=True, exist_ok=True)
    db = open_cache(output / 'fingerprints.sqlite3')
    if args.cached_only:
        print('Searching cached entries only; uncached files will be skipped.', flush=True)
    else:
        build_cache(rows, root, db, args.ffmpeg.resolve(), max(1, min(args.workers, 12)))
    if not args.reference:
        print('Fingerprint cache ready. Supply --reference with a recording to search.', flush=True)
        return
    recording = decode(args.reference.resolve(), args.ffmpeg.resolve())
    reference = fingerprint(recording)
    reference_keys = np.unique(reference[:, 0])
    print(f'Reference fingerprints: {len(reference)}', flush=True)
    found = []
    for count, row in enumerate(rows, 1):
        record = db.execute('SELECT hashes,error FROM tracks WHERE path=?', (row['path'],)).fetchone()
        if not record or record[1]:
            continue
        candidate = np.frombuffer(record[0], dtype='<u4').reshape(-1, 2)
        if len(candidate) == 0 or np.count_nonzero(np.isin(candidate[:, 0], reference_keys)) < 6:
            continue
        alignment = find_alignment(candidate, reference)
        if alignment:
            found.append({**{key: row[key] for key in ('guid', 'type', 'path', 'duration_seconds')}, **alignment})
        if count % 5000 == 0:
            print(f'Matched {count}/{len(rows)}; candidates={len(found)}', flush=True)
    print(f'Verifying waveforms for {len(found)} landmark candidates', flush=True)
    def verify(item):
        try:
            return {**item, **verify_waveform(decode(root / item['path'], args.ffmpeg.resolve()), recording, item)}
        except Exception:
            return {**item, 'waveform_score': 0.0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        verified = []
        total = len(found)
        for count, item in enumerate(pool.map(verify, found), 1):
            verified.append(item)
            if count % 1000 == 0 or count == total:
                print(f'Waveform verification {count}/{total}', flush=True)
        found = verified
    for item in found:
        item.pop('offset_seconds', None)
    found.sort(key=lambda item: (item['waveform_score'], item['landmark_votes']), reverse=True)
    fields = ['guid', 'type', 'path', 'duration_seconds', 'reference_seconds', 'waveform_score', 'landmark_votes', 'hash_coverage', 'matched_reference_seconds', 'matched_source_seconds']
    with (output / 'matches.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(found)
    (output / 'matches.json').write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding='utf-8')
    entries = []
    for item in found[:200]:
        seconds = item['reference_seconds']
        uri = html.escape((root / item['path']).as_uri(), quote=True)
        entries.append(
            f'<tr><td>{html.escape(item["guid"])}.{html.escape(item["type"])}</td>'
            f'<td><button onclick="document.querySelector(\'video\').currentTime={seconds:.3f};document.querySelector(\'video\').play()">{seconds:.2f}초로 이동</button></td>'
            f'<td>파형 {item["waveform_score"]:.3f}<br>지문 {item["landmark_votes"]} / {item["hash_coverage"]:.3f}</td>'
            f'<td><audio controls preload="none" src="{uri}"></audio><br><a href="{uri}">원본 파일</a></td></tr>'
        )
    page = ('<!doctype html><meta charset="utf-8"><title>녹화 사운드 자동 검색</title>'
            '<style>body{font:16px system-ui;background:#0b0c10;color:#eee;margin:30px}video{width:min(900px,95%);max-height:400px}td,th{padding:12px;border-bottom:1px solid #555}a{color:#7df}button{padding:8px}audio{width:260px}</style>'
            '<h1>녹화에서 찾은 사운드 후보</h1><p>파형 유사도순 상위 200개입니다. 점수는 확률이 아니며 경쟁전 전용 여부를 보증하지 않습니다. 녹화의 시점과 원본을 비교해 확인하세요.</p>'
            '<p>짧은 클릭, 겹친 소리, 변조·루프·배속·다른 채널 믹스로 누락되거나 오탐이 생길 수 있습니다. 전체 결과는 matches.csv에 있습니다.</p>'
            f'<video controls preload="metadata" src="{html.escape(args.reference.resolve().as_uri(), quote=True)}"></video>'
            '<table><thead><tr><th>GUID</th><th>녹화 시점</th><th>일치 지문 수 / 비율</th><th>추출 원본</th></tr></thead><tbody>'
            + ''.join(entries) + '</tbody></table>')
    (output / 'matches.html').write_text(page, encoding='utf-8')
    print(f'Finished: {len(found)} candidates. These are acoustic matches, not semantic proof of competitive use. {output / "matches.csv"}', flush=True)


if __name__ == '__main__':
    main()
