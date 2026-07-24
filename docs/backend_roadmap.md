# 백엔드 관점 개선·발전 로드맵 (제안, 07-18)

> 본평가·함정셋·오류 감사에서 나온 실측 근거 + 최신 연구를 백엔드 설계로 연결한 제안 문서.
> 우선순위는 발표(§9 일정) 기준이 아니라 "제품으로 쓰이려면" 기준. 채택 여부는 회의에서.

## 0. 우리가 실측으로 확인한 백엔드 요구사항

07-18 본평가 560노트 감사에서 나온 생성 견고성 이슈(전체 1.1%):

| 이슈 | 실측 | 시사점 |
|---|---|---|
| 퇴행성 반복 루프 | 32B가 test2 D2N144에서 동일 패턴 문장 무한반복(11.7K자) | greedy는 반복 루프에 무방비 → **서빙단 반복 가드 필수** |
| 완전 붕괴 출력 | qwen7b가 valid D2N071에서 한자 낙서 1줄만 출력 | **출력 검증 게이트 + 재시도 정책** 필요 |
| 헤더 더듬기 | llama soap에서 `PHYSICAL EXAMINATION` 4~9회 반복 (4건) | 포맷을 프롬프트가 아니라 **디코딩 제약**으로 보장해야 |
| 번역기 환각 | 초단문 "sure."에 혈압 서사 창작(웹, 92bca42로 가드) | 파이프라인의 **모든 LLM 호출**에 검증 필요 — 생성기만이 아님 |

judge 배치 자체는 건전(28,631문장 판정, 파싱실패 0). 이슈는 전부 생성 쪽.

## 1. 검증 계층 2-티어화 — 비용·지연의 구조적 해결

지금: 문장마다 32B judge 1콜(노트당 25~30콜, 2×A6000 점유). 실서비스에선 비싸고 느림.

**제안**: [MiniCheck](https://arxiv.org/abs/2404.10774) (EMNLP 2024) 계열 **소형 grounding 검증기(770M)를 1차 스크리너**로 두는 2-티어:

```
노트 문장 ──> [T1] MiniCheck류 소형 검증기 (GPU 0.1장, ms급)
                ├─ 확실히 grounded ──> 통과 (대부분)
                └─ 의심/애매 ──────> [T2] 32B judge 정밀판정 (+ 근거 turn 지목)
```

- MiniCheck-FT5는 GPT-4급 판정을 ~1/400 비용으로 재현 주장 — 우리 32B 대비로도 큰 폭 절감.
- 우리 판정 데이터가 이미 있음: **judge 판정 3만 문장 + 함정셋**이 소형 검증기의 fine-tune/캘리브레이션 데이터로 바로 쓰임(②의 사람 라벨이 들어오면 gold 기준까지 확보).
- 함정셋(perturb.py)이 티어 게이트 튜닝의 회귀 테스트가 됨: "2-티어로 바꿔도 검출률 90.6% 유지되나"를 수치로 확인.

## 2. 디코딩 제약으로 포맷 보장 — 프롬프트 규칙의 구조화

지금: S/O/A/P 배너·[T#] 인용을 프롬프트(RULE 4 v2)로 요청 → 모델이 어기면 사후 발견(llama 헤더 더듬기, 문단 몰아달기).

**제안**: vLLM [Structured Outputs](https://docs.vllm.ai/en/v0.8.2/features/structured_outputs.html)(xgrammar/outlines 백엔드, [vLLM 블로그](https://blog.vllm.ai/2025/01/14/struct-decode-intro.html))로 **문법 자체를 강제**:

- 섹션 문법: `S: SUBJECTIVE\n...O: OBJECTIVE\n...` 순서·배너를 GBNF/regex로 고정 → tagger 미인식·배너 변형 문제 소멸.
- 문장말 `[T\d+(, T\d+)*]` 인용을 문법에 포함 → 인용 커버리지 100% 구조 보장(v2 프롬프트는 "부탁", 이건 "강제").
- 부수효과: 반복 루프도 문법 종결 조건으로 차단 가능.
- 트레이드오프: 제약 디코딩은 처리량 저하([성능 비교](https://blog.squeezebits.com/guided-decoding-performance-vllm-sglang)) + 과제약 시 내용 품질 왜곡 위험 → **A/B로 soap-v2(프롬프트) vs soap-v3(문법) 격자 비교** 후 채택. 우리 파이프라인은 stage 하나 추가면 됨.

## 3. 출력 검증 게이트 + 재시도 정책 (§0 직결)

`generate.py`에 노트 수준 검증기 추가 (규칙 기반, 수 ms):

1. 반복 감지(동일 라인 ≥3연속 or n-gram 루프) → 절단 또는 재생성
2. 언어 검증(비영어 문자 비율 임계) → 재생성
3. 구조 검증(4배너 존재·순서) → 재생성
4. 재생성은 temperature 0.3 + seed 변화 1~2회(greedy 재현성은 로그로 보존), 최종 실패 시 `[GENERATION ERROR]` 명시

웹(`server.py`)의 truncated_repeat 가드를 배치로 승격하는 것 — 이미 절반 구현돼 있음.

## 4. judge 신뢰성: 패널·극성 강화 (self-preference 해소)

- 근거: self-preference는 실측되는 바이어스([Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/pdf/2410.21819), [Do LLM Evaluators Prefer Themselves for a Reason?](https://arxiv.org/pdf/2504.03846)) — **이종·이크기 모델 패널 다수결**로 50%+ 감소 보고.
- 우리 적용: 32B(Qwen) + Llama-8B + MiniCheck류의 **3-패널 다수결**(32B 생성분 채점 시 특히). 패널은 clients.chat 구조상 모델 키 목록만 늘리면 됨.
- 함정셋이 보여준 약점(부정뒤집기 74.3%) → judge 프롬프트에 **극성(부정/확실성) 명시 대조 단계** 추가 후 perturb 재실행으로 개선 검증. (회귀 테스트 루프: 프롬프트 수정 → perturb → 검출률 비교)

## 5. 누락(recall) 방향 — 검증의 반쪽 채우기

지금 judge는 precision만(쓴 문장의 근거). 누락은 ROUGE 대리뿐.

- **역방향 judge**: gold(또는 대화 핵심 발화)를 기준으로 "이 정보가 노트에 반영됐나"를 문장별 entailment — own_metrics의 `_UNKNOWN` 프롬프트 구조 재사용 가능.
- 참고: [의료 요약 누락의 외재적 평가](https://arxiv.org/pdf/2311.08303) — 누락은 임상 downstream 영향으로 평가해야 한다는 논지. 발표 한계 슬라이드에 인용 가치.
- 최근 의료 환각 벤치마크들(MedHallu·FaithBench·[MedBench v5](https://arxiv.org/html/2606.24155) 등)이 환각/누락을 분리 측정하는 추세 — 우리 지표 체계(환각=judge, 누락=역방향)와 정합.

## 6. 서빙 최적화 (실배치 비용)

| 항목 | 지금 | 개선 |
|---|---|---|
| judge prefill | 문장마다 동일 대화문 재전송 | vLLM **prefix caching**(같은 대화 프리픽스 KV 재사용) — 문장 25개면 prefill 대부분 절약. 배치 judge 처리량 수 배 |
| 32B 배치 | FP16, 2×A6000(tp=2) | **AWQ/GPTQ 4bit → 1×A6000** 탑재 — GPU 반값. 함정셋으로 판정 열화 회귀 확인 |
| 노트 지연 | 생성 완료 후 일괄 judge | **스트리밍 문장 검증**: 생성 스트림에서 문장 완성 즉시 judge 큐 투입 → 사용자 체감 지연 = 마지막 문장 판정 시간 |
| GPU 배분 | 7B 2대 + 32B(2장) 상시 | 2-티어(§1) 도입 시: 생성 7B 1대 + 소형 검증기 + 32B는 온디맨드 |

## 7. 제안 우선순위 (백엔드 관점)

| 순위 | 항목 | 근거 | 비용 |
|---|---|---|---|
| 1 | §3 출력 검증 게이트 | 오늘 실측 버그 직결, 반나절 | 소 |
| 2 | §4 judge 극성 강화 + perturb 회귀 | 함정셋 약점 직결, 1일 | 소 |
| 3 | §6 prefix caching·스트리밍 검증 | 데모 체감 즉효 | 중 |
| 4 | §2 구조화 디코딩 A/B (soap-v3) | 포맷 문제 구조적 종결 | 중 |
| 5 | §1 2-티어 검증(MiniCheck류) | 실서비스 비용 구조 | 대(모델 도입) |
| 6 | §5 역방향 judge(누락) | 검증 완성도 | 대(신규 지표) |

---
*근거 링크: [MiniCheck](https://aclanthology.org/2024.emnlp-main.499/) · [vLLM Structured Outputs](https://docs.vllm.ai/en/v0.8.2/features/structured_outputs.html) · [XGrammar](https://arxiv.org/pdf/2411.15100) · [Self-Preference Bias](https://arxiv.org/pdf/2410.21819) · [Omission 평가](https://arxiv.org/pdf/2311.08303) · [Guided Decoding 성능](https://blog.squeezebits.com/guided-decoding-performance-vllm-sglang)*
