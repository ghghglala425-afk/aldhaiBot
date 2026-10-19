# -*- coding: utf-8 -*-
"""بذور البيانات: سجلّ اللغات + كورس تجريبي يعمل فورا.

التشغيل:
    python -m pipeline.seed          (محليا بعد ضبط DATABASE_URL)
    docker compose exec api python -m pipeline.seed
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from core.db import SessionLocal, init_db
from core.logging import get_logger, setup_logging
from core.models import (
    Badge,
    CodeSample,
    Course,
    Hint,
    Lab,
    Language,
    Lesson,
    Option,
    Question,
    Quiz,
    Stage,
)
from pipeline.languages_data import LANGUAGES

setup_logging()
log = get_logger("pipeline.seed")


async def seed_languages() -> int:
    added = 0
    async with SessionLocal() as session:
        for item in LANGUAGES:
            exists = await session.execute(
                select(Language).where(Language.slug == item["slug"])
            )
            if exists.scalar_one_or_none():
                continue
            session.add(
                Language(
                    slug=item["slug"],
                    name=item["name"],
                    name_ar=item.get("name_ar"),
                    paradigm=item.get("paradigm"),
                    difficulty=item.get("difficulty", "medium"),
                    is_security_relevant=item.get("security", False),
                    is_esoteric=item.get("esoteric", False),
                    docker_image=item.get("docker_image"),
                )
            )
            added += 1
        await session.commit()
    log.info("أُضيفت %s لغة جديدة.", added)
    return added


DEMO_LESSON_CODES = [
    ("مرحبا بالعالم", "print('Hello, Security!')", "طباعة نص بسيط — أول برنامج بلغة بايثون."),
    ("المتغيرات", "port = 443\nproto = 'https'\nprint(proto, port)", "تعريف متغيرات وطباعتها."),
    ("الشروط", "status = 200\nprint('OK' if status == 200 else 'FAIL')", "تعبير شرطي مختصر."),
    ("الحلقات", "for p in [22, 80, 443]:\n    print('scanning', p)", "المرور على منافذ شائعة."),
    ("الدوال", "def banner(name):\n    return f'== {name} =='\nprint(banner('Nmap'))", "تعريف دالة وإرجاع قيمة."),
    ("القوائم", "ports = [21, 22, 80]\nports.append(443)\nprint(ports)", "قائمة وتعديلها."),
    ("القواميس", "svc = {'80': 'http', '443': 'https'}\nprint(svc['443'])", "قاموس مفاتيح وقيم."),
    ("معالجة الأخطاء", "try:\n    int('x')\nexcept ValueError:\n    print('input غير صالح')", "التقاط الاستثناءات."),
    ("الملفات", "open('log.txt', 'w').write('packet intercepted')\nprint(open('log.txt').read())", "كتابة وقراءة ملف."),
    ("التعبيرات النمطية", "import re\nprint(re.findall(r'\\d+', 'IP 192 and 10'))", "استخراج الأرقام."),
    ("تجزئة كلمة المرور", "import hashlib\nprint(hashlib.sha256(b'pass').hexdigest()[:16])", "تجزئة SHA-256."),
    ("فك الترميز Base64", "import base64\nprint(base64.b64decode('c2VjdXJl').decode())", "فك ترميز Base64."),
    ("طلبات الشبكة", "# requests.get('https://example.com')\nprint('GET / HTTP/1.1')", "بناء طلب HTTP يدويًا."),
    ("اكتشاف المنافذ", "for p in range(20, 24):\n    print(p, 'open' if p == 22 else 'closed')", "محاكاة فحص منافذ."),
    ("توليد كلمة مرور", "import secrets\nprint(secrets.token_hex(8))", "توليد قيمة عشوائية آمنة."),
]

# موسوعة مبسّطة لبعض أمثلة العرض (تُشرح في الواجهة كتشريح + استخدامات)
DEMO_ATLAS: dict[str, dict] = {
    "مرحبا بالعالم": {
        "anatomy": [
            {"line": 1, "code": "print('Hello, Security!')", "explain": "نداء الدالة print مع نص ثابت بين علامتي تنصيص."},
        ],
        "usages": [
            {"name": "طباعة نص بسيط", "signature": "print(object)", "description": "طبع قيمة واحدة.", "example": "print('hi')", "output": "hi"},
            {"name": "طباعة عدة وسائط", "signature": "print(a, b, c)", "description": "تفصل بينها مسافة تلقائيا.", "example": "print('a', 1)", "output": "a 1"},
            {"name": "فاصل مخصص", "signature": "print(*o, sep='|')", "description": "تحديد فاصل بين الوسائط.", "example": "print('a','b',sep='|')", "output": "a|b"},
            {"name": "إنهاء مخصص", "signature": "print(o, end='')", "description": "تغيير نهاية السطر (بدل \\n).", "example": "print('a',end=''); print('b')", "output": "ab"},
            {"name": "الكتابة إلى ملف", "signature": "print(o, file=f)", "description": "توجيه الخرج إلى ملف مفتوح.", "example": "import sys; print('x', file=sys.stderr)", "output": "(إلى stderr)"},
            {"name": "تفريغ البافر", "signature": "print(o, flush=True)", "description": "إجبار الإفراغ الفوري للخرج.", "example": "print('done', flush=True)", "output": "done"},
            {"name": "تنسيق f-string", "signature": "print(f'{v}')", "description": "دمج القيم داخل النص.", "example": "x=3; print(f'x={x}')", "output": "x=3"},
            {"name": "طباعة أنواع مختلفة", "signature": "print(obj)", "description": "يطبع أي كائن عبر str().", "example": "print([1,2], {'a':1})", "output": "[1, 2] {'a': 1}"},
        ],
        "parameters": [
            {"name": "*objects", "type": "Any", "description": "القيم المطلوب طبعها.", "default": "", "required": False},
            {"name": "sep", "type": "str", "description": "الفاصل بين القيم.", "default": "' '", "required": False},
            {"name": "end", "type": "str", "description": "ما يُطبع بعد آخر قيمة.", "default": "'\\n'", "required": False},
            {"name": "file", "type": "TextIO", "description": "وجهة الخرج.", "default": "sys.stdout", "required": False},
            {"name": "flush", "type": "bool", "description": "إفراغ البافر فورا.", "default": "False", "required": False},
        ],
        "returns": "لا تُرجع شيئا (None).",
        "gotchas": ["نسيان علامات التنصيص يجعل النص متغيرا.", "print تُرجع None فلا تُستخدم في التعيين."],
        "security_notes": ["لا تطبع أسرارا/توكنات إلى السجلات (log injection).", "تطهير مدخلات المستخدم قبل طباعتها لتجنّب تلويث الطرفية."],
        "related": ["input", "sys.stdout", "logging"],
        "tags": ["أساسيات", "إدخال-وإخراج"],
    },
    "المتغيرات": {
        "anatomy": [
            {"line": 1, "code": "port = 443", "explain": "تعريف متغير port بقيمة صحيحة."},
            {"line": 2, "code": "proto = 'https'", "explain": "تعريف متغير نصي proto."},
            {"line": 3, "code": "print(proto, port)", "explain": "طباعة قيمتَي المتغيرين."},
        ],
        "usages": [
            {"name": "تعيين قيمة", "signature": "x = value", "description": "إنشاء/تحديث متغير.", "example": "x = 5", "output": "5"},
            {"name": "تعيين متعدد", "signature": "a, b = 1, 2", "description": "فك حزمة إلى متغيرات.", "example": "a,b=1,2; print(a,b)", "output": "1 2"},
            {"name": "تبديل القيم", "signature": "a, b = b, a", "description": "تبديل دون متغير مؤقت.", "example": "a,b=1,2; a,b=b,a; print(a)", "output": "2"},
            {"name": "تعيين متسلسل", "signature": "a = b = 0", "description": "نفس القيمة لعدة متغيرات.", "example": "a=b=0; print(a,b)", "output": "0 0"},
            {"name": "التعيين المركّب", "signature": "x += 1", "description": "تحديث بالعملية نفسها.", "example": "x=1; x+=2; print(x)", "output": "3"},
            {"name": "متغير نصي", "signature": "s = 'txt'", "description": "قيمة نصية", "example": "s='hi'; print(len(s))", "output": "2"},
            {"name": "حذف متغير", "signature": "del x", "description": "إزالة الاسم من النطاق.", "example": "x=1; del x; print('ok')", "output": "ok"},
            {"name": "التحقق من النوع", "signature": "type(x)", "description": "نوع القيمة المخزّنة.", "example": "print(type(3))", "output": "<class 'int'>"},
        ],
        "parameters": [],
        "returns": "المتغير ليس دالة؛ يحمل قيمة من نوع ما.",
        "gotchas": ["استخدام متغير قبل تعريفه يرفع NameError.", "النصوص الرقمية الملتبسة قد تُفسَّر خطأ."],
        "security_notes": ["لا تخزّن كلمات المرور كنص صريح؛ استخدم hashlib/secrets.", "تحقّق من نوع المدخلات لتجنّب أخطاء الحقن."],
        "related": ["int", "str", "type", "isinstance"],
        "tags": ["أساسيات", "أنواع-البيانات"],
    },
}



async def seed_demo_course() -> int:
    async with SessionLocal() as session:
        exists = await session.execute(select(Course).where(Course.slug == "python-security"))
        if exists.scalar_one_or_none():
            log.info("الكورس التجريبي موجود مسبقا.")
            return 0

        course = Course(
            slug="python-security",
            title="بايثون للأمن السيبراني",
            title_en="Python for Cybersecurity",
            description="من الصفر إلى أدوات أمنية حقيقية بلغة بايثون: أساسيات، شبكات، تشفير، وأتمتة.",
            track="cybersecurity",
            difficulty="beginner",
            icon="🐍",
            order_index=1,
            is_published=True,
        )
        session.add(course)
        await session.flush()

        stage = Stage(
            course_id=course.id,
            slug="basics",
            title="المرحلة الأولى: الأساسيات",
            order_index=1,
            is_published=True,
        )
        session.add(stage)
        await session.flush()

        lesson = Lesson(
            stage_id=stage.id,
            slug="hello-security",
            title="مقدمة: أول خطوة في الأمن",
            summary="تعرّف على بايثون وأدواته الأساسية عبر أمثلة عملية وموسوعة أكواد مشروحة.",
            objectives=["تشغيل بايثون", "المتغيرات والدوال", "تجزئة وترميز", "محاكاة فحص منافذ"],
            content_md="## نظرة عامة\nفي هذا الدرس نبنى الأساس العملي لأدوات الأمن بلغة بايثون.",
            language_slug="python",
            difficulty="beginner",
            est_minutes=25,
            order_index=1,
            xp_reward=50,
            min_score=70,
            status="published",
            is_verified=True,
        )
        session.add(lesson)
        await session.flush()

        for i, (title, code, expl) in enumerate(DEMO_LESSON_CODES, start=1):
            atlas = DEMO_ATLAS.get(title, {})
            session.add(
                CodeSample(
                    lesson_id=lesson.id,
                    language="python",
                    title=title,
                    code=code,
                    explanation=expl,
                    anatomy=atlas.get("anatomy", []),
                    usages=atlas.get("usages", []),
                    parameters=atlas.get("parameters", []),
                    returns=atlas.get("returns", ""),
                    gotchas=atlas.get("gotchas", []),
                    security_notes=atlas.get("security_notes", []),
                    related=atlas.get("related", []),
                    tags=atlas.get("tags", []),
                    order_index=i,
                    is_verified=True,
                )
            )

        quiz = Quiz(lesson_id=lesson.id, pass_score=70, shuffle=True)
        session.add(quiz)
        await session.flush()

        q1 = Question(quiz_id=quiz.id, text="ما الأمر الذي يطبع نصا في بايثون؟", kind="single", order_index=1)
        session.add(q1)
        await session.flush()
        for idx, (txt, corr) in enumerate(
            [("print()", True), ("echo", False), ("show", False), ("log", False)]
        ):
            session.add(Option(question_id=q1.id, text=txt, is_correct=corr, order_index=idx))

        q2 = Question(quiz_id=quiz.id, text="أي مكتبة تُستخدم لتجزئة SHA-256؟", kind="single", order_index=2)
        session.add(q2)
        await session.flush()
        for idx, (txt, corr) in enumerate(
            [("hashlib", True), ("crypto2", False), ("hash256", False), ("secure", False)]
        ):
            session.add(Option(question_id=q2.id, text=txt, is_correct=corr, order_index=idx))

        await session.commit()
        log.info("تم إنشاء الكورس التجريبي بالدرس والاختبار.")
        return 1


async def seed_badges() -> int:
    from core.gamification import BADGE_DEFS

    added = 0
    async with SessionLocal() as session:
        for slug, title, desc, icon in BADGE_DEFS:
            exists = await session.scalar(select(Badge).where(Badge.slug == slug))
            if exists:
                continue
            session.add(Badge(slug=slug, title=title, description=desc, icon=icon))
            added += 1
        await session.commit()
    log.info("أُضيفت %s شارة.", added)
    return added


async def seed_labs() -> int:
    async with SessionLocal() as session:
        lesson = await session.scalar(select(Lesson).where(Lesson.slug == "hello-security"))
        if not lesson:
            return 0
        exists = await session.scalar(select(Lab).where(Lab.lesson_id == lesson.id))
        if exists:
            log.info("المختبر التجريبي موجود مسبقا.")
            return 0

        lab = Lab(
            lesson_id=lesson.id,
            title="اكتشف العلم المخفي",
            description="حلّل الكود التالي واستخرج العلم المضمّن بعد فك ترميز Base64.",
            kind="ctf",
            flags=["KHEET{b4s3_64_1s_n0t_3ncrypt10n}"],
            points=100,
        )
        session.add(lab)
        await session.flush()
        session.add(Hint(lab_id=lab.id, text="البيانات مشفّرة بترميز Base64 وليست تشفيرا.",
                        cost_xp=5, order_index=0))
        session.add(Hint(lab_id=lab.id, text="جرّب: echo 'S0hFRVQ...' | base64 -d",
                        cost_xp=15, order_index=1))
        await session.commit()
        log.info("أُنشئ مختبر تجريبي.")
        return 1


async def seed_target_labs() -> int:
    from core.config import settings
    from pipeline.targets_data import TARGETS

    ext = settings.external_target_urls
    added = 0
    async with SessionLocal() as session:
        lesson = await session.scalar(select(Lesson).where(Lesson.slug == "hello-security"))
        if not lesson:
            return 0
        for spec in TARGETS:
            exists = await session.scalar(
                select(Lab).where(Lab.lesson_id == lesson.id, Lab.title == spec["title"])
            )
            url = ext.get(spec["slug"])
            if exists:
                if url and not exists.external_url:
                    exists.external_url = url
                continue
            session.add(
                Lab(
                    lesson_id=lesson.id,
                    title=spec["title"],
                    description=spec["description"],
                    kind="target",
                    docker_image=spec["image"],
                    target_port=spec.get("target_port"),
                    target_path=spec.get("path"),
                    runtime_port=spec.get("runtime_port"),
                    external_url=url,
                    tasks=spec["tasks"],
                    points=sum(t.get("points", 0) for t in spec["tasks"]),
                )
            )
            added += 1
        await session.commit()
    log.info("أُضيفت %s بيئة هدف.", added)
    return added


async def seed_paths() -> int:
    from core.models import LearningPath

    PATHS = [
        {"slug": "web-hacking", "title": "مسار اختراق تطبيقات الويب",
         "description": "من أساسيات الويب إلى استغلال الثغرات: جافاسكربت، PHP، SQL والدفاع.",
         "icon": "🕸️", "order": 1,
         "course_slugs": ["javascript-security", "php-security", "sql-security"]},
        {"slug": "offensive-python", "title": "مسار بايثون الهجومي",
         "description": "أتمتة الأمن وكتابة الأدوات بلغة بايثون من الصفر.",
         "icon": "🐍", "order": 2, "course_slugs": ["python-security", "bash-security"]},
        {"slug": "memory-exploitation", "title": "مسار استغلال الذاكرة",
         "description": "لغة C، تجاوزات المخزن المؤقت، وبناء الشيل كود.",
         "icon": "⚙️", "order": 3, "course_slugs": ["c-security", "python-security"]},
    ]
    added = 0
    async with SessionLocal() as session:
        for spec in PATHS:
            exists = await session.scalar(select(LearningPath).where(LearningPath.slug == spec["slug"]))
            if exists:
                continue
            session.add(LearningPath(**spec))
            added += 1
        await session.commit()
    log.info("أُضيف %s مسار تعلّمي.", added)
    return added


async def main() -> None:
    await init_db()
    await seed_languages()
    await seed_demo_course()
    await seed_badges()
    await seed_labs()
    await seed_target_labs()
    await seed_paths()
    log.info("اكتملت البذور.")


if __name__ == "__main__":
    asyncio.run(main())
