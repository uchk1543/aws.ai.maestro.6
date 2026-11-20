# 협업 규칙
저장소 세팅(라벨·마일스톤·이슈, 병합 방식, 보호 규칙)은 PM이 한 번 했다. 절차와 다시 하는 법: `.kiro/specs/00-skeleton/handover.md`.

## 처음 한 번 (각자 PC)
```bash
git config --global user.name "이름"
git config --global user.email "GitHub에 등록한 이메일"
git config --global pull.rebase false
git config --global init.defaultBranch main
gh repo clone uchk1543/aws.ai.maestro.6 && cd aws.ai.maestro.6
uv sync && uv run pytest
```
Kiro로 처음 열 때 신뢰(Trust)를 눌러야 `.kiro/` 설정이 읽힌다. Agent Steering 패널에 team.md와 agent-design.md가 보이는지 확인한다.
## 작업 고르기 (GitHub 이슈)
- 작업은 모두 이슈로 있다. 원본은 `.github/tasks.csv`, 설명은 `.kiro/specs/00-skeleton/e2e-plan.md`.
- 내가 몇 번 담당인지, 누구와 무엇을 주고받는지는 [TEAM.md](TEAM.md)에 있다.
- 이슈 목록에서 라벨 `담당:<내 담당>`으로 걸러 내게 배정된 것을 본다. 마일스톤 P0 → P1 순서로 한다.
- 시작할 때 이슈에 댓글로 "시작"을 남긴다. 막히면 라벨 `막힘`을 붙이고 무엇을 기다리는지 적는다.
- 새 작업이 생기면 이슈 템플릿 "작업"으로 만들고 PM에게 알린다.

## 브랜치 규칙
- **언제 만드나**: 이슈를 시작할 때 내가 만든다. 미리 만들어 두지 않는다 (출발점이 낡는다).
- **하나에 하나**: 브랜치 하나 = 이슈 하나 = PR 하나. 내게 배정된 이슈만 한다. 이슈가 없는 일이면 이슈 템플릿으로 먼저 이슈를 만든다.
- **이름**: `<종류>/<번호>-<짧은-영문-이름>`. 영문 소문자·숫자·하이픈만 쓴다.

  | 종류 | 언제 | 번호 | 예 |
  |---|---|---|---|
  | `feat` | 기능 | 작업 ID (소문자) | `feat/b7-weight-check` |
  | `fix` | 버그 | 이슈 번호 | `fix/61-null-total` |
  | `docs` | 문서만 | 작업 ID 또는 이슈 번호 | `docs/58-branch-rules` |
  | `chore` | 설정·의존성·CI | 작업 ID 또는 이슈 번호 | `chore/f4-textract-policy` |
- **만드는 방법 (둘 중 하나)**
  1. 이슈 화면 오른쪽 Development → **Create a branch** → 이름을 위 규칙대로 고친다 → "Checkout locally"를 고르고 나오는 명령을 실행한다. 최신 main에서 만들어지고 이슈와 자동으로 연결된다.
  2. 터미널: `git switch main && git pull && git switch -c feat/b7-weight-check`
- **수명**: 반나절 이하. PR이 합쳐지면 GitHub에서 자동으로 지워진다. 내 PC에서는 `git switch main && git pull && git branch -d <브랜치>`로 지운다.
- **하지 않는 것**: main에서 바로 작업, 남의 브랜치에 push, 브랜치 하나에 이슈 여러 개.

## 작업 흐름
```bash
git switch main && git pull                  # 항상 최신 main에서 시작
git switch -c feat/b7-weight-check           # 브랜치 규칙 참고 (이슈 화면 Create a branch도 된다)
# Kiro 작업 하나 끝날 때마다
git add -A && git commit -m "feat(validate): 총중량 대조 규칙"
git push -u origin feat/b7-weight-check      # GitHub에서 PR, 본문에 Closes #이슈번호
# main이 바뀌었으면 PR 화면의 "Update branch" 또는
git fetch && git merge origin/main
```
- main 직접 push 금지 (보호 규칙 `protect-main`·`review-main`으로 막혀 있다. PM도 마찬가지). rebase, force push 금지.
- 합치기: 팀원 PR은 승인 1명 + CI 통과 뒤 PM이 합친다. PM의 PR은 CI 통과 뒤 PM이 승인 없이 합친다 (`gh pr merge <번호> --squash --admin`).
- 커밋 전에 `git status`로 AI가 바꾼 파일 목록을 본다. 담당 폴더 밖이 바뀌었으면 `git restore <파일>`로 되돌린다.
- 푸시 전 키 검사: `git diff --cached | grep -E "AKIA[0-9A-Z]{16}"` (아무것도 안 나와야 정상)
- 이슈 하나 = 브랜치 하나 = PR 하나. 이슈 안의 Kiro 작업(30분)마다 커밋하고, 보통 2~4개면 PR. 반나절 넘게 들고 있지 않는다.
- 팀 전체로 P0 이슈를 먼저 한다. 내 P0가 없거나 끝났을 때만 P1 이슈를 연다.
## 폴더 소유권
| 경로 | 담당 |
|---|---|
| `agent/`, `tools/extract.py`, `tools/reread.py`, `tools/query.py`, `tools/report.py`, `samples/`, `eval/*.csv` | 1번 판독 |
| `tools/validate.py`, `tools/rules/`, `tools/hs.py`, `tools/declaration.py`, `eval/*.py`, `data/hs/` | 2번 검증 |
| `web/` | 3번 화면 |
| `api/`, `tools/ocr.py`, `tools/wms.py` | 4번 서버 |
| `infra/` | PM (리소스 생성·배포 실행은 PM만. 4번은 PR로 고칠 수 있다) |
| `docs/presentation/` | 5번 발표 (담당 정해질 때까지 PM) |
| `data/seed/` | 1번 판독 (A5, #79) |
| `.kiro/`, `docs/schema.md`, `docs/examples/`, `tools/models.py`, `pyproject.toml`, `uv.lock`, `.github/`, `TEAM.md`, `tests/unit/test_contracts.py`, `tests/unit/fakes.py` | 공용 (PM 또는 대리 승인) |

이 표는 `.github/CODEOWNERS`와 같다. 남의 파일을 고쳐야 하면 직접 고치지 말고 담당자에게 요청한다.
`tests/unit/`의 나머지 테스트 파일은 그 테스트가 검사하는 코드의 담당이 고친다 (예: `test_validate.py`는 2번).

## 공용 파일 바꾸는 순서
공용 파일은 모두가 기대는 약속이다. 둘이 동시에 고치면 충돌이 나고, 한 사람이 바꾸면 다른 사람 코드가 깨질 수 있다. 그래서 한 번에 하나씩, PM이 순서를 정해 합친다.

1. **이슈부터**: 이슈 템플릿 "작업"으로 만들고 라벨 `공용 파일`을 붙인다. 무엇을, 왜 바꾸는지, 영향받는 담당이 누구인지 적는다.
   예: "ExtractedDocument에 B/L 칸 bl_no·vessel 추가. 영향: 2번(대조 규칙), 3번(화면)".
2. **PM이 순서를 정한다**: 같은 공용 파일을 고치는 이슈가 둘 이상이면 한 번에 하나만 진행한다. 다음 사람은 앞의 PR이 합쳐진 뒤 최신 main에서 시작한다.
3. **브랜치·PR**: `chore/<이슈번호>-<짧은-이름>`. 영향받는 쪽 코드와 테스트도 같은 PR에서 함께 고친다. 남의 담당 파일을 고치면 그 담당자가 리뷰한다(CODEOWNERS가 자동 요청).
4. **합친 뒤 공지**: PM이 단톡에 "공용 파일 변경 합쳐짐, 각자 브랜치에서 `git merge origin/main`"을 알린다.

파일별 주의
- **`tools/models.py`, `docs/schema.md`, `docs/examples/`**: 셋을 같은 PR에서 함께 고친다. 예시와 모델이 어긋나면 CI(`test_examples.py`)가 실패한다.
- **`tests/unit/test_contracts.py`(담당 사이 연결 약속)**: 담당끼리 부르는 함수의 이름·받는 것·반환이 여기 고정되어 있다. 약속된 인자를 바꾸거나 빼면 CI가 실패하고 메시지에 담당과 순서가 나온다. 끝에 키워드 전용 인자를 기본값과 함께 더하는 것은 이슈 없이 해도 된다.
- **`pyproject.toml`, `uv.lock`(의존성)**: `uv add <패키지>`만 쓴다. `uv.lock`이 충돌하면 손으로 고치지 말고 최신 main을 합친 뒤 `uv lock`으로 다시 만든다.
- **`.kiro/steering/`**: 모든 사람의 Kiro 동작이 바뀐다. 합친 뒤 공지에 무엇이 바뀌었는지 한 줄로 적는다.
## 합치기와 배포 시각
- **합치기는 수시로**: 승인 1명 + CI 통과하면 PM이 바로 합친다 (PM이 자리에 없으면 대리 승인자). 몰아서 합치지 않는다. PR이 쌓이면 충돌이 커지고, 남은 PR마다 Update branch와 CI를 다시 돌려야 한다.
- **공용 파일 PR은 한 번에 하나**: 순서는 PM이 정한다 ("공용 파일 바꾸는 순서").
- **배포는 정해진 시각**: 15 · 18 · 23 · 03 · 07시와 데모 직전에 PM이 그 시각의 main으로 배포하고 단톡에 알린다.
- **각자 최신으로**: 내 PR이 합쳐졌을 때, 공용 파일 변경 공지를 봤을 때, 새 이슈를 시작할 때 `git switch main && git pull` (작업 중인 브랜치는 `git merge origin/main`).
토요일 09시 기능 동결 뒤에는 데모에 나오는 버그 수정만 합친다. 데모 전 정상 커밋에 `git tag demo-v1 && git push --tags`.
## 충돌이 나면
PR 작성자가 자기 브랜치에서 해결한다 (Kiro 병합 편집기). 해결 후 반드시 `uv run pytest`를 돌리고 push한다. 30분 넘게 막히면 바로 말한다.
