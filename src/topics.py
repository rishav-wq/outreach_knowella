"""What a subscriber can ask for — the taxonomy the website's signup form offers.

Deliberately the SAME vocabulary as knowella.com's "What are you interested in?"
form. Someone who ticked Cold Chain there should see Cold Chain when they come back
to change their mind; two taxonomies for one person's interests means the second one
silently contradicts the promise made by the first.

Distinct from Library topics (Freight, Logistics, Venture Capital), which describe
how WE tag leads. These describe what a READER asked for, and only one of those is
a promise.

A publication declares which of these it covers, and an issue reaches a subscriber
when the two overlap. Without that mapping the form is a wish list: someone ticks
Cold Chain, nothing we publish is about cold chain, and they hear nothing — or
worse, hear everything.
"""
from __future__ import annotations

GROUPS: list[dict] = [
    {"name": "Operations", "topics": [
        "Process Management", "SOPs & Work Instructions", "CAPA", "Risk Management",
        "Quality Management", "Performance & KPIs", "Training & Onboarding",
        "Continuous Improvement"]},
    {"name": "Supply Chain", "topics": [
        "Logistics", "Supplier Management", "Procurement", "Inventory & Warehouse",
        "Freight & Carriers", "Cold Chain", "Compliance", "Demand Planning"]},
    {"name": "Workplace Safety", "topics": [
        "Health & Safety", "Hazard Management", "OSHA", "PPE", "Job Safety Analysis",
        "Incident & Near Miss", "Ergonomics", "Investigations"]},
]

ALL = [t for g in GROUPS for t in g["topics"]]

# What each publication actually covers, so a topic is a promise we can keep.
# Seeded onto the three publications; editable per publication afterwards.
DEFAULTS: dict[str, list[str]] = {
    "The Safety Brief": ["Health & Safety", "Hazard Management", "OSHA", "PPE",
                         "Job Safety Analysis", "Incident & Near Miss",
                         "Investigations", "Risk Management"],
    "Freight Paperwork": ["Logistics", "Freight & Carriers", "Compliance",
                          "Procurement", "Inventory & Warehouse", "Cold Chain",
                          "Supplier Management", "SOPs & Work Instructions"],
    "Ergonomics Notes": ["Ergonomics", "Health & Safety", "Incident & Near Miss",
                         "Training & Onboarding"],
}


def clean(values) -> list[str]:
    """Only topics that exist. A tampered form post cannot invent an interest, and a
    renamed topic drops out rather than lingering as a value nothing matches."""
    known = set(ALL)
    return [v for v in (values or []) if v in known]
