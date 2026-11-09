"""Claude review of inspected seller datasets, with a deterministic offline fallback.

What reaches the model: the column schema, the column profile and at most 20 sample rows, with
every cell the privacy scan flagged replaced by "[redacted]" first. Flagged columns also lose
their value statistics (min, max, mean), and a time coverage built from a flagged column is not
sent. Research sends only the public listing text, the schema and the time coverage. Nothing in
this module logs payloads, prompts or model output; log lines carry the task, the dataset id and
error class names only.

Prompts are versioned files in `prompts/` (`<name>.md` is the system prompt, `<name>.schema.json`
the tool Claude must call). Output comes back as the input of that strict tool, is validated
here, and only then cached in private object storage by prompt version, model and dataset
SHA-256, so retries and re-uploads of the same bytes do not call the API again. One call, with
its retries and web-search continuations, ends well inside the worker's step timeout.

Without ANTHROPIC_API_KEY, `engine()` returns None and the stages use `fallback_review`.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, ValidationError, field_validator

from .config import PipelineSettings
from .slicing import slug
from .storage import ObjectExistsError, ObjectStore

logger = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent / "prompts"
REVIEW_PROMPT = "dataset_review.v1"
RESEARCH_PROMPT = "dataset_research.v1"
MAX_SAMPLE_ROWS = 20
MAX_TOKENS = 16_000
# A web-search turn may pause; continue it at most this many times.
MAX_CONTINUATIONS = 4
# The SDK retries connection errors, timeouts, 429 and 5xx this many times per request.
MAX_RETRIES = 2
# One ask, with its retries and continuations, uses at most this share of the step timeout, so a
# slow call never outlives its step and gets paid for again by the worker that reclaims it.
STEP_SHARE = 0.6
# Models that accept server-side refusal fallbacks (beta). Other models get a plain request.
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

MAX_TITLE = 90
MAX_DESCRIPTION = 600
MAX_TAGS = 8
MAX_TAG = 40
MAX_CATEGORY = 40
MAX_CONCERNS = 10
MAX_MESSAGE = 300
MAX_SOURCES = 5


class Unavailable(Exception):
    """Claude gave no usable answer. The message is a short reason code, never model or row text."""


@dataclass(frozen=True)
class Prompt:
    name: str
    system: str
    tool: dict
    effort: str


@cache
def load_prompt(name: str, effort: str = "medium") -> Prompt:
    system = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    tool = json.loads((PROMPTS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Prompt(name=name, system=system, tool={**tool, "strict": True}, effort=effort)


@dataclass
class Answer:
    output: dict
    model: str
    request_id: str | None = None
    search_urls: list[str] = field(default_factory=list)


class Engine(Protocol):
    model: str

    def ask(self, prompt: Prompt, payload: dict, web_search: bool = False) -> Answer: ...


class Claude:
    def __init__(self, settings: PipelineSettings):
        self.model = settings.sliver_ai_model
        step_share = settings.pipeline_step_timeout_seconds * STEP_SHARE
        self.budget = min(settings.sliver_ai_timeout_seconds, step_share)
        # The key is passed explicitly: an unset key means the fallback, never another credential.
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=MAX_RETRIES)

    def ask(self, prompt: Prompt, payload: dict, web_search: bool = False) -> Answer:
        messages: list[dict] = [
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}
        ]
        request: dict = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": prompt.system,
            # Forced tool choice is not available on current models: the prompt asks for the call
            # and `strict` keeps its input schema-valid.
            "tools": [prompt.tool, *([WEB_SEARCH_TOOL] if web_search else [])],
            "messages": messages,
            "output_config": {"effort": prompt.effort},
        }
        if self.model in FALLBACK_MODELS:
            request.update(betas=[FALLBACK_BETA], fallbacks="default")
        urls: list[str] = []
        deadline = time.monotonic() + self.budget
        try:
            for _ in range(MAX_CONTINUATIONS + 1):
                remaining = deadline - time.monotonic()
                if remaining < 1:
                    raise Unavailable("deadline")
                # Timed-out attempts are retried, so each attempt gets an equal share of what is left.
                response = self.client.beta.messages.create(**request, timeout=remaining / (MAX_RETRIES + 1))
                urls.extend(search_urls(response.content))
                if response.stop_reason != "pause_turn":
                    break
                messages.append({"role": "assistant", "content": response.content})
        except anthropic.APIStatusError as error:
            raise Unavailable(f"api_status_{error.status_code}") from None
        except anthropic.APIConnectionError:
            raise Unavailable("api_connection") from None
        if response.stop_reason in ("refusal", "max_tokens", "pause_turn"):
            raise Unavailable(response.stop_reason)
        for block in response.content:
            if block.type == "tool_use" and block.name == prompt.tool["name"]:
                return Answer(dict(block.input), response.model, getattr(response, "_request_id", None), urls)
        raise Unavailable("no_tool_call")


def search_urls(content) -> list[str]:
    urls = []
    for block in content:
        if getattr(block, "type", None) == "web_search_tool_result" and isinstance(block.content, list):
            urls.extend(item.url for item in block.content if getattr(item, "url", None))
    return urls


def engine(settings: PipelineSettings) -> Engine | None:
    return Claude(settings) if settings.anthropic_api_key else None


def cache_key(prompt: Prompt, model: str, sha256: str) -> str:
    return f"ai-cache/{prompt.name}/{slug(model)}/{sha256}.json"


def ask_cached(
    store: ObjectStore,
    ai: Engine,
    prompt: Prompt,
    payload: dict,
    sha256: str,
    validate: Callable[[Answer], dict],
    web_search: bool = False,
) -> tuple[dict, Answer, bool]:
    """Returns the validated output, the answer and whether it came from the cache.

    Cache entries are immutable, so an answer is cached only after `validate` accepts it; a
    rejected answer raises `Unavailable` and the next run asks again.
    """
    key = cache_key(prompt, ai.model, sha256)
    try:
        record = json.loads(store.get(key))
        cached = Answer(record["output"], record["model"], record.get("request_id"), record["search_urls"])
    except Exception:
        cached = None  # a missing or unreadable cache entry is a miss
    if cached is not None:
        try:
            return validate(cached), cached, True
        except Unavailable:
            # Written before answers were validated first; it can never be replaced, so ask again.
            logger.warning("ignoring an invalid cached %s result for %s", prompt.name, sha256[:12])
    answer = ai.ask(prompt, payload, web_search=web_search)
    output = validate(answer)
    record = {
        "output": answer.output,
        "model": answer.model,
        "request_id": answer.request_id,
        "search_urls": answer.search_urls,
    }
    try:
        store.put(key, json.dumps(record, sort_keys=True).encode(), content_type="application/json")
    except ObjectExistsError:
        pass
    except Exception:
        logger.warning("could not cache the %s result for %s", prompt.name, sha256[:12])
    return output, answer, False


# --- output validation --------------------------------------------------------------------


def clean_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


class Concern(BaseModel):
    column: str = ""
    severity: Literal["low", "medium", "high"]
    message: str

    @field_validator("column", mode="after")
    @classmethod
    def short_column(cls, value: str) -> str:
        return value.strip()[:160]

    @field_validator("message", mode="after")
    @classmethod
    def short_message(cls, value: str) -> str:
        return clean_text(value, MAX_MESSAGE)


class SliceChoice(BaseModel):
    column: str = ""
    period: Literal["value", "month", "none"] = "none"


class Review(BaseModel):
    category: str
    tags: list[str]
    title: str
    description: str
    quality_concerns: list[Concern]
    sensitivity_concerns: list[Concern]
    slice: SliceChoice

    @field_validator("category", mode="after")
    @classmethod
    def category_slug(cls, value: str) -> str:
        return slug(value)[:MAX_CATEGORY].strip("-") or "general"

    @field_validator("tags", mode="after")
    @classmethod
    def tag_list(cls, value: list[str]) -> list[str]:
        tags: list[str] = []
        for tag in value:
            cleaned = clean_text(tag.lower(), MAX_TAG).rstrip("…")
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        return tags[:MAX_TAGS]

    @field_validator("title", mode="after")
    @classmethod
    def short_title(cls, value: str) -> str:
        return clean_text(value, MAX_TITLE)

    @field_validator("description", mode="after")
    @classmethod
    def short_description(cls, value: str) -> str:
        return clean_text(value, MAX_DESCRIPTION)

    @field_validator("quality_concerns", "sensitivity_concerns", mode="after")
    @classmethod
    def few_concerns(cls, value: list[Concern]) -> list[Concern]:
        return value[:MAX_CONCERNS]


def validate_review(output: dict) -> dict:
    try:
        review = Review.model_validate(output)
    except ValidationError:
        raise Unavailable("invalid_output") from None
    if not review.title or not review.description:
        raise Unavailable("invalid_output")
    for concern in review.quality_concerns:
        concern.severity = "medium" if concern.severity == "high" else concern.severity
    return review.model_dump()


class Source(BaseModel):
    url: str
    title: str = ""
    note: str = ""


class Research(BaseModel):
    freely_available: Literal["yes", "partly", "no", "unknown"]
    summary: str
    sources: list[Source]


def validate_research(output: dict, search_urls: list[str]) -> dict:
    try:
        research = Research.model_validate(output)
    except ValidationError:
        raise Unavailable("invalid_output") from None
    returned = set(search_urls)
    # Keep only sources the web search actually returned, so a cited page is never invented.
    sources = [
        {"url": source.url, "title": clean_text(source.title, 160), "note": clean_text(source.note, 300)}
        for source in research.sources
        if source.url in returned and source.url.startswith(("https://", "http://"))
    ][:MAX_SOURCES]
    return {
        "freely_available": research.freely_available,
        "summary": clean_text(research.summary, MAX_DESCRIPTION),
        "sources": sources,
    }


# --- the deterministic fallback -----------------------------------------------------------

# Column-name keywords for the fallback category, matched against name tokens.
CATEGORY_KEYWORDS = {
    "port-operations": {"berth", "terminal", "port", "vessel", "quay", "crane", "teu", "anchorage"},
    "shipping-schedules": {"eta", "etd", "delay", "sailing", "sailings", "schedule", "carrier", "route"},
    "freight-rates": {"rate", "rates", "freight", "lane", "container", "tariff", "spot"},
    "customs": {"customs", "hs", "clearance", "declaration", "duty", "import", "export"},
}
TAG_STOPWORDS = {
    "and", "the", "per", "pct", "avg", "mean", "min", "max", "total", "count", "number", "num", "id",
    "value", "values", "start", "end", "type", "usd", "hours", "days", "date", "week", "month", "year",
}  # fmt: skip


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    return [token for token in re.split(r"[^a-z0-9]+", spaced.lower()) if token]


def fallback_category(header: list[str]) -> str:
    tokens = [token for name in header for token in name_tokens(name)]
    scores = {
        category: sum(token in words for token in tokens) for category, words in CATEGORY_KEYWORDS.items()
    }
    best = max(scores, key=lambda category: scores[category])
    return best if scores[best] else "general"


def fallback_tags(header: list[str], category: str) -> list[str]:
    tags: list[str] = [] if category == "general" else category.split("-")[:1]
    for name in header:
        for token in name_tokens(name):
            if len(token) >= 3 and not token.isdigit() and token not in TAG_STOPWORDS and token not in tags:
                tags.append(token)
    return tags[:MAX_TAGS]


def join_names(names: list[str], limit: int = 8) -> str:
    shown = names[:limit]
    if len(names) > limit:
        return ", ".join(shown) + f" and {len(names) - limit} more"
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def fallback_review(
    title: str, header: list[str], row_count: int, time_coverage: dict | None, slice_choice: dict
) -> dict:
    """Listing metadata built only from public facts: the seller's title, column names and counts."""
    category = fallback_category(header)
    description = f"{row_count:,} rows with {len(header)} columns: {join_names(header)}."
    if time_coverage:
        description += f" Covers {time_coverage['start']} to {time_coverage['end']}."
    if slice_choice.get("column"):
        how = "calendar month" if slice_choice.get("period") == "month" else slice_choice["column"]
        description += f" Available in slivers by {how}."
    return {
        "category": category,
        "tags": fallback_tags(header, category),
        "title": clean_text(title, MAX_TITLE),
        "description": clean_text(description, MAX_DESCRIPTION),
        "quality_concerns": [],
        "sensitivity_concerns": [],
        "slice": {"column": slice_choice.get("column") or "", "period": slice_choice.get("period") or "none"},
    }
