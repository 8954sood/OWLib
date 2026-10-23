# 검증 결과 · 2026-10-24 KST

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
