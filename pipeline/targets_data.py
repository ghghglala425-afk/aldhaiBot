# -*- coding: utf-8 -*-
"""كتالوج بيئات الهدف (Targets) — حاويات مفتوحة المصدر للتدرّب على ثغرات حقيقية.

الصور المدرجة مصادرها حرة/مفتوحة (MIT / GPL) ويمكن تشغيلها محليًا بلا شبكة خارجية.
كل بيئة تحتوي مهامًا موجّهة (Tasks) بإجابات قابلة للتحقق ونقاط.
"""
from __future__ import annotations

TARGETS: list[dict] = [
    {
        "slug": "juice-shop",
        "title": "OWASP Juice Shop",
        "icon": "🧃",
        "image": "bkimminich/juice-shop",
        "target_port": 3000,
        "runtime_port": 3041,
        "path": "/",
        "difficulty": "intermediate",
        "license": "MIT",
        "description": (
            "تطبيق ويب حديث مليء بالثغرات (حقن SQL، XSS، كسر المصادقة). "
            "بيئة آمنة للتدرّب على اختبار اختراق تطبيقات الويب."
        ),
        "tasks": [
            {"order": 1, "title": "لوحة النتائج", "prompt": "افتح صفحة تتبّع التقدّم (Score Board). ما اسم الإطار الواجهي المستخدم؟",
             "answer": "angular", "points": 20},
            {"order": 2, "title": "مسار الدخول", "prompt": "ما مسار صفحة تسجيل الدخول داخل التطبيق؟",
             "answer": "#/login", "points": 20},
            {"order": 3, "title": "حقن في البحث", "prompt": "حقل البحث مصاب بنوع شائع من الحقن. ما اسمه المختصر؟",
             "answer": "sqli", "points": 25},
            {"order": 4, "title": "المنفذ", "prompt": "على أي منفذ يخدم التطبيق افتراضيًا؟",
             "answer": "3000", "points": 15},
            {"order": 5, "title": "تشفير كلمات المرور", "prompt": "ما خوارزمية تجزئة كلمات المرور المستخدمة داخليًا؟",
             "answer": "bcrypt", "points": 25},
        ],
    },
    {
        "slug": "dvwa",
        "title": "DVWA — تطبيق ويب مصاب",
        "icon": "🩹",
        "image": "vulnerables/web-dvwa",
        "target_port": 80,
        "runtime_port": 8041,
        "path": "/",
        "difficulty": "beginner",
        "license": "GPL",
        "description": (
            "Damn Vulnerable Web Application: تطبيق PHP متعمّد الثغرات لتدريس "
            "الأمن على مستويات أمان متعددة (low/medium/high/impossible)."
        ),
        "tasks": [
            {"order": 1, "title": "بيانات الدخول", "prompt": "ما بيانات الدخول الافتراضية (بصيغة مستخدم:كلمةمرور)؟",
             "answer": "admin:password", "points": 20},
            {"order": 2, "title": "تفعيل الثغرات", "prompt": "أي مستوى أمان يجب ضبطه لتظهر الثغرات بوضوح؟",
             "answer": "low", "points": 20},
            {"order": 3, "title": "أول ثغرة", "prompt": "ما اسم صفحة ثغرة حقن قواعد البيانات؟",
             "answer": "sql injection", "points": 25},
            {"order": 4, "title": "XSS", "prompt": "ما اسم ثغرة تنفيذ السكربت في المتصفح (نوع منعكس)؟",
             "answer": "xss reflected", "points": 20},
            {"order": 5, "title": "قراءة الكود", "prompt": "ماذا يفعل زر View Source؟",
             "answer": "يعرض الكود المصدري", "points": 15},
        ],
    },
]
