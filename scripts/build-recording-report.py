"""Build a local, portable shortlist from the two recording matching passes."""

import argparse
import csv
import html
import json
import pathlib
import shutil
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--analysis', type=pathlib.Path, required=True)
    parser.add_argument('--reference', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--residual-short-dir', type=pathlib.Path)
    parser.add_argument('--focus-start', type=float)
    parser.add_argument('--focus-end', type=float)
    parser.add_argument('--bgm-evidence', type=pathlib.Path)
    parser.add_argument('--refinement', type=pathlib.Path)
    parser.add_argument('--confirmed', action='append', default=[], help='User-confirmed GUID; repeat for multiple files')
    args = parser.parse_args()
    root = args.root.resolve()
    candidates = {}
    for filename, method in [('matches.json', 'landmarks+waveform'), ('short-matches.json', 'short-waveform')]:
        for item in json.loads((args.analysis / filename).read_text(encoding='utf-8')):
            if item['waveform_score'] < 0.6:
                continue
            item['method'] = method
            item['duration_seconds'] = float(item['duration_seconds'])
            score = item['waveform_score']
            duration = item['duration_seconds']
            threshold = 0.95 if duration < 0.04 else 0.9 if duration < 0.08 else 0.8
            item['tier'] = 'strong_candidate' if score >= threshold else 'possible_candidate'
            t = item.get('matched_reference_seconds', item['reference_seconds'])
            in_focus = args.focus_start is not None and args.focus_end is not None and args.focus_start <= t <= args.focus_end
            item['recording_context'] = ('지정한 밴픽 화면 구간' if in_focus else '그 외 영상 구간 또는 긴 소리 시작점')
            if item['guid'] not in candidates or score > candidates[item['guid']]['waveform_score']:
                candidates[item['guid']] = item
    if args.residual_short_dir:
        residual = {}
        for line in (args.residual_short_dir / 'short-results.jsonl').read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
                residual[item['guid']] = item
            except json.JSONDecodeError:
                pass
        for item in candidates.values():
            other = residual.get(item['guid'])
            if not other:
                continue
            item['original_waveform_score'] = item['waveform_score']
            item['residual_waveform_score'] = other['waveform_score']
            if other['waveform_score'] >= 0.6:
                item['waveform_score'] = other['waveform_score']
                item['reference_seconds'] = other['reference_seconds']
                item.pop('matched_reference_seconds', None)
                threshold = 0.95 if item['duration_seconds'] < 0.04 else 0.9 if item['duration_seconds'] < 0.08 else 0.8
                item['tier'] = 'strong_candidate' if item['waveform_score'] >= threshold else 'possible_candidate'
                item['method'] = 'short-waveform-after-bgm-reduction'
            else:
                item['tier'] = 'possible_candidate'
                item['background_sensitive'] = True
    if args.refinement:
        for item in json.loads(args.refinement.read_text(encoding='utf-8')):
            if item['waveform_score'] >= .6:
                item['duration_seconds'] = float(item['duration_seconds'])
                item['method'] = 'global-waveform-after-bgm-reduction'
                candidates[item['guid']] = item
    for item in candidates.values():
        duration = item['duration_seconds']
        threshold = .95 if duration < .04 else .9 if duration < .08 else .8
        item['tier'] = 'strong_candidate' if item['waveform_score'] >= threshold and not item.get('background_sensitive') else 'possible_candidate'
        if args.focus_start is not None and args.focus_end is not None:
            focused = [occurrence for occurrence in item.get('occurrences', [])
                       if args.focus_start <= occurrence['matched_reference_seconds'] <= args.focus_end
                       and occurrence['waveform_score'] >= threshold]
            if focused:
                item['global_waveform_score'] = item['waveform_score']
                item.update(max(focused, key=lambda occurrence: occurrence['waveform_score']))
        t = item.get('matched_reference_seconds', item['reference_seconds'])
        in_focus = args.focus_start is not None and args.focus_end is not None and args.focus_start <= t <= args.focus_end
        item['recording_context'] = '지정한 밴픽 화면 구간' if in_focus else '그 외 영상 구간 또는 긴 소리 시작점'
    if args.bgm_evidence:
        for evidence in json.loads(args.bgm_evidence.read_text(encoding='utf-8')):
            item = candidates.get(evidence['guid'])
            if not item or args.focus_start is None or args.focus_end is None:
                continue
            spans = [[max(start, args.focus_start), min(end, args.focus_end)]
                     for start, end in evidence['matching_intervals']
                     if min(end, args.focus_end) - max(start, args.focus_start) >= 3]
            if spans:
                item['recording_context'] = '지정한 밴픽 화면 구간 (BGM 연속 일치)'
                item['evidence_intervals'] = spans
                item['matched_reference_seconds'] = spans[0][0] + 0.5
    for guid in args.confirmed:
        guid = guid.split('.')[0].upper()
        if guid not in candidates:
            raise ValueError(f'Confirmed GUID is missing from candidates: {guid}')
        candidates[guid]['tier'] = 'confirmed_by_user'
    ordered = sorted(candidates.values(), key=lambda item: (item['tier'] == 'confirmed_by_user', item['waveform_score']), reverse=True)
    args.output.mkdir(parents=True, exist_ok=False)
    copies = args.output / 'strong-candidates'
    copies.mkdir()
    priority = args.output / 'ban-pick-priority'
    priority.mkdir()
    confirmed = args.output / 'confirmed'
    confirmed.mkdir()
    priority_count = 0
    for item in ordered:
        item['file_url'] = (root / item['path']).as_uri()
        if item['tier'] == 'confirmed_by_user':
            source = (root / item['path']).resolve()
            if not source.is_relative_to(root):
                raise ValueError('Source path leaves extraction root')
            shutil.copy2(source, confirmed / source.name)
            item['file_url'] = 'confirmed/' + quote(source.name)
        if item['tier'] == 'strong_candidate':
            source = (root / item['path']).resolve()
            if not source.is_relative_to(root):
                raise ValueError('Source path leaves extraction root')
            destination = copies / source.name
            shutil.copy2(source, destination)
            item['file_url'] = 'strong-candidates/' + quote(source.name)
            if item['recording_context'].startswith('지정한'):
                t = item.get('matched_reference_seconds', item['reference_seconds'])
                name = ('BGM_' if item.get('evidence_intervals') else f'{t:06.2f}s_') + source.name
                shutil.copy2(source, priority / name)
                item['file_url'] = 'ban-pick-priority/' + quote(name)
                priority_count += 1
    (args.output / 'candidates.json').write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = ['guid', 'type', 'duration_seconds', 'reference_seconds', 'matched_reference_seconds',
              'waveform_score', 'tier', 'method', 'recording_context', 'path']
    with (args.output / 'candidates.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(ordered)
    strong = sum(item['tier'] == 'strong_candidate' for item in ordered)
    escaped_reference = html.escape(args.reference.resolve().as_uri(), quote=True)
    data = json.dumps(ordered, ensure_ascii=True).replace('</', '<\\/')
    document = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>경쟁전 녹화 사운드 후보</title><style>
body{font:16px system-ui;background:#0b0c10;color:#e8edf8;max-width:1250px;margin:24px auto;padding:0 16px}video{width:100%;max-height:440px;background:black}button,select,input{font:inherit;padding:9px;margin:5px;background:#202636;color:inherit;border:1px solid #567;border-radius:6px}button{cursor:pointer}audio{width:100%;margin:12px 0}td,th{padding:10px;border-bottom:1px solid #345;text-align:left}table{width:100%;border-collapse:collapse}small{color:#bac8dd}a{color:#7df}.score{color:#7fe4bd}code{word-break:break-all}#path{min-height:24px}
</style><h1>경쟁전 녹화에서 찾은 사운드 후보</h1>
<p>__SUMMARY__</p><p><small>점수는 파형 상관값이며 정답 확률이 아닙니다. 영상에 등장한 소리의 후보이지, 경쟁전 전용·전체 사운드 목록은 아닙니다. 같은 소리의 변형과 중복 후보가 포함될 수 있습니다. 구간 표시는 영상 장면에 따른 추정입니다.</small></p>
<video id="video" controls preload="metadata" src="__REFERENCE__"></video>
<p><select id="tier"><option value="strong_candidate">확인 음원 + 강한 후보</option><option value="confirmed_by_user">사용자 확인 음원만</option><option value="">추가 후보 포함</option></select>
<select id="kind"><option value="">모든 길이</option><option value="sfx">효과음 후보 (10초 미만)</option><option value="music">긴 소리·BGM 후보 (10초 이상)</option></select>
<input id="query" placeholder="GUID, 타입, 구간 검색" aria-label="검색"><label><input id="focus" type="checkbox" __FOCUS__>지정한 밴픽 구간만</label><label><input id="group" type="checkbox" checked>비슷한 시점의 후보 묶기</label><label><input id="auto" type="checkbox">다음 후보 자동 재생</label><button id="next">다음 후보 듣기 →</button></p>
<audio id="player" controls preload="none"></audio><div id="path"></div><p id="count"></p>
<table><thead><tr><th>듣기 / 영상 비교</th><th>GUID · 구간</th><th>길이</th><th>파형 점수</th></tr></thead><tbody id="rows"></tbody></table>
<script>const data=__DATA__;let visible=[],current=-1;const el=id=>document.getElementById(id);
function play(item,index){current=index;el('video').pause();el('player').src=item.file_url;el('player').play().catch(()=>{});el('path').textContent=item.path;}
function render(){let q=el('query').value.toLowerCase();visible=data.filter(x=>(!el('tier').value||x.tier===el('tier').value||(el('tier').value==='strong_candidate'&&x.tier==='confirmed_by_user'))&&(!el('focus').checked||x.tier==='confirmed_by_user'||x.recording_context.startsWith('지정한'))&&(!el('kind').value||(el('kind').value==='music'?x.duration_seconds>=10:x.duration_seconds<10))&&(!q||[x.guid,x.type,x.recording_context].join(' ').toLowerCase().includes(q)));const total=visible.length;if(el('group').checked){const seen=new Set();visible=visible.filter(x=>{if(x.tier==='confirmed_by_user')return true;const key=Math.round((x.matched_reference_seconds??x.reference_seconds)*4)+':'+(x.type==='0B2'?'voice':x.duration_seconds>=10?'music':x.duration_seconds<.35?'short':'effect');if(seen.has(key))return false;seen.add(key);return true})}current=-1;el('rows').replaceChildren();el('count').textContent=visible.length+'개 표시 / 원본 후보 '+total+'개';
for(const [i,x]of visible.entries()){let tr=document.createElement('tr');let td=document.createElement('td');let b=document.createElement('button');b.textContent='원본 듣기';b.onclick=()=>play(x,i);td.append(b);let v=document.createElement('button');let t=x.matched_reference_seconds??x.reference_seconds;v.textContent='영상 '+t.toFixed(2)+'초';v.onclick=()=>{el('player').pause();el('video').currentTime=Math.max(0,t-0.2);el('video').play().catch(()=>{})};td.append(v);tr.append(td);for(const text of [x.guid+'.'+x.type+' · '+(x.tier==='confirmed_by_user'?'사용자 확인 · ':'')+x.recording_context,x.duration_seconds.toFixed(3)+'초',x.waveform_score.toFixed(3)]){let c=document.createElement('td');c.textContent=text;tr.append(c)}el('rows').append(tr)}}
for(const id of ['tier','kind','query','group','focus'])el(id).addEventListener('input',render);el('next').onclick=()=>{if(visible.length)play(visible[(current+1)%visible.length],(current+1)%visible.length)};el('player').onended=()=>{if(el('auto').checked&&current+1<visible.length)el('next').click()};render();</script></html>'''
    confirmed_count = sum(item['tier'] == 'confirmed_by_user' for item in ordered)
    document = document.replace('__SUMMARY__', f'사용자 확인 {confirmed_count}개 · 밴픽 구간 우선 후보 {priority_count}개 · 영상 전체 강한 후보 {strong}개 · 추가 후보 {len(ordered) - strong - confirmed_count}개. 확인 원본은 confirmed, 우선 후보는 ban-pick-priority 폴더에 있습니다.')
    document = document.replace('__FOCUS__', 'checked' if args.focus_start is not None else '')
    document = document.replace('__REFERENCE__', escaped_reference).replace('__DATA__', data)
    (args.output / 'index.html').write_text(document, encoding='utf-8')
    print(json.dumps({'confirmed_by_user': confirmed_count, 'priority_candidates': priority_count, 'strong_candidates': strong, 'possible_candidates': len(ordered) - strong - confirmed_count,
                      'report': str(args.output / 'index.html')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
