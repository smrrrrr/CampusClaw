# -*- coding: utf-8 -*-
"""POST /api/student/conversations —— 创建会话。"""


def test_create_conversation(api, student_headers, db_conn):
    """创建会话：返回 id/title，且数据库 conversations 落一行（student_id=3, class_id=102）。"""
    r = api.post("/api/student/conversations", json={}, headers=student_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body.get("id")
    assert cid, "响应应返回会话 id"
    assert body.get("title"), "响应应返回会话标题"

    row = db_conn.execute(
        "select student_id, class_id from conversations where id=?", (cid,)
    ).fetchone()
    assert row is not None, "数据库应有该会话行"
    assert row["student_id"] == 3
    assert row["class_id"] == 102

    # 清理：删除会话（会级联删除其消息），保持幂等
    d = api.delete(f"/api/student/conversations/{cid}", headers=student_headers)
    assert d.status_code == 200, d.text
    assert (
        db_conn.execute("select count(*) c from conversations where id=?", (cid,)).fetchone()["c"]
        == 0
    )