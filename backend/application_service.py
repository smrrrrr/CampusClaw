"""内置学科应用、提示词模板与应用级资料/技能边界。"""
import json

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models import AIApplication, AgentConfig

SUBJECTS = {
    "math": ("数学解题助手", "数学", "先识别已知条件和目标，再引导选择定理、拆解步骤，鼓励学生解释依据并自己计算。"),
    "physics": ("物理学习助手", "物理", "先明确物理情境，逐步引导画图、受力分析和建模，检查单位与适用条件，让学生自己推导。"),
    "english": ("英语学习助手", "英语", "通过上下文线索、句子结构和例句引导学生判断词义、分析语法、理解阅读和修改表达。"),
}


def builtin_templates():
    return [{"id": f"builtin-{key}", "name": label, "content": f"你是{subject}学习助手。{guide}引用班级资料时用 [n] 标明来源，数学公式使用 LaTeX。", "builtin": True}
            for key, (label, subject, guide) in SUBJECTS.items()]


def ensure_applications(db, class_id):
    existing = {a.subject for a in db.query(AIApplication).filter_by(class_id=class_id)}
    cfg = db.query(AgentConfig).filter_by(class_id=class_id).first()
    for key, (name, _, _) in SUBJECTS.items():
        if key in existing:
            continue
        # 嵌套事务处理并发首次访问的唯一约束，不回滚其他班级业务。
        try:
            with db.begin_nested():
                db.add(AIApplication(class_id=class_id, subject=key, name=name,
                                     system_prompt=next(t["content"] for t in builtin_templates() if t["id"] == f"builtin-{key}"),
                                     tutor_enabled=cfg.tutor_enabled if cfg else True,
                                     material_ids="[]", skill_ids="[]"))
        except IntegrityError:
            pass
    db.commit()
    return db.query(AIApplication).filter_by(class_id=class_id).order_by(AIApplication.id).all()


def get_application(db, class_id, application_id):
    if application_id is None:
        return None
    app = db.query(AIApplication).filter_by(id=application_id, class_id=class_id).first()
    if app is None:
        raise HTTPException(404, "学科应用不存在")
    return app


def binding_ids(raw):
    return json.loads(raw) if raw is not None else None


def application_data(app, *, student=False):
    result = {"id": app.id, "name": app.name, "subject": app.subject, "tutor_enabled": app.tutor_enabled}
    if not student:
        result.update(class_id=app.class_id, system_prompt=app.system_prompt,
                      material_ids=binding_ids(app.material_ids), skill_ids=binding_ids(app.skill_ids))
    return result
