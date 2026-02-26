"""Polish → English L1 interference pattern tracking.

Maintains a knowledge base of common interference patterns that Polish
native speakers exhibit when learning English, and tracks per-student
which patterns they have exhibited vs overcome over time.
"""

import json
import logging
from datetime import datetime, timezone

from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge base of Polish → English interference patterns
# ---------------------------------------------------------------------------

L1_PATTERNS: dict[str, dict] = {
    "article_omission": {
        "category": "articles",
        "description": "Omitting articles (a/an/the) — Polish has no articles",
        "cefr_range": ["A1", "A2", "B1", "B2"],
        "examples": ["I have dog", "She is teacher", "I saw moon"],
        "correction": "Articles mark whether a noun is specific (the) or general (a/an)",
        "sub_patterns": [
            {"detail": "missing_indefinite_article", "description": "Omitting a/an with singular countable nouns"},
            {"detail": "missing_definite_article", "description": "Omitting 'the' with known/specific referents"},
            {"detail": "articles_in_complex_clauses", "description": "Dropping articles in subordinate clauses while using them in main clauses"},
        ],
    },
    "preposition_confusion": {
        "category": "prepositions",
        "description": "Incorrect preposition choice from Polish na/w/do mapping",
        "cefr_range": ["A1", "A2", "B1"],
        "examples": ["on the university", "in Monday", "I go to home"],
        "correction": "English prepositions must be learned as collocations",
        "sub_patterns": [
            {"detail": "time_prepositions", "description": "in/on/at confusion with time expressions"},
            {"detail": "place_prepositions", "description": "in/on/at confusion with places"},
            {"detail": "movement_prepositions", "description": "to/into/onto confusion"},
        ],
    },
    "word_order_errors": {
        "category": "word_order",
        "description": "Non-English word order from Polish free word order",
        "cefr_range": ["A1", "A2", "B1"],
        "examples": ["Very much I like it", "Always I am going"],
        "correction": "English requires Subject-Verb-Object order",
        "sub_patterns": [
            {"detail": "adverb_placement", "description": "Adverbs placed before auxiliary verbs"},
            {"detail": "adjective_after_noun", "description": "Adjective placed after noun (Polish order)"},
            {"detail": "question_formation", "description": "Missing do/does in questions"},
        ],
    },
    "tense_confusion": {
        "category": "tenses",
        "description": "Tense errors from Polish 3-tense system vs English 12",
        "cefr_range": ["A2", "B1", "B2"],
        "examples": ["I live here for 5 years", "I am go every day"],
        "correction": "Match tense to time reference and aspect",
        "sub_patterns": [
            {"detail": "present_perfect_avoidance", "description": "Using past simple instead of present perfect"},
            {"detail": "continuous_overuse", "description": "Using continuous forms with stative verbs"},
            {"detail": "simple_continuous_confusion", "description": "Mixing present simple and continuous"},
            {"detail": "future_form_confusion", "description": "Will vs going to vs present continuous for future"},
        ],
    },
    "false_friends": {
        "category": "false_friends",
        "description": "Using Polish-looking English words with wrong meanings",
        "cefr_range": ["A2", "B1", "B2", "C1"],
        "examples": ["aktualnie→actually (should be 'currently')", "ewentualnie→eventually (should be 'possibly')"],
        "correction": "These words look similar but mean different things",
        "sub_patterns": [
            {"detail": "aktualnie_actually", "description": "Using 'actually' to mean 'currently'"},
            {"detail": "ewentualnie_eventually", "description": "Using 'eventually' to mean 'possibly'"},
            {"detail": "sympatyczny_sympathetic", "description": "Using 'sympathetic' to mean 'nice/likeable'"},
        ],
    },
    "pronunciation_transfer": {
        "category": "pronunciation",
        "description": "Polish phonological interference in English",
        "cefr_range": ["A1", "A2", "B1", "B2"],
        "examples": ["th→f/t", "w→v", "vowel length errors"],
        "correction": "Practice target sounds with minimal pairs",
        "sub_patterns": [
            {"detail": "th_substitution", "description": "Replacing th sounds with f, t, or d"},
            {"detail": "w_v_confusion", "description": "Pronouncing English w as v"},
            {"detail": "vowel_length", "description": "Not distinguishing long/short vowels"},
        ],
    },
    "phrasal_verb_avoidance": {
        "category": "phrasal_verbs",
        "description": "Avoiding phrasal verbs (Polish has none), using formal alternatives",
        "cefr_range": ["B1", "B2", "C1"],
        "examples": ["Using 'investigate' instead of 'look into'"],
        "correction": "Phrasal verbs are essential for natural English",
        "sub_patterns": [
            {"detail": "avoidance", "description": "Using Latin-origin formal verbs instead of phrasal verbs"},
            {"detail": "particle_errors", "description": "Using wrong particle with verb"},
            {"detail": "separability_errors", "description": "Not separating separable phrasal verbs"},
        ],
    },
    "formality_register": {
        "category": "register",
        "description": "Inappropriate formality level from Polish Pan/Pani system",
        "cefr_range": ["B1", "B2", "C1"],
        "examples": ["Overly formal in casual contexts", "Too casual in business"],
        "correction": "English register depends heavily on context",
        "sub_patterns": [
            {"detail": "overly_formal", "description": "Using excessively formal language in casual settings"},
            {"detail": "too_casual", "description": "Being too informal in professional contexts"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def record_interference_pattern(
    student_id: int,
    db,
    category: str,
    detail: str,
) -> None:
    """Record or increment an observed L1 interference pattern for a student.

    If a matching row already exists the occurrence counter is bumped and
    ``last_seen_at`` is refreshed.  Otherwise a brand-new row is inserted.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Check for an existing record
    cursor = await db.execute(
        "SELECT id FROM l1_interference_tracking "
        "WHERE student_id = ? AND pattern_category = ? AND pattern_detail = ?",
        (student_id, category, detail),
    )
    row = await cursor.fetchone()

    if row is not None:
        await db.execute(
            "UPDATE l1_interference_tracking "
            "SET occurrences = occurrences + 1, last_seen_at = ?, status = 'exhibited' "
            "WHERE id = ?",
            (now, row["id"]),
        )
    else:
        await db.execute(
            "INSERT INTO l1_interference_tracking "
            "(student_id, pattern_category, pattern_detail, status, occurrences, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, 'exhibited', 1, ?, ?)",
            (student_id, category, detail, now, now),
        )

    await db.commit()


async def mark_pattern_overcome(
    student_id: int,
    db,
    category: str,
    detail: str,
) -> None:
    """Mark a previously-exhibited interference pattern as overcome."""
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        "UPDATE l1_interference_tracking "
        "SET status = 'overcome', overcome_at = ? "
        "WHERE student_id = ? AND pattern_category = ? AND pattern_detail = ?",
        (now, student_id, category, detail),
    )
    await db.commit()


async def get_student_interference_profile(
    student_id: int,
    db,
) -> dict:
    """Return the full L1 interference profile for a student.

    Returns a dict with two keys:
    - ``exhibited``: patterns still actively observed
    - ``overcome``: patterns the student has overcome

    Each item carries category, detail, occurrences, first_seen_at,
    and last_seen_at.
    """
    cursor = await db.execute(
        "SELECT pattern_category, pattern_detail, status, occurrences, "
        "first_seen_at, last_seen_at, overcome_at "
        "FROM l1_interference_tracking WHERE student_id = ? "
        "ORDER BY last_seen_at DESC",
        (student_id,),
    )
    rows = await cursor.fetchall()

    exhibited: list[dict] = []
    overcome: list[dict] = []

    for row in rows:
        entry = {
            "category": row["pattern_category"],
            "detail": row["pattern_detail"],
            "occurrences": row["occurrences"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
        }
        if row["status"] == "overcome":
            entry["overcome_at"] = row["overcome_at"]
            overcome.append(entry)
        else:
            exhibited.append(entry)

    return {"exhibited": exhibited, "overcome": overcome}


# ---------------------------------------------------------------------------
# AI-powered text analysis
# ---------------------------------------------------------------------------

def _build_pattern_summary() -> str:
    """Build a concise textual summary of L1_PATTERNS for the AI prompt."""
    lines: list[str] = []
    for key, pattern in L1_PATTERNS.items():
        lines.append(f"## {key} ({pattern['category']})")
        lines.append(f"Description: {pattern['description']}")
        lines.append(f"CEFR range: {', '.join(pattern['cefr_range'])}")
        lines.append(f"Examples: {'; '.join(pattern['examples'])}")
        for sp in pattern["sub_patterns"]:
            lines.append(f"  - {sp['detail']}: {sp['description']}")
        lines.append("")
    return "\n".join(lines)


async def analyze_text_for_interference(
    text: str,
    student_level: str,
) -> list[dict]:
    """Use AI to scan student-written text for Polish L1 interference.

    Returns a list of detected patterns, each with:
    - ``category``: top-level pattern key (e.g. ``"article_omission"``)
    - ``detail``: sub-pattern detail string (e.g. ``"missing_indefinite_article"``)
    - ``evidence``: the specific phrase / sentence in the text that triggered detection
    - ``severity``: ``"low"`` / ``"medium"`` / ``"high"``
    """
    pattern_reference = _build_pattern_summary()

    system_prompt = (
        "You are an expert ESL error analyst specialising in Polish (L1) to English (L2) interference.\n\n"
        "You will receive a piece of text written by a Polish student learning English.\n"
        f"The student's current CEFR level is {student_level}.\n\n"
        "Your task is to identify any L1 interference patterns present in the text.\n"
        "Use the following reference of known Polish→English interference patterns:\n\n"
        f"{pattern_reference}\n\n"
        "For each interference instance you find, return a JSON object with these keys:\n"
        "  - \"category\": the top-level pattern key (e.g. \"article_omission\")\n"
        "  - \"detail\": the sub-pattern detail string (e.g. \"missing_indefinite_article\")\n"
        "  - \"evidence\": the exact phrase or sentence from the text showing the error\n"
        "  - \"severity\": one of \"low\", \"medium\", or \"high\" based on how much it\n"
        "    impedes communication and how unexpected it is at the student's level\n\n"
        "Severity guidelines:\n"
        "  - \"high\": pattern that should have been overcome at this CEFR level, or severely impedes meaning\n"
        "  - \"medium\": pattern common at this level but notable\n"
        "  - \"low\": minor issue, expected at this level\n\n"
        "Return your answer as a JSON object with a single key \"patterns\" whose value is a list.\n"
        "If no interference patterns are found, return {\"patterns\": []}.\n"
        "Return ONLY valid JSON, no other text."
    )

    try:
        response = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            use_case="cheap",
            temperature=0.3,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("AI call failed during L1 interference analysis: %s", exc)
        return []

    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as exc:
        logger.error("AI returned invalid JSON for L1 interference analysis: %s", exc)
        return []
    patterns = parsed.get("patterns", [])

    # Normalise and validate each entry
    validated: list[dict] = []
    for item in patterns:
        category = item.get("category", "")
        detail = item.get("detail", "")
        evidence = item.get("evidence", "")
        severity = item.get("severity", "low")

        if severity not in ("low", "medium", "high"):
            severity = "low"

        if category and detail and evidence:
            validated.append({
                "category": category,
                "detail": detail,
                "evidence": evidence,
                "severity": severity,
            })

    return validated
