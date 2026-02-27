import json
import logging
from app.services.ai_client import ai_chat
from app.services.prompts import load_prompt
from app.models.lesson import (
    LessonContent,
    WarmUp,
    Presentation,
    ControlledPractice,
    FreePractice,
    WrapUp,
)

logger = logging.getLogger(__name__)


async def generate_lesson(
    student_id: int,
    profile: dict,
    progress_history: list[dict],
    session_number: int,
    current_level: str,
    previous_topics: list[str] | None = None,
    recall_weak_areas: list[str] | None = None,
    teacher_session_notes: str | None = None,
    teacher_skill_observations: list[dict] | None = None,
    cefr_history: list[dict] | None = None,
    vocabulary_due_for_review: list[str] | None = None,
    difficulty_profile: dict | None = None,
    learning_dna: dict | None = None,
    l1_interference_profile: dict | None = None,
) -> LessonContent:
    lesson_prompt = load_prompt("lesson_generator.yaml")

    system_prompt = lesson_prompt["system_prompt"]
    user_template = lesson_prompt["user_template"]

    progress_text = "No previous lessons." if not progress_history else json.dumps(progress_history, indent=2)
    topics_text = "None (first lesson)." if not previous_topics else ", ".join(previous_topics)

    recall_text = "None." if not recall_weak_areas else ", ".join(recall_weak_areas)

    user_message = user_template.format(
        session_number=session_number,
        current_level=current_level,
        profile_summary=profile.get("profile_summary", "No profile summary available"),
        priorities=", ".join(profile.get("priorities", [])),
        gaps=json.dumps(profile.get("gaps", []), indent=2),
        progress_history=progress_text,
        previous_topics=topics_text,
        recall_weak_areas=recall_text,
    )

    # Append teacher-sourced context sections
    if teacher_session_notes:
        user_message += f"\n\nTEACHER NOTES FROM LAST CLASS:\n{teacher_session_notes}\n"

    if teacher_skill_observations:
        lines = []
        for obs in teacher_skill_observations:
            entry = f"- {obs['skill']}: {obs.get('score', '?')}/100"
            if obs.get("cefr_level"):
                entry += f" ({obs['cefr_level']})"
            if obs.get("notes"):
                entry += f" — {obs['notes']}"
            lines.append(entry)
        user_message += "\n\nTEACHER SKILL RATINGS (most recent):\n" + "\n".join(lines) + "\n"

    if cefr_history:
        lines = []
        for entry in cefr_history:
            parts = [f"Overall {entry.get('level', '?')}"]
            for skill in ("grammar", "vocabulary", "reading", "speaking", "writing"):
                val = entry.get(f"{skill}_level")
                if val:
                    parts.append(f"{skill.title()} {val}")
            lines.append(f"- {entry.get('recorded_at', '?')}: {' | '.join(parts)}")
        user_message += "\n\nCEFR PROGRESSION:\n" + "\n".join(lines) + "\n"

    if vocabulary_due_for_review:
        user_message += (
            "\n\nVOCABULARY DUE FOR REVIEW (incorporate naturally into exercises):\n"
            + ", ".join(vocabulary_due_for_review)
            + "\n"
        )

    if difficulty_profile:
        lines = []
        for skill, adjustment in difficulty_profile.items():
            if adjustment == "simplify":
                lines.append(f"- {skill}: SIMPLIFY (student is struggling — use easier examples, more scaffolding)")
            elif adjustment == "challenge":
                lines.append(f"- {skill}: CHALLENGE (student is mastering — increase complexity, reduce hints)")
            else:
                lines.append(f"- {skill}: MAINTAIN (appropriate level)")
        user_message += (
            "\n\nADAPTIVE DIFFICULTY (based on spaced-repetition performance data):\n"
            + "\n".join(lines)
            + "\nAdjust exercise difficulty per skill accordingly.\n"
        )

    # Learning DNA: full student profile with learning speed, modality strengths, etc.
    if learning_dna:
        dna_sections = []

        speed = learning_dna.get("learning_speed", {})
        if speed.get("classification"):
            dna_sections.append(f"Learning Speed: {speed['classification']} (avg {speed.get('avg_repetitions_to_mastery', '?')} reps to mastery)")

        modalities = learning_dna.get("modality_strengths", {})
        strong = [k for k, v in modalities.items() if v.get("classification") == "strong"]
        weak = [k for k, v in modalities.items() if v.get("classification") == "weak"]
        if strong:
            dna_sections.append(f"Strongest Modalities: {', '.join(strong)}")
        if weak:
            dna_sections.append(f"Weakest Modalities: {', '.join(weak)}")

        engagement = learning_dna.get("engagement_patterns", {})
        if engagement.get("score_trend"):
            dna_sections.append(f"Score Trend: {engagement['score_trend']}")

        challenge = learning_dna.get("optimal_challenge_level", {})
        if challenge.get("recommendation"):
            recent = challenge.get('recent_avg_score', challenge.get('current_avg_score', '?'))
            lifetime = challenge.get('current_avg_score', '?')
            dna_sections.append(f"Challenge Recommendation: {challenge['recommendation']} (recent avg: {recent}, lifetime avg: {lifetime})")

        frustration = learning_dna.get("frustration_indicators", {})
        if frustration.get("declining_scores"):
            dna_sections.append("WARNING: Declining scores detected — use more scaffolding and encouragement")
        if frustration.get("low_engagement_streak", 0) > 3:
            dna_sections.append(f"WARNING: {frustration['low_engagement_streak']} days inactive — re-engage with high-interest topics")

        errors = learning_dna.get("error_patterns", [])
        if errors:
            top_errors = ", ".join(f"{e['area']} ({e['count']}x)" for e in errors[:3])
            dna_sections.append(f"Top Error Patterns: {top_errors}")

        vocab = learning_dna.get("vocabulary_acquisition", {})
        if vocab.get("retention_rate") is not None:
            dna_sections.append(f"Vocabulary Retention: {round(vocab['retention_rate'] * 100, 1)}% ({vocab.get('mastered_words', 0)}/{vocab.get('total_words', 0)} mastered)")

        if dna_sections:
            user_message += "\n\nLEARNING DNA PROFILE:\n" + "\n".join(f"- {s}" for s in dna_sections) + "\n"
            user_message += (
                "\nUse this DNA to: adjust pacing based on learning speed, "
                "target exercises toward weakest modalities, use strongest modalities "
                "as scaffolding, include stretch zones for growth, and adapt exercise "
                "types accordingly.\n"
            )

    # L1 interference patterns from Polish
    if l1_interference_profile:
        exhibited = l1_interference_profile.get("exhibited", [])
        if exhibited:
            lines = []
            for p in exhibited[:8]:
                lines.append(f"- {p['category']}/{p['detail']} (seen {p.get('occurrences', 1)}x)")
            user_message += (
                "\n\nACTIVE POLISH L1 INTERFERENCE PATTERNS (target these in exercises):\n"
                + "\n".join(lines)
                + "\nDesign exercises that specifically practice correct forms for these patterns.\n"
            )

        overcome = l1_interference_profile.get("overcome", [])
        if overcome:
            user_message += (
                "\nOVERCOME L1 PATTERNS (occasional reinforcement only): "
                + ", ".join(f"{p['category']}/{p['detail']}" for p in overcome[:5])
                + "\n"
            )

    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="lesson",
            temperature=0.7,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("AI call failed during lesson generation: %s", exc)
        raise ValueError("AI failed to generate lesson") from exc

    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as exc:
        logger.error("AI returned invalid JSON for lesson: %s", exc)
        raise ValueError("AI failed to generate lesson") from exc

    # Build 5-phase sub-models from AI response (if present)
    warm_up = None
    if result.get("warm_up"):
        warm_up = WarmUp(**result["warm_up"])

    presentation = None
    if result.get("presentation"):
        presentation = Presentation(**result["presentation"])

    controlled_practice = None
    if result.get("controlled_practice"):
        controlled_practice = ControlledPractice(**result["controlled_practice"])

    free_practice = None
    if result.get("free_practice"):
        free_practice = FreePractice(**result["free_practice"])

    wrap_up = None
    if result.get("wrap_up"):
        wrap_up = WrapUp(**result["wrap_up"])

    lesson = LessonContent(
        objective=result.get("objective", ""),
        polish_explanation=result.get("polish_explanation", ""),
        exercises=result.get("exercises", []),
        conversation_prompts=result.get("conversation_prompts", []),
        win_activity=result.get("win_activity", ""),
        difficulty=result.get("difficulty", current_level),
        warm_up=warm_up,
        presentation=presentation,
        controlled_practice=controlled_practice,
        free_practice=free_practice,
        wrap_up=wrap_up,
    )

    # Attach skill_tags as extra attribute for the caller to store
    lesson._skill_tags = result.get("skill_tags", [])

    # Attach teacher guidance notes if the AI generated them
    lesson._teacher_guidance = result.get("teacher_guidance", None)

    return lesson
