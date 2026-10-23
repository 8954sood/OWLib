"""Supplement landmark matching with full-recording correlation for short UI sounds."""

import argparse
import concurrent.futures
import csv
import importlib.util
import json
import pathlib
import subprocess
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--ffmpeg', type=pathlib.Path, required=True)
    parser.add_argument('--reference', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--audio-stream', type=int, default=0)
    parser.add_argument('--max-duration', type=float, default=0.35)
    parser.add_argument('--minimum-score', type=float, default=0.6)
    parser.add_argument('--candidates-json', type=pathlib.Path, help='Optional JSON shortlist from a previous pass')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('matcher', pathlib.Path(__file__).with_name('find-recorded-sounds.py'))
    matcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matcher)
    process = subprocess.run([str(args.ffmpeg), '-v', 'error', '-i', str(args.reference),
                              '-map', f'0:a:{args.audio_stream}', '-ac', '1', '-ar', str(matcher.RATE),
                              '-f', 'f32le', 'pipe:1'], capture_output=True, timeout=180, check=True)
    recording = np.frombuffer(process.stdout, dtype='<f4').astype(np.float64)
    args.output.mkdir(parents=True, exist_ok=True)
    reference_stat = args.reference.stat()
    configuration = {
        'version': 1, 'reference': str(args.reference.resolve()),
        'reference_size': reference_stat.st_size, 'reference_mtime': reference_stat.st_mtime_ns,
        'root': str(args.root.resolve()), 'audio_stream': args.audio_stream,
        'max_duration': args.max_duration,
    }
    selected = None
    if args.candidates_json:
        selected = {item['guid'] for item in json.loads(args.candidates_json.read_text(encoding='utf-8'))}
        configuration['candidate_guids'] = sorted(selected)
    config_file = args.output / 'short-config.json'
    if config_file.exists() and json.loads(config_file.read_text(encoding='utf-8')) != configuration:
        raise ValueError('This output folder contains results for a different recording/configuration; use a new output folder')
    config_file.write_text(json.dumps(configuration, indent=2), encoding='utf-8')
    with (args.root / 'index.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['status'] == 'success'
                and row['type'] != '0B2' and 0.016 <= float(row['duration_seconds']) <= args.max_duration
                and (selected is None or row['guid'] in selected)]
    length = 1 << (len(recording) + int(args.max_duration * matcher.RATE) - 1).bit_length()
    recording_fft = np.fft.rfft(recording, length)
    sums = np.concatenate(([0.0], np.cumsum(recording)))
    squares = np.concatenate(([0.0], np.cumsum(recording * recording)))
    variance_cache = {}
    result_file = args.output / 'short-results.jsonl'
    completed = {}
    if result_file.exists():
        for line in result_file.read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
                completed[item['guid']] = item
            except json.JSONDecodeError:
                pass
    pending = [row for row in rows if row['guid'] not in completed]
    started = time.monotonic()

    def work(row):
        try:
            samples = matcher.decode(args.root / row['path'], args.ffmpeg).astype(np.float64)
            samples -= samples.mean()
            size = len(samples)
            template_energy = float(np.sum(samples * samples))
            if size < 128 or template_energy < 1e-10:
                return {**row, 'waveform_score': 0.0, 'reference_seconds': 0.0}
            correlation = np.fft.irfft(recording_fft * np.conj(np.fft.rfft(samples, length)), length)[:len(recording) - size + 1]
            variance = variance_cache.get(size)
            if variance is None:
                variance = np.maximum(squares[size:] - squares[:-size] - (sums[size:] - sums[:-size]) ** 2 / size, 0)
                if len(variance_cache) < 64:
                    variance_cache[size] = variance
            score = np.abs(correlation) / np.sqrt(np.maximum(variance * template_energy, 1e-20))
            score[variance / size < 1e-7] = 0
            index = int(np.argmax(score))
            return {**row, 'waveform_score': float(min(1, score[index])), 'reference_seconds': index / matcher.RATE}
        except Exception as error:
            return {**row, 'waveform_score': 0.0, 'reference_seconds': 0.0, 'match_error': str(error)}

    print(f'Short-sound search: {len(rows)} files, {len(pending)} pending', flush=True)
    with result_file.open('a', encoding='utf-8') as out:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            for count, result in enumerate(pool.map(work, pending), 1):
                completed[result['guid']] = result
                out.write(json.dumps(result, ensure_ascii=False) + '\n')
                out.flush()
                if count % 100 == 0 or count == len(pending):
                    print(f'Short sounds {count}/{len(pending)} in {time.monotonic() - started:.0f}s', flush=True)
    matches = sorted((item for item in completed.values() if item['waveform_score'] >= args.minimum_score),
                     key=lambda item: item['waveform_score'], reverse=True)
    (args.output / 'short-matches.json').write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Finished: {len(matches)} short-sound candidates above {args.minimum_score}. Scores are not probabilities.', flush=True)


if __name__ == '__main__':
    main()
