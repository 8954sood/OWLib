# 검증 결과 · 2026-10-24 KST

## 실제 게임 오류 수정 후 추가 검증

- 수정 코드: `111453c0`. [성공한 Actions 실행](https://github.com/8954sood/OWLib/actions/runs/39983215511), [수정 Artifact](https://github.com/8954sood/OWLib/actions/runs/39983215511/artifacts/12513879202).
- 수정 ZIP SHA-256: `56a52870e50b44025cd5d2ddfb091feb3c19284ec7ff7d80617dec10e271a383`.
- 기존 실추출 로그의 실패 15,987건은 모두 `Invalid Ogg page`였다. 실제 실패 파일 하나에서 Vorbis/revorb 출력 43,662바이트 중 정상 Ogg EOS 끝은 43,661바이트이며 추가 1바이트가 있음을 재현했다. 기존 검증기가 이를 오류로 판정하고 파일을 삭제했다. Vorbis 컨버터가 호출자 입력까지 닫아 원본 백업과 대체 변환도 실패했다.
- 수정: native Vorbis 출력은 EOS 페이지 끝까지만 복사, 입력 스트림 소유권 보존, 출력 검증 실패도 외부 컨버터 fallback 대상에 포함, fallback 쓰기 위치를 0으로 초기화. 합성 padding 회귀 테스트 추가.
- `D:\Overwatch`의 **실제 `2.25.0.1.154504KB` / RKR / koKR** 설치에서 기존 실패 GUID 80개를 `--sound-guids` 진단 옵션으로 재추출했다. **Ogg=80, failed=0, exit=0**. 80개 모두 FFmpeg 전체 디코딩 종료 코드 0, 오류 출력 없음.
- 실게임 파일이나 추출 오디오는 GitHub에 업로드하지 않았다. 로컬 증거: `.owlib-validation/retest-80-fixed.log`, `retest-80-decode.json`, `retest-80-fixed/index.csv`.
- 전체 132,194개 재추출 및 밴픽 사운드 식별을 완료한 것은 아니다. 아래 초기 검증의 '실제 데이터 미검증'은 최초 빌드 당시의 기록이며, 위 실제 표본 검증으로 범위를 갱신한다.

## 최초 빌드 검증 기록

검증한 기능 코드 커밋: `f5e1cc2d` (Add self-contained Windows build and all-sounds extraction for 154504).

- [성공한 GitHub Actions 실행](https://github.com/8954sood/OWLib/actions/runs/39981308561)
- [Windows 실행 파일 Artifact](https://github.com/8954sood/OWLib/actions/runs/39981308561/artifacts/12513482999) · 524,640,907 bytes
- [빌드/테스트 로그 Artifact](https://github.com/8954sood/OWLib/actions/runs/39981308561/artifacts/12513338194)
- ZIP SHA-256: `a5b089df82415b306efa2255bd507da2352dc9c35a477edd4c91e45771e42145`

## 통과한 검증

1. 로컬 actionlint `v1.7.12`: 워크플로 문법/표현식 검사.
2. Node `--check`: HTML에 포함된 JavaScript 문법 검사.
3. Windows Actions: .NET 10 SDK, 재귀 submodule 체크아웃, 공식 TACTLib 기반 SHA 검사와 저장된 패치 적용.
4. vgmstream/FFmpeg 배포 ZIP의 고정 SHA-256 검사.
5. DataTool·TankView 실제 `Release`, `win-x64`, `--self-contained true` publish.
6. 합성 Wwise Opus → Ogg 변환 및 최종 EOS/길이 검사. 합성 PCM → vgmstream/FFmpeg → Ogg 변환.
7. Vorbis/Opus Ogg granule 기반 길이, Opus pre-skip, 뱅크 DIDX 오프셋·DATA padding·반복 WEM ID 구분.
8. 파일별 읽기/변환 실패 격리, 실패 원본 WEM 보존, GUID 중복 제거, 부분 출력 제거, CSV/JS/오류 로그.
9. 실제 `ExtractAllSounds.Parse` 호출, 명령 검색 등록, CLI positional 파싱, 출력 경로 중첩/기존 디렉터리 거부.
10. CMF/TRG 함수의 키·IV 길이, 같은 count 입력에 대한 일치. 이는 실제 매니페스트 복호화 검증이 아님.
11. publish 결과의 native 런타임·librevorb·코드북·정적 리소스·self-contained runtimeconfig 확인.
12. 빈 DOTNET_ROOT + roll-forward 비활성화 상태에서 DataTool 도움말/명령 표시 및 TankView 프로세스 시작.

## 검증하지 못한 부분

- 실제 게임 154504 데이터가 없어 CMF/TRG 복호화, 실제 전체 오디오 추출, 누락률, 게임 파일 불변성의 전후 해시 검증을 수행하지 못함. 읽기 전용은 소스의 FileAccess.Read 및 출력 경로 검사로 확인함.
- 커뮤니티 TRG IV 계산의 packageCount 항은 PR 작성자가 추정한 것임. 공식 병합/승인된 지원이 아님.
- 밴픽 효과음/BGM의 실제 GUID 식별과 청취 비교 미수행.
- HTML 탐색기의 실제 브라우저 화면·재생·localStorage 동작은 미검증. 브라우저 자동화 도구가 `file://` 프로토콜 접근을 보안 정책으로 거부함. JavaScript 문법 검사만 통과.
- self-contained CI 검사는 SDK가 설치된 러너에서 빈 런타임 경로로 실행한 검사임. 깨끗한 Windows VM 전체 검증은 아님.

로컬 Windows에 .NET SDK/런타임을 설치하지 않았으며 모든 .NET 컴파일은 Actions에서 수행함.

추가 로컬 실행 검사: Actions Artifact ZIP을 다운로드해 위 SHA-256을 확인하고 `D:\owkr-Internal-balance\test\OWLib-Windows-154504`에 압축 해제함. 현재 Windows에서 `dotnet` 명령이 PATH에 없는 상태로, 빈 DOTNET_ROOT/roll-forward 비활성화를 지정하고 다운로드한 `DataTool.exe unused-game-path extract-all-sounds --help`를 실행해 종료 코드 0 및 새 명령 표시를 확인함. 로그: `D:\owkr-Internal-balance\test\.owlib-validation\local-datatool-help.log`. 실제 게임을 연 검사가 아님.
