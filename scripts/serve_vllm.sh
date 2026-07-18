#!/usr/bin/env bash
# 로컬 vLLM 서빙 — 모델별 1개씩 기동. served-model-name = config.MODELS 키.
#   사용법:  bash scripts/serve_vllm.sh <model-key> [gpus]
#   예:      bash scripts/serve_vllm.sh qwen2.5-7b            # GPU0, 포트8001
#            bash scripts/serve_vllm.sh qwen2.5-32b 0,1       # 32B는 tp=2(2장)
#
# huggingface.co 직접 사용(현재 접속 가능). 차단 시:  export HF_ENDPOINT=https://hf-mirror.com
# 게이트 모델(llama/mistral)이 401이면 config.py 주석의 ungated 재업로드로 HF 교체.
set -euo pipefail
cd "$(dirname "$0")/.."
VLLM=.venv-vllm/bin/vllm
# flashinfer 0.6.13 번들 CCCL 헤더가 cu13 nvcc와 비호환 → 샘플링 커널 JIT 실패.
# 해결: flashinfer 샘플러를 끄고 native PyTorch 샘플러 사용(greedy/temp=0라 동등, JIT 불필요).
export VLLM_USE_FLASHINFER_SAMPLER=0
# (아래 CUDA_HOME/PATH는 혹시 다른 JIT 경로가 nvcc/ninja를 찾을 때 대비 — 무해)
export CUDA_HOME="$PWD/.venv-vllm/lib/python3.10/site-packages/nvidia/cu13"
export PATH="$PWD/.venv-vllm/bin:$CUDA_HOME/bin:$PATH"
KEY="${1:?model key 필요: qwen2.5-7b | llama3.1-8b | mistral-7b | qwen2.5-32b}"

case "$KEY" in
  qwen2.5-7b)  HF=Qwen/Qwen2.5-7B-Instruct;                PORT=8001; TP=1; GPUS="${2:-0}"   ;;
  llama3.1-8b) HF=NousResearch/Meta-Llama-3.1-8B-Instruct; PORT=8002; TP=1; GPUS="${2:-1}"   ;;
  mistral-7b)  HF=mistralai/Mistral-7B-Instruct-v0.3;      PORT=8003; TP=1; GPUS="${2:-2}"   ;;
  qwen2.5-32b) HF=Qwen/Qwen2.5-32B-Instruct;               PORT=8004; TP=2; GPUS="${2:-0,1}" ;;
  *) echo "unknown model key: $KEY" >&2; exit 1 ;;
esac

echo ">> serving $KEY  ($HF)  GPUs=$GPUS  port=$PORT  tp=$TP"
CUDA_VISIBLE_DEVICES="$GPUS" "$VLLM" serve "$HF" \
  --served-model-name "$KEY" --port "$PORT" \
  --tensor-parallel-size "$TP" --gpu-memory-utilization 0.9 --max-model-len 16384
