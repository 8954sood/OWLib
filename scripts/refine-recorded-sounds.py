"""Search full recording offsets for shortlisted effects, including repeated occurrences."""

import argparse
import concurrent.futures
import importlib.util
import json
import pathlib
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--analysis', type=pathlib.Path, required=True)
    parser.add_argument('--reference', type=pathlib.Path, required=True)
    parser.add_argument('--ffmpeg', type=pathlib.Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('finder', pathlib.Path(__file__).with_name('find-recorded-sounds.py'))
    finder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(finder)
    recording = finder.decode(args.reference, args.ffmpeg).astype(np.float64)
    candidates = {}
    for name, minimum in [('nonvoice-matches.json', .25), ('short-matches.json', .8)]:
        for item in json.loads((args.analysis / name).read_text(encoding='utf-8')):
            if float(item['duration_seconds']) <= 10 and item['waveform_score'] >= minimum:
                candidates[item['guid']] = item
    length = 1 << (len(recording) + 16000 - 1).bit_length()
    transform = np.fft.rfft(recording, length)
    sums = np.concatenate(([0.0], np.cumsum(recording)))
    squares = np.concatenate(([0.0], np.cumsum(recording * recording)))
    variances = {}

    def work(item):
        samples = finder.decode(args.root / item['path'], args.ffmpeg).astype(np.float64)
        size = min(len(samples), 16000)
        if size < 128:
            return {**item, 'waveform_score': 0.0, 'occurrences': []}
        energy = np.concatenate(([0.0], np.cumsum(samples * samples)))
        begin = int(np.argmax(energy[size:] - energy[:-size]))
        template = samples[begin:begin + size].copy()
        template -= template.mean()
        template_energy = np.sum(template * template)
        if template_energy < 1e-12:
            return {**item, 'waveform_score': 0.0, 'occurrences': []}
        correlation = np.fft.irfft(transform * np.conj(np.fft.rfft(template, length)), length)[:len(recording) - size + 1]
        variance = variances.get(size)
        if variance is None:
            variance = np.maximum(squares[size:] - squares[:-size] - (sums[size:] - sums[:-size]) ** 2 / size, 0)
            if len(variances) < 64:
                variances[size] = variance
        scores = np.abs(correlation) / np.sqrt(np.maximum(variance * template_energy, 1e-20))
        scores[variance / size < 1e-7] = 0
        best = int(np.argmax(scores))
        score = float(min(1.0, scores[best]))
        occurrences = []
        for _ in range(30):
            peak = int(np.argmax(scores))
            value = float(min(1.0, scores[peak]))
            if value < .6:
                break
            occurrences.append({'reference_seconds': max(0.0, (peak - begin) / finder.RATE),
                                'matched_reference_seconds': peak / finder.RATE,
                                'waveform_score': value})
            radius = max(size // 2, finder.RATE // 8)
            scores[max(0, peak - radius):peak + radius + 1] = 0
        return {**item, 'waveform_score': score, 'reference_seconds': max(0.0, (best - begin) / finder.RATE),
                'matched_reference_seconds': best / finder.RATE, 'matched_source_seconds': begin / finder.RATE,
                'occurrences': occurrences}

    started = time.monotonic()
    found = []
    print(f'Refining {len(candidates)} effects against the full recording', flush=True)
    with (args.analysis / 'refinement-results.jsonl').open('w', encoding='utf-8') as stream:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            for count, item in enumerate(pool.map(work, candidates.values()), 1):
                stream.write(json.dumps(item, ensure_ascii=False) + '\n')
                stream.flush()
                found.append(item)
                if count % 100 == 0 or count == len(candidates):
                    print(f'Refined {count}/{len(candidates)} in {time.monotonic() - started:.0f}s', flush=True)
    found.sort(key=lambda item: item['waveform_score'], reverse=True)
    (args.analysis / 'refined-matches.json').write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Refinement finished; {sum(item["waveform_score"] >= .8 for item in found)} above .8. Candidates require review.', flush=True)


if __name__ == '__main__':
    main()
