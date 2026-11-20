# 인계 절차 (PM, 내일 아침)

KIRO_BOOTSTRAP.md에서 아직 남은 부분(0-1·0-3·0-4, 4장 MCP, 6장 5번, 8장, 9장)만 옮겼다.
아래 순서대로 한 번 하면 다섯 명이 GitHub에서 브랜치 + PR로 일할 수 있다.

## 0. 사람과 아이디
담당 1~5번의 하는 일은 [TEAM.md](../../../TEAM.md) 1번 표에 있다.

| 자리 | GitHub 아이디 |
|---|---|
| 저장소 | `uchk1543/aws.ai.maestro.6` (공개) |
| PM (저장소 소유) | `uchk1543` |
| 1 판독 · 2 검증 · 3 화면 · 4 서버 | `nuzz3800` · `Ladea1224` · `GaMaius` · `nnhhlee` |
| 5 발표 | 미정 (PM이 이슈 관리) |
| 대리 승인자 | `nnhhlee` (PM이 올린 PR을 승인) |

## 1. 인계 전과 뒤의 차이
- **인계 전**: PM 혼자 main에 직접 커밋·push한다. 보호 규칙은 아직 걸지 않는다.
  보호 규칙의 "승인 1명 필수"는 작성자 본인 승인을 인정하지 않아서, 혼자일 때 걸면 PM의 PR을 아무도 승인할 수 없다.
- **인계 뒤 (아래 5번부터)**: 모두 브랜치 + PR로만 일한다.

## 2. 지킬 것 (인계 뒤에도 그대로)
- 키·토큰·비밀번호를 어떤 파일에도 적지 않는다. `.env`는 커밋하지 않는다.
- `git push --force`, rebase, 히스토리 재작성을 하지 않는다.
- 저장소 공개 여부 변경, 협업자 추가·삭제는 PM만 한다.
- 서울(ap-northeast-2) 밖에 리소스를 만들지 않는다. 이름은 모두 `team06-`으로 시작한다.
- OpenSearch Serverless, NAT Gateway, EC2, RDS, Provisioned Throughput을 만들지 않는다.
- 데이터셋용 서류를 코드로 지어내지 않는다 (agent-design.md 11번).
- 지금 단계에 없는 기능의 몸통(동작)을 미리 만들지 않는다. 떠오르면 자기 Spec의 tasks.md에 '나중'으로 적는다.
  빈 함수 모양과 이슈는 협업을 위해 미리 만들어 두었다 (team.md 협업).
- 팀 전체로 P0가 끝까지 도는 것을 먼저 한다. P0 몫이 없거나 끝난 사람만 P1을 시작한다.

## 3. 아침 순서 (체크리스트)
- [ ] 3-1. AWS 권한 받기 → 뼈대 배포 (`infra/README.md` "실행 순서", S4). 배포는 인계 뒤에도 PM만 한다 (team.md AWS)
- [ ] 3-2. `.kiro/settings/mcp.json` 만들기 (4장, 아래)
- [ ] 3-3. TEAM.md 1번 표와 `.github/CODEOWNERS`의 `<...>`를 아이디로 바꾸고 커밋
- [ ] 3-4. 원격 연결, push, CI 확인
- [ ] 3-5. 병합 방식 설정 (6-5)
- [ ] 3-6. 이슈·라벨·마일스톤 만들기 (`scripts/github_setup.py`)
- [ ] 3-7. 오늘 밤 확인 목록 (8장)
- [ ] 3-8. 출발점 태그 (9-1)
- [ ] 3-9. main 보호 규칙 (9-2), 동작 확인 (9-3)
- [ ] 3-10. 넘기기 (9-4), 단톡 공지 (9-5)

### 3-4. 원격 연결과 push
```bash
git remote add origin https://github.com/uchk1543/aws.ai.maestro.6.git
git push -u origin main
gh run list --limit 1                         # ci 가 success 인지
```

### 3-5. 병합 방식 (6-5)
squash만 허용하면 PR 하나 = main 커밋 하나라 되돌리기 쉽다. 합친 브랜치는 자동 삭제, PR 화면에 "Update branch" 버튼이 생긴다.
```bash
gh api -X PATCH repos/uchk1543/aws.ai.maestro.6 \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true -F allow_update_branch=true \
  -f squash_merge_commit_title=PR_TITLE
```

### 3-6. 이슈·라벨·마일스톤
```bash
uv run python -m scripts.github_setup --repo uchk1543/aws.ai.maestro.6          # 미리보기
uv run python -m scripts.github_setup --repo uchk1543/aws.ai.maestro.6 --apply \
  --assign 판독=nuzz3800 --assign 검증=Ladea1224 --assign 화면=GaMaius --assign 서버=nnhhlee
```

## 4. Kiro MCP 설정

### 팀 공용 `.kiro/settings/mcp.json` (저장소에 커밋)
문서 서버는 읽기 전용이라 모두에게 붙여도 안전하다. AWS를 직접 조작하는 서버는 여기 넣지 않는다.
```json
{
  "mcpServers": {
    "aws-docs": {
      "command": "uvx",
      "args": ["awslabs.aws-documentation-mcp-server@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" },
      "disabled": false,
      "autoApprove": ["search_documentation", "read_documentation"]
    },
    "strands": {
      "command": "uvx",
      "args": ["strands-agents-mcp-server"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### PM 개인용 `~/.kiro/settings/mcp.json` (저장소 밖, PM만)
팀 저장소에 넣으면 다섯 명의 Kiro에 모두 붙어 "배포는 한 명만" 원칙이 무너진다.
```json
{
  "mcpServers": {
    "aws-api": {
      "command": "uvx",
      "args": ["awslabs.aws-api-mcp-server@latest"],
      "env": { "AWS_REGION": "ap-northeast-2" },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```
- `autoApprove`는 비워 둔다. 호출마다 명령을 읽고 승인한다.
- 만들기·바꾸기는 MCP로 즉석에서 하지 않는다. `infra/` 스크립트로만 한다. MCP는 조회에만 쓴다.
  즉석으로 만든 리소스는 나중에 어떤 설정인지 아무도 알 수 없다.
- PM만 쓴다. 다른 팀원에게 이 설정을 나눠 주지 않는다.

## 8. 인계 전에 확인할 것
- [ ] `uv run pytest` 통과, main CI success
- [ ] Function URL 응답 (S4) 또는 끝까지 한 번 (S5)
- [ ] `infra/README.md`에 리소스와 실행 순서가 적혀 있음
- [ ] AWS에 `team06-` 아닌 리소스나 서울 밖 리소스가 없음 (MCP 조회로 확인)
- [ ] 공개 Function URL은 동시 실행 상한 5가 걸려 있음

## 9. 인계

### 9-1. 출발점 태그
```bash
git switch main && git pull
git tag skeleton-v0 && git push --tags
```

### 9-2. main 보호 규칙 (Ruleset)
규칙 파일: `.kiro/specs/00-skeleton/ruleset-main.json`
- `deletion`: main 삭제 방지
- `non_fast_forward`: force push 방지 (남의 커밋 덮어쓰기 방지)
- `pull_request`: 직접 push 금지, 승인 1명, 공용 파일은 CODEOWNERS 승인, 리뷰 코멘트 해결 필수, squash만
- `required_status_checks` + `strict`: CI(`test`) 통과 필수, 최신 main을 반영한 상태로만 병합
- `bypass_actors: []`: 소유자 포함 우회 없음. 긴급 시 Ruleset을 잠깐 disabled로 바꾼다
```bash
gh api -X POST repos/uchk1543/aws.ai.maestro.6/rulesets --input .kiro/specs/00-skeleton/ruleset-main.json
gh api repos/uchk1543/aws.ai.maestro.6/rulesets          # protect-main, active 확인
```
- 403 또는 "Upgrade to GitHub Pro or make this repository public": 비공개 저장소 + 무료 요금제에서는 보호 규칙이 걸리지 않는다.
  공개로 바꿀지 요금제를 올릴지 PM이 정한다. 그동안은 "main 직접 push 금지"를 말로 합의한다.
- 422로 `allowed_merge_methods`가 거부되면 그 줄만 빼고 다시 시도한다 (3-5 설정으로 효과는 같다).

### 9-3. 동작 확인
```bash
git switch -c chore/ruleset-check
echo "" >> README.md && git commit -am "chore: 보호 규칙 확인"
git push origin chore/ruleset-check:main      # 거부(GH013)되어야 정상
git push -u origin chore/ruleset-check
gh pr create --fill && gh pr checks --watch   # test 통과, 승인 대기 상태면 정상
gh pr close --delete-branch
git switch main && git branch -D chore/ruleset-check
```

### 9-4. 넘기기
- `api/`, `tools/ocr.py`, `tools/wms.py` → 4번 서버. 배포 권한과 `infra/`는 PM이 그대로 갖는다.
- 4번과 `infra/README.md`를 함께 한 번 읽어, 새 테이블·권한이 필요할 때 infra/ PR로 올리는 방법을 맞춘다.
- PM의 개인 `aws-api` MCP는 PM만 쓰므로 켜 둔다. 조회에만 쓰고, 만들기·바꾸기는 infra/ 스크립트로만 한다.
- 각자 GitHub 이슈(라벨 `담당:<내 담당>`)와 `.kiro/specs/README.md`의 자기 Spec 폴더에서 시작한다. Spec 1은 금요일 10~12시에 팀이 함께 승인한다.

### 9-5. 팀원 공지 (단톡에 그대로)
```
저장소: https://github.com/uchk1543/aws.ai.maestro.6  (출발점 태그 skeleton-v0)
1) clone 후 CONTRIBUTING.md "처음 한 번"부터 따라 하기, Kiro로 열 때 Trust 누르기
2) TEAM.md에서 내 번호 확인 → GitHub 이슈에서 라벨 "담당:<내 담당>"으로 보기. P0 마일스톤부터
3) main 직접 push는 막혀 있어요. 브랜치 feat/<작업ID>-이름 → PR (본문에 Closes #이슈번호)
4) 자기 담당 폴더만 고치기 (CONTRIBUTING.md 표). 공용 파일 바꾸면 단톡에 알리기
5) 합치는 시각: 15 · 18 · 23 · 03 · 07시
```
