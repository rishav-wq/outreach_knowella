---
title: Knowella Outreach
emoji: 📧
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# outreach-agent

A reusable cold-outreach **personalization engine**. The intelligent layer of the
cold-email stack — research a lead, ground the facts, write a genuinely personal
angle, quality-gate it, and hand it to a sending platform.

It is deliberately **not** a bulk mailer, a lead source, or an email host. Those
are commodity layers bought elsewhere:

```
Apollo (leads)  ->  THIS ENGINE (research + personalize + gate)  ->  Instantly (send)
   commodity              your product / the intelligence              commodity
```

## The one rule that makes it reusable

The **engine never changes**. Everything campaign-specific lives in one config
file (`config/<campaign>.yaml`). To run outreach for a different product, market,
or brand, you swap the config — not the code. Four inputs:

1. **WHO**  — the ICP / lead filters (Apollo)
2. **WHAT** — the offer + value props
3. **WHAT'S TRUE** — grounding facts (anti-hallucination)
4. **VOICE** — tone + framing for the angle

## Pipeline

```
leads ─► research(lead) ─► personalize(lead, research) ─► quality_gate ─► push to Instantly
         (Tavily + web)     (Gemini, grounded angle)      (drop/fallback)
```

The quality gate is the safety valve: the model may only assert facts present in
the research. A lead with no usable research gets a safe generic line or is
dropped — a hallucinated "congrats on your Series B" is worse than sending nothing.

## Model choice

Default **Gemini `gemini-2.5-flash`** via Google's OpenAI-compatible endpoint.
This is batch work — latency is irrelevant, so we optimize for quality-per-dollar.
Provider/model is per-step config (`engine` calls pass it), swappable to Groq /
OpenAI / Anthropic via the same OpenAI-compatible SDK by changing base_url + model.

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env        # fill in keys
cp config/campaign.example.yaml config/my-campaign.yaml
python -m src.main --campaign config/my-campaign.yaml --dry-run
```

`--dry-run` runs research + personalize + gate and prints results **without**
pushing to Instantly. Drop the flag to actually queue sends.

## Status

Skeleton. `src/llm.py` and `src/models.py` are functional; the engine and
integration modules are stubs with clear signatures and TODOs — fill them in
while the mailboxes warm up.
