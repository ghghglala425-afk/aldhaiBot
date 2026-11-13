# -*- coding: utf-8 -*-
"""مخططات المحتوى المولَّد — تحقق صارم قبل أي حفظ.

النماذج هنا *متسامحة في الإدخال*: نماذج LLM تُخرج أحياناً خيارات كسلاسل
نصية أو بمفاتيح مختلفة (`is_correct` بدل `correct`)، أو تسمّي الكود `example`.
نقبل هذه الصيغ ونحوّلها، بدل إفشال الدرس كله بسبب اختلاف تسمية.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# مرادفات أسماء اللغات كما يكتبها النموذج أحياناً.
_LANGUAGE_ALIASES = {
    "c++": "cpp",
    "cplusplus": "cpp",
    "c plus plus": "cpp",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "c#": "csharp",
    "cs": "csharp",
    "csharp ": "csharp",
    "golang": "go",
    "py": "python",
    "python3": "python",
    "sh": "bash",
    "shell": "bash",
}

_KIND_ALIASES = {
    "single": "single",
    "single_choice": "single",
    "single-choice": "single",
    "one": "single",
    "choice": "single",
    "mcq": "single",
    "multiple_choice": "single",
    "text": "single",
    "multi": "multi",
    "multiple": "multi",
    "multi_select": "multi",
    "multiple_select": "multi",
    "multiple-choice": "multi",
    "checkbox": "multi",
    "checkboxes": "multi",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
        "correct",
        "right",
        "نعم",
        "صحيح",
        "صح",
    }


def _option_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or "").strip()
    return str(item or "").strip()


def _mark_correct(items: list, correct: Any) -> None:
    """يعلّم الإجابة الصحيحة في قائمة خيارات مبنية من مفاتيح السؤال.

    يقبل: رقم موضع (0-based أو 1-based)، حرفا (A/B/C/أ/ب/ج)، نص الخيار،
    أو قائمة من أي منها.
    """
    if correct is None or isinstance(correct, bool):
        return
    if isinstance(correct, (list, tuple, set)):
        for token in correct:
            _mark_correct(items, token)
        return
    if isinstance(correct, (int, float)):
        idx = int(correct)
        if not 0 <= idx < len(items) and 1 <= idx <= len(items):
            idx -= 1
        if 0 <= idx < len(items):
            item = items[idx]
            if isinstance(item, dict):
                item["correct"] = True
        return
    text = str(correct).strip()
    if not text:
        return
    if any(sep in text for sep in ",،/|;"):
        for token in text.replace("،", ",").replace("|", ",").replace(";", ",").split(","):
            _mark_correct(items, token.strip())
        return
    if text.isdigit():
        _mark_correct(items, int(text))
        return
    lowered = text.rstrip(".)").strip().lower()
    if len(lowered) == 1:
        letters = "abcd"
        arabic = "أبجد"
        if lowered in letters:
            _mark_correct(items, letters.index(lowered))
            return
        if lowered in arabic:
            _mark_correct(items, arabic.index(lowered))
            return
    for item in items:
        if _option_text(item).lower() == text.lower():
            if isinstance(item, dict):
                item["correct"] = True
            return


def _alias(data: dict, target: str, keys: tuple[str, ...]) -> str:
    """قيمة أول مفتاح بديل غير فارغ (مفيد لاختلاف تسمية النماذج)."""
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


class AnatomyLine(BaseModel):
    """سطر من تشريح الكود."""

    line: int = 0
    code: str = ""
    # لا نفرض حدا أدنى: سطر بلا شرح يُستبعد في طبقة الإثراء بدل إسقاط الكود كله.
    explain: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            return {"code": text, "explain": text}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not str(data.get("explain") or "").strip():
            data["explain"] = _alias(
                data,
                "explain",
                ("explanation", "desc", "description", "text", "note", "comment",
                 "details", "summary", "meaning", "purpose", "role",
                 "شرح", "الشرح", "تفسير", "توضيح", "المعنى", "الغرض"),
            )
        if not str(data.get("code") or "").strip():
            data["code"] = _alias(data, "code", ("snippet", "source", "content", "الكود"))
        if not data.get("line"):
            raw_line = _alias(data, "line", ("line_no", "line_number", "number", "رقم"))
            if raw_line.isdigit():
                data["line"] = int(raw_line)
        return data


class CodeUsage(BaseModel):
    """استخدام واحد من استخدامات الكود/الدالة."""

    name: str = ""
    signature: str = ""
    description: str = ""
    example: str = ""
    output: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value.strip(), "description": value.strip()}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not str(data.get("name") or "").strip():
            data["name"] = _alias(
                data, "name",
                ("title", "method", "function", "api", "usage", "الاسم", "الاستخدام"),
            )
        if not str(data.get("signature") or "").strip():
            data["signature"] = _alias(data, "signature", ("syntax", "form", "صيغة", "التوقيع"))
        if not str(data.get("description") or "").strip():
            data["description"] = _alias(
                data, "description", ("desc", "details", "explain", "explanation", "وصف", "الوصف")
            )
        if not str(data.get("example") or "").strip():
            data["example"] = _alias(
                data, "example", ("code", "snippet", "sample", "usage_example", "مثال")
            )
        if not str(data.get("output") or "").strip():
            data["output"] = _alias(
                data, "output", ("result", "returns", "expected_output", "المخرج", "النتيجة")
            )
        return data


class ParamInfo(BaseModel):
    name: str = ""
    type: str = ""
    description: str = ""
    default: str = ""
    required: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value.strip()}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not str(data.get("name") or "").strip():
            data["name"] = _alias(
                data, "name",
                ("param", "parameter", "arg", "argument", "key", "الاسم", "المعامل"),
            )
        if not str(data.get("type") or "").strip():
            data["type"] = _alias(data, "type", ("datatype", "data_type", "النوع"))
        if not str(data.get("description") or "").strip():
            data["description"] = _alias(
                data, "description", ("desc", "explain", "explanation", "وصف", "الوصف")
            )
        if "required" in data:
            data["required"] = _as_bool(data["required"])
        return data


class GeneratedCode(BaseModel):
    language: str
    title: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=3)
    explanation: str = Field(min_length=5)
    expected_output: str = ""
    # ==== موسوعة الأكواد ====
    anatomy: list[AnatomyLine] = Field(default_factory=list)
    usages: list[CodeUsage] = Field(default_factory=list)
    parameters: list[ParamInfo] = Field(default_factory=list)
    returns: str = ""
    gotchas: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        """يقبل أسماء بديلة للحقول الشائعة في مخرجات النماذج."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not data.get("language"):
            for key in ("lang", "programming_language", "language_name"):
                if data.get(key):
                    data["language"] = data[key]
                    break
        if not data.get("language"):
            data["language"] = ""
        if not data.get("code"):
            for key in ("example", "source", "snippet", "source_code", "content"):
                if isinstance(data.get(key), str) and data[key].strip():
                    data["code"] = data[key]
                    break
        if not str(data.get("title") or "").strip():
            data["title"] = "مثال عملي"
        if not str(data.get("explanation") or "").strip():
            data["explanation"] = "مثال يوضّح الفكرة عمليا."
        if "expected_output" not in data and "output" in data:
            data["expected_output"] = data.get("output")
        return data

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        key = (value or "").strip().lower()
        return _LANGUAGE_ALIASES.get(key, key or "python")


class GeneratedOption(BaseModel):
    text: str = Field(min_length=1)
    correct: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        """يقبل خياراً كنص مجرّد أو بمفاتيح بديلة."""
        if isinstance(value, str):
            return {"text": value, "correct": False}
        if isinstance(value, (int, float)):
            return {"text": str(value), "correct": False}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        for key in ("text", "option", "label", "value", "answer_text"):
            if isinstance(data.get(key), (str, int, float)) and str(data[key]).strip():
                data["text"] = str(data[key])
                break
        for key in ("correct", "is_correct", "isCorrect", "right", "valid", "answer"):
            if key in data and not isinstance(data[key], (list, tuple, dict)):
                data["correct"] = _as_bool(data[key])
                break
        return data


class GeneratedQuestion(BaseModel):
    text: str = Field(min_length=5)
    kind: str = "single"
    options: list[GeneratedOption] = Field(min_length=2)
    explanation: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        """يوحّد نص السؤال، نوعه، وصيغ الخيارات (قائمة/قاموس)."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not str(data.get("text") or "").strip():
            for key in ("question", "prompt", "q", "title"):
                if data.get(key):
                    data["text"] = data[key]
                    break
        kind = str(data.get("kind") or data.get("type") or "single").strip().lower()
        data["kind"] = _KIND_ALIASES.get(kind, kind)
        options = data.get("options")
        if isinstance(options, dict):
            correct = data.get("correct")
            for key in ("answer", "correct_answer", "answers", "correct_index"):
                if correct is None and data.get(key) is not None:
                    correct = data.get(key)
            keys: list[str] = []
            items: list[dict] = []
            for key, val in options.items():
                keys.append(str(key))
                if isinstance(val, dict):
                    item = dict(val)
                    item.setdefault("text", str(key))
                else:
                    item = {"text": str(val)}
                items.append(item)
            correct_keys: set[str] = set()
            if isinstance(correct, str):
                correct_keys = {
                    token.strip()
                    for token in correct.replace(",", " ").split()
                    if token.strip()
                }
            elif isinstance(correct, (list, tuple, set)):
                correct_keys = {str(token).strip() for token in correct}
            if correct_keys:
                for key, item in zip(keys, items):
                    item["correct"] = key in correct_keys or item.get("text") in correct_keys
            elif isinstance(correct, (int, float)) and not isinstance(correct, bool):
                idx = int(correct)
                if not 0 <= idx < len(items) and 1 <= idx <= len(items):
                    idx -= 1
                if 0 <= idx < len(items):
                    items[idx]["correct"] = True
            data["options"] = items
        elif isinstance(options, list):
            items = [
                {"text": option, "correct": False} if isinstance(option, str) else option
                for option in options
            ]
            correct = (
                data.get("correct")
                if data.get("correct") is not None
                else data.get("correct_index", data.get("answer_index", data.get("answer")))
            )
            if correct is None:
                correct = data.get("correct_answer")
            if correct is not None:
                _mark_correct(items, correct)
            data["options"] = items
        return data

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in {"single", "multi"}:
            raise ValueError("kind يجب أن يكون single أو multi")
        return v


class GeneratedLesson(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    summary: str = Field(min_length=10)
    objectives: list[str] = Field(min_length=2)
    content_md: str = Field(min_length=200)
    difficulty: str = "beginner"
    est_minutes: int = 25
    code_samples: list[GeneratedCode] = Field(min_length=1)
    quiz_questions: list[GeneratedQuestion] = Field(min_length=1)
    # ==== عناصر الحفظ والتركيز ====
    key_points: list[str] = Field(default_factory=list)
    memory_hook: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    further_reading: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        """يقبل أسماء بديلة للقوائم الرئيسية."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "quiz_questions" not in data and isinstance(data.get("questions"), list):
            data["quiz_questions"] = data["questions"]
        if "code_samples" not in data and isinstance(data.get("codes"), list):
            data["code_samples"] = data["codes"]
        return data

    @field_validator("difficulty")
    @classmethod
    def _diff(cls, v: str) -> str:
        if v not in {"beginner", "intermediate", "advanced"}:
            raise ValueError("difficulty غير صالح")
        return v
