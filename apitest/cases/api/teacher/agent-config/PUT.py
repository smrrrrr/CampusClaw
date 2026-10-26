# -*- coding: utf-8 -*-
"""PUT /api/teacher/agent-config —— 保存班级提示词与技能开关；用后还原。"""


def test_save_agent_config_persists_and_restores(
    api, teacher_headers, db_conn
):
    """PUT 保存配置 → 数据库被更新；随后还原为原值，保证幂等。"""
    # 快照数据库原值（作为本次还原基线）
    row = db_conn.execute(
        "select system_prompt, tutor_enabled from agent_configs where class_id=101"
    ).fetchone()
    orig_prompt = "" if row is None else row["system_prompt"]
    orig_tutor = False if row is None else bool(row["tutor_enabled"])

    new_prompt = "apitest 自定义系统提示词：面向测试的动态配置。"
    new_tutor = True

    # 写入新配置
    r = api.put(
        "/api/teacher/agent-config",
        json={"class_id": 101, "system_prompt": new_prompt, "tutor_enabled": new_tutor},
        headers=teacher_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tutor_enabled"] is True
    assert body["system_prompt"] == new_prompt

    # 数据库一致性：agent_configs 的 class_id=101 行已被更新
    row2 = db_conn.execute(
        "select system_prompt, tutor_enabled from agent_configs where class_id=101"
    ).fetchone()
    assert row2 is not None
    assert row2["system_prompt"] == new_prompt
    assert bool(row2["tutor_enabled"]) is new_tutor

    # 还原原值，避免污染真实配置
    r3 = api.put(
        "/api/teacher/agent-config",
        json={"class_id": 101, "system_prompt": orig_prompt, "tutor_enabled": orig_tutor},
        headers=teacher_headers,
    )
    assert r3.status_code == 200, r3.text
    row3 = db_conn.execute(
        "select system_prompt, tutor_enabled from agent_configs where class_id=101"
    ).fetchone()
    assert row3["system_prompt"] == orig_prompt
    assert bool(row3["tutor_enabled"]) == orig_tutor