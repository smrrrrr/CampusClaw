# -*- coding: utf-8 -*-
"""POST /api/student/ai-question —— AI 检索提问（校验 citations + ai_question_logs）。

测试学生：20230002（class 102，id=3）。class-102 已有已索引材料，检索应命中它。
"""

from conftest import SEED_QUESTION


def test_ai_question_returns_citations_and_logs(
    api, student_headers, db_conn, class102_material_id
):
    """提问命中 class-102 已索引材料：citations 非空且指向该材料；数据库新增提问日志。"""
    r = api.post(
        "/api/student/ai-question",
        json={"question": SEED_QUESTION},
        headers=student_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    log_id = body.get("id")
    try:
        # 响应内容校验
        assert body.get("id"), "响应应返回提问记录 id"
        assert body.get("answer"), "AI 应有回答正文"
        assert isinstance(body.get("remaining"), int)
        assert body.get("citations"), "期望检索到 class-102 已索引资料的 citations"
        for c in body["citations"]:
            assert c["material_id"] == class102_material_id, "引用材料应是 class-102 已索引材料"
            assert isinstance(c["chunk_index"], int)
            assert c["excerpt"]
            assert isinstance(c["score"], (int, float))

        # 数据库一致性：ai_question_logs 新增一行，student_id=3、class_id=102、问题匹配、答案写入
        rows = db_conn.execute(
            "select id, student_id, class_id, question, answer from ai_question_logs "
            "where student_id=3 order by id desc limit 1"
        ).fetchall()
        assert rows, "数据库应新增 ai_question_logs 记录"
        new = rows[0]
        assert new["id"] == log_id
        assert new["class_id"] == 102
        assert new["question"] == SEED_QUESTION
        assert new["answer"], "日志的 answer 应被写入"
    finally:
        # 无论断言是否通过，都清理本用例产生的日志，保持幂等
        if log_id:
            db_conn.execute("delete from ai_question_logs where id=?", (log_id,))
            db_conn.commit()