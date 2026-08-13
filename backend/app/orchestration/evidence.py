"""
EvidenceModel for Ask Kriton's visualization pipeline.

Narrative text and visualizations must derive from the SAME evidence — never
let them independently re-derive facts from raw search results, or they can
silently disagree. This module is the shared, normalized shape that
structured-data connectors (dbnomics.py, frankfurter.py, …) populate, and
that the visualization pipeline (data_shape.py, visualization/orchestrator.py)
consumes.

MVP scope: only `observations`/`measures`/`dimensions`/`units`/`sources`/
`warnings` are populated today, backed by DBnomics (time series) and
Frankfurter (a single FX rate). `entities`/`relationships`/`events` are
defined for forward compatibility with a future evidence-graph pipeline but
are not populated by anything yet — there is no entity/relationship
extraction step in this codebase today, so leave them empty rather than
fabricate placeholder data.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """One (dimension_value, measure_value) point — e.g. one period of a time series."""

    dimension: str    # e.g. a period label: "2024-Q1"
    value: float
    measure: str = "value"


class Entity(BaseModel):
    id: str
    name: str
    type: str = "unknown"
    aliases: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    source_id: str
    target_id: str
    type: str = "related_to"
    directed: bool = True


class EvidenceModel(BaseModel):
    subject: str | None = None

    facts: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)

    # A second, independently-fetched real series aligned to the SAME periods
    # as `observations` — populated only for a correlation-shaped query
    # (dbnomics.py's _find_two_series), never derived/interpolated from the
    # primary series. len(secondary_observations) always equals
    # len(observations) when populated; each index i is the same period.
    secondary_subject: str | None = None
    secondary_observations: list[Observation] = Field(default_factory=list)
    secondary_units: list[str] = Field(default_factory=list)

    # Parts-of-a-whole evidence (e.g. real, named PSC shareholders and their
    # declared ownership band from Companies House — market_data.py's
    # _find_ownership) — reuses Observation's (dimension, value) shape with
    # dimension=holder label, value=percent (a band midpoint, never an exact
    # filed figure; see composition_caveat). Never populated from a guess.
    composition_subject: str | None = None
    composition: list[Observation] = Field(default_factory=list)
    composition_caveat: str | None = None

    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)

    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)

    sources: list[str] = Field(default_factory=list)   # source URLs/ids backing this evidence
    warnings: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.observations and not self.entities and not self.relationships and not self.composition
