# -*- coding: utf-8 -*-
"""سجلّ لغات البرمجة (نواة التغطية العالمية).

القائمة قابلة للتوسّع بلا حد — يُضاف أي لغـة عبر إضافة سطر.
الحقول: slug, name, name_ar, paradigm, difficulty, security, esoteric, docker_image
"""
from __future__ import annotations

LANGUAGES: list[dict] = [
    # الأكثر انتشارا
    {"slug": "python", "name": "Python", "name_ar": "بايثون", "paradigm": "multi", "difficulty": "easy", "security": True, "docker_image": "python:3.12-slim"},
    {"slug": "javascript", "name": "JavaScript", "name_ar": "جافاسكربت", "paradigm": "multi", "difficulty": "easy", "security": True, "docker_image": "node:22-slim"},
    {"slug": "typescript", "name": "TypeScript", "name_ar": "تايبسكربت", "paradigm": "multi", "difficulty": "medium", "security": True, "docker_image": "node:22-slim"},
    {"slug": "c", "name": "C", "name_ar": "سي", "paradigm": "procedural", "difficulty": "hard", "security": True, "docker_image": "gcc:14"},
    {"slug": "cpp", "name": "C++", "name_ar": "سي بلس بلس", "paradigm": "multi", "difficulty": "hard", "security": True, "docker_image": "gcc:14"},
    {"slug": "java", "name": "Java", "name_ar": "جافا", "paradigm": "oop", "difficulty": "medium", "security": True, "docker_image": "eclipse-temurin:21"},
    {"slug": "go", "name": "Go", "name_ar": "غو", "paradigm": "multi", "difficulty": "medium", "security": True, "docker_image": "golang:1.23"},
    {"slug": "rust", "name": "Rust", "name_ar": "رست", "paradigm": "multi", "difficulty": "hard", "security": True, "docker_image": "rust:1.82-slim"},
    {"slug": "php", "name": "PHP", "name_ar": "بي إتش بي", "paradigm": "multi", "difficulty": "easy", "security": True, "docker_image": "php:8.3-cli"},
    {"slug": "ruby", "name": "Ruby", "name_ar": "روبي", "paradigm": "oop", "difficulty": "easy", "security": True, "docker_image": "ruby:3.3-slim"},
    {"slug": "csharp", "name": "C#", "name_ar": "سي شارب", "paradigm": "oop", "difficulty": "medium", "security": True, "docker_image": "mcr.microsoft.com/dotnet/sdk:8.0"},
    {"slug": "kotlin", "name": "Kotlin", "name_ar": "كوتلن", "paradigm": "multi", "difficulty": "medium", "security": True, "docker_image": "eclipse-temurin:21"},
    {"slug": "swift", "name": "Swift", "name_ar": "سويفت", "paradigm": "multi", "difficulty": "medium", "security": True, "docker_image": "swift:5.10"},
    {"slug": "dart", "name": "Dart", "name_ar": "دارت", "paradigm": "oop", "difficulty": "easy", "security": False, "docker_image": "dart:stable"},
    {"slug": "r", "name": "R", "name_ar": "آر", "paradigm": "statistical", "difficulty": "medium", "security": False, "docker_image": "r-base:4.4"},
    {"slug": "scala", "name": "Scala", "name_ar": "سكالا", "paradigm": "multi", "difficulty": "hard", "security": False, "docker_image": "sbtscala/scala-sbt:latest"},
    {"slug": "perl", "name": "Perl", "name_ar": "بيرل", "paradigm": "multi", "difficulty": "medium", "security": True, "docker_image": "perl:5.40-slim"},
    {"slug": "bash", "name": "Bash", "name_ar": "باش", "paradigm": "scripting", "difficulty": "easy", "security": True, "docker_image": "bash:5.2"},
    {"slug": "powershell", "name": "PowerShell", "name_ar": "باورشل", "paradigm": "scripting", "difficulty": "easy", "security": True, "docker_image": "mcr.microsoft.com/powershell:latest"},
    {"slug": "sql", "name": "SQL", "name_ar": "إس كيو إل", "paradigm": "declarative", "difficulty": "easy", "security": True, "docker_image": "postgres:16-alpine"},
    {"slug": "lua", "name": "Lua", "name_ar": "لوا", "paradigm": "multi", "difficulty": "easy", "security": False, "docker_image": "debian:bookworm-slim"},
    {"slug": "haskell", "name": "Haskell", "name_ar": "هسكل", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "haskell:9.8"},
    {"slug": "erlang", "name": "Erlang", "name_ar": "إرلانغ", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "erlang:27"},
    {"slug": "elixir", "name": "Elixir", "name_ar": "إليكسير", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "elixir:1.17"},
    {"slug": "clojure", "name": "Clojure", "name_ar": "كلوجر", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "clojure:latest"},
    {"slug": "fsharp", "name": "F#", "name_ar": "إف شارب", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "mcr.microsoft.com/dotnet/sdk:8.0"},
    {"slug": "ocaml", "name": "OCaml", "name_ar": "أوكامل", "paradigm": "functional", "difficulty": "hard", "security": False, "docker_image": "ocaml/opam:latest"},
    {"slug": "zig", "name": "Zig", "name_ar": "زيغ", "paradigm": "multi", "difficulty": "hard", "security": True, "docker_image": "ziglang/zig:latest"},
    {"slug": "nim", "name": "Nim", "name_ar": "نِم", "paradigm": "multi", "difficulty": "medium", "security": False, "docker_image": "nimlang/nim:latest"},
    {"slug": "v", "name": "V", "name_ar": "في", "paradigm": "multi", "difficulty": "medium", "security": False, "docker_image": "thevlang/vlang:latest"},
    {"slug": "julia", "name": "Julia", "name_ar": "جوليا", "paradigm": "multi", "difficulty": "medium", "security": False, "docker_image": "julia:1.10"},
    {"slug": "matlab", "name": "MATLAB", "name_ar": "ماتلاب", "paradigm": "multi", "difficulty": "medium", "security": False, "docker_image": "mathworks/matlab:latest"},
    {"slug": "groovy", "name": "Groovy", "name_ar": "غروفي", "paradigm": "multi", "difficulty": "medium", "security": False, "docker_image": "groovy:4"},
    {"slug": "objective-c", "name": "Objective-C", "name_ar": "أوبجكتف سي", "paradigm": "oop", "difficulty": "hard", "security": True, "docker_image": "gcc:14"},
    {"slug": "fortran", "name": "Fortran", "name_ar": "فورتران", "paradigm": "procedural", "difficulty": "hard", "security": False, "docker_image": "gcc:14"},
    {"slug": "cobol", "name": "COBOL", "name_ar": "كوبول", "paradigm": "procedural", "difficulty": "hard", "security": False, "docker_image": "gcc:14"},
    {"slug": "assembly", "name": "Assembly", "name_ar": "لغة التجميع", "paradigm": "low-level", "difficulty": "hard", "security": True, "docker_image": "gcc:14"},
    {"slug": "solidity", "name": "Solidity", "name_ar": "سوليديتي", "paradigm": "oop", "difficulty": "hard", "security": True, "docker_image": "ethereum/solc:stable"},
    {"slug": "yaml", "name": "YAML", "name_ar": "يامل", "paradigm": "config", "difficulty": "easy", "security": True, "docker_image": "python:3.12-slim"},
    {"slug": "html", "name": "HTML", "name_ar": "إتش تي إم إل", "paradigm": "markup", "difficulty": "easy", "security": True, "docker_image": "node:22-slim"},
    {"slug": "css", "name": "CSS", "name_ar": "سي إس إس", "paradigm": "stylesheet", "difficulty": "easy", "security": False, "docker_image": "node:22-slim"},
    {"slug": "regex", "name": "Regex", "name_ar": "التعابير النمطية", "paradigm": "pattern", "difficulty": "medium", "security": True, "docker_image": "python:3.12-slim"},
    # لغات شاذة/تاريخية
    {"slug": "brainfuck", "name": "Brainfuck", "name_ar": "برينفك", "paradigm": "esoteric", "difficulty": "hard", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
    {"slug": "lolcode", "name": "LOLCODE", "name_ar": "لولكود", "paradigm": "esoteric", "difficulty": "medium", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
    {"slug": "whitespace", "name": "Whitespace", "name_ar": "وايت سبيس", "paradigm": "esoteric", "difficulty": "hard", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
    {"slug": "befunge", "name": "Befunge", "name_ar": "بيفنغ", "paradigm": "esoteric", "difficulty": "hard", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
    {"slug": "piet", "name": "Piet", "name_ar": "بييت", "paradigm": "esoteric", "difficulty": "hard", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
    {"slug": "malbolge", "name": "Malbolge", "name_ar": "مالبولج", "paradigm": "esoteric", "difficulty": "hard", "security": False, "esoteric": True, "docker_image": "debian:bookworm-slim"},
]
