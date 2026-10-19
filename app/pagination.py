# -*- coding: utf-8 -*-
"""ترقيم الصفحات الموحّد (قوائم الدروس/الأكواد/اللغات/البحث)."""
from __future__ import annotations

from telegram import InlineKeyboardButton

DEFAULT_PER_PAGE = 8


def total_pages(count: int, per_page: int = DEFAULT_PER_PAGE) -> int:
    per_page = max(1, per_page)
    return max(1, (count + per_page - 1) // per_page)


def clamp_page(page: int, pages: int) -> int:
    return max(0, min(page, max(0, pages - 1)))


def slice_page(items: list, page: int, per_page: int = DEFAULT_PER_PAGE) -> list:
    per_page = max(1, per_page)
    page = clamp_page(page, total_pages(len(items), per_page))
    start = page * per_page
    return items[start : start + per_page]


def nav_row(
    prefix: str,
    page: int,
    pages: int,
    *,
    extra: list[InlineKeyboardButton] | None = None,
    home: InlineKeyboardButton | None = None,
) -> list[InlineKeyboardButton]:
    """صف تنقّل: السابق · مؤشّر الصفحة · التالي (يُخفى إن لا داعي)."""
    row: list[InlineKeyboardButton] = []
    if pages > 1:
        if page > 0:
            row.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}:{page - 1}"))
        row.append(InlineKeyboardButton(f"• {page + 1}/{pages} •", callback_data="noop"))
        if page < pages - 1:
            row.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}:{page + 1}"))
    if extra:
        row.extend(extra)
    if home:
        row.append(home)
    return row
