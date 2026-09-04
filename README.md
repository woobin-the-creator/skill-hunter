# skill-hunter

GitHub 저장소에서 Agent Skill을 찾고, 저장소 내부 의존성까지 분석해 안전하게
가져오는 dependency-aware importer입니다.

`skill-hunter`는 그 자체로 Agent Skill이면서 독립 실행 가능한 Python CLI입니다.
저장소 어디에 있든 `SKILL.md`를 찾고, 선택한 skill이 실제로 참조하는 sibling
skill·공유 파일·script import·symlink target을 dependency graph로 만든 다음,
설치 전에 검토 가능한 계획을 보여줍니다. 탐색이나 설치 과정에서 원본 저장소의
script를 실행하지 않습니다.

## 가장 빠른 설치

아래 3줄을 현재 사용 중인 AI coding agent에 그대로 붙여넣으세요.

```text
이 가이드를 읽고 skill-hunter를 현재 프로젝트의 Agent Skill로 설치해줘:
https://github.com/woobin-the-creator/skill-hunter/blob/main/INSTALL.md
기존 설치는 덮어쓰지 말고, 완료 후 설치 경로·commit SHA·검증 결과를 알려줘.
```

기본값은 프로젝트 로컬 설치입니다. 모든 프로젝트에서 사용하려면 첫 줄의
`현재 프로젝트의`를 `글로벌`로 바꾸면 됩니다.

`INSTALL.md`는 상세 원칙을 담은
[`docs/agent-installation.md`](docs/agent-installation.md)를 가리키는 실제 Git
심볼릭 링크입니다.

## 왜 필요한가

Agent Skill은 항상 하나의 폴더 안에서 완결되지 않습니다. `SKILL.md`가 다음과
같은 저장소 내부 자원에 의존할 수 있습니다.

```text
skill-a
├── skill-b
│   └── shared/rules.md
├── scripts/foo.py
│   └── shared/utils.py
└── templates/report.md
```

`SKILL.md`가 있는 폴더만 복사하면 이런 상대경로나 import가 깨집니다.
반대로 저장소 전체를 설치하면 관련 없는 대용량 파일과 실행 코드까지 들어옵니다.

`skill-hunter`는 분석에는 임시 저장소 전체를 사용할 수 있지만, 최종 설치에는
선택한 skill과 실행에 필요한 repository-local dependency closure만 포함합니다.
원본 기준 상대경로는 그대로 유지합니다.

## 주요 기능

- `skills/`, `.claude/skills/`, `.agents/skills/`, nested package 등 위치와
  관계없이 `SKILL.md` 탐색
- skill 이름, 경로, 설명, frontmatter, dependency metadata, 설치 가능 여부 표시
- 명시적·재귀적·transitive skill dependency 처리
- 상대경로 파일과 디렉터리 분석
- repository 내부 symlink target 확인 및 cycle/escape 차단
- Python, Node.js, shell의 정적 repository-local dependency 분석
- 자연어로 호출되는 다른 skill을 `Inferred` 또는 `Possible` 후보로 분류
- dependency cycle 탐지와 공유 dependency 중복 제거
- Claude Code, OpenCode, Codex, universal/custom destination adapter
- 설치 전 `--dry-run`, 충돌 diff 요약, source revision 고정
- source URL, commit, dependency graph, SHA-256을 provenance로 기록
- Python 표준 라이브러리 중심 구현
- runtime에서 `gh` 불필요, `git`이 없어도 public GitHub archive fallback 제공

## 요구사항

- Python 3.9 이상
- 원격 저장소를 사용할 경우 GitHub 네트워크 접근
- `git` 권장, 필수는 아님

PyPI runtime dependency는 없습니다. CLI 패키지를 설치할 때만 일반적인 Python
build backend인 `setuptools`와 `wheel`이 사용됩니다.

## 직접 설치

AI Agent에 맡기지 않고 직접 설치하려는 경우에만 이 절차를 사용하세요.

### Agent Skill로 직접 설치

전체 Git checkout을 그대로 두면 이후 `git pull`로 업데이트하기 쉽습니다. 아래 명령은
대상 경로가 아직 없을 때만 실행하세요.

#### Claude Code

프로젝트 로컬:

```bash
mkdir -p .claude/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  .claude/skills/skill-hunter
```

글로벌:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.claude/skills/skill-hunter
```

#### OpenCode

프로젝트 로컬:

```bash
mkdir -p .opencode/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  .opencode/skills/skill-hunter
```

글로벌:

```bash
mkdir -p ~/.config/opencode/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.config/opencode/skills/skill-hunter
```

#### Codex

프로젝트 로컬:

```bash
mkdir -p .agents/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  .agents/skills/skill-hunter
```

글로벌:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/woobin-the-creator/skill-hunter.git \
  ~/.agents/skills/skill-hunter
```

설치 후 agent가 자동으로 새 skill을 감지하지 못하면 해당 agent를 재시작하거나 skill
목록을 reload하세요.

### CLI만 설치

Agent Skill 자동 호출이 필요하지 않고 CLI만 사용하려면 격리된 Python 환경 또는
`pipx`를 권장합니다.

저장소 checkout에서 바로 실행:

```bash
git clone https://github.com/woobin-the-creator/skill-hunter.git
cd skill-hunter
python3 scripts/skill_hunter.py --help
```

Python console command 설치:

```bash
python3 -m pip install git+https://github.com/woobin-the-creator/skill-hunter.git
skill-hunter --help
```

### 설치 확인

Agent Skill 경로를 직접 설치했다면 `<설치경로>`를 실제 경로로 바꿔 실행합니다.

```bash
python3 <설치경로>/scripts/skill_hunter.py --version
python3 <설치경로>/scripts/skill_hunter.py --help
```

정상 설치 예시:

```text
skill-hunter 0.1.0
```

## Agent에서 사용하는 방법

설치 후에는 git 명령이나 skill directory 구조를 알 필요가 없습니다. 다음처럼
자연어로 요청할 수 있습니다.

```text
https://github.com/foo/bar 여기 있는 스킬 보여줘
이 레포의 skill 목록 보여줘
frontend-design skill의 dependency를 분석해줘
여기 있는 스킬 전부 설치해줘
skill-a를 프로젝트 로컬에 설치해줘
skill-a를 글로벌 skill로 설치해줘
이 skill이 다른 파일이나 skill에 의존하는지도 확인해줘
```

`skill-hunter` Agent Skill은 실제 설치 전에 dry-run을 실행하고, semantic dependency
후보와 security signal을 검토하며, 계획을 사용자에게 보여준 다음 승인을 받도록
지시합니다.

### Claude Code 예시

```text
/skill-hunter https://github.com/foo/bar 여기 있는 스킬 보여줘
```

### OpenCode 예시

```text
skill-hunter를 사용해서 https://github.com/foo/bar 의 skill 목록과 dependency를 확인해줘.
```

### Codex 예시

```text
$skill-hunter https://github.com/foo/bar 에서 frontend-design을 분석하고 설치 계획을 보여줘.
```

## CLI 사용법

설치된 console command와 repository script는 같은 인터페이스를 제공합니다.

```text
skill-hunter inspect SOURCE
skill-hunter list SOURCE
skill-hunter analyze SOURCE --skill NAME [--skill NAME ...]
skill-hunter analyze SOURCE --all
skill-hunter install SOURCE --skill NAME --target TARGET --scope SCOPE --dry-run
```

repository checkout 또는 Agent Skill 내부에서는 다음처럼 실행합니다.

```bash
python3 scripts/skill_hunter.py list https://github.com/foo/bar
```

### 저장소의 skill 목록 보기

```bash
python3 scripts/skill_hunter.py inspect https://github.com/foo/bar
python3 scripts/skill_hunter.py list https://github.com/foo/bar --json
```

- `list`: 간결한 목록
- `inspect`: skill별 구조 경고까지 표시
- `--json`: agent나 다른 도구가 처리할 수 있는 machine-readable 결과

두 명령 모두 설치 경로를 변경하지 않습니다.

### 특정 skill의 dependency 분석

```bash
python3 scripts/skill_hunter.py analyze https://github.com/foo/bar \
  --skill frontend-design
```

출력 예시:

```text
Source:      https://github.com/foo/bar
Revision:    9c84e1f0123456789c84e1f0123456789c84e1f0
Requested:   frontend-design
Install set: frontend-design, design-system
Risk:        MEDIUM

Confirmed dependencies:
  - skill:frontend-design -> skill:design-system [explicit-skill]
  - file:scripts/render.py -> file:shared/utils.py [python-import]

Scripts (not executed):
  - skills/frontend-design/scripts/render.py
```

### 설치 전 dry-run

Claude Code 프로젝트 로컬:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --skill frontend-design \
  --target claude \
  --scope project \
  --dry-run
```

Codex 글로벌:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --skill frontend-design \
  --target codex \
  --scope global \
  --dry-run
```

저장소의 유효한 skill을 모두 선택:

```bash
python3 scripts/skill_hunter.py install https://github.com/foo/bar \
  --all \
  --target opencode \
  --scope project \
  --dry-run
```

계획을 검토하고 승인했다면 같은 명령에서 `--dry-run`을 제거하고 `--yes`를
추가합니다. 비대화형 실제 설치는 `--yes`가 없으면 중단됩니다.

## Dependency 분석 방식

각 dependency edge에는 source, target, 종류, confidence, 근거 문장과 위치가
기록됩니다.

### Confirmed

정적 분석으로 repository-local target이 명확한 dependency입니다. 기본 설치 closure에
자동으로 포함합니다.

- `requires`, `metadata.requires`와 호환 metadata
- `skill.json`, `plugin.json`, `manifest.json`의 dependency 선언
- 실제 존재하는 `./`, `../` 상대경로
- `scripts/foo.py`, `references/rules.md` 같은 conventional resource 경로
- repository 내부 symlink target
- Python repository-local import
- Node.js 상대 import/require
- shell `source` 또는 local script 호출
- 상대경로로 직접 참조한 다른 `SKILL.md`

### Inferred

다른 skill을 사용하라는 자연어 지시가 명확하지만 machine-readable 선언은 아닌
경우입니다.

```text
Use the `frontend-design` skill before performing this task.
```

기본 설치에서는 제외합니다. 근거를 검토한 뒤 실제 dependency가 맞으면
`--include-inferred`를 사용합니다.

### Possible

예시, 비교, 선택 사항, 부정문처럼 dependency인지 불확실한 언급입니다. 자동으로
설치하지 않습니다. 사용자가 근거를 확인하고 의도적으로 선택할 때만
`--include-possible`을 사용합니다.

### 지원 범위 요약

| Dependency 유형 | Confidence | 처리 방식 |
| --- | --- | --- |
| Frontmatter/JSON manifest dependency | Confirmed | 재귀적 skill closure |
| 기존 상대경로 파일·디렉터리 | Confirmed | repository 구조를 유지해 포함 |
| 내부 symlink | Confirmed | link와 target을 함께 포함 |
| Python 정적 import | Confirmed | local module을 재귀 분석 |
| Node.js 정적 import/require | Confirmed | local module을 재귀 분석 |
| Shell source/local 실행 경로 | Confirmed | script를 재귀 분석 |
| 명령형 자연어 skill 호출 | Inferred | 검토 후 opt-in |
| 예시·비교·모호한 skill 언급 | Possible | 기본 제외 |

동일 node는 한 번만 materialize합니다. `foo -> bar -> foo` 같은 cycle은 닫힌
경로로 보고하되 무한 재귀나 중복 설치를 일으키지 않습니다.

## Agent destination adapter

| Target | 프로젝트 로컬 | 글로벌 |
| --- | --- | --- |
| `claude` | `.claude/skills` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` |
| `opencode` | `.opencode/skills` | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills` |
| `codex` | `.agents/skills` | `~/.agents/skills` |
| `codex-legacy` | `.codex/skills` | `${CODEX_HOME:-~/.codex}/skills` |
| `universal` | `.agents/skills` | `${XDG_CONFIG_HOME:-~/.config}/agents/skills` |
| `custom` | 명시적 `--destination` | 명시적 `--destination` |

`--target auto`는 기존 설정 marker가 정확히 하나일 때만 선택합니다. 여러 agent가
설치되어 있거나 판단할 수 없으면 추측하지 않고 명시적인 target을 요구합니다.

경로 규약은 [Agent Skills specification](https://agentskills.io/specification),
[Claude Code skills 문서](https://code.claude.com/docs/en/slash-commands),
[OpenCode skills 문서](https://opencode.ai/docs/skills),
[OpenAI Codex 공식 문서](https://developers.openai.com/codex/skills)를 기준으로
검토했습니다.

## 설치 구조와 provenance

skill 밖의 dependency가 있어도 상대경로가 깨지지 않도록 최소 closure를 원래
repository 구조로 저장합니다.

```text
<state>/stores/<source>/<commit>-<closure>/
├── provenance.json
└── repo/
    ├── skills/foo/
    ├── skills/bar/
    └── shared/utils.py
```

선택한 agent skill directory에는 store 내부 skill root를 가리키는 상대 symlink를
만듭니다.

- Project state: `<project>/.skill-hunter`
- Global state: `${XDG_DATA_HOME:-~/.local/share}/skill-hunter`

`provenance.json`에는 다음 정보가 기록됩니다.

- canonical source URL
- GitHub source의 정확한 40자 commit SHA
- 사용자가 요청한 skill과 transitive skill 목록
- confidence와 근거를 포함한 dependency edge
- 설치된 모든 repository-relative path
- regular file의 SHA-256 또는 symlink target
- destination adapter, scope, 설치 시각

같은 state root의 `registry.json`은 향후 `update`, `remove`, `reinstall`, integrity
verification을 구현할 수 있도록 설치 소유권을 기록합니다.

## 안전 원칙

GitHub repository의 metadata, 문서, 경로, symlink, script를 모두 신뢰하지 않는
입력으로 취급합니다.

- source script, `setup.py`, install hook, package manager, test를 실행하지 않음
- Git working-tree checkout 없이 immutable Git tree object를 직접 materialize
- checkout filter, hook, `.gitattributes` export exclusion의 영향 차단
- archive download 크기, 파일 수, 압축 해제 크기 제한
- absolute path, traversal, special file, 외부·broken·circular symlink 차단
- state directory와 agent destination overlap 차단
- 기존 skill을 overwrite하지 않고 작은 diff 요약 후 중단
- 실제 설치 전에 source closure hash를 다시 확인해 TOCTOU 변경 차단
- staging, atomic rename, 실패 시 생성한 link/store rollback
- executable, hook, network/process 실행, destructive command, credential reference,
  `curl | sh` 패턴을 설치 전에 표시
- repository metadata의 terminal control character 제거
- 원본 branch 이름이 아니라 분석에 사용한 commit SHA 기록

`Risk: LOW`는 신뢰 보증이나 malware 판정이 아닙니다. 정적 분석은 위험 신호를
줄여 주지만 제3자 skill의 안전성을 증명하지는 못합니다.

## 알려진 한계

- dynamic import, runtime reflection, 생성되는 경로는 완전히 해석할 수 없음
- pip, npm, system package 같은 외부 dependency를 자동 설치하지 않음
- cross-repository skill dependency는 MVP에서 자동 획득하지 않음
- Git submodule을 자동 초기화하지 않음
- 안전한 Agent Skill frontmatter subset만 지원하며 범용 YAML parser는 아님
- GitHub `/tree/<ref>/<path>` URL에서 `/`가 포함된 branch는 모호할 수 있음
- skill root 밖 dependency가 있는 graph는 symlink mode가 필요함
- Windows symlink는 Developer Mode 또는 별도 권한이 필요할 수 있음
- 자연어 dependency confidence는 보수적 heuristic이므로 agent 또는 사용자 검토가 필요함

branch 이름에 `/`가 있으면 repository root URL과 `--ref`를 함께 사용하세요.

```bash
python3 scripts/skill_hunter.py analyze https://github.com/foo/bar \
  --ref feature/my-branch \
  --skill skill-a
```

## 개발과 테스트

runtime test dependency 없이 표준 라이브러리 `unittest`를 사용합니다.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q skill_hunter scripts
```

현재 test suite는 다음을 포함한 42개 사례를 검증합니다.

- 독립 skill
- 명시적·transitive dependency
- 상대경로 파일
- 내부·외부·절대·circular symlink
- Python, Node.js, shell dependency
- dependency cycle과 공유 node deduplication
- 기존 설치 collision과 sentinel 보존
- 자연어 `Inferred`/`Possible` 분류
- unrelated 대용량 directory 제외
- GitHub archive path traversal 차단
- project/global agent adapter
- provenance와 commit SHA
- dry-run 무변경성
- 분석 후 source 변경 차단
- source script 미실행

GitHub Actions는 Python 3.9, 3.12, 3.13에서 compile, 42개 테스트, package 설치,
두 CLI entrypoint smoke test를 실행합니다.

실제 public repository dry-run 검증:

- `junior/skilla`: 일반 `skills/<name>` 구조
- `axross/nakami`: `.claude/skills/<name>` 및 Node.js script 구조
- `vercel-labs/agent-skills`: bundled rules, multiline YAML, source directory와
  frontmatter name이 다른 구조

검증 중 외부 저장소 script는 실행하지 않았습니다. `git`과 `gh`가 PATH에 없는
상태에서도 public GitHub archive fallback을 검증했습니다.

설계와 상세 증거는 다음 문서에 있습니다.

- [`INSTALL.md`](INSTALL.md): AI Agent용 설치 원칙을 가리키는 심볼릭 링크
- [`docs/design.md`](docs/design.md)
- [`docs/acceptance.md`](docs/acceptance.md)
- [`docs/real-world-validation.md`](docs/real-world-validation.md)

## 관련 생태계

구현은 clean-room 방식입니다. 생태계 규약과 UX를 이해하기 위해 MIT 라이선스의
[Vercel `skills` CLI](https://github.com/vercel-labs/skills)와
[`junior/skilla`](https://github.com/junior/skilla)를 검토했지만, 해당 프로젝트의
source code를 복사하지 않았습니다.

`skill-hunter`는 그중에서도 repository-local dependency graph와 상대경로를 보존하는
최소 설치 artifact에 초점을 둡니다.

## 라이선스

[MIT](LICENSE)
