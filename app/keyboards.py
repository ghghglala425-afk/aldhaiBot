# -*- coding: utf-8 -*-
"""أزرار ولوحات البوت."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from core.config import settings

MENU_COURSES = "📚 الكورسات"
MENU_LANGUAGES = "🌍 اللغات"
MENU_PATHS = "🛤️ المسارات"
MENU_DAILY = "🎯 الدرس اليومي"
MENU_SEARCH = "🔎 بحث"
MENU_TOOLS = "🕵️ الأدوات"
MENU_RUN = "▶️ تشغيل كود"
MENU_ASSISTANT = "🤖 المساعد"
MENU_RANK = "🏆 ترتيبي"
MENU_ACCOUNT = "👤 حسابي"

MENU_TEXTS = [
    MENU_COURSES,
    MENU_LANGUAGES,
    MENU_PATHS,
    MENU_DAILY,
    MENU_SEARCH,
    MENU_TOOLS,
    MENU_RUN,
    MENU_ASSISTANT,
    MENU_RANK,
    MENU_ACCOUNT,
]


def main_reply_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(MENU_COURSES), KeyboardButton(MENU_LANGUAGES)],
        [KeyboardButton(MENU_PATHS), KeyboardButton(MENU_DAILY)],
        [KeyboardButton(MENU_SEARCH), KeyboardButton(MENU_ASSISTANT)],
        [KeyboardButton(MENU_TOOLS), KeyboardButton(MENU_RUN)],
        [KeyboardButton(MENU_RANK), KeyboardButton(MENU_ACCOUNT)],
    ]
    if settings.MINIAPP_URL:
        rows.insert(
            0,
            [KeyboardButton("🚀 فتح التطبيق", web_app=WebAppInfo(url=settings.MINIAPP_URL))],
        )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def welcome_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🆕 تسجيل جديد", callback_data="auth:register"),
            InlineKeyboardButton("🔑 دخول", callback_data="auth:login"),
        ]
    ]
    if settings.MINIAPP_URL:
        rows.append(
            [InlineKeyboardButton("🚀 فتح التطبيق", web_app=WebAppInfo(url=settings.MINIAPP_URL))]
        )
    return InlineKeyboardMarkup(rows)


def courses_kb(courses: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{c['icon'] or '📘'} {c['title']}", callback_data=f"course:{c['id']}")]
        for c in courses
    ]
    return InlineKeyboardMarkup(rows)


def menu_with_app() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.MINIAPP_URL:
        rows.append(
            [InlineKeyboardButton("🚀 فتح التطبيق الكامل", web_app=WebAppInfo(url=settings.MINIAPP_URL))]
        )
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


def languages_kb(langs: list[dict], page: int = 0, pages: int = 1, per_page: int = 12) -> InlineKeyboardMarkup:
    from app.pagination import nav_row, slice_page

    rows: list[list[InlineKeyboardButton]] = []
    chunk = slice_page(langs, page, per_page)
    for i in range(0, len(chunk), 2):
        pair = chunk[i : i + 2]
        rows.append([
            InlineKeyboardButton(
                f"{l['icon']} {l['name_ar']}", callback_data=f"lang:{l['slug']}"
            )
            for l in pair
        ])
    rows.append(nav_row("langs", page, pages))
    return InlineKeyboardMarkup(rows)
