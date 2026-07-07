"""Load + validate the campaign config and environment."""
from __future__ import annotations

import os

import yaml
from dotenv import load_dotenv

REQUIRED = ("name", "icp", "offer", "voice")

# repo root = parent of src/, so .env loads no matter the working directory
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env() -> None:
    load_dotenv(os.path.join(_ROOT, ".env"))


def load_campaign(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"campaign {path} missing required keys: {missing}")
    cfg.setdefault("knowledge", [])
    cfg.setdefault("models", {})
    cfg.setdefault("sending", {})
    cfg.setdefault("research", {})
    cfg.setdefault("verify", {})
    cfg.setdefault("apollo", {})
    cfg.setdefault("experiment", {})
    return cfg
