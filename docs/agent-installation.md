# AI Agent용 skill-hunter 설치 원칙

이 문서는 AI coding agent가
`https://github.com/woobin-the-creator/skill-hunter`에서 `skill-hunter`를 안전하게
설치할 때 따라야 하는 실행 지침이다. 사용자의 명시적 요청이 이 문서의 기본 scope보다
우선한다.

## 1. 설치 대상 결정

먼저 현재 디렉터리와 Git repository root를 확인하고, 실행 중인 agent가 Claude Code,
OpenCode, Codex 또는 기타 Agent Skills 호환 agent인지 판단한다.

사용자가 scope를 말하지 않았다면 프로젝트 로컬 설치를 기본값으로 사용한다. 글로벌
설치가 명시된 경우에만 글로벌 경로에 쓴다.

| Agent | 프로젝트 로컬 | 글로벌 |
| --- | --- | --- |
| Claude Code | `<project>/.claude/skills/skill-hunter` | `~/.claude/skills/skill-hunter` |
| OpenCode | `<project>/.opencode/skills/skill-hunter` | `~/.config/opencode/skills/skill-hunter` |
| Codex | `<project>/.agents/skills/skill-hunter` | `~/.agents/skills/skill-hunter` |
| Codex legacy | `<project>/.codex/skills/skill-hunter` | `${CODEX_HOME:-~/.codex}/skills/skill-hunter` |

기타 agent는 공식 문서나 현재 설정에서 skill directory를 확인한다. 확인할 수 없으면
프로젝트 로컬 `.agents/skills/skill-hunter`를 제안하고 사용자에게 한 번만 질문한다.

## 2. 기존 설치 보호

destination을 읽기 전용으로 확인한다. 파일, 디렉터리, symlink 중 무엇이든 이미
존재하면 덮어쓰거나 삭제하지 않는다.

가능한 범위에서 다음만 확인하고 결과를 보고한 뒤 중단한다.

- 같은 source repository에서 설치한 것인지
- 현재 commit 또는 version
- 수정된 파일이 있는지
- 사용자가 선택할 수 있는 다른 scope 또는 destination

## 3. 실행 환경 확인

- Python 3.9 이상을 확인한다.
- `git`이 있으면 사용하되 `gh` CLI는 요구하거나 설치하지 않는다.
- `git`이 없으면 GitHub HTTPS API와 bounded archive download를 사용한다.
- 외부 Python runtime package를 설치하지 않는다.
- 권한이 필요한 네트워크 접근이나 파일 쓰기는 실제 작업 직전에만 요청한다.

## 4. 신뢰하지 않는 source로 취급

platform에 맞는 임시 디렉터리로 source를 가져오고 정확한 commit SHA를 기록한다.
source repository의 다음 항목은 실행하지 않는다.

- `scripts/` 아래 파일
- `setup.py` 또는 install script
- package manager command
- Git hook
- test
- `curl | sh` 또는 유사 pipe-to-shell command

Git을 사용할 때는 가능하면 working-tree hook과 filter 실행을 피한다. Archive를 사용할
때는 absolute path, `..` traversal, 과도한 파일 수와 압축 해제 크기를 검사한다.

## 5. 최소 설치 artifact

다음 파일과 디렉터리만 원래 상대 구조대로 staging에 복사한다.

```text
SKILL.md
LICENSE
agents/openai.yaml
references/
scripts/skill_hunter.py
skill_hunter/
```

다음 항목은 Agent Skill 실행에 필요하지 않으므로 destination에 복사하지 않는다.

```text
README.md
docs/
tests/
.git/
build/
dist/
*.egg-info/
```

복사 과정에서 symlink를 발견하면 target을 resolve한다. repository 밖을 가리키거나,
absolute·broken·circular symlink이면 설치를 중단한다.

## 6. 원자적 설치

destination과 같은 부모 filesystem에 임시 staging directory를 만든다. 모든 필수 파일과
경로를 확인한 뒤 staging을 한 번의 rename으로 destination에 배치한다.

중간 단계가 실패하면 agent가 이번 작업에서 만든 staging만 정리한다. 기존 사용자 파일,
다른 skill directory, agent 설정은 변경하지 않는다.

## 7. 설치 검증

다음을 확인한다.

1. `destination/SKILL.md`가 존재한다.
2. `destination/LICENSE`가 존재한다.
3. `SKILL.md` frontmatter의 `name`이 `skill-hunter`다.
4. 아래 명령이 `skill-hunter 0.1.0` 이상의 version을 출력한다.
5. `--help` 명령이 성공한다.

```bash
python3 <destination>/scripts/skill_hunter.py --version
python3 <destination>/scripts/skill_hunter.py --help
```

현재 agent가 새 skill을 즉시 reload하지 못하면 재시작 또는 skill reload가 필요하다고
알린다.

## 8. 완료 보고

마지막에 다음을 요약한다.

- 감지한 agent와 선택한 scope
- 최종 설치 경로
- canonical source URL
- 설치에 사용한 commit SHA
- 복사한 파일 수
- version/help 검증 결과
- 재시작 또는 reload 필요 여부

검증 후 임시 source와 staging을 안전하게 정리한다. 위 범위를 벗어난 시스템 설정 변경,
기존 파일 삭제, source script 실행은 하지 않는다.
