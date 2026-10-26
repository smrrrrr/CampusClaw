"""DeepSeek 生成解答（openai 兼容 chat completions）。

职责：把学生的问题 + 本班检索到的资料分块组装成上下文，
调用 DeepSeek 生成解题答案。未配置 API Key 时返回 None（非流式），由调用方降级。

- generate_answer：一次性非流式生成（旧 ask_ai 使用）
- stream_chat：SSE 流式生成（多轮会话使用），逐字吐出 delta
- resolve_system_prompt：按班级 AgentConfig 解析提示词（自定义 + 解题引导技能开关）
"""

from __future__ import annotations

import json
import time

import httpx
from application_service import SUBJECTS
from invocation_audit import OutboundCall, record_skip

from config import settings

# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
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

# 兼容旧引用（add-rag-search 时期模块级常量，现作为默认提示词）
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT

# 「解题引导技能」：由教师配置开关控制，开启后 AI 采用苏格拉底式提问引导、不直接给最终答案
TUTOR_SKILL_PROMPT = (
    "【解题引导技能 · 苏格拉底式引导】你是采用苏格拉底提问法的高中学科辅导老师，通过一步步提问引导学生自己解题。\n"
    "关键在于：**学生用自然语言或作答数字即可，不要让他输入任何公式或 LaTeX**；需要式子时由你代为写出。\n"
    "1. 先复述题目核心，请学生用自己的话说说这题考哪个知识点、该用什么公式（说名字或思路即可，不必打公式）；\n"
    "2. 每次只抛出一个问题，等学生回答后再给下一步引导，不得一次问多个；\n"
    "3. 学生只要给出思路或关键数值就据此反馈：答对则肯定并给下一个引导问题；答错或卡住则给更小的子问题或一个反例纠正，而不是替他重做；\n"
    "4. 关键计算与最终结论让学生自己完成，你只给方向与切入点，可代为把用到的公式写出来，但不替学生把数字代算到底；\n"
    "5. 仅当学生明确表示「不会」或尝试多次仍未突破时，才分步给出留有步骤的提示性解答，让学生能跟上；\n"
    "6. 全程保持鼓励语气。"
)


def resolve_system_prompt(config, subject: str | None = None) -> str:
    """按班级 AgentConfig 解析最终系统提示词。

    开启「解题引导」时完全采用苏格拉底式框架，不使用教师自定义提示词，
    以保证不与"直接给出结论"类文案冲突；未开启引导时沿用教师自定义或默认提示词。
    """
    if config is not None and config.tutor_enabled:
        # 解题引导开启：仅用苏格拉底框架 + 必要的格式/溯源规则，忽略教师自定义提示词
        subject_prompt = ""
        if subject in SUBJECTS:
            _, label, guide = SUBJECTS[subject]
            subject_prompt = f"\n【学科引导】你是{label}辅导老师。{guide}\n"
        return (
            TUTOR_SKILL_PROMPT
            + subject_prompt
            + "\n\n【格式与溯源强制要求】\n"
            "1. 引用资料时用 [n] 标注来源编号；资料没有的要说明「未在资料中找到」，不编造；"
            "标准数学公式一律用 LaTeX：行内 $...$、独立公式整体用 $$...$$ 独占一行；\n"
            "2. 全程不得出现「资料检索」「召回」「按标准形式给出」「由此可见」「我们可知」等"
            "过程描述、检索状态或过渡性元话语，直接以引导性提问与学生对话。"
        )

    custom = config.system_prompt.strip() if config and (config.system_prompt or "").strip() else ""
    return custom or DEFAULT_SYSTEM_PROMPT


def _build_user_message(
    question: str,
    context_block: str | None,
    tutor_enabled: bool = False,
) -> str:
    if context_block:
        if tutor_enabled:
            return (
                f"问题：{question}\n\n"
                f"以下是本班可检索资料的相关段落（[n] 为来源编号）：\n"
                f"{context_block}\n\n"
                "请用苏格拉底式提问引导我一步步解题，每次只问一个问题；"
                "我可以用自然语言或数值作答；不要直接给出完整解题步骤或最终答案。"
            )
        return (
            f"问题：{question}\n\n"
            f"以下是从本班可检索资料中召回的相关段落（[n] 为来源编号）：\n"
            f"{context_block}\n\n请据此给出解答。"
        )
    # 本轮未命中新资料：不短路拒绝，交由模型依据既有对话与常识自然回复。
    # 这样后续作答（延续原题）可继续，换新话题（如食堂）则如实说明资料未覆盖。
    return (
        f"问题：{question}\n\n"
        "本轮未检索到新的班级资料。若该话题在此前的对话/资料中已出现，可据此延续；"
        "若确实没有相关资料，请如实说明「未在资料中找到」，不要编造。"
    )


def build_chat_messages(
    system_prompt: str,
    history: list[tuple[str, str]],
    question: str,
    context_block: str | None,
    tutor_enabled: bool = False,
) -> list[dict]:
    """构造多轮对话消息数组：system + 历史轮次 + 当前问题（含检索上下文）。

    tutor_enabled 为 True 时采用苏格拉底式引导措辞，避免用户消息指令压过系统提示词。
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for role, content in history:  # 按时间顺序排列的历史 (user/assistant)
        if content:
            messages.append({"role": role, "content": content})
    messages.append(
        {"role": "user", "content": _build_user_message(question, context_block, tutor_enabled)}
    )
    return messages


# ---------------------------------------------------------------------------
# 调用
# ---------------------------------------------------------------------------


class LLMGenerationError(Exception):
    """DeepSeek 调用失败。"""


def generate_answer(question: str, context_block: str | None) -> str | None:
    """一次性非流式生成解答。

    返回生成文本；未配置 API Key 返回 None（调用方做降级提示）；
    调用失败抛 LLMGenerationError。
    """
    if not settings.deepseek_api_key:
        record_skip("未配置模型 API Key")
        return None

    messages = build_chat_messages(
        DEFAULT_SYSTEM_PROMPT, [], question, context_block
    )
    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": settings.deepseek_temperature,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    for attempt in range(2):
        try:
            with OutboundCall("llm_answer", url, payload) as audit:
                resp = httpx.post(url, json=payload, headers=headers, timeout=settings.deepseek_timeout)
                audit.response = {"http_status": resp.status_code, "body": resp.text}
                resp.raise_for_status()
                data = resp.json()
                audit.response["body"] = data
                return data["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            if attempt == 0 and isinstance(exc, httpx.HTTPError):
                time.sleep(1.0)
                continue
            raise LLMGenerationError(f"DeepSeek 调用失败: {exc}") from exc


async def stream_chat(
    messages: list[dict],
    *,
    timeout: float | None = None,
    temperature: float | None = None,
):
    """流式生成，并保存实际请求及 SSE data 帧；无 Key 时明确记录跳过。"""
    if not settings.deepseek_api_key:
        record_skip("未配置模型 API Key")
        raise LLMGenerationError("未配置 DeepSeek API Key")

    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature if temperature is not None else settings.deepseek_temperature,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    timeout = timeout or settings.deepseek_timeout

    try:
        with OutboundCall("llm_answer", url, payload) as audit:
            audit.response = {"events": [], "answer": "", "completed": False}
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    audit.response["http_status"] = resp.status_code
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "ignore")
                        audit.response["body"] = body
                        raise LLMGenerationError(f"DeepSeek HTTP {resp.status_code}: {body[:200]}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            audit.response["completed"] = True
                            break
                        # 保留全部 data 帧，包括 usage/finish_reason/错误帧。
                        audit.response["events"].append(data)
                        try:
                            obj = json.loads(data)
                            if "error" in obj:
                                raise LLMGenerationError("模型流返回错误")
                            if obj.get("choices") and obj["choices"][0].get("finish_reason"):
                                audit.response["completed"] = True
                            delta = obj["choices"][0].get("delta", {}).get("content") or ""
                            if delta:
                                audit.response["answer"] += delta
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                    if not audit.response["completed"]:
                        raise LLMGenerationError("模型流提前结束")
    except httpx.HTTPError as exc:
        raise LLMGenerationError(f"DeepSeek 流式调用失败: {exc}") from exc
