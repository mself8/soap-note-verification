# 협업 규칙

## 브랜치 전략 — 사람별 브랜치

- `main`은 **보호 브랜치**: 직접 push 금지. 모든 변경은 PR로만 병합.
- 각자 **자기 이름 브랜치**에서 작업 (예: `songyoon`, `<이름>`).
  ```bash
  git checkout main && git pull
  git checkout -b <내이름>        # 처음 한 번
  # ...작업, 커밋...
  git push -u origin <내이름>
  ```
- 어느 정도 묶음이 완성되면 **`main`으로 PR** 생성.

## PR 규칙

- PR 병합에는 **팀원 1인 이상 승인** 필요 (자기 PR은 자기가 승인 불가).
- 리뷰어가 볼 수 있게 PR 설명에 "무엇을/왜"를 한 줄이라도 남기기.
- 병합 방식은 자유 (Squash 권장 — 커밋 히스토리 깔끔).

## 팁 — 막판 충돌 방지

사람별 브랜치는 오래 놔두면 `main`에서 멀어져 병합이 힘들어집니다.
**작은 묶음이 끝날 때마다 PR로 자주 합치고**, 작업 전 `git pull origin main`으로 최신화하세요.

## 데이터

- `data/`는 gitignore. 각자 clone:
  ```bash
  cd data
  git clone --depth 1 https://github.com/abachaa/MTS-Dialog.git
  git clone --depth 1 https://github.com/wyim/aci-bench.git
  ```
