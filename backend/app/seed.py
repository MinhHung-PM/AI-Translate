"""Development seed data (users, division, projects, glossary).

Only for development/demo databases; refuses to run in production. It does
not create meetings or metrics — dashboards show real data only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.catalog import get_catalog
from app.core.config import get_settings
from app.models import (
    AIProviderConfiguration,
    Division,
    DivisionAssignment,
    GlossaryEntry,
    Project,
    ProjectMembership,
    User,
)
from app.models.enums import GlobalRole, KeyStorage, Language, ProjectRole

USERS = [
    ("admin@example.com", "Quản trị viên", GlobalRole.admin),
    ("pm@example.com", "Trần Minh (PM)", GlobalRole.project_manager),
    ("member@example.com", "Nguyễn Văn An (BrSE)", GlobalRole.member),
    ("ba@example.com", "Lê Thu Hà (BA)", GlobalRole.member),
    ("divmgr@example.com", "Phạm Quốc Huy (Division Manager)", GlobalRole.division_manager),
    ("outsider@example.com", "Hoàng Lan (Dự án khác)", GlobalRole.member),
]


def _get_or_create_user(db: Session, email: str, name: str, role: GlobalRole) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=name, role=role)
        db.add(user)
        db.flush()
    return user


def seed(db: Session) -> None:
    settings = get_settings()
    if settings.is_production:
        # Compose runs the seed step by default; production never gets demo data (skip, don't fail).
        print("Production environment: demo seed data skipped")
        return
    division = db.scalar(select(Division).where(Division.name == "Japan Delivery Division 1"))
    if division is None:
        division = Division(name="Japan Delivery Division 1", description="Khối dự án khách hàng Nhật Bản")
        db.add(division)
        db.flush()
    users = {email: _get_or_create_user(db, email, name, role) for email, name, role in USERS}

    def project(code: str, name: str, client: str, div: Division | None) -> Project:
        p = db.scalar(select(Project).where(Project.code == code))
        if p is None:
            p = Project(
                code=code,
                name=name,
                client_name=client,
                division_id=div.id if div else None,
                default_source_language=Language.ja,
                default_target_language=Language.vi,
                default_memo_language=Language.vi,
                translation_instructions="Giữ nguyên thuật ngữ IT tiếng Anh (API, UAT, deploy, PR).",
                created_by_id=users["pm@example.com"].id,
            )
            db.add(p)
            db.flush()
        return p

    alpha = project("ALPHA", "Hệ thống quản lý kho (Sakura Logistics)", "Sakura Logistics K.K.", division)
    beta = project("BETA", "Cổng thông tin nội bộ (Fuji Bank)", "Fuji Bank", None)

    def member(p: Project, email: str, role: ProjectRole) -> None:
        user = users[email]
        if (
            db.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == p.id, ProjectMembership.user_id == user.id
                )
            )
            is None
        ):
            db.add(ProjectMembership(project_id=p.id, user_id=user.id, role=role))

    member(alpha, "pm@example.com", ProjectRole.manager)
    member(alpha, "member@example.com", ProjectRole.member)
    member(alpha, "ba@example.com", ProjectRole.member)
    member(beta, "outsider@example.com", ProjectRole.manager)

    divmgr = users["divmgr@example.com"]
    if db.scalar(select(DivisionAssignment).where(DivisionAssignment.user_id == divmgr.id)) is None:
        db.add(DivisionAssignment(user_id=divmgr.id, division_id=division.id, can_view_transcripts=False))

    for src, tgt, ctx in [
        ("在庫引当", "phân bổ tồn kho", "Nghiệp vụ kho"),
        ("出荷指示", "chỉ thị xuất hàng", None),
        ("受入テスト", "UAT", "Kiểm thử chấp nhận"),
        ("仕様書", "tài liệu đặc tả", None),
    ]:
        if (
            db.scalar(
                select(GlossaryEntry).where(GlossaryEntry.project_id == alpha.id, GlossaryEntry.source_term == src)
            )
            is None
        ):
            db.add(
                GlossaryEntry(
                    project_id=alpha.id,
                    source_term=src,
                    preferred_translation=tgt,
                    source_language=Language.ja,
                    target_language=Language.vi,
                    context=ctx,
                )
            )

    # Default to the mock provider in development so the workflow runs without keys.
    if get_catalog().get("mock"):
        for user in users.values():
            if db.scalar(select(AIProviderConfiguration).where(AIProviderConfiguration.user_id == user.id)) is None:
                db.add(
                    AIProviderConfiguration(
                        user_id=user.id,
                        provider="mock",
                        model="mock-deterministic",
                        is_default=True,
                        key_storage=KeyStorage.none,
                    )
                )
    db.commit()
