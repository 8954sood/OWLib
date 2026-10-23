# DataTool - OWLib [![Build Status](https://github.com/overtools/OWLib/actions/workflows/dotnet.yml/badge.svg)](https://github.com/overtools/OWLib/actions/workflows/dotnet.yml) [![Discord](https://img.shields.io/discord/346445737367699456.svg?label=&logo=discord&logoColor=ffffff&color=7389D8&labelColor=6A7EC2)](https://discord.gg/XM93ZdB)

## Windows · 154504 전체 사운드 추출

오버워치 `2.25.0.1.154504`용 커뮤니티 패치를 적용하고 Windows x64용 DataTool·TankView를 **GitHub Actions에서 self-contained로 빌드**합니다. 사용자 PC에는 .NET SDK·런타임이 필요 없습니다. EXE만 따로 옮기지 말고 DLL·리소스 폴더 전체를 유지하세요.

### 다운로드 → 게임 경로 지정 → 추출

1. 이 포크의 **Actions → OWLib Windows 154504 → Run workflow**에서 브랜치를 선택합니다. `codex/windows-154504-all-sounds` push 시에도 빌드합니다.
2. 성공한 실행의 **Artifacts → OWLib-Windows-154504**를 다운로드합니다. GitHub 로그인이 필요하며 보관 기간은 30일입니다.
3. 예를 들어 `D:\Tools\OWLib-Windows-154504`에 **모두** 압축 해제하고 게임·Battle.net을 종료합니다.
4. Battle.net 설정에서 설치 경로를 확인합니다. `.build.info`와 `Data`가 있는 루트이며 일반적으로 `_retail_` 자체가 아닙니다. Steam도 실제 Overwatch 설치 폴더를 지정하세요.
5. PowerShell에서 실행합니다. 출력은 게임 폴더 밖의 **아직 존재하지 않는 새 폴더**여야 합니다.

```powershell
Set-Location 'D:\Tools\OWLib-Windows-154504\DataTool'
& .\DataTool.exe 'C:\Program Files (x86)\Overwatch' extract-all-sounds 'D:\OWSounds' --language=koKR --speech-language=koKR
$LASTEXITCODE
Start-Process 'D:\OWSounds\browser.html'
```

언어 자동 감지를 쓰려면 두 언어 옵션을 생략합니다. 종료 코드 `0`은 탐색 중 파일 오류 없음, `2`는 일부 파일 실패 후 나머지 처리를 완료했다는 뜻입니다. 초기화 실패는 별도 비정상 종료입니다. 파일 0개나 빈 인덱스는 추출 성공의 근거가 아닙니다. 기존 출력을 덮어쓰지 않으므로 재실행은 `D:\OWSounds-run2` 같은 새 경로로 합니다.

```text
OWLib-Windows-154504/
  DataTool/DataTool.exe       # 이 폴더의 모든 DLL·Static·Third Party 필요
  TankView/TankView.exe       # Windows Desktop 런타임 자체 포함
  README.md
  LICENSE
  BUILD.txt

OWSounds/
  03F/{FULL_GUID}.03F.ogg
  0B2/{FULL_GUID}.0B2.ogg
  0BB/{FULL_GUID}.0BB.ogg
  043/{BANK_GUID}.043_wem-{WEM_ID}_{ORDINAL}.ogg
  index.csv
  errors.log
  audio-index.js
  browser.html
```

### 실제 추출 범위

초기 버전에서 `Invalid Ogg page`가 대량 발생했다면 **수정 커밋 `111453c0` 이후 Artifact**를 사용하세요. Vorbis/revorb 출력 끝의 추가 바이트와 입력 스트림 소유권 문제를 수정했습니다. 기존 실패 실게임 파일 80개가 수정본에서 80/80 성공했고 전체 디코딩도 통과했습니다. 기존 출력은 보존하고 새 출력 폴더로 다시 추출하세요. 자세한 범위와 한계는 [VALIDATION.md](VALIDATION.md)에 기록했습니다.

일부 GUID만 재현하려면 `--sound-guids=07C00000002A593B,05D000000000012F`처럼 전체 64비트 GUID를 쉼표로 지정할 수 있습니다. 이 옵션을 생략하면 전체 탐색입니다.

기존 `extract-everything`은 영웅/일반/음악/음성/맵 추출기를 조합합니다. 새 명령은 `Program.TrackedFiles`의 **모든 `03F`, `0B2`, `0BB` GUID를 직접 순회**합니다. 타입은 `DataTool/FindLogic/Combo.cs`의 실제 sound/voice 처리에 근거하며, 음악/영웅/UI 분류나 STU 참조로 제한하지 않습니다. `043` 뱅크의 `DIDX`/`DATA`에서도 내장 WEM을 추출하고 이벤트/HIRC 파싱에는 의존하지 않습니다. 내장 미디어가 없는 이벤트 뱅크는 `no_embedded_media`로 기록합니다.

- Vorbis WEM은 기존 ww2ogg + librevorb로, Wwise Opus는 기존 Opus 컨버터로 Ogg에 담습니다. 채널을 임의로 스테레오로 바꾸지 않습니다. Opus 최종 페이지에 EOS 플래그를 기록하도록 수정했습니다.
- 기본 변환 실패 시 동봉한 vgmstream으로 WAV를 디코딩하고 FFmpeg `libvorbis -q:a 5`로 Ogg Vorbis를 생성합니다. 이 경로는 손실 재인코딩이며 프로세스마다 120초 제한이 있습니다. 외부 도구 배포본의 라이선스·출처도 `Third Party`에 포함합니다.
- 변환 실패는 해당 파일만 실패 처리하고 `.wem` 원본을 보존합니다. 누락/암호화/손상/미지원 코덱은 CSV와 `errors.log`에 남깁니다. 뱅크 구조가 손상되어 남은 오프셋을 신뢰할 수 없으면 그 뱅크의 나머지 항목은 추출할 수 없습니다.
- CSV: `guid,type,media_id,ordinal,source_bytes,output_bytes,duration_seconds,status,path,error`. GUID는 전체 64비트 값입니다. 뱅크 내 반복 WEM ID도 ordinal로 구분합니다. 동일 콘텐츠라도 GUID/뱅크가 다르면 보존하고, 동일 GUID만 중복 처리하지 않습니다.
- 길이는 출력 Ogg의 Vorbis 샘플레이트/최종 granule 또는 Opus 48 kHz granule에서 pre-skip을 빼 계산합니다. 전체 디코딩/청취 검증은 아닙니다. 실패 행의 길이는 비웁니다.
- CSV·오류 기록은 파일마다 즉시 flush합니다. 강제 종료되면 JS 인덱스가 완성되지 않을 수 있으므로 이때는 CSV를 사용하세요.
- 진행률은 리소스 GUID 처리 수이며 Ogg 성공 수·실패 수를 별도로 표시합니다. 뱅크 하나에서 여러 파일이 나올 수 있습니다.

**전체 = 현재 빌드·지역·선택된 설치 음성 언어의 매니페스트가 노출하는 위 타입 리소스 전체**입니다. 모든 언어/지역의 콘텐츠가 설치됐다는 뜻은 아닙니다. 다른 음성 언어도 필요하면 해당 게임 언어를 설치하고 `--speech-language=enUS` 등으로 별도 폴더에 실행하세요. 새 미확인 타입이나 키가 없는 파일까지 추출을 보장하지 않습니다.

새 명령은 초기화 전에 온라인 복구를 끄고 로컬 아카이브만 읽습니다. TACTLib 컨테이너는 `FileAccess.Read`로 열며 게임 데이터를 변경하지 않습니다. 설치 폴더 중첩·상위 출력 경로와 출력 경로 ancestry의 junction/symlink를 거부합니다. 도구도 게임 폴더 밖에 풀어 두세요. 기존의 다른 명령은 온라인 기본값이 별개입니다.

### 밴픽 사운드 탐색

`browser.html`을 Edge/Chrome에서 직접 엽니다. 서버·Python·.NET이 필요 없습니다. 같은 폴더의 `audio-index.js`와 타입별 폴더를 유지하세요. 검색, 타입·길이 필터, 재생, 즐겨찾기, 전체 파일 URL 확인, 100개 단위 페이지, 분류 JSON 내보내기를 제공합니다. 분류/즐겨찾기는 브라우저 localStorage에 저장되므로 저장소 차단이나 폴더 이동에 대비해 내보내세요.

분류 항목: 카드 호버 / 영웅 클릭 / 밴 투표 / 밴 확정 / 영웅 애니메이션 / BGM / 카운트다운·시간 경고 / 기타. GUID로 용도를 자동 식별하지는 않습니다. 짧은 효과음은 최대 길이를 낮추고, BGM 후보는 최소 길이를 늘려 청취하며 실제 화면과 비교하세요. Opus 다채널은 브라우저에 따라 외부 플레이어가 필요할 수 있습니다.

### 녹화 기준 자동 사운드 검색 (실험적)

`scripts/find-recorded-sounds.py`는 경쟁전 녹화/녹음의 오디오를 추출 Ogg와 로컬에서 비교합니다. 파일별 음향 지문을 SQLite에 캐시하고 시간 오프셋에 일관된 후보를 찾은 다음, 파형의 정규화 상관으로 순위를 다시 계산합니다. 결과는 `matches.csv`, `matches.json`, 녹화 시점 이동·원본 재생이 가능한 `matches.html`입니다. 음원이나 녹화는 외부로 전송하지 않습니다.

분석 환경에 Python + NumPy 및 동봉 FFmpeg가 필요합니다. 현재 작업 환경에서는 Codex에 포함된 Python/NumPy를 사용하므로 .NET SDK 설치는 필요 없습니다.

```powershell
python scripts/find-recorded-sounds.py --root 'D:\OWSounds-fixed' --ffmpeg 'D:\owkr-Internal-balance\test\OWLib-Windows-154504-fixed\DataTool\Third Party\ffmpeg\bin\ffmpeg.exe' --reference 'D:\recordings\competitive.mp4' --include-voice
```

기준 녹화가 필수입니다. 초기 분석은 오래 걸릴 수 있고 재실행은 캐시를 재사용합니다. `--include-voice`를 지정하면 음성도 포함합니다. 기본값은 `0B2` 제외입니다. `--limit`는 개발 진단용 부분 분석이므로 전체 검색 시 생략하세요. 결과는 음향 유사 후보이며 경쟁전 전용이라는 의미가 아닙니다. 짧은 클릭, 변조, 다른 믹스, 소리가 겹친 경우 누락/오탐이 가능하고 녹화에 없는 이벤트는 찾을 수 없습니다.

검증: 오프셋·볼륨 변화·잡음 추가 합성 테스트, 실제 추출 음원 12개의 합성 녹음 지문 매칭, 실제 추출 파일 1,000개 중 세 원본을 합친 테스트 녹음의 정답을 1·2·3위 및 정확한 시점으로 검색. 실제 녹화에서도 사용자가 원하는 음원 한 개를 확인했지만, 전체 정확도/재현율은 측정하지 않았습니다. 테스트용 원본/녹음은 GitHub에 올리지 않았습니다.

`find-short-recorded-sounds.py`는 지문이 부족한 짧은 소리를 전체 녹화와 직접 비교하고, `refine-recorded-sounds.py`는 효과음 후보의 반복 시점을 검색합니다. `build-recording-report.py`는 이 결과들을 새로운 출력 폴더에 모읍니다. 사용자가 직접 확인한 GUID는 `--confirmed GUID`를 반복 지정하면 점수와 별개인 `confirmed_by_user`로 CSV에 기록되고, `confirmed` 폴더에 복사되며 기본 화면의 구간 필터에서도 표시됩니다. 파형 상관값은 정답 확률이 아니므로 낮은 점수도 실제 정답일 수 있습니다.

`find-similar-voice.py --root EXTRACT_ROOT --cache FINGERPRINTS_SQLITE --seed CONFIRMED_OGG --ffmpeg FFMPEG_EXE --output NEW_FOLDER`로 기존 캐시의 모든 `0B2` 음성을 확인 음원과 비교할 수 있습니다. 결과는 음향 변형 후보이며 같은 화자·대사·경쟁전 용도를 보장하지 않습니다. 기본 기준 음원 자신도 비교 결과에 포함됩니다.

### 버전 고정·커뮤니티 패치 검토

- OWLib 기준: [`546efa19516d7df7ba138802d221c73ad886df28`](https://github.com/overtools/OWLib/commit/546efa19516d7df7ba138802d221c73ad886df28).
- 공식 TACTLib 기준: [`129f977b604b2576bfd048e0f2be8b44ee983f39`](https://github.com/overtools/TACTLib/commit/129f977b604b2576bfd048e0f2be8b44ee983f39). 2026-10-24 확인 시 공식 최신 코드에 154504 클래스가 없습니다.
- [PR #40](https://github.com/overtools/TACTLib/pull/40)은 **닫힘·미병합** 상태입니다. [`9b333b84211a4b95928e01be303b5ed27729c0aa`](https://github.com/sandsand244263/TACTLib/commit/9b333b84211a4b95928e01be303b5ed27729c0aa)의 두 추가 클래스만 `patches/tactlib-154504.patch`로 보관합니다. 매번 커뮤니티 브랜치를 fetch하지 않습니다.
- 검토: 변경 파일 두 개만 존재, CMF/TRG의 512바이트 테이블 일치, 기존 `ManifestCrypto` 자동 등록 규칙·인터페이스 일치, 키/IV 길이·인덱싱 확인, 공식 기반 SHA/patch 적용 검사. 기존 fallback 정책과 다른 빌드는 그대로입니다.
- **TRG IV의 packageCount 항은 작성자가 구조 검사를 통해 추정한 계산입니다.** PR의 실제 클라이언트 검증 주장은 여기서 독립 재현하지 못했습니다. 154504 복호화를 실데이터로 검증했다는 뜻이 아닙니다.
- vgmstream `r2117`, FFmpeg BtbN `autobuild-2026-10-23-13-04`/`n8.1.3-24-g92611900bb`의 URL·SHA-256은 `scripts/fetch-audio-tools.ps1`에 고정합니다. 파일이 없어지거나 해시가 달라지면 빌드를 중단합니다.

### Actions 검증

`.github/workflows/build-windows.yml`: 재귀 submodule 체크아웃 → .NET 10 SDK → 고정 패치 적용 → 외부 컨버터 해시 확인 → 두 프로젝트 각각 `Release`, `win-x64`, `--self-contained true` publish → 합성 리소스 테스트 → 파일·런타임 포함 검사 및 실행 → Artifact 업로드. 두 앱은 별도 폴더에 publish합니다. 실패 시에도 `OWLib-Windows-154504-logs`에 텍스트 로그와 MSBuild binlog를 보존합니다.

`tests/AudioSmoke`는 합성 Ogg/뱅크로 오프셋, 중복 ID, 길이, 실패 격리, 원본 보존, CSV, CLI 등록/파싱/실행, 출력 경로, 복호화 함수 형태를 검사합니다. self-contained 검사는 .NET 경로를 빈 폴더로 지정하고 DataTool 도움말과 TankView 프로세스 시작을 확인합니다. **게임 데이터 없는 CI에서는 실제 사운드 추출, 154504 복호화, 밴픽 사운드 식별 성공을 주장하지 않습니다.**

---

Series of programs (tools) to interact with the Overwatch files.

## Downloads & Help
Downloads for the tools and updates are posted on GitHub releases and on our Discord where you can also find support and disccusion around using them.

Join the Discord here: [https://discord.gg/XM93ZdB](https://discord.gg/XM93ZdB)

If the discord invite link does not work, paste `XM93ZdB` into the invite link box when clicking `Add Server > Join Server`

## How to use
DataTool is a command line application which means you need to know how to use a command line.

0. Make sure Overwatch is installed.
1. Download the latest release from our Discord
2. Extract the all the files to a folder, do not put it in your Overwatch Directory.
3. Open a command line in the folder where you extracted the files.
4. Run DataTool.exe via command line for a list of help and supported commands.

Most commands follow the structure `DataTool.exe <overwatch_directory> <mode> [mode args]`

### Blender Addon
In order to import skins or maps into Blender extracted by the tool, you will need to install our blender addon: https://github.com/overtools/io_scene_owm<br>
Releases and updates for the addon are also posted on our Discord linked above.<br>
**Blender 3.5 or above is required.**

### Example List Commands
```
DataTool.exe "C:\Games\Overwatch" list-heroes
DataTool.exe "C:\Games\Overwatch" list-unlocks
DataTool.exe "C:\Games\Overwatch" list-maps
DataTool.exe "C:\Games\Overwatch" list-achievements
```

#### JSON output
Many of the list commands support JSON output.<br>
To do this you must provide the `--json` flag as well as an `--out` flag to specify where to save the JSON file.<br>
Example:
```
DataTool.exe "C:\Games\Overwatch" list-heroes --json --out="C:\Games\Extracts\Heroes.json"
```

### Example Extract Commands

Some of the more common extract commands include:
 * extract-unlocks - extract all hero unlocks such as skins, highlight intros, emotes, sprays, icons
 * extract-general - handles extracting all class unlocks such as all class sprays and icons and portraits
 * extract-maps - extract maps
 * extract-hero-voice - extracts all heroes voicelines and groups them by type (kinda)
 * extract-conversations - extracts all hero conversations

In most cases when using extract commands, you must provide the name of what you want to extract or use `*` for everything.<br>
See below for some examples.

#### Example Commands
```
Tracers Overwatch 1 Skin (You can enter the name of any skin):
DataTool.exe "C:\Games\Overwatch" extract-unlocks "C:\Games\Extracts" "Tracer|skin=Overwatch 1"

All Heroes Overwatch 1 Skins:
DataTool.exe "C:\Games\Overwatch" extract-unlocks "C:\Games\Extracts" "*|skin=Overwatch 1"

All Heroes Skins (will take long time):
DataTool.exe "C:\Games\Overwatch" extract-unlocks "C:\Games\Extracts" "*|skin=*"

Everything - includes skins, emotes, highlight intros, etc. (will take very long time)
DataTool.exe "C:\Games\Overwatch" extract-unlocks "C:\Games\Extracts" *

Extract Dorado map
DataTool.exe "C:\Games\Overwatch" extract-maps "C:\Games\Extracts" "Dorado"

Extract All Maps (will take a long time)
DataTool.exe "C:\Games\Overwatch" extract-maps "C:\Games\Extracts" *

Extract Tracers Voicelines
DataTool.exe "C:\Games\Overwatch" extract-hero-voice "C:\Games\Extracts" Tracer

Extract Tracers Conversations
DataTool.exe "C:\Games\Overwatch" extract-conversations "C:\Games\Extracts" Tracer
```

#### Extract Unlocks filters
The extract unlocks command supports extracting a lot of data and you can filter to specifically what you want.<br>
The command structure looks like: `DataTool.exe <overwatch_directory> extract-unlocks <output_directory> [filters]`<br>
Filters follow the format `{hero name}|{type}={item name}`. You can specify `*` for the hero name or the type for everything.<br>
Valid types include: skin, icon, spray, victorypose, emote, voiceline

#### Example Filters
```
"*"                                   // Everything (all heroes skins, sprays, etc) (very slow)
"*|skin=*"                            // All Heroes Skins
"Tracer|skin=Overwatch 1"             // Tracers Overwatch 1 skin
"Reaper|spray=*"                      // Reaper's sprays
"Reaper|voiceline=*"                  // Reapers unlockable voicelines
```

### Tool Flags
There is also a variety of flags you can use that can change how some of the extract commands work.
```
--subtitles-with-sounds - Extracts subtitles in txt files next to the audio files (default false)
--voice-group-by-hero - When extracting voicelines, groups them by the hero (default true)
--voice-group-by-type - When extracting voicelines, groups them by the type (default true)
--voice-group-by-skin - When extracting voicelines, groups them by the skin (default false)
--voice-group-by-locale - When extracting voicelines, groups them by the locale (default false)
```

## Disclaimer
This project is not affiliated with Blizzard Entertainment, Inc.<br>
All trademarks referenced herein are the properties of their respective owners.<br>
2025 Blizzard Entertainment, Inc. All rights reserved.
