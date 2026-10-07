"""Structured output the LLM must return (validated with pydantic, sent as a strict JSON schema)."""

from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str = Field(description="One factual statement from the answer.")
    source_ids: list[str] = Field(description="Ids of the sources that state this fact, e.g. ['S1'].")


class GeneratedAnswer(BaseModel):
    answer: str = Field(description="Concise answer with inline source ids like [S1]; empty if abstaining.")
    claims: list[Claim] = Field(description="Every factual statement in the answer, each with its sources.")
    abstained: bool = Field(description="True if the sources do not contain enough evidence to answer.")
    abstain_reason: str = Field(description="Why the question cannot be answered from the sources; empty otherwise.")
