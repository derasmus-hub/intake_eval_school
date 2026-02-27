# Learning Loop: Path to Perfection

**Based on E2E test run analysis — February 2026**

---

## What the E2E Test Revealed

Your test ran 3 learning cycles and proved the core loop works: session confirmed → lesson generated → quiz generated → quiz submitted → plan updated → next lesson adapts. That's a real achievement. But the diff between test runs exposes **7 specific issues** preventing this loop from being production-quality. This guide addresses each one with exact code fixes.

---

## Issue 1: `session_automation.py` Doesn't Use the Rich Lesson Generator

**Severity: CRITICAL — This is the single biggest gap**

You built a sophisticated `lesson_generator.py` with 12 input parameters covering teacher observations, CEFR history, learning DNA, L1 interference patterns, vocabulary due for review, and adaptive difficulty profiles. But `session_automation.py` doesn't use it. Instead, it reimplements a simpler version that calls `ai_chat()` directly with only 8 template variables — losing all the intelligence.

**Evidence from the diff:** Lessons 1 and 2 both covered articles because the AI had no teacher observations, no learning DNA, and no difficulty profile to guide it toward different topics.

**What `build_lesson_for_session()` currently passes to the AI:**
- `session_number`, `current_level`, `profile_summary`
- `priorities`, `gaps`, `progress_history`
- `previous_topics`, `recall_weak_areas`

**What `lesson_generator.generate_lesson()` also supports but is never used in the automated flow:**
- `teacher_session_notes` — notes from the last class
- `teacher_skill_observations` — skill scores from recent sessions
- `cefr_history` — how the student's level has progressed
- `vocabulary_due_for_review` — SRS-based vocab needing review
- `difficulty_profile` — per-skill simplify/challenge/maintain
- `learning_dna` — learning speed, modality strengths, error patterns, frustration flags
- `l1_interference_profile` — Polish interference patterns to target

### Fix

Replace the direct `ai_chat()` call in `session_automation.py:build_lesson_for_session()` with a call to `lesson_generator.generate_lesson()`, and gather the additional context data.

**In `session_automation.py`, add these context-gathering functions:**

```python
async def get_teacher_observations(db, student_id: int) -> list[dict]:
    """Get recent teacher skill observations."""
    cursor = await db.execute(
        """SELECT skill, score, cefr_level, notes
           FROM session_skill_observations
           WHERE student_id = ?
           ORDER BY created_at DESC
           LIMIT 10""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_cefr_history(db, student_id: int) -> list[dict]:
    """Get CEFR level progression."""
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, reading_level,
                  confidence, source, recorded_at
           FROM cefr_history
           WHERE student_id = ?
           ORDER BY recorded_at DESC
           LIMIT 5""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_vocabulary_due(db, student_id: int) -> list[str]:
    """Get vocabulary cards due for review (SM-2 schedule)."""
    cursor = await db.execute(
        """SELECT word FROM vocabulary_cards
           WHERE student_id = ? AND next_review <= datetime('now')
           ORDER BY next_review ASC
           LIMIT 10""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [r["word"] for r in rows]


async def get_learning_dna(db, student_id: int) -> dict | None:
    """Get latest learning DNA profile."""
    cursor = await db.execute(
        """SELECT dna_json FROM learning_dna
           WHERE student_id = ?
           ORDER BY updated_at DESC
           LIMIT 1""",
        (student_id,)
    )
    row = await cursor.fetchone()
    if row and row["dna_json"]:
        dna = row["dna_json"]
        return json.loads(dna) if isinstance(dna, str) else dna
    return None


async def get_teacher_notes_for_lesson(db, student_id: int) -> str | None:
    """Get the most recent teacher session notes."""
    cursor = await db.execute(
        """SELECT teacher_notes FROM sessions
           WHERE student_id = ? AND teacher_notes IS NOT NULL
           ORDER BY scheduled_at DESC
           LIMIT 1""",
        (student_id,)
    )
    row = await cursor.fetchone()
    return row["teacher_notes"] if row else None
```

**Then replace `build_lesson_for_session()` lines 227–260 (the direct AI call) with:**

```python
from app.services.lesson_generator import generate_lesson

# Gather rich context
teacher_obs = await get_teacher_observations(db, student_id)
cefr_hist = await get_cefr_history(db, student_id)
vocab_due = await get_vocabulary_due(db, student_id)
dna = await get_learning_dna(db, student_id)
teacher_notes = await get_teacher_notes_for_lesson(db, student_id)

# Call the REAL lesson generator with ALL context
lesson = await generate_lesson(
    student_id=student_id,
    profile=profile,
    progress_history=context["progress_history"],
    session_number=session_number,
    current_level=current_level,
    previous_topics=context["previous_topics"],
    recall_weak_areas=context["quiz_weak_areas"],
    teacher_session_notes=teacher_notes,
    teacher_skill_observations=teacher_obs,
    cefr_history=cefr_hist,
    vocabulary_due_for_review=vocab_due,
    learning_dna=dna,
)

lesson_json = {
    "objective": lesson.objective,
    "polish_explanation": lesson.polish_explanation,
    "exercises": lesson.exercises,
    "conversation_prompts": lesson.conversation_prompts,
    "win_activity": lesson.win_activity,
    "difficulty": lesson.difficulty,
}
# Add 5-phase structure
if lesson.warm_up:
    lesson_json["warm_up"] = lesson.warm_up.dict()
if lesson.presentation:
    lesson_json["presentation"] = lesson.presentation.dict()
if lesson.controlled_practice:
    lesson_json["controlled_practice"] = lesson.controlled_practice.dict()
if lesson.free_practice:
    lesson_json["free_practice"] = lesson.free_practice.dict()
if lesson.wrap_up:
    lesson_json["wrap_up"] = lesson.wrap_up.dict()

# Add skill tags if generated
if hasattr(lesson, '_skill_tags'):
    lesson_json["skill_tags"] = lesson._skill_tags
```

---

## Issue 2: Skill Tags Are Free-Form — Aggregation Is Meaningless

**Severity: CRITICAL**

**Evidence from the diff:**
- Quiz 1 skill tags: `grammar_articles_indefinite`, `grammar_articles_definite`, `vocabulary_articles`
- Quiz 2 skill tags: `articles_a_an_usage`, `articles_the_usage`
- Quiz 3 skill tags: `vocabulary_business`, `grammar_ordering`

These are all AI-generated free-text strings. The plan updater aggregates accuracy by skill tag, but `grammar_articles_indefinite` and `articles_a_an_usage` are **never linked** even though they test the same knowledge. When the system calculates "how is this student doing on articles?", it sees 3 separate 0% skills instead of one consolidated picture.

### Fix: Define a Skill Taxonomy and Constrain the AI

**Step A: Create a skill taxonomy file `app/data/skill_taxonomy.json`:**

```json
{
  "grammar": {
    "articles": ["articles_definite", "articles_indefinite", "articles_zero"],
    "present_simple": ["present_simple_affirmative", "present_simple_negative", "present_simple_questions"],
    "present_continuous": ["present_continuous_form", "present_continuous_usage"],
    "past_simple": ["past_simple_regular", "past_simple_irregular"],
    "sentence_structure": ["word_order", "subject_verb_agreement"]
  },
  "vocabulary": {
    "business": ["business_basic", "business_meetings", "business_email"],
    "everyday": ["everyday_objects", "everyday_actions", "everyday_descriptions"],
    "academic": ["academic_basic"]
  },
  "pronunciation": {
    "th_sounds": ["th_voiced", "th_voiceless"],
    "w_v_distinction": ["w_v_minimal_pairs"],
    "word_stress": ["word_stress_patterns"]
  },
  "conversation": {
    "basic_descriptions": ["describe_people", "describe_places"],
    "business_contexts": ["business_intro", "business_phone"]
  }
}
```

**Step B: Add the taxonomy to both prompt files.**

In `prompts/session_quiz.yaml`, add to the system prompt:

```
SKILL TAG RULES (CRITICAL):
You MUST use ONLY these skill tags for questions. Do NOT invent new ones.

Grammar tags: articles_definite, articles_indefinite, articles_zero,
present_simple_affirmative, present_simple_negative, present_simple_questions,
present_continuous_form, present_continuous_usage, past_simple_regular,
past_simple_irregular, word_order, subject_verb_agreement

Vocabulary tags: business_basic, business_meetings, business_email,
everyday_objects, everyday_actions, everyday_descriptions

Pronunciation tags: th_voiced, th_voiceless, w_v_minimal_pairs, word_stress_patterns

Conversation tags: describe_people, describe_places, business_intro, business_phone

Each question MUST have exactly one skill_tag from this list.
```

Do the same in `prompts/lesson_generator.yaml` for the `skill_tags` array.

**Step C: Add a normalization function in `app/services/quiz_scorer.py`:**

```python
SKILL_ALIASES = {
    "grammar_articles": "articles_definite",
    "articles_a_an_usage": "articles_indefinite",
    "articles_the_usage": "articles_definite",
    "grammar_articles_indefinite": "articles_indefinite",
    "grammar_articles_definite": "articles_definite",
    "grammar_articles_sentence_structure": "word_order",
    "vocabulary_business": "business_basic",
    "grammar_ordering": "word_order",
    "grammar_sentence_order": "word_order",
    "sentence_structure": "word_order",
    "translation_business": "business_basic",
}

def normalize_skill_tag(tag: str) -> str:
    """Map free-form AI skill tags to canonical taxonomy tags."""
    return SKILL_ALIASES.get(tag, tag)
```

Then call `normalize_skill_tag()` in `score_quiz_attempt()` before storing each `quiz_attempt_item`.

---

## Issue 3: 30-Second Timeout Causes First-Call Failures

**Severity: HIGH**

**Evidence from the diff:**
```
Lesson generation: failed (timeout on initial session; lesson generated in-cycle instead)
```

The first AI call in a fresh container is a cold start. OpenAI's API can take 10–15s just for the first connection, plus the actual generation time. A 30-second timeout is too tight.

### Fix

In `session_automation.py`, increase the timeout and add retry logic:

```python
async def on_session_confirmed(db, session_id, teacher_id):
    result = {"lesson": {"status": STATUS_PENDING}, "quiz": {"status": STATUS_PENDING}}

    # Attempt lesson generation with retry
    for attempt in range(2):  # Max 2 attempts
        try:
            timeout = 60.0 if attempt == 0 else 45.0  # Generous first attempt
            lesson_result = await asyncio.wait_for(
                build_lesson_for_session(db, session_id),
                timeout=timeout
            )
            if lesson_result.get("success"):
                result["lesson"] = {
                    "status": STATUS_COMPLETED,
                    "artifact_id": lesson_result.get("artifact_id"),
                }
                break
            else:
                result["lesson"] = {"status": STATUS_FAILED, "error": lesson_result.get("error")}
        except asyncio.TimeoutError:
            if attempt == 0:
                logger.warning(f"Lesson gen attempt 1 timed out for session {session_id}, retrying...")
                continue
            result["lesson"] = {"status": STATUS_FAILED, "error": "Generation timed out after retry"}

    # ... quiz generation follows same pattern
```

---

## Issue 4: Quiz Scoring Is Exact-Match Only

**Severity: HIGH**

The `score_question()` function in `quiz_scorer.py` uses `normalize_answer()` which just does `.strip().lower()`. For real students, this means:

- "She is a teacher" vs "she's a teacher" → **WRONG** (contractions)
- "the meeting" vs "a meeting" → **WRONG** (valid alternate articles)
- "Ona jest nauczycielką" translated as "She is teacher" → **WRONG** (missing article, but correct for a Polish speaker learning)

Translation and reorder questions will almost always score 0% for real students, skewing the plan updater toward "everything is weak."

### Fix: Add Fuzzy Matching and AI-Assisted Grading

**Step A: Improve `score_question()` for simple cases:**

```python
def score_question(question, student_answer):
    q_type = question.get("type", "")
    correct_answer = question.get("correct_answer", "")
    student_norm = normalize_answer(student_answer)
    correct_norm = normalize_answer(correct_answer)

    is_correct = False

    if q_type == "multiple_choice":
        is_correct = student_norm == correct_norm

    elif q_type == "true_false":
        # ... existing logic is fine

    elif q_type == "fill_blank":
        # Allow minor variations
        is_correct = student_norm == correct_norm
        if not is_correct:
            # Strip articles for comparison (common Polish learner issue)
            student_stripped = student_norm.lstrip("a ").lstrip("an ").lstrip("the ")
            correct_stripped = correct_norm.lstrip("a ").lstrip("an ").lstrip("the ")
            if student_stripped == correct_stripped and len(correct_stripped) > 2:
                is_correct = True  # Partial credit: right word, wrong article

    elif q_type in ("translate", "reorder"):
        # These need AI grading — mark for async evaluation
        is_correct = student_norm == correct_norm
        # Flag for AI re-evaluation
        return {
            "is_correct": is_correct,
            "expected_answer": correct_answer,
            "needs_ai_grading": True,
            "explanation": question.get("explanation", ""),
        }

    else:
        is_correct = student_norm == correct_norm

    return {
        "is_correct": is_correct,
        "expected_answer": correct_answer,
        "needs_ai_grading": False,
        "explanation": question.get("explanation", ""),
    }
```

**Step B: Add an AI grading function for translation/reorder (call asynchronously after scoring):**

```python
async def ai_grade_open_answer(question_text, expected, student_answer, student_level):
    """Use AI to grade translation/reorder answers with partial credit."""
    prompt = f"""Grade this English learner's answer. Student level: {student_level}

Question: {question_text}
Expected answer: {expected}
Student's answer: {student_answer}

Respond with JSON:
{{"is_correct": true/false, "partial_credit": 0.0-1.0, "feedback": "brief explanation"}}

Rules:
- Accept grammatically correct alternatives (contractions, synonyms)
- For A1 students, accept answers missing articles if the core meaning is correct
- partial_credit: 1.0 = perfect, 0.5 = meaning correct but grammar errors, 0.0 = wrong
"""
    result = await ai_chat(
        messages=[{"role": "system", "content": "You are a fair English teacher grading A1-C2 students."},
                  {"role": "user", "content": prompt}],
        use_case="assessment",
        temperature=0.1,
        json_mode=True,
    )
    return json.loads(result)
```

---

## Issue 5: Plan Updater Only Sees Previous Plan Summary, Not Structured Data

**Severity: HIGH**

**In `plan_updater.py` line 210-215:**
```python
previous_plan_summary = "No previous plan exists."
if previous_plan:
    plan_json = previous_plan.get("plan_json", {})
    previous_plan_summary = plan_json.get("summary", ...)
```

The AI only sees a 2-sentence text summary of the previous plan. It doesn't see the structured `top_weaknesses`, `goals_next_2_weeks`, `recommended_drills`, or `difficulty_adjustment` from the last plan version. This means the plan updater can't tell if goals were met or if the same weaknesses persist.

### Fix

Pass the full previous plan JSON to the prompt, not just the summary:

```python
# In update_learning_plan(), replace lines 210-215 with:
previous_plan_text = "No previous plan exists."
if previous_plan:
    plan_json = previous_plan.get("plan_json", {})
    if isinstance(plan_json, str):
        plan_json = json.loads(plan_json)

    # Pass structured data, not just summary
    previous_plan_text = f"""Summary: {plan_json.get('summary', 'N/A')}
Goals: {json.dumps(plan_json.get('goals_next_2_weeks', []))}
Top Weaknesses: {json.dumps(plan_json.get('top_weaknesses', []))}
Difficulty Adjustment: {json.dumps(plan_json.get('difficulty_adjustment', {}))}
Grammar Focus: {json.dumps(plan_json.get('grammar_focus', {}))}
Vocabulary Focus: {json.dumps(plan_json.get('vocabulary_focus', {}))}"""
```

And update `prompts/plan_update.yaml` to tell the AI how to use this:

```
PREVIOUS PLAN:
{previous_plan_summary}

INSTRUCTIONS FOR USING PREVIOUS PLAN:
- Check if previous goals were achieved based on quiz scores
- If a weakness from the previous plan is still below 60%, KEEP it as high priority
- If a weakness improved above 70%, move it to maintenance and add a new focus area
- Never drop more than 1 focus area per update (continuity matters)
```

---

## Issue 6: Lesson Topic Repetition Despite "Don't Repeat" Rules

**Severity: HIGH**

**Evidence from the diff:**
- Lesson 1: Articles (a/an/the)
- Lesson 2: Articles + pronunciation — **still articles as primary topic**
- Lesson 3: Finally shifted to present tenses

The prompt says "NEVER repeat the same topic area as the previous lesson unless the student scored below 50%." But the AI repeated articles anyway. Why? Because:

1. The `previous_topics` list is extracted from `topics_json` and `lesson_json["objective"][:50]` — these are free-form strings, not structured topic identifiers. The AI sees "To introduce and practice the use of English articles" as a string, not as a `grammar.articles` tag it can match against.

2. The progress_history has no score data yet when generating lesson 2 (the quiz for lesson 1 hasn't been taken yet — quizzes are pre-class, so quiz 1 is taken *before* session 2, not after session 1).

### Fix A: Pass structured topic data, not free-form strings

In `session_automation.py:get_student_context()`, replace the previous_topics extraction (lines 104-132) with:

```python
# Get previous lesson skill tags (structured, not free-form)
cursor = await db.execute(
    """SELECT lst.tag_type, lst.tag_value, lst.cefr_level, la.created_at
       FROM lesson_skill_tags lst
       JOIN lesson_artifacts la ON la.id = lst.lesson_id
       WHERE la.student_id = ?
       ORDER BY la.created_at DESC
       LIMIT 10""",
    (student_id,)
)
tag_rows = await cursor.fetchall()
context["previous_skill_tags"] = [
    f"{r['tag_type']}→{r['tag_value']} ({r['cefr_level']})"
    for r in tag_rows
]

# Also get objectives as backup
cursor = await db.execute(
    """SELECT lesson_json FROM lesson_artifacts
       WHERE student_id = ?
       ORDER BY created_at DESC
       LIMIT 3""",
    (student_id,)
)
for row in await cursor.fetchall():
    lesson = json.loads(row["lesson_json"]) if isinstance(row["lesson_json"], str) else row["lesson_json"]
    if lesson.get("objective"):
        context["previous_topics"].append(lesson["objective"][:80])
```

### Fix B: Include quiz scores alongside previous topics

Update the prompt template to show which topics have been tested and what scores they got:

```
PREVIOUS LESSONS AND THEIR QUIZ RESULTS:
{previous_lessons_with_scores}
```

And build this in the code:

```python
# After gathering context, build lessons-with-scores summary
cursor = await db.execute(
    """SELECT la.id, la.lesson_json, la.topics_json,
              qa.score as quiz_score
       FROM lesson_artifacts la
       LEFT JOIN next_quizzes nq ON nq.derived_from_lesson_artifact_id = la.id
       LEFT JOIN quiz_attempts qa ON qa.quiz_id = nq.id
       WHERE la.student_id = ?
       ORDER BY la.created_at DESC
       LIMIT 5""",
    (student_id,)
)
rows = await cursor.fetchall()
lessons_summary = []
for row in rows:
    lesson = json.loads(row["lesson_json"]) if isinstance(row["lesson_json"], str) else row["lesson_json"]
    score = f"{int(row['quiz_score'] * 100)}%" if row["quiz_score"] is not None else "not yet tested"
    lessons_summary.append(f"- {lesson.get('objective', 'Unknown')[:60]} → Quiz: {score}")

context["previous_lessons_with_scores"] = "\n".join(lessons_summary) or "No previous lessons."
```

---

## Issue 7: No Session Completion / Post-Class Hook

**Severity: MEDIUM**

Sessions go from `requested` → `confirmed` but never to `completed`. There's no `on_session_completed()` hook. This means:

- Teacher notes added after class don't trigger plan updates (the `on_teacher_notes_added` hook exists but is only called if someone manually hits the endpoint)
- The progress table stays empty (no lesson completion tracking in the automated flow)
- Learning points are never extracted from completed lessons

### Fix: Add a session completion endpoint and wire up the hooks

**In `app/routes/scheduling.py`, add:**

```python
@router.post("/api/teacher/sessions/{session_id}/complete")
async def complete_session(
    session_id: int,
    body: SessionCompleteRequest,  # teacher_notes, homework, session_summary
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    # Verify teacher owns this session
    session = await get_session(db, session_id)
    if session["teacher_id"] != current_user["id"]:
        raise HTTPException(403, "Not your session")

    # Update session
    await db.execute(
        """UPDATE sessions
           SET status = 'completed',
               teacher_notes = ?,
               homework = ?,
               session_summary = ?
           WHERE id = ?""",
        (body.teacher_notes, body.homework, body.session_summary, session_id)
    )
    await db.commit()

    student_id = session["student_id"]

    # Trigger post-class hooks
    # 1. Extract learning points from lesson
    artifact = await get_session_lesson(db, session_id)
    if artifact and artifact.get("lesson_json"):
        from app.services.learning_point_extractor import extract_learning_points
        points = await extract_learning_points(
            artifact["lesson_json"],
            session.get("current_level", "A1")
        )
        for point in points:
            await db.execute(
                """INSERT INTO learning_points
                   (student_id, lesson_id, point_type, content,
                    polish_explanation, example_sentence, importance_weight)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (student_id, artifact["id"], point["point_type"],
                 point["content"], point["polish_explanation"],
                 point["example_sentence"], point["importance_weight"])
            )
        await db.commit()

    # 2. Update learning plan if notes are substantial
    from app.services.plan_updater import on_teacher_notes_added
    await on_teacher_notes_added(db, student_id, session_id)

    return {"status": "completed", "learning_points_extracted": len(points)}
```

---

## Summary: Priority Order for Implementation

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | Use rich `lesson_generator.generate_lesson()` in session automation | 2 hours | Unlocks teacher obs, DNA, L1, vocab review |
| 2 | Standardize skill tag taxonomy | 1 hour | Makes all aggregation meaningful |
| 3 | Increase timeout + add retry | 15 min | Eliminates cold-start failures |
| 4 | Pass full previous plan to updater | 30 min | Plan continuity across versions |
| 5 | Pass structured topics + scores to lesson gen | 1 hour | Stops topic repetition |
| 6 | Add session completion hook | 2 hours | Closes the post-class gap |
| 7 | Improve quiz scoring (fuzzy + AI grading) | 3 hours | Accurate scores for real students |

**Total estimated effort: ~10 hours of focused work.**

After implementing all 7 fixes, re-run the E2E test and verify:

1. Each lesson covers a **different primary topic** across 3 cycles
2. Skill tags are **consistent** across all quizzes (same tag = same skill)
3. No timeout failures on first session confirmation
4. Plan v2 explicitly references whether v1 goals were met
5. Plan v3 shows clear progression from v1→v2→v3 with measurable targets
6. Learning points are extracted after session completion
7. Teacher observations appear in lesson 2 and 3 context

---

## Appendix: What's Already Working Well

These aspects of the loop are solid and should not change:

- **5-phase lesson model** (warm-up → presentation → controlled practice → free practice → wrap-up) — well-structured and pedagogically sound
- **Quiz derived from lesson artifacts** via `derived_from_lesson_artifact_id` FK — clean traceability
- **Plan versioning** (v1→v2→v3) triggered by `on_quiz_submitted()` — correct architecture
- **SM-2 spaced repetition** on learning points and vocabulary cards — the algorithm is correctly implemented
- **Polish L1 interference awareness** in the prompt design — unique competitive advantage
- **Fail-soft pattern** in `on_session_confirmed()` — generation errors don't block session confirmation
- **Idempotency guards** on both lesson and quiz generation — safe to retry
- **Score progression** (0% → 17% → 40%) proves the plan updates are influencing lesson content
