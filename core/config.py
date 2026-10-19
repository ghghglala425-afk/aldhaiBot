# -*- coding: utf-8 -*-
"""إعدادات المشروع — تُقرأ من .env مع تحقق صارم عند الإقلاع."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    BOT_TOKEN: str = ""
    BOT_MODE: str = "polling"
    WEBHOOK_URL: str = ""
    WEBHOOK_PATH: str = "webhook"
    WEBHOOK_PORT: int = 8443
    WEBHOOK_SECRET: str = ""
    ADMIN_IDS: str = ""

    # AI (متوافق مع OpenAI؛ يعمل مع LM Studio/Ollama محليا)
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    # موديل أسرع/أرخص اختياري لتوليد المخططات (اتركه فارغا لاستخدام AI_MODEL)
    AI_MODEL_FAST: str = ""
    AI_TIMEOUT: int = 120
    AI_MAX_TOKENS: int = 4096
    # auto | json_object | json_schema | none  — «auto» يجرّب الأنسب ثم يتراجع تدريجيا
    AI_JSON_MODE: str = "auto"
    AI_MAX_RETRIES: int = 3

    # ===== طبقة المزوّدين المجانيين (تسبق AI_BASE_URL عند تفعيل AI_FREE_MODE) =====
    # ترتيب المحاولة (مفصول بفاصلة): gemini,groq,openrouter
    AI_PROVIDER_ORDER: str = "gemini,groq,openrouter"
    AI_FREE_MODE: bool = False
    # ميزانية يومية إجمالية بالتوكنات (0 = بلا سقف)
    AI_DAILY_TOKEN_BUDGET: int = 250_000
    # حدود الطبقة المجانية (عدّلها عند تغيّر سياسات المزوّد)
    GEMINI_API_KEY: str = ""
    GEMINI_API_KEY_2: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_RPM: int = 10
    GEMINI_RPD: int = 250
    GEMINI_TPD: int = 250_000
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_RPM: int = 30
    GROQ_RPD: int = 1_000
    GROQ_TPD: int = 200_000
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    OPENROUTER_RPM: int = 20
    OPENROUTER_RPD: int = 50
    OPENROUTER_TPD: int = 0

    # DB / Cache
    DATABASE_URL: str = "postgresql+asyncpg://cyber:cyber@db:5432/cyberbot"
    REDIS_URL: str = "redis://cache:6379/0"

    # Security
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_TTL_MIN: int = 10080
    JWT_ALGORITHM: str = "HS256"

    # App
    ENV: str = "dev"
    LOG_LEVEL: str = "INFO"
    # مجلد السجلات الدوّارة (فارغ = stdout فقط)
    LOG_DIR: str = "data/logs"
    MINIAPP_URL: str = ""
    # نطاقات مسموح لأدوات اختبار الويب (Repeater/Fuzzer) — فارغ = localhost فقط
    PROXY_ALLOWED_HOSTS: str = "localhost,127.0.0.1"
    PROXY_TIMEOUT: int = 20

    # Content generation / verification
    GEN_MIN_CODES: int = 12
    GEN_MIN_QUESTIONS: int = 8
    GEN_MIN_USAGES: int = 8
    GEN_ENRICH_ATLAS: bool = True
    GEN_ATLAS_BATCH: int = 5
    GEN_MAX_REPAIRS: int = 3
    GEN_CONCURRENCY: int = 2
    VERIFY_EXEC: bool = True
    # تنفيذ الأكواد محليا عند غياب Docker (معطّل افتراضيا — بلا عزل). الأسلم: VERIFY_EXEC=0.
    SANDBOX_LOCAL: bool = False
    VERIFY_CODE_CONCURRENCY: int = 4
    SANDBOX_MEM_MB: int = 256
    SANDBOX_CPUS: str = "0.5"
    SANDBOX_TIMEOUT: int = 10
    AUTO_PUBLISH: bool = False

    # ===== التوسّع العالمي: مخطط كل لغة = مراحل × دروس =====
    GEN_STAGES: int = 10
    GEN_LESSONS_PER_STAGE: int = 100
    GEN_OUTLINE_ENABLED: bool = True
    # توليد تلقائي عند فتح درس مخطط (Lazy fill)
    GEN_LAZY_ON_OPEN: bool = True
    # تسخين أول N درس لكل لغة عند بناء المخطط
    GEN_WARM_LESSONS: int = 20
    # عامل الخلفية داخل عملية البوت
    GEN_WORKER_CONCURRENCY: int = 4
    GEN_QUEUE_POLL: int = 5
    GEN_JOB_MAX_ATTEMPTS: int = 3
    GEN_LESSON_TIMEOUT: int = 1800
    # سقف مهام الطابور (queued+running). 0 = بلا سقف. يحمي الحصة المجانية من الإغراق.
    GEN_QUEUE_MAX: int = 100

    # بيئات الهدف: روابط خارجية بديلة عن الحاويات المحلية. صيغة: slug=url,slug=url
    TARGET_EXTERNAL_URLS: str = ""

    @field_validator("BOT_MODE")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        v = (v or "polling").lower()
        if v not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE يجب أن يكون polling أو webhook")
        return v

    @field_validator("AI_JSON_MODE")
    @classmethod
    def _check_json_mode(cls, v: str) -> str:
        v = (v or "auto").lower()
        if v not in {"auto", "json_object", "json_schema", "none"}:
            raise ValueError("AI_JSON_MODE يجب أن يكون auto|json_object|json_schema|none")
        return v

    @property
    def ai_json_modes(self) -> List[str]:
        """ترتيب أوضاع JSON المطلوب تجربتها (يتراجع تدريجيا حتى 'بلا قيد')."""
        mode = self.AI_JSON_MODE
        if mode == "json_object":
            return ["json_object", "none"]
        if mode == "json_schema":
            return ["json_schema", "none"]
        if mode == "none":
            return ["none"]
        return ["json_object", "json_schema", "none"]

    @property
    def outline_model(self) -> str:
        """موديل توليد المخطط (أسرع إن حُدِّد AI_MODEL_FAST)."""
        return self.AI_MODEL_FAST or self.AI_MODEL

    @property
    def free_providers(self) -> List[str]:
        """أسماء المزوّدين المجانيين المضبوطين بالترتيب المطلوب."""
        keys = {
            "gemini": bool(self.GEMINI_API_KEY or self.GEMINI_API_KEY_2),
            "groq": bool(self.GROQ_API_KEY),
            "openrouter": bool(self.OPENROUTER_API_KEY),
        }
        order = [p.strip().lower() for p in (self.AI_PROVIDER_ORDER or "").split(",") if p.strip()]
        return [p for p in order if keys.get(p)]

    @property
    def ai_configured(self) -> bool:
        """هل يوجد أي مسار AI صالح (مزوّد مجاني أو نقطة نهاية OpenAI-متوافقة)؟"""
        if self.AI_FREE_MODE and self.free_providers:
            return True
        return bool(self.AI_API_KEY)

    @property
    def ai_mode(self) -> str:
        """free = طبقة المزوّدين | direct = AI_BASE_URL | off = معطّل."""
        if self.AI_FREE_MODE and self.free_providers:
            return "free"
        if self.AI_API_KEY:
            return "direct"
        return "off"

    @property
    def lessons_per_language(self) -> int:
        return max(1, self.GEN_STAGES) * max(1, self.GEN_LESSONS_PER_STAGE)

    @property
    def admin_ids(self) -> List[int]:
        out: List[int] = []
        for part in (self.ADMIN_IDS or "").split(","):
            part = part.strip()
            if part.isdigit():
                out.append(int(part))
        return out

    @property
    def allowed_proxy_hosts(self) -> List[str]:
        return [h.strip().lower() for h in (self.PROXY_ALLOWED_HOSTS or "").split(",") if h.strip()]

    @property
    def external_target_urls(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in (self.TARGET_EXTERNAL_URLS or "").split(","):
            if "=" not in part:
                continue
            slug, url = part.split("=", 1)
            slug, url = slug.strip().lower(), url.strip()
            if slug and url:
                out[slug] = url
        return out

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() in {"prod", "production"}

    def check_required(self) -> list[str]:
        """تُعيد قائمة الأخطاء المانعة للإقلاع (فارغة = يمكن التشغيل)."""
        errors: list[str] = []
        if not self.BOT_TOKEN or ":" not in self.BOT_TOKEN:
            errors.append("BOT_TOKEN غير مضبوط أو غير صالح (الصيغة: 123456:ABC...)")
        if self.is_prod and self.SECRET_KEY in {"", "change-me", "change-me-with-a-long-random-string"}:
            errors.append("SECRET_KEY ضعيف — اضبطه في بيئة الإنتاج")
        if self.is_prod and self.BOT_MODE == "webhook" and not self.WEBHOOK_URL:
            errors.append("WEBHOOK_URL مطلوب عند BOT_MODE=webhook")
        return errors

    def check_warnings(self) -> list[str]:
        """تحذيرات لا تمنع الإقلاع (مثل غياب مزوّد AI: التصفّح يبقى يعمل)."""
        warnings: list[str] = []
        if not self.ai_configured:
            warnings.append(
                "لا يوجد مزوّد AI — التوليد والمساعد الذكي معطّلان. "
                "فعّل AI_FREE_MODE=1 مع GEMINI_API_KEY/GROQ_API_KEY، "
                "أو اضبط AI_API_KEY لنقطة نهاية OpenAI-متوافقة."
            )
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
