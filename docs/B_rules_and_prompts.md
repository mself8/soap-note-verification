# B. 규칙 설계 및 프롬프트 구현

> 담당 영역: §10-B. 규칙 4종을 **상상이 아니라 gold note 대조로** 도출. 각 규칙에 데이터 근거 1건 이상.

## B-1. 발화주체 규칙 — 계획서 원안은 반례로 기각

계획서 §10-B: *"환자 발화→S, 의사 발화→O/A"*. **ACI valid 첫 대화가 곧바로 반례**:

- 대화: `[doctor] ... so , brian is a 58 year old male with a past medical history significant for congestive heart failure and hypertension , who presents today for follow-up ...`
- 이 내용이 gold note에서 간 곳: **HISTORY OF PRESENT ILLNESS** = **S**(주관적 병력).
- 화자는 의사인데 섹션은 S → "의사 발화→O/A"는 틀림.

의사는 진료 내내 병력을 **구술 정리**한다(dictation 스타일). 따라서 규칙축은 화자가 아니라 **발화행위(speech act)**:

| 발화행위 | → SOAP | 판별 신호 |
|---|---|---|
| 병력 청취·서술 (환자 호소, 과거력, 사회력) | **S** | 증상·경과·과거력 서술 |
| 진찰·검사 소견 (신체진찰, 활력징후, 검사수치) | **O** | 관찰·측정된 값 |
| 의학적 판단·감별 | **A** | 진단명·감별·중증도 |
| 치료·검사 지시·교육 | **P** | 처방·오더·follow-up |

화자 태그는 **citation(근거 추적)**엔 필수지만 S/O/A/P 분류축은 아님. 두 용도를 분리한다.

## B-2. 확신도(hedge) 보존 규칙 — gold note가 이미 지키는 규약 (실측)

정답 노트가 확신도를 **어휘로 구분해 보존**하는지 실측 (MTS train+val gold / ACI train+val gold):

| 어휘군 | MTS 노트 출현 | ACI 노트 출현 |
|---|---|---|
| `denies` (명시적 부정단언) | 184 | 202 |
| `reports`/`states`/`complains of` (환자보고) | 247 | 323 |
| `appears`/`seems` (관찰 추정) | 49 | 24 |
| `likely`/`probable`/`suspected`/`consistent with` (추정) | 24 | 46 |
| `no evidence of`/`negative for`/`without` (음성소견) | 70 | 45 |
| `history of` (과거력) | 237 | 138 |

→ 확신도 보존은 **우리가 발명하는 게 아니라 정답이 이미 지키는 규약**. 규칙화 근거 확실.

**규칙 초안**: 대화의 확신도 표지(환자 "잘 모르겠는데", "아마") → 노트에서 확정문으로 승격 금지. `reports/denies/appears/likely`로 원 확신도를 보존. 이를 **자작하지 말고 i2b2 2010 assertion 6분류**(present / absent / possible / conditional / hypothetical / not-associated)에 대응시키면 기성 표준이라 발표 방어에 유리. ← **오늘 검토 결론: 채택 권장** (denies=absent, likely=possible 등 자연 대응).

## B-3. 미확인 처리 규칙 — 표기법을 새로 정의해야 함

N/A 관행 없음 확정(§A-0). "미확인"류 자연어는 ACI 노트에 3/207(1%)로 산발적일 뿐 규약이 아님. → **우리가 표기법·채점법을 정의**해야 하고 그게 기여 항목.

- 표기 초안: 섹션이 대화에서 확인 불가 → `[미확인: 대화에서 언급되지 않음]` (자유생성으로 채우기 금지)
- S가 88%, O 4%/A 5%/P 3%(MTS 분포)라 **미확인 규칙은 O/A/P에서 가장 자주 걸린다** → 함정셋의 "누락회피 실패"와 정확히 겹침.

## B-4. 근거 연결(citation) 규칙

- 대화에 turn_id 부여 → 노트 각 문장에 근거 turn 표시.
- **선행 과제**: MTS `Doctor:` vs ACI `[doctor]` + 오타태그(`Guest_clinican`) 흡수하는 정규화 유틸(§A-4).
- **측정 한계 명시**: citation gold가 없음 → **precision은 측정 가능**(생성한 근거가 실제 그 turn에 있나), **recall은 LLM-judge 없이 측정 불가**. 지표 정의에 이 비대칭을 반영.

## B-5. 프롬프트 단계 (계획서 §4 유지)

Baseline → 개선1(역할·형식·환각금지) → 개선2(발화행위 분류 B-1 + 확신도 B-2 + 미확인 B-3 + citation B-4) → 개선3(자기검증). 개선2가 위 규칙 4종의 집약 지점.
