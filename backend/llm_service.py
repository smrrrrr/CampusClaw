"""DeepSeek 生成解答（openai 兼容 chat completions）。

职责：把学生的问题 + 本班检索到的资料分块组装成上下文，
调用 DeepSeek 生成解题答案。未配置 API Key 时返回 None，由调用方降级。
"""

import httpx

from config import settings

SYSTEM_PROMPT = (
    "你是校园 AI 解题助手。只能依据用户提供的「班级资料」解答问题：\n"
    "1. 引用资料时用 [n] 标注来源编号，编号对应资料段落前带的标签；\n"
    "2. 严格基于资料内容，资料没有的一定说明「未在资料中找到」，不要编造；\n"
    "3. 分步写出推理过程，最后给出结论；\n"
    "4. 若无任何资料，如实说明当前班级暂无相关学习资料。"
)


def _build_user_message(question: str, context_block: str | None) -> str:
    if context_block:
        return (
            f"问题：{question}\n\n"
            f"以下是从本班可检索资料中召回的相关段落（[n] 为来源编号）：\n"
            f"{context_block}\n\n请据此给出解答。"
        )
    return f"问题：{question}\n\n当前检索未命中任何班级资料，请说明没有可用资料。"


class LLMGenerationError(Exception):
    """DeepSeek 调用失败。"""


def generate_answer(question: str, context_block: str | None) -> str | None:
    """调用 DeepSeek 生成解答。

    返回生成文本；未配置 API Key 返回 None（调用方做降级提示）；
    调用失败抛 LLMGenerationError。
    """
    if not settings.deepseek_api_key:
        return None

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(question, context_block)},
        ],
        "temperature": settings.deepseek_temperature,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=settings.deepseek_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        raise LLMGenerationError(f"DeepSeek 调用失败: {exc}") from exc