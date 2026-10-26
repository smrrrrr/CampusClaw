# -*- coding: utf-8 -*-
"""POST /api/student/conversations/{id}/chat —— 会话内 SSE 流式提问。

覆盖：创建会话 + 发送一条消息；SSE 事件解析；校验最终 answer / citations，
并核验数据库 messages（user+assistant）与 ai_question_logs 落库一致。
"""

from conftest import CHAT_QUESTION, parse_sse


def test_conversation_chat_sse(
    api, student_headers, db_conn, class102_material_id
):
    # 1) 创建会话
    r = api.post("/api/student/conversations", json={}, headers=student_headers)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    try:
        # 2) 发送一条消息（SSE 流式返回）
        resp = api.post(
            f"/api/student/conversations/{cid}/chat",
            json={"question": CHAT_QUESTION},
            headers=student_headers,
        )
        assert resp.status_code == 200, resp.text
        assert "text/event-stream" in resp.headers.get("content-type", "").lower()

        events = parse_sse(resp.text)
        assert events, "SSE 流中应至少有一个事件"
        types = [e["type"] for e in events]

        # 应包含若干 delta 及一个终结事件（done / error）
        assert types[-1] in ("done", "error"), f"缺失终结事件：{types}"

        if events[-1]["type"] == "done":
            final = events[-1]
            assert final.get("answer"), "done 事件应携带回答正文"
            # 命中 class-102 已索引材料，citations 非空且指向该材料
            assert final.get("citations"), "期望检索到 class-102 引用"
            for c in final["citations"]:
                assert c["material_id"] == class102_material_id
            assistant_answer = final["answer"]
        else:
            # 未配置 Key / 调用失败时的降级分支：给出提示文本（仍须落库）
            assistant_answer = events[-1].get("message", "")

        # 3) 数据库一致性
        #    a. messages 已持久化 user + assistant 两条
        msgs = db_conn.execute(
            "select role, content, sources from messages where conversation_id=? order by id",
            (cid,),
        ).fetchall()
        assert len(msgs) >= 2, "会话中应至少存在 user 与 assistant 两条消息"
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == CHAT_QUESTION
        assert msgs[-1]["role"] == "assistant"

        #    b. ai_question_logs 落一行，且 answer 已由 assistant 消息回填
        rows = db_conn.execute(
            "select id, student_id, class_id, question, answer from ai_question_logs "
            "where student_id=3 order by id desc limit 1"
        ).fetchall()
        assert rows, "数据库应新增 ai_question_logs 记录"
        log = rows[0]
        assert log["class_id"] == 102
        assert log["question"] == CHAT_QUESTION
        assert log["answer"], "chat 结束后 answer 应被回填写入"
    finally:
        # 无论断言是否通过，都清理本用例产生的提问日志（学生3 + 该问题）并删除会话
        db_conn.execute(
            "delete from ai_question_logs where student_id=3 and class_id=102 and question=?",
            (CHAT_QUESTION,),
        )
        db_conn.commit()
        d = api.delete(f"/api/student/conversations/{cid}", headers=student_headers)
        assert d.status_code == 200, d.text