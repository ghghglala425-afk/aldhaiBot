# -*- coding: utf-8 -*-
"""مخططات المحتوى المولَّد — تحقق صارم قبل أي حفظ."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AnatomyLine(BaseModel):
    """سطر من تشريح الكود."""

    line: int = 0
    code: str = ""
    explain: str = Field(min_length=2)


class CodeUsage(BaseModel):
    """استخدام واحد من استخدامات الكود/الدالة."""

    name: str = Field(min_length=2)
    signature: str = ""
    description: str = Field(min_length=3)
    example: str = Field(min_length=1)
    output: str = ""


class ParamInfo(BaseModel):
    name: str = Field(min_length=1)
    type: str = ""
    description: str = ""
    default: str = ""
    required: bool = False


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


class GeneratedOption(BaseModel):
    text: str = Field(min_length=1)
    correct: bool = False


class GeneratedQuestion(BaseModel):
    text: str = Field(min_length=5)
    kind: str = "single"
    options: list[GeneratedOption] = Field(min_length=2)
    explanation: str = ""

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

    @field_validator("difficulty")
    @classmethod
    def _diff(cls, v: str) -> str:
        if v not in {"beginner", "intermediate", "advanced"}:
            raise ValueError("difficulty غير صالح")
        return v
