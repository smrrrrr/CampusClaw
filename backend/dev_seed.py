"""开发用种子数据：建表 + 插入测试账号（幂等，可反复运行）。"""

import json

from database import Base, SessionLocal, engine
from models import Class, Role, User
from security import hash_password

Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    # 班级
    for cid, cname in [(101, "一年级1班"), (102, "一年级2班")]:
        obj = db.query(Class).filter_by(id=cid).first()
        if not obj:
            db.add(Class(id=cid, name=cname))
    db.commit()

    # 教师（已改密，任教班级 101+102，可直接登录）
    t = db.query(User).filter_by(identifier="TEA001").first()
    if not t:
        t = User(
            role=Role.teacher,
            identifier="TEA001",
            password_hash=hash_password("Teach@2026"),
            name="王老师",
            must_change_password=False,
        )
        db.add(t)
    t.teaching_classes = json.dumps([101, 102])
    db.commit()

    # 学生：多娃手机 13800000001（小明+小红），单娃 13800000002（小刚）
    seeds = [
        ("20230001", "小明", "13800000001", 101),
        ("20230002", "小红", "13800000001", 102),
        ("20230003", "小刚", "13800000002", 101),
    ]
    for ident, name, phone, cid in seeds:
        u = db.query(User).filter_by(identifier=ident).first()
        if not u:
            u = User(
                role=Role.student,
                identifier=ident,
                password_hash=hash_password("thu" + ident[-6:]),
                name=name,
                phone=phone,
                class_id=cid,
                must_change_password=True,
            )
            db.add(u)
        else:
            # 强制重置为初始密码（开发用）
            u.password_hash = hash_password("thu" + ident[-6:])
            u.must_change_password = True
            u.phone = phone
            u.class_id = cid
            u.name = name
    db.commit()

    print("=== 种子数据就绪 ===")
    for u in db.query(User).order_by(User.id).all():
        tc = json.loads(u.teaching_classes) if u.teaching_classes else None
        print(f"  {u.role.value:8s} | {u.identifier} | {u.name} | phone={u.phone} | class={u.class_id} | teaching={tc} | mcp={u.must_change_password}")
finally:
    db.close()
