# -*- coding: utf-8 -*-
"""اختبار خريطة المنهج."""
from pipeline.taxonomy import SECURITY_COURSES, iter_lessons, lesson_slug


def test_lessons_generated_for_all_courses():
    plans = iter_lessons()
    slugs = {p.course_slug for p in plans}
    assert slugs == {c["slug"] for c in SECURITY_COURSES}


def test_each_course_has_24_lessons():
    for course in SECURITY_COURSES:
        plans = iter_lessons([course["slug"]])
        assert len(plans) == 24


def test_lesson_slug_is_unique_per_course():
    plans = iter_lessons()
    keys = [(p.course_slug, lesson_slug(p)) for p in plans]
    assert len(keys) == len(set(keys))


def test_lesson_index_sequential():
    plans = iter_lessons(["python-security"])
    assert [p.lesson_index for p in plans] == list(range(1, 25))
