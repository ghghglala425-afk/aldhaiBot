# -*- coding: utf-8 -*-
"""نماذج قاعدة البيانات (SQLAlchemy 2.0) — مخطط شامل للمنصّة.

يشمل: المستخدمون · الجلسات · المنهج (كورسات/مراحل/دروس) · الوسائط · الأكواد ·
الاختبارات · المحاولات · التقدّم · النقاط · الشارات · السلاسل اليومية ·
التذكيرات · الشهادات · المختبرات · التلميحات · الملاحظات · النقاش ·
سجلّ التدقيق · سجلّ اللغات والمكتبات.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# =====================================================================
#  المستخدمون والمصادقة
# =====================================================================
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(unique=True, index=True)
    pass_hash: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="student")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    locale: Mapped[str] = mapped_column(String(5), default="ar")
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Riyadh")
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    last_streak_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")
    progress: Mapped[list["Progress"]] = relationship(back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="sessions")


# =====================================================================
#  سجلّ اللغات والمكتبات (التغطية العالمية)
# =====================================================================
class Language(Base):
    __tablename__ = "languages"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    name_ar: Mapped[Optional[str]] = mapped_column(String(80))
    paradigm: Mapped[Optional[str]] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    is_security_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_esoteric: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    docker_image: Mapped[Optional[str]] = mapped_column(String(120))


class Framework(Base):
    __tablename__ = "frameworks"

    id: Mapped[int] = mapped_column(primary_key=True)
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[Optional[str]] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("language_id", "slug", name="uq_framework"),)


# =====================================================================
#  المنهج: كورسات → مراحل → دروس
# =====================================================================
class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    title_en: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    track: Mapped[str] = mapped_column(String(40), default="programming", index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    icon: Mapped[Optional[str]] = mapped_column(String(40))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    stages: Mapped[list["Stage"]] = relationship(
        back_populates="course", order_by="Stage.order_index"
    )


class Stage(Base):
    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("course_id", "slug", name="uq_stage"),)

    course: Mapped["Course"] = relationship(back_populates="stages")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="stage", order_by="Lesson.order_index"
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(250))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    objectives: Mapped[list] = mapped_column(JSON, default=list)
    content_md: Mapped[Optional[str]] = mapped_column(Text)
    # ==== عناصر الحفظ والتركيز ====
    key_points: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    memory_hook: Mapped[Optional[str]] = mapped_column(Text, default="", server_default="")
    prerequisites: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    further_reading: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # مدة القراءة المتوقعة بالدقائق — للخطط اليومية
    est_reading_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    language_slug: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    est_minutes: Mapped[int] = mapped_column(Integer, default=20)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    xp_reward: Mapped[int] = mapped_column(Integer, default=50)
    min_score: Mapped[int] = mapped_column(Integer, default=70)
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 0 = غير محدود
    status: Mapped[str] = mapped_column(String(20), default="draft")  # outline|draft|verified|published
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("stage_id", "slug", name="uq_lesson"),)

    stage: Mapped["Stage"] = relationship(back_populates="lessons")
    assets: Mapped[list["LessonAsset"]] = relationship(back_populates="lesson")
    codes: Mapped[list["CodeSample"]] = relationship(back_populates="lesson")
    quizzes: Mapped[list["Quiz"]] = relationship(back_populates="lesson")
    labs: Mapped[list["Lab"]] = relationship(back_populates="lesson")


class LessonAsset(Base):
    __tablename__ = "lesson_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # audio|video|pdf|image
    lang: Mapped[str] = mapped_column(String(5), default="ar")
    url: Mapped[str] = mapped_column(String(500))
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    size_kb: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lesson: Mapped["Lesson"] = relationship(back_populates="assets")


class CodeSample(Base):
    __tablename__ = "code_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(250))
    code: Mapped[str] = mapped_column(Text)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    expected_output: Mapped[Optional[str]] = mapped_column(Text)
    # ==== موسوعة الأكواد (Code Atlas) ====
    anatomy: Mapped[list] = mapped_column(JSON, default=list)          # [{line, code, explain}]
    usages: Mapped[list] = mapped_column(JSON, default=list)           # [{name, signature, description, example, output}]
    parameters: Mapped[list] = mapped_column(JSON, default=list)       # [{name, type, description, default, required}]
    returns: Mapped[Optional[str]] = mapped_column(Text)
    gotchas: Mapped[list] = mapped_column(JSON, default=list)          # أخطاء شائعة
    security_notes: Mapped[list] = mapped_column(JSON, default=list)   # ملاحظات أمنية
    related: Mapped[list] = mapped_column(JSON, default=list)          # موضوعات/دوال مرتبطة
    tags: Mapped[list] = mapped_column(JSON, default=list)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lesson: Mapped["Lesson"] = relationship(back_populates="codes")


# =====================================================================
#  الاختبارات
# =====================================================================
class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    pass_score: Mapped[int] = mapped_column(Integer, default=70)
    shuffle: Mapped[bool] = mapped_column(Boolean, default=True)

    lesson: Mapped["Lesson"] = relationship(back_populates="quizzes")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz", order_by="Question.order_index"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="single")  # single|multi|text|code
    points: Mapped[int] = mapped_column(Integer, default=1)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(
        back_populates="question", order_by="Option.order_index"
    )


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped["Question"] = relationship(back_populates="options")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    answers: Mapped[list["Answer"]] = relationship(back_populates="attempt")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    response: Mapped[Optional[str]] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    points: Mapped[int] = mapped_column(Integer, default=0)

    attempt: Mapped["Attempt"] = relationship(back_populates="answers")


# =====================================================================
#  التقدّم · النقاط · الشارات · السلاسل
# =====================================================================
class Progress(Base):
    __tablename__ = "progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="locked")
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_progress"),)

    user: Mapped["User"] = relationship(back_populates="progress")


class XpEvent(Base):
    __tablename__ = "xp_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(60))
    ref: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(String(40))


class UserBadge(Base):
    __tablename__ = "user_badges"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id", ondelete="CASCADE"))
    earned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)


class DailyAssignment(Base):
    __tablename__ = "daily_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily"),)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), default="daily_lesson")
    time_of_day: Mapped[str] = mapped_column(String(5), default="19:00")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LearningPath(Base):
    """مسار تعلّمي يجمع عدة كورسات في رحلة واحدة."""

    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(String(40))
    course_slugs: Mapped[list] = mapped_column(JSON, default=list)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PathCertificate(Base):
    __tablename__ = "path_certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "path_id", name="uq_path_cert"),)


# =====================================================================
#  المختبرات والتلميحات والتسليمات
# =====================================================================
class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="ctf")  # ctf|sandbox|exercise|target
    docker_image: Mapped[Optional[str]] = mapped_column(String(150))
    flags: Mapped[list] = mapped_column(JSON, default=list)
    # ==== بيئات الهدف (TryHackMe-like) ====
    tasks: Mapped[list] = mapped_column(JSON, default=list)  # [{order,title,prompt,answer,points}]
    target_port: Mapped[Optional[int]] = mapped_column(Integer)   # منفذ الحاوية الداخلي
    target_path: Mapped[Optional[str]] = mapped_column(String(200))
    runtime_port: Mapped[Optional[int]] = mapped_column(Integer)  # منفذ المضيف المفضّل
    external_url: Mapped[Optional[str]] = mapped_column(String(400))  # هدف خارجي بديل عن الحاوية
    points: Mapped[int] = mapped_column(Integer, default=100)

    lesson: Mapped["Lesson"] = relationship(back_populates="labs")
    hints: Mapped[list["Hint"]] = relationship(back_populates="lab")
    instances: Mapped[list["LabInstance"]] = relationship(back_populates="lab")


class LabInstance(Base):
    """قالب هدف يعمل لحساب مستخدم (حاوية معزولة)."""

    __tablename__ = "lab_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id", ondelete="CASCADE"))
    container_id: Mapped[Optional[str]] = mapped_column(String(80))
    url: Mapped[Optional[str]] = mapped_column(String(300))
    host_port: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="starting")  # starting|running|stopped|error
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "lab_id", name="uq_lab_instance"),)

    lab: Mapped["Lab"] = relationship(back_populates="instances")


class Hint(Base):
    __tablename__ = "hints"

    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    cost_xp: Mapped[int] = mapped_column(Integer, default=10)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    lab: Mapped["Lab"] = relationship(back_populates="hints")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


# =====================================================================
#  الملاحظات · المرجعيات · النقاش · سجلّ التدقيق
# =====================================================================
class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_bookmark"),)


class Discussion(Base):
    __tablename__ = "discussions"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("discussions.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[Optional[str]] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProxyLog(Base):
    """سجلّ طلبات أدوات الاختبار (Repeater/Intruder-lite)."""

    __tablename__ = "proxy_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(10), default="GET")
    url: Mapped[str] = mapped_column(String(600))
    req_headers: Mapped[dict] = mapped_column(JSON, default=dict)
    req_body: Mapped[Optional[str]] = mapped_column(Text)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    resp_headers: Mapped[dict] = mapped_column(JSON, default=dict)
    resp_body: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


# =====================================================================
#  طابور التوليد (Outline-first + Lazy fill)
# =====================================================================
class GenerationJob(Base):
    """مهمة توليد واحدة: مخطط لغة، أو درس كامل (Lazy)، أو إثراء أطلس."""

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="lesson")  # outline|lesson|atlas
    language: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    course_slug: Mapped[Optional[str]] = mapped_column(String(80))
    lesson_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[Optional[str]] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    dedup_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


# =====================================================================
#  استهلاك الذكاء الاصطناعي (طبقة المزوّدين المجانيين)
# =====================================================================
class AIUsage(Base):
    """عدّاد استهلاك يومي لكل مزوّد — يمنع تجاوز الحصص المجانية."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    day: Mapped[dt.date] = mapped_column(Date, index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_ai_usage_day"),)


# =====================================================================
#  سجل تنفيذ الكود + الإشعارات (ميزات متقدمة)
# =====================================================================
class CodeExecution(Base):
    """سجل تنفيذ الكود — لمقارنة الأداء والأخطاء الشائعة."""

    __tablename__ = "code_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    lesson_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL"), index=True
    )
    code_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("code_samples.id", ondelete="SET NULL"), index=True
    )
    language: Mapped[str] = mapped_column(String(50), default="python")
    code: Mapped[str] = mapped_column(Text, default="")
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    memory_mb: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Notification(Base):
    """الإشعارات الذكية."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewSchedule(Base):
    """جدولة المراجعة المتباعدة (Spaced Repetition - SM-2)."""

    __tablename__ = "review_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    ease_factor: Mapped[float] = mapped_column(default=2.5)
    interval: Mapped[int] = mapped_column(default=1)
    repetition: Mapped[int] = mapped_column(default=0)
    next_review: Mapped[dt.date] = mapped_column(Date, index=True)
    last_quality: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_review_schedule"),)


class LessonRating(Base):
    """تقييم المستخدم للدرس (1-5)."""

    __tablename__ = "lesson_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer, default=5)
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_lesson_rating_user"),)


class LessonTimeLog(Base):
    """سجل الوقت المستغرق في كل درس."""

    __tablename__ = "lesson_time_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CodeFavorite(Base):
    """أكواد المفضلة للمستخدم."""

    __tablename__ = "code_favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("code_samples.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("user_id", "code_id", name="uq_code_favorite"),)


class CodeShare(Base):
    """مشاركة مقتطف كود برابط."""

    __tablename__ = "code_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("code_samples.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="")
    share_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ContentReport(Base):
    """بلاغ عن محتوى غير مناسب."""

    __tablename__ = "content_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(30))
    content_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
