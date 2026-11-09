"""Stage 6 (behind SLIVER_AI_RESEARCH, off by default): Claude searches the web for freely available
data equivalent to this listing. It sees only the public listing, the schema and the time
coverage, never rows. Cited sources are limited to pages the web search actually returned.
"""

import logging

from .. import ai
from .context import StageContext
from .leakguard import flagged_columns, shareable_coverage
from .table import StageResult, finding

logger = logging.getLogger(__name__)

VERDICTS = {
    "yes": "Equivalent data appears to be freely available",
    "partly": "Part of this data appears to be freely available",
    "no": "No freely available equivalent found",
    "unknown": "Could not tell whether equivalent data is freely available",
}


def run(context: StageContext) -> StageResult:
    if not context.settings.sliver_ai_research:
        return StageResult(
            summary="Research is turned off (SLIVER_AI_RESEARCH).", details={"enabled": False}, skipped=True
        )
    engine = ai.engine(context.settings)
    if engine is None:
        return StageResult(
            summary="Research needs ANTHROPIC_API_KEY; there is no offline fallback.",
            details={"enabled": True, "engine": None},
            skipped=True,
        )
    listing = context.details("ai_review").get("listing")
    if not listing:
        return StageResult(
            summary="Skipped: the AI review did not finish.", details={"enabled": True}, skipped=True
        )
    payload = {
        "listing": listing,
        "columns": [{"name": column["name"], "type": column["type"]} for column in context.dataset.columns],
        "time_coverage": shareable_coverage(
            context.details("profile").get("time_coverage"), flagged_columns(context.findings("privacy"))
        ),
    }
    details: dict = {"enabled": True, "prompt": ai.RESEARCH_PROMPT}
    try:
        research, answer, cached = ai.ask_cached(
            context.store,
            engine,
            ai.load_prompt(ai.RESEARCH_PROMPT),
            payload,
            context.dataset.sha256,
            validate=lambda answer: ai.validate_research(answer.output, answer.search_urls),
            web_search=True,
        )
    except ai.Unavailable as error:
        logger.warning("claude research unavailable for dataset %s: %s", context.dataset.id, error)
        return StageResult(
            summary="Research could not finish.",
            findings=[
                finding("research_unavailable", "low", f"Claude could not finish the research ({error}).")
            ],
            details={**details, "error": str(error)},
        )
    details.update(research, model=answer.model, cached=cached, request_id=answer.request_id)
    findings = []
    verdict = research["freely_available"]
    if verdict in ("yes", "partly"):
        findings.append(
            finding(
                "free_equivalent" if verdict == "yes" else "partial_free_equivalent",
                "medium" if verdict == "yes" else "low",
                f"{VERDICTS[verdict]}: {research['summary']}",
                sources=[source["url"] for source in research["sources"]],
            )
        )
    sources = len(research["sources"])
    summary = f"{VERDICTS[verdict]} ({sources} source{'s' if sources != 1 else ''})."
    return StageResult(summary=summary, findings=findings, details=details)
