# -*- coding: utf-8 -*-
"""إصلاح تلقائي لأخطاء الترجمة الشائعة في الأكواد المولّدة.

النماذج تكتب غالباً كودا صحيحا منطقيا لكنه لا يُترجم بسبب سطر `#include`
ناقص أو اسم كلاس Java لا يطابق اسم ملف Judge0. نضيف هذه السطور بدل رفض
الدرس كله. الإصلاحات محافظة: لا تغيّر منطق الكود.
"""
from __future__ import annotations

import re

from pipeline.sandbox_runner import clean_code


def _has_include(code: str, name: str) -> bool:
    pattern = rf"#\s*include\s*[<\"]([^>\"]*/)?{re.escape(name)}[>\"]"
    return re.search(pattern, code) is not None


def _insert_after_includes(code: str, line: str) -> str:
    lines = code.splitlines()
    last = -1
    for i, text in enumerate(lines):
        if text.lstrip().startswith("#include"):
            last = i
    if last >= 0:
        lines.insert(last + 1, line)
        return "\n".join(lines)
    return line + "\n" + code


def _strip_embedded_fences(code: str) -> str:
    """يزيل أسوار Markdown في منتصف الكود (تظهر عند نسخ مثال مشروح)."""
    return "\n".join(
        line for line in code.splitlines() if not line.strip().startswith("```")
    )


def repair_code(language: str, code: str) -> str:
    """يعيد كودا نظيفا بترويسات لازمة للترجمة حيث أمكن."""
    language = (language or "").strip().lower()
    text = _strip_embedded_fences(clean_code(code))

    if language in {"c", "cpp"}:
        includes: list[str] = []
        if language == "cpp":
            if re.search(r"\b(cout|cin|cerr|endl)\b", text) and not _has_include(
                text, "iostream"
            ):
                includes.append("#include <iostream>")
            for header, token in (
                ("string", "std::string"),
                ("vector", "std::vector"),
                ("map", "std::map"),
                ("unordered_map", "std::unordered_map"),
                ("set", "std::set"),
                ("algorithm", "std::sort"),
            ):
                if token in text and not _has_include(text, header):
                    includes.append(f"#include <{header}>")
        if re.search(
            r"\b(printf|scanf|puts|gets|sprintf|snprintf|fprintf)\s*\(", text
        ) and not (_has_include(text, "stdio.h") or _has_include(text, "cstdio")):
            includes.append("#include <stdio.h>" if language == "c" else "#include <cstdio>")

        if includes:
            unique = list(dict.fromkeys(includes))
            text = "\n".join(unique) + "\n" + text

        if language == "cpp":
            unqualified = re.search(r"(?<!std::)\b(cout|cin|cerr|endl)\b", text)
            if (
                unqualified
                and "using namespace std;" not in text
                and not re.search(r"\busing\s+std::", text)
            ):
                text = _insert_after_includes(text, "using namespace std;")

    elif language == "java":
        # Judge0 يترجم الملف باسم Main.java: أي public class آخر يفشل.
        match = re.search(r"public\s+(?:final\s+)?class\s+([A-Za-z_]\w*)", text)
        if match and match.group(1) != "Main":
            text = text[: match.start(1)] + "Main" + text[match.end(1) :]

    return text.strip()
