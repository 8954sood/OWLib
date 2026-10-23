"""Compare several locally edited game clips against extracted sounds in one pass."""

import argparse
import concurrent.futures
import csv
import html
import importlib.util
import json
import pathlib
import shutil
import sqlite3
import time
from urllib.parse import quote

import numpy as np


def correlations(template, recording):
    template = template.astype(np.float64)
    template = template - template.mean()
    size = len(template)
    if size < 128 or size > len(recording):
        return None
    energy = float(np.dot(template, template))
    if energy < 1e-12:
        return None
    length = 1 << (len(recording) + size - 1).bit_length()
    dots = np.fft.irfft(np.fft.rfft(recording, length) * np.conj(np.fft.rfft(template, length)), length)[:len(recording) - size + 1]
    sums = np.r_[0, np.cumsum(recording)]
    squares = np.r_[0, np.cumsum(recording * recording)]
    variance = np.maximum(squares[size:] - squares[:-size] - (sums[size:] - sums[:-size]) ** 2 / size, 0)
    scores = np.abs(dots) / np.sqrt(np.maximum(variance * energy, 1e-20))
    scores[variance / size < 1e-8] = 0
    return np.minimum(scores, 1), dots, energy


def compare(samples, recording, starts, rate, focus=None):
    samples = samples.astype(np.float64)
    size, count = len(samples), len(recording)
    minimum_overlap = min(size, max(128, min(1600, size // 2, count // 2)))
    if size < 128 or count < 128:
        return None
    length = 1 << (size + count - 1).bit_length()
    dots = np.fft.irfft(np.fft.rfft(recording, length) * np.conj(np.fft.rfft(samples, length)), length)
    offsets = np.arange(-size + minimum_overlap, count - minimum_overlap + 1)
    source_starts = np.maximum(0, -offsets)
    reference_starts = np.maximum(0, offsets)
    overlaps = np.minimum(size - source_starts, count - reference_starts)
    sx = np.r_[0, np.cumsum(samples)]
    xx = np.r_[0, np.cumsum(samples * samples)]
    sy = np.r_[0, np.cumsum(recording)]
    yy = np.r_[0, np.cumsum(recording * recording)]
    sums_x = sx[source_starts + overlaps] - sx[source_starts]
    sums_y = sy[reference_starts + overlaps] - sy[reference_starts]
    centered_dots = dots[offsets % length] - sums_x * sums_y / overlaps
    vx = np.maximum(xx[source_starts + overlaps] - xx[source_starts] - sums_x ** 2 / overlaps, 0)
    vy = np.maximum(yy[reference_starts + overlaps] - yy[reference_starts] - sums_y ** 2 / overlaps, 0)
    scores = np.minimum(1., np.abs(centered_dots) / np.sqrt(np.maximum(vx * vy, 1e-20)))
    scores[(vx / overlaps < 1e-8) | (vy / overlaps < 1e-8)] = 0
    if focus is not None:
        focus_overlap = np.maximum(0, np.minimum(reference_starts + overlaps, focus[1]) - np.maximum(reference_starts, focus[0]))
        scores[focus_overlap < np.minimum(overlaps * .5, .08 * rate)] = 0
    floors = np.where(overlaps < .04 * rate, .95, np.where(overlaps < .08 * rate, .9, np.where(overlaps < .15 * rate, .8, .65)))
    explained = centered_dots ** 2 / np.maximum(vx, 1e-20)
    explained[scores < floors] = 0
    peak = int(np.argmax(explained)) if np.max(explained) > 0 else int(np.argmax(scores))
    remaining = explained.copy()
    occurrences = []
    fitted = np.zeros(count)
    for _ in range(12):
        index = int(np.argmax(remaining))
        if remaining[index] <= 0 or scores[index] < max(float(floors[index]), float(scores[peak]) * .85):
            break
        occurrences.append({'clip_seconds': int(reference_starts[index]) / rate,
                            'source_seconds': int(source_starts[index]) / rate,
                            'resource_start_clip_seconds': int(offsets[index]) / rate,
                            'overlap_seconds': int(overlaps[index]) / rate,
                            'waveform_score': float(scores[index])})
        source_start = int(source_starts[index])
        reference_start = int(reference_starts[index])
        overlap = int(overlaps[index])
        component = samples[source_start:source_start + overlap] - sums_x[index] / overlap
        fitted[reference_start:reference_start + overlap] += component * centered_dots[index] / max(vx[index], 1e-20)
        radius = max(round(min(size, count) * .95), rate // 10)
        remaining[max(0, index - radius):index + radius + 1] = 0
        if size > count:
            break
    energy = max(0., float(np.dot(recording, recording) - np.dot(recording - fitted, recording - fitted)))
    return {'waveform_score': float(scores[peak]), 'clip_seconds': int(reference_starts[peak]) / rate,
            'source_seconds': int(source_starts[peak]) / rate,
            'resource_start_clip_seconds': int(offsets[peak]) / rate,
            'template_seconds': int(overlaps[peak]) / rate,
            'method': 'whole-resource' if overlaps[peak] == size else 'edge-clipped-resource',
            'explained_clip_energy': min(1., energy / max(float(np.dot(recording, recording)), 1e-20)),
            'occurrences': occurrences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['root', 'cache', 'ffmpeg', 'output', 'recordings']:
        parser.add_argument('--' + name, type=pathlib.Path, required=True)
    parser.add_argument('--clips', type=pathlib.Path, nargs='+', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--refine-results', type=pathlib.Path, help='Recheck the union of leading candidates from an earlier pass')
    parser.add_argument('--voice-clip', action='append', default=[], help='Clip stem where voice candidates should be shown before layered UI sounds')
    parser.add_argument('--rate', type=int, choices=[8000, 24000, 48000], default=8000)
    parser.add_argument('--leaders', type=int, default=1000, help='Per-clip shortlist size for refinement')
    parser.add_argument('--pitch-search', action='store_true', help='Verify shortlisted candidates with small playback speed variations')
    parser.add_argument('--candidate-guids', type=pathlib.Path, help='JSON list of additional GUIDs to verify directly')
    parser.add_argument('--context-seconds', type=float, default=0., help='Restore original recording context to verify effects truncated by editing')
    args = parser.parse_args()
    if args.candidate_guids and not args.refine_results:
        parser.error('--candidate-guids requires --refine-results')
    args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('finder', pathlib.Path(__file__).with_name('find-recorded-sounds.py'))
    finder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(finder)
    if args.rate != 8000 and not args.refine_results:
        raise ValueError('Higher-rate verification requires a previous candidate pass')
    finder.RATE = args.rate
    rate = finder.RATE
    with (args.root / 'index.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = {row['path']: row for row in csv.DictReader(stream) if row['status'] == 'success'}
    recordings = []
    for info in json.loads(args.recordings.read_text(encoding='utf-8')):
        recordings.append({**info, 'samples': finder.decode(pathlib.Path(info['path']), args.ffmpeg).astype(float),
                           'residual_samples': finder.decode(pathlib.Path(info['residual']), args.ffmpeg).astype(float),
                           'bgm_samples': finder.decode(pathlib.Path(info['bgm']), args.ffmpeg).astype(float) if info.get('bgm') else None})
        source = recordings[-1]
        if args.rate > 8000 and source['bgm_samples'] is not None:
            anchor = round(18 * rate)
            expected = round(source['bgm_offset'] * rate) + anchor
            padding = rate // 4000
            window_start = max(0, expected - padding)
            result = correlations(source['bgm_samples'][anchor:anchor + rate], source['samples'][window_start:expected + rate + padding])
            if result is not None:
                source['bgm_offset'] = (window_start + int(np.argmax(result[0])) - anchor) / rate
    clips = []
    for path in args.clips:
        samples = finder.decode(path, args.ffmpeg).astype(float)
        best = None
        for source in recordings:
            result = correlations(samples, source['samples'])
            if result is None:
                continue
            scores = result[0]
            index = int(np.argmax(scores))
            score = float(scores[index])
            if best is None or score > best['score']:
                best = {'source': source, 'index': index, 'score': score}
        if best is None:
            raise ValueError('Cannot locate clip in supplied recordings')
        source = best['source']
        begin = best['index']
        original_begin = begin
        original_size = len(samples)
        if args.context_seconds:
            begin = max(0, begin - round(args.context_seconds * rate))
            end = min(len(source['samples']), original_begin + original_size + round(args.context_seconds * rate))
            samples = source['samples'][begin:end].copy()
        residual = samples.copy()
        # Subtract only the BGM estimate removed from the original recording.
        if best['score'] >= .7:
            bgm = source['samples'][begin:begin + len(samples)] - source['residual_samples'][begin:begin + len(samples)]
            if source['bgm_samples'] is not None:
                bgm = np.zeros(len(samples))
                indices = np.arange(begin, begin + len(samples)) - round(source['bgm_offset'] * rate)
                valid = (indices >= 0) & (indices < len(source['bgm_samples']))
                bgm[valid] = source['bgm_samples'][indices[valid]]
            gain = float(np.dot(samples, bgm) / max(np.dot(bgm, bgm), 1e-20))
            if source['bgm_samples'] is not None:
                mask = np.abs(bgm) > max(float(np.percentile(np.abs(bgm), 60)), 1e-8)
                if np.count_nonzero(mask) > 128:
                    gain = float(np.median(samples[mask] / bgm[mask]))
            segment = source['samples'][begin:begin + len(samples)]
            scale = float(np.dot(samples, segment) / max(np.dot(segment, segment), 1e-20))
            limit = 1.5 * source.get('bgm_gain', 2) * abs(scale)
            if 0 <= gain <= limit:
                residual -= gain * bgm
        clip = {'name': path.stem, 'path': str(path), 'samples': samples, 'residual': residual,
                'hashes': finder.fingerprint(samples), 'source_recording': source['path'],
                'source_start_seconds': begin / rate, 'source_alignment_score': best['score'],
                'prior': {}, 'results': []}
        clip['focus'] = (original_begin - begin, original_begin - begin + original_size)
        clip['original_source_start_seconds'] = original_begin / rate
        clip['previous_positions'] = {}
        for analysis_path in source['analyses']:
            for item in json.loads(pathlib.Path(analysis_path).read_text(encoding='utf-8')):
                if item['waveform_score'] < .25:
                    continue
                occurrences = item.get('occurrences', []) or [item]
                for occurrence in occurrences:
                    t = occurrence.get('reference_seconds', item['reference_seconds'])
                    if t <= begin / rate + len(samples) / rate and t + float(item['duration_seconds']) >= begin / rate:
                        clip['prior'].setdefault(item['path'], []).append(t - begin / rate)
        clips.append(clip)
        print(json.dumps({'clip': path.name, 'source_start_seconds': begin / rate, 'alignment': best['score']}), flush=True)
    alignments = {}
    keys = [np.unique(clip['hashes'][:, 0]) for clip in clips]
    selected = None
    if args.refine_results:
        selected = set()
        for clip in clips:
            previous = json.loads((args.refine_results / clip['name'] / 'candidates.json').read_text(encoding='utf-8'))
            leaders = sorted(previous, key=lambda item: item['explained_clip_energy'], reverse=True)[:args.leaders]
            leaders += sorted(previous, key=lambda item: item['original_waveform_score'], reverse=True)[:max(30, args.leaders // 3)]
            leaders += [item for item in previous if item['type'] == '0B2']
            for item in leaders:
                clip['previous_positions'].setdefault(item['path'], []).append(item.get('resource_start_clip_seconds', item['clip_seconds'] - item['source_seconds']))
            selected.update(item['path'] for item in leaders)
            if args.leaders >= 1000:
                selected.update(clip['prior'])
        if args.candidate_guids:
            extra = set(json.loads(args.candidate_guids.read_text(encoding='utf-8')))
            selected.update(row['path'] for row in rows.values() if row['guid'] in extra)
    with sqlite3.connect(args.cache.resolve().as_uri() + '?mode=ro', uri=True) as db:
        for count, (path, blob) in enumerate(db.execute("SELECT path,hashes FROM tracks WHERE error=''"), 1):
            if path not in rows or (selected is not None and path not in selected) or args.rate != 8000:
                continue
            hashes = np.frombuffer(blob, dtype='<u4').reshape(-1, 2)
            for index, clip in enumerate(clips):
                if len(hashes) and np.count_nonzero(np.isin(hashes[:, 0], keys[index])) >= 6:
                    alignment = finder.find_alignment(hashes, clip['hashes'])
                    if alignment:
                        alignments.setdefault(path, {})[index] = alignment
            if count % 20000 == 0:
                print(f'Fingerprint screening {count}/{len(rows)}', flush=True)
    pending = [row for path, row in rows.items() if (selected is not None and path in selected) or (selected is None and (path in alignments
               or (row['type'] != '0B2' and .016 <= float(row['duration_seconds']) <= 5)
               or any(path in clip['prior'] for clip in clips)))]
    print(f'Decoding {len(pending)} sources once for all {len(clips)} clips', flush=True)

    def work(row):
        try:
            samples = finder.decode(args.root / row['path'], args.ffmpeg)
            results = []
            for index, clip in enumerate(clips):
                if args.pitch_search and row['path'] not in clip['previous_positions']:
                    continue
                starts = []
                offsets = list(clip['prior'].get(row['path'], []))
                offsets.extend(clip['previous_positions'].get(row['path'], []))
                alignment = alignments.get(row['path'], {}).get(index)
                if alignment:
                    offsets.append(alignment['offset_seconds'])
                regions = [(0, samples)]
                if len(samples) > 60 * rate:
                    regions = []
                    for offset in (offsets[:3] or [0.]):
                        first = max(0, -round(offset * rate) - rate // 2)
                        last = min(len(samples), len(clip['samples']) - round(offset * rate) + rate // 2)
                        if last > first:
                            regions.append((first, samples[first:last]))
                original = residual = None
                for source_begin, region in regions:
                    speeds = sorted({1., *np.arange(.9, 1.101, .005), *np.arange(.995, 1.0051, .0005)}) if args.pitch_search else [1.]
                    grid = np.arange(len(region))
                    for speed in speeds:
                        warped = region if speed == 1. else np.interp(np.arange(round(len(region) / speed)) * speed, grid, region)
                        left = compare(warped, clip['samples'], starts, rate, clip['focus'])
                        right = compare(warped, clip['residual'], starts, rate, clip['focus'])
                        for item in [left, right]:
                            if item:
                                item['source_seconds'] = item['source_seconds'] * speed + source_begin / rate
                                item['resource_start_clip_seconds'] -= source_begin / rate / speed
                                item['playback_speed'] = float(speed)
                                if len(region) != len(samples):
                                    item['method'] = 'prior-window-of-long-resource'
                                for occurrence in item['occurrences']:
                                    occurrence['source_seconds'] = occurrence['source_seconds'] * speed + source_begin / rate
                                    occurrence['resource_start_clip_seconds'] -= source_begin / rate / speed
                        if left and (original is None or (left['explained_clip_energy'], left['waveform_score']) > (original['explained_clip_energy'], original['waveform_score'])):
                            original = left
                        if right and (residual is None or (right['explained_clip_energy'], right['waveform_score']) > (residual['explained_clip_energy'], residual['waveform_score'])):
                            residual = right
                if original is None or residual is None:
                    continue
                for item in [original, residual]:
                    item['clip_seconds'] -= clip['focus'][0] / rate
                    item['resource_start_clip_seconds'] -= clip['focus'][0] / rate
                    for occurrence in item['occurrences']:
                        occurrence['clip_seconds'] -= clip['focus'][0] / rate
                        occurrence['resource_start_clip_seconds'] -= clip['focus'][0] / rate
                # Residual is used for ranking; retain the unmodified comparison as evidence.
                if max(original['waveform_score'], residual['waveform_score']) >= .45:
                    results.append((index, {**{k: row[k] for k in ['guid', 'type', 'path', 'duration_seconds']},
                                            **residual, 'original_waveform_score': original['waveform_score']}))
            return results, None
        except Exception as error:
            return [], {'path': row['path'], 'error': str(error)}

    started = time.monotonic()
    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as stream, (args.output / 'errors.jsonl').open('w', encoding='utf-8') as errors:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for count, (results, error) in enumerate(pool.map(work, pending), 1):
                for index, item in results:
                    clips[index]['results'].append(item)
                    stream.write(json.dumps({'clip': clips[index]['name'], **item}, ensure_ascii=False) + '\n')
                if error:
                    errors.write(json.dumps(error) + '\n')
                if count % 1000 == 0 or count == len(pending):
                    stream.flush()
                    print(f'Compared {count}/{len(pending)} sources in {time.monotonic() - started:.0f}s', flush=True)
    summary = []
    sections = []
    for index, clip in enumerate(clips):
        clip['results'].sort(key=lambda item: (clip['name'] in args.voice_clip and item['type'] == '0B2' and item['waveform_score'] >= .65, item['explained_clip_energy']), reverse=True)
        directory = args.output / clip['name']
        directory.mkdir()
        ranked = clip['results']
        for item in ranked[:20]:
            source = (args.root / item['path']).resolve()
            if not source.is_relative_to(args.root.resolve()):
                raise ValueError('Source leaves extraction root')
            shutil.copy2(source, directory / source.name)
        metadata = {k: clip[k] for k in ['name', 'path', 'source_recording', 'source_start_seconds', 'original_source_start_seconds', 'source_alignment_score']}
        metadata['analysis_rate'] = rate
        metadata['context_seconds'] = args.context_seconds
        summary.append({**metadata, 'candidates': ranked[:50]})
        (directory / 'candidates.json').write_text(json.dumps(ranked, ensure_ascii=False, indent=2), encoding='utf-8')
        with (directory / 'candidates.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['guid', 'type', 'duration_seconds', 'waveform_score', 'original_waveform_score', 'explained_clip_energy', 'clip_seconds', 'source_seconds', 'template_seconds', 'resource_start_clip_seconds', 'playback_speed', 'method', 'path'], extrasaction='ignore')
            writer.writeheader()
            writer.writerows(ranked)
        entries = []
        for item in ranked[:20]:
            filename = pathlib.Path(item['path']).name
            uri = quote(clip['name']) + '/' + quote(filename)
            entries.append(f'<tr><td>{html.escape(filename)}</td><td>{item["waveform_score"]:.3f} / {item["original_waveform_score"]:.3f}</td><td>{item["explained_clip_energy"]:.1%}</td><td>클립 {item["clip_seconds"]:.3f}초 / {len(item["occurrences"])}회<br>원본 {item["source_seconds"]:.3f}초부터 {item["template_seconds"]:.3f}초 비교</td><td><audio controls preload="none" src="{uri}"></audio></td></tr>')
        sections.append(f'<section><h2>{html.escape(clip["name"])}</h2><p>원본 영상 약 {clip["original_source_start_seconds"]:.3f}초부터 · 컷 정렬 {clip["source_alignment_score"]:.3f}</p><video controls preload="metadata" src="{html.escape(pathlib.Path(clip["path"]).as_uri(), quote=True)}"></video><table><thead><tr><th>원본 GUID</th><th>파형: BGM 감소 / 원본</th><th>클립 에너지 설명량</th><th>클립 시점 / 반복</th><th>원본 듣기</th></tr></thead><tbody>{"".join(entries)}</tbody></table></section>')
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    document = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>컷별 원본 사운드 검색</title><style>body{background:#0b0c10;color:#eee;font:16px system-ui;margin:24px}video{width:500px;max-width:95%}td,th{padding:10px;text-align:left;border-bottom:1px solid #456}audio{width:260px}section{margin-bottom:50px}table{border-collapse:collapse}</style><h1>컷별 원본 사운드 후보</h1><p>각 클립의 상위 20개입니다. 여러 겹의 소리·같은 소리의 변형이 포함됩니다. 파형 점수는 정답 확률이 아니며 에너지 설명량은 BGM을 근사 감소한 클립에 대한 값입니다. 원본 듣기로 확인하세요. 부분 비교는 대사나 효과음 전체의 일치를 보장하지 않습니다.</p>' + ''.join(sections) + '</html>'
    (args.output / 'index.html').write_text(document, encoding='utf-8')
    print(f'Finished: {args.output / "index.html"}', flush=True)


if __name__ == '__main__':
    main()
