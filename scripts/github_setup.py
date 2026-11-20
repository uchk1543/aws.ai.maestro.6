"""GitHub 협업 세팅: .github/tasks.csv → 라벨 · 마일스톤 · 이슈. 담당: PM

실행 (저장소를 GitHub에 올린 뒤, gh auth login 상태에서):
    uv run python -m scripts.github_setup --repo <OWNER>/<REPO>                 # 미리보기만
    uv run python -m scripts.github_setup --repo <OWNER>/<REPO> --apply \\
        --assign 판독=<아이디> --assign 검증=<아이디> --assign 화면=<아이디> \\
        --assign 서버=<아이디> --assign 발표=<아이디>

다시 실행해도 안전하다: 같은 제목의 이슈, 같은 이름의 마일스톤은 건너뛰고 라벨은 덮어쓴다.
지우는 일은 하지 않는다.
"""

import argparse
import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_CSV = ROOT / ".github" / "tasks.csv"

# 담당 → (라벨 색, 설명). 사람과 담당의 대응은 TEAM.md 1번 표
ROLES = {
    "판독": ("1f77b4", "1번: 서류 분류·읽기, 에이전트 루프, 다시 확인, 현황 채팅, 데이터셋"),
    "검증": ("2ca02c", "2번: 대조 규칙, HS 코드, 신고서 초안, 채점"),
    "화면": ("9467bd", "3번: web/ 화면 전체"),
    "서버": ("ff7f0e", "4번: API, Textract, 가상 WMS, 저장소 코드 (배포는 PM)"),
    "발표": ("e377c2", "5번: 가상 화물 기록, 시나리오, 시간 측정, 발표 자료"),
    "PM": ("5319e7", "PM: AWS 리소스 생성·배포 단독, PR 합치기, 공용 파일 승인"),
}
# 단계 → (마일스톤 이름, 마감 UTC 또는 None, 설명). 금 18시 KST = 금 09시 UTC
PHASES = {
    "P0": ("P0 첫 배포 (금 18시)", "2026-11-20T09:00:00Z", "2종 분류·읽기, 규칙 3개, 등급, 근거, 채점"),
    "P1": ("P1 다섯 기능 (토 02시)", "2026-11-20T17:00:00Z", "4종, OCR, 다시 확인, HS, 신고서, WMS, 현황 조회, 화면"),
    "P2": ("P2 여유가 있을 때", None, "시간이 모자라면 빼는 것"),
    "발표": ("발표 준비 (토 기능 동결 뒤)", None, "시나리오, 숫자, 영상, PDF, 리허설"),
}
EXTRA_LABELS = {
    "공용 파일": ("d93f0b", "공용 파일 변경 (team.md 협업 목록). 단톡 공지"),
    "막힘": ("b60205", "다른 이슈나 권한을 기다리는 중"),
    "bug": ("d73a4a", "돌던 것이 안 돈다"),
}
COLUMNS = ["id", "title", "role", "phase", "depends", "files", "done"]
# 공용 파일 (team.md 협업, CODEOWNERS 공용 칸과 같다)
SHARED = (".kiro/", "docs/schema.md", "docs/examples/", "tools/models.py", "pyproject.toml", "uv.lock", ".github/", "TEAM.md", "tests/unit/test_contracts.py", "tests/unit/fakes.py")


# ---------------------------------------------------------------------------
# 계획 (GitHub 호출 없음, 테스트 대상)
# ---------------------------------------------------------------------------
def load_tasks(path: Path = TASKS_CSV) -> list[dict[str, str]]:
    """tasks.csv를 읽고 검사한다. 잘못되면 ValueError."""
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"tasks.csv 머리줄이 {COLUMNS}와 다릅니다: {reader.fieldnames}")
        tasks = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("tasks.csv에 같은 id가 두 번 있습니다")
    for t in tasks:
        if t["role"] not in ROLES:
            raise ValueError(f"{t['id']}: 담당 {t['role']!r}는 {sorted(ROLES)} 중 하나여야 합니다")
        if t["phase"] not in PHASES:
            raise ValueError(f"{t['id']}: 단계 {t['phase']!r}는 {sorted(PHASES)} 중 하나여야 합니다")
        for dep in t["depends"].split():
            if dep not in ids:
                raise ValueError(f"{t['id']}: 없는 작업 {dep}에 의존합니다")
    return tasks


def owner_text(role: str) -> str:
    """이슈 본문의 담당 표기. 예: '2번 검증 담당', 'PM'."""
    if role == "PM":
        return "PM"
    return f"{ROLES[role][1].split(':')[0]} {role} 담당"


def issue_title(task: dict[str, str]) -> str:
    return f"[{task['id']}] {task['title']}"


def issue_body(task: dict[str, str]) -> str:
    deps = " ".join(f"[{d}]" for d in task["depends"].split()) or "없음"
    files = "\n".join(f"- `{f}`" for f in task["files"].split()) or "- (없음)"
    return (
        f"**작업 ID**: {task['id']}  \n"
        f"**담당**: {owner_text(task['role'])} (TEAM.md)  \n"
        f"**단계**: {task['phase']}\n\n"
        f"### 고칠 파일\n{files}\n\n"
        f"### 끝난 기준\n{task['done'] or '(담당자가 채운다)'}\n\n"
        f"### 먼저 끝나야 하는 작업\n{deps}\n"
        "기다리는 동안은 `tests/unit/fakes.py`와 `docs/examples/`로 먼저 만든다.\n\n"
        "### 진행 방법\n"
        f"- 브랜치: `feat/{task['id'].lower()}-<짧은-이름>`\n"
        "- PR 본문에 `Closes #<이 이슈 번호>`\n"
        "- 근거: `.kiro/specs/00-skeleton/e2e-plan.md`, `.kiro/steering/agent-design.md`\n"
    )


def labels_for(task: dict[str, str]) -> list[str]:
    labels = [f"담당:{task['role']}", f"단계:{task['phase']}"]
    if any(f.startswith(SHARED) for f in task["files"].split()):
        labels.append("공용 파일")
    return labels


def plan_labels() -> list[tuple[str, str, str]]:
    labels = [(f"담당:{r}", c, d) for r, (c, d) in ROLES.items()]
    labels += [(f"단계:{p}", "c5def5", desc) for p, (_, _, desc) in PHASES.items()]
    labels += [(n, c, d) for n, (c, d) in EXTRA_LABELS.items()]
    return labels


# ---------------------------------------------------------------------------
# GitHub 호출
# ---------------------------------------------------------------------------
class Gh:
    """gh CLI 호출. apply가 거짓이면 명령만 출력한다 (읽기 명령은 실행)."""

    def __init__(self, repo: str, apply: bool):
        self.repo, self.apply = repo, apply

    def read(self, *args: str) -> str:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout

    def write(self, *args: str) -> None:
        print("  $ gh " + " ".join(args))
        if self.apply:
            subprocess.run(["gh", *args], check=True, timeout=60)


def run(repo: str, apply: bool, assignees: dict[str, str]) -> None:
    tasks = load_tasks()
    gh = Gh(repo, apply)
    print(f"[github] {repo} · 작업 {len(tasks)}개 · {'실제 생성' if apply else '미리보기'}")

    print("[github] 라벨")
    for name, color, desc in plan_labels():
        gh.write("label", "create", name, "--repo", repo, "--color", color, "--description", desc, "--force")

    print("[github] 마일스톤")
    existing_ms = {m["title"] for m in json.loads(gh.read("api", f"repos/{repo}/milestones?state=all&per_page=100"))}
    for title, due, desc in PHASES.values():
        if title in existing_ms:
            print(f"  있음: {title}")
            continue
        args = ["api", "-X", "POST", f"repos/{repo}/milestones", "-f", f"title={title}", "-f", f"description={desc}"]
        if due:
            args += ["-f", f"due_on={due}"]
        gh.write(*args)

    print("[github] 이슈")
    existing = {i["title"] for i in json.loads(gh.read("issue", "list", "--repo", repo, "--state", "all", "--limit", "500", "--json", "title"))}
    for task in tasks:
        title = issue_title(task)
        if title in existing:
            print(f"  있음: {title}")
            continue
        args = ["issue", "create", "--repo", repo, "--title", title, "--body", issue_body(task),
                "--label", ",".join(labels_for(task)), "--milestone", PHASES[task["phase"]][0]]
        if task["role"] in assignees:
            args += ["--assignee", assignees[task["role"]]]
        gh.write(*args)
    if not apply:
        print("[github] 미리보기였습니다. 실제로 만들려면 --apply")


def main() -> None:
    parser = argparse.ArgumentParser(description="tasks.csv로 GitHub 라벨·마일스톤·이슈를 만든다")
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--apply", action="store_true", help="실제로 만든다 (없으면 미리보기)")
    parser.add_argument("--assign", action="append", default=[], metavar="담당=아이디", help="예: 판독=octocat")
    args = parser.parse_args()
    assignees = {}
    for pair in args.assign:
        role, _, user = pair.partition("=")
        if role not in ROLES or not user:
            parser.error(f"--assign 형식: 담당=아이디, 담당은 {sorted(ROLES)}")
        assignees[role] = user
    run(args.repo, args.apply, assignees)


if __name__ == "__main__":
    main()
