"""DeepSeek 生成解答（openai 兼容 chat completions）。

职责：把学生的问题 + 本班检索到的资料分块组装成上下文，
调用 DeepSeek 生成解题答案。未配置 API Key 时返回 None，由调用方降级。
"""

from __future__ import annotations

import time

import httpx

from config import settings

SYSTEM_PROMPT = (
    "你是校园 AI 解题助手。只能依据用户提供的「班级资料」解答问题：\n"
    "1. 引用资料时用 [n] 标注来源编号，编号对应资料段落前带的标签；\n"
    "2. 严格基于资料内容，资料没有的一定说明「未在资料中找到」，不要编造；\n"
    "3. 分步写出推理过程，最后给出结论；\n"
    "4. 若无任何资料，如实说明当前班级暂无相关学习资料；\n"
    "5. 数学、物理等学科的标准公式必须用 LaTeX 输出（行内公式用 $...$ 包裹，"
    "独立公式整体用 $$...$$ 独占一行包裹），"
    "例如分式写 \\frac{}{}、根式写 \\sqrt{}、向量写 \\vec{a}、余弦夹角公式写 "
    "$$\\cos\\langle\\vec{a},\\vec{b}\\rangle=\\frac{\\vec{a}\\cdot\\vec{b}}{|\\vec{a}|\\,|\\vec{b}|}$$；\n"
    "6. 当班级资料明确提到了某个公式或知识点（如「两向量夹角的坐标计算公式」），但召回文本因文档格式限制未包含公式本体时，"
    "请直接以 LaTeX 呈现该章节的标准公式，并正常用 [n] 标注其来源资料；"
    "不要在回答中出现「据资料重建」「公式本体未收录」「文档格式限制」「仅保留标题」等内部处理说明，"
    "也不要编造资料中不存在的知识点；\n"
    "7. 当用户直接询问一个教材中的标准数学/物理恒等式或公式（如向量夹角余弦公式）时，"
    "请直接以 LaTeX 输出该标准公式并用 [n] 标注来源资料；若资料未涉及，仍可如实给出该标准公式，"
    "但不要在回答中出现「教材标准公式」「召回文本未含公式本体」等内部说明，"
    "也不得为资料中不存在的非常规结论编造公式；\n"
    "8. 整段回答直接进入解题与结论，禁止出现「资料检索」「召回」「按标准形式给出」「以下」「由此可见」"
    "「我们可知」等过程描述、检索状态说明或过渡性元话语，也不要解释文档格式；一段话里若有多个公式，"
    "紧接使用即可，不用额外铺垫。"
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
        # 瞬时错误（超时/5xx）重试一次，降低偶发失败导致的前端降级
        if isinstance(exc, httpx.HTTPError) or getattr(getattr(exc, "response", None), "status_code", 200) >= 500:
            try:
                time.sleep(1.0)
                resp = httpx.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=settings.deepseek_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            except (httpx.HTTPError, KeyError, ValueError, IndexError):
                pass
        raise LLMGenerationError(f"DeepSeek 调用失败: {exc}") from exc