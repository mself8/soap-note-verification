"""모델-불가지 chat(). 로컬 vLLM(OpenAI 호환) 우선. 후속 API는 여기 분기만 추가."""
import time

from openai import OpenAI

from . import config

_clients = {}  # port -> OpenAI


def _client_for(model):
    if model not in config.MODELS:
        raise KeyError(f"미등록 모델 '{model}'. config.MODELS 참고: {list(config.MODELS)}")
    spec = config.MODELS[model]
    port = spec["port"]
    if port not in _clients:
        # 로컬 vLLM 서버. api_key 는 형식상 필요(검사 안 함).
        _clients[port] = OpenAI(base_url=f"http://localhost:{port}/v1", api_key="EMPTY", timeout=180)
    return _clients[port], spec["served_name"]


def chat(model, system, user, temperature=0.0, max_tokens=1400, retries=3, response_format=None):
    """단일 턴 생성. system=None 이면 user만.

    response_format: OpenAI 표준 {"type":"json_schema","json_schema":{...}} — vLLM 0.25가
    디코더 레벨로 스키마를 강제함(구조 강제 디코딩). legacy extra_body guided_json은
    이 버전에서 무시되므로 쓰지 말 것(실측).
    """
    client, served = _client_for(model)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    kwargs = {}
    if response_format:
        kwargs["response_format"] = response_format
    last = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=served, messages=messages,
                temperature=temperature, max_tokens=max_tokens, **kwargs,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — 네트워크/서버 기동중 재시도
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"chat 실패({retries}회) model={model}: {last}")


def health(model):
    """서버가 떠 있는지 1회 확인."""
    try:
        return bool(chat(model, None, "reply with: ok", max_tokens=5, retries=1))
    except Exception:
        return False
