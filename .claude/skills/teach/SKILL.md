---
name: teach
description: Teach a concept from the SQL Copilot project (RAG, embeddings, LoRA, LangGraph, Docker, eval, etc.) at the user's level, with analogy, diagram, example, and quiz. Also extends docs/study-guide.html. Use when the user says "teach me", "explain", "I don't understand", or when a new concept first appears while building.
---

# Teach skill

Use this whenever a concept needs explaining or the study guide needs extending.

## Format for a lesson (chat)
1. **One-line hook**: the idea in plain words.
2. **Analogy**: everyday comparison.
3. **How it works here**: where it sits in the pipeline (Retrieve -> Generate -> Verify -> Guard) and which file/folder.
4. **Tiny example**: a runnable snippet or concrete input/output from this project (the SaaS schema: organizations, subscriptions, orders, payments...).
5. **Gotcha**: the most common mistake.
6. **Check question**: one question; wait for the answer before going deeper.

Levels: **basics** (what/why), **working** (how, with code), **advanced** (trade-offs, failure modes, numbers). Ask or infer which level; default to basics then offer to go deeper.

## Extending the study guide
- File: `docs/study-guide.html` (single self-contained file: inline CSS/JS/SVG, no external assets).
- Add a `<section id="...">` in the right place (basics -> advanced order), add its link to the nav, and add glossary terms and a quiz item if relevant.
- Reuse existing CSS classes (`.card`, `.callout`, `.diagram`, `.quiz`) and the color-per-stage convention: teal=retrieve, violet=generate, amber=verify, rose=guard, blue=infra/UI, green=done/data.
- Keep claims honest: mark unverified numbers as such.
