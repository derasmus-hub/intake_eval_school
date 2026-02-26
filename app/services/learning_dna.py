import json
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter

from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)


def _safe_json_parse(raw, default=None):
    """Parse a JSON string from a DB column, returning default on failure."""
    if not raw:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


async def compute_learning_dna(student_id: int, db, trigger_event: str = "manual") -> dict:
    """
    Compute a full Learning DNA profile for a student.

    Queries multiple tables to build a living, evolving model that captures
    how this student learns, what they struggle with, and where they excel.
    Returns the DNA dict and persists it to the learning_dna table.
    """
    logger.info("Computing Learning DNA for student_id=%s trigger=%s", student_id, trigger_event)

    # ── Gather raw data from all sources ──────────────────────────────────

    # learning_points (SM-2 data)
    cursor = await db.execute(
        "SELECT ease_factor, interval_days, repetitions, times_reviewed, "
        "last_recall_score, point_type FROM learning_points WHERE student_id = ?",
        (student_id,),
    )
    learning_points_rows = await cursor.fetchall()

    # vocabulary_cards
    cursor = await db.execute(
        "SELECT ease_factor, repetitions, next_review, review_count, created_at "
        "FROM vocabulary_cards WHERE student_id = ?",
        (student_id,),
    )
    vocab_rows = await cursor.fetchall()

    # session_skill_observations
    cursor = await db.execute(
        "SELECT skill, score, cefr_level, notes "
        "FROM session_skill_observations WHERE student_id = ? ORDER BY created_at",
        (student_id,),
    )
    skill_obs_rows = await cursor.fetchall()

    # progress (lesson completion data)
    cursor = await db.execute(
        "SELECT score, completed_at, areas_improved, areas_struggling "
        "FROM progress WHERE student_id = ? ORDER BY completed_at",
        (student_id,),
    )
    progress_rows = await cursor.fetchall()

    # quiz_attempts
    cursor = await db.execute(
        "SELECT score, submitted_at FROM quiz_attempts WHERE student_id = ? ORDER BY submitted_at",
        (student_id,),
    )
    quiz_rows = await cursor.fetchall()

    # writing_submissions
    cursor = await db.execute(
        "SELECT cefr_level, overall_score FROM writing_submissions WHERE student_id = ?",
        (student_id,),
    )
    writing_rows = await cursor.fetchall()

    # recall_sessions
    cursor = await db.execute(
        "SELECT overall_score, weak_areas, status FROM recall_sessions WHERE student_id = ?",
        (student_id,),
    )
    recall_rows = await cursor.fetchall()

    # game_scores
    cursor = await db.execute(
        "SELECT game_type, score, played_at FROM game_scores WHERE student_id = ?",
        (student_id,),
    )
    game_rows = await cursor.fetchall()

    # cefr_history
    cursor = await db.execute(
        "SELECT level, recorded_at FROM cefr_history WHERE student_id = ? ORDER BY recorded_at",
        (student_id,),
    )
    cefr_rows = await cursor.fetchall()

    # users (current profile)
    cursor = await db.execute(
        "SELECT current_level, goals, problem_areas FROM users WHERE id = ?",
        (student_id,),
    )
    user_row = await cursor.fetchone()

    # daily_challenges
    cursor = await db.execute(
        "SELECT progress, completed, challenge_type FROM daily_challenges WHERE student_id = ?",
        (student_id,),
    )
    challenge_rows = await cursor.fetchall()

    # lessons (topic history)
    cursor = await db.execute(
        "SELECT content, objective FROM lessons WHERE student_id = ?",
        (student_id,),
    )
    lesson_rows = await cursor.fetchall()

    # xp_log (for activity streak analysis)
    cursor = await db.execute(
        "SELECT created_at FROM xp_log WHERE student_id = ? ORDER BY created_at DESC",
        (student_id,),
    )
    xp_log_rows = await cursor.fetchall()

    # ── Compute DNA dimensions ────────────────────────────────────────────

    # (a) Learning Speed
    learning_speed = _compute_learning_speed(learning_points_rows)

    # (b) Modality Strengths
    modality_strengths = _compute_modality_strengths(skill_obs_rows)

    # (c) Vocabulary Acquisition
    vocabulary_acquisition = _compute_vocabulary_acquisition(vocab_rows)

    # (d) Engagement Patterns
    engagement_patterns = _compute_engagement_patterns(
        progress_rows, game_rows, challenge_rows, recall_rows
    )

    # (e) Optimal Challenge Level
    optimal_challenge_level = _compute_optimal_challenge_level(progress_rows)

    # (f) Frustration Indicators
    frustration_indicators = _compute_frustration_indicators(
        progress_rows, learning_points_rows, xp_log_rows
    )

    # (g) Error Patterns
    error_patterns = _compute_error_patterns(progress_rows)

    # (h) CEFR Trajectory
    cefr_trajectory = _compute_cefr_trajectory(cefr_rows, user_row)

    # ── Assemble the full DNA dict ────────────────────────────────────────

    dna = {
        "student_id": student_id,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "learning_speed": learning_speed,
        "modality_strengths": modality_strengths,
        "vocabulary_acquisition": vocabulary_acquisition,
        "engagement_patterns": engagement_patterns,
        "optimal_challenge_level": optimal_challenge_level,
        "frustration_indicators": frustration_indicators,
        "error_patterns": error_patterns,
        "cefr_trajectory": cefr_trajectory,
    }

    # ── Persist to learning_dna table ─────────────────────────────────────

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM learning_dna WHERE student_id = ?",
        (student_id,),
    )
    count_row = await cursor.fetchone()
    version_number = (count_row["cnt"] if count_row else 0) + 1

    await db.execute(
        "INSERT INTO learning_dna (student_id, dna_json, version, trigger_event) VALUES (?, ?, ?, ?)",
        (student_id, json.dumps(dna), version_number, trigger_event),
    )
    await db.commit()

    logger.info(
        "Learning DNA v%d saved for student_id=%s", version_number, student_id
    )

    return dna


# ── Dimension computation helpers ─────────────────────────────────────────


def _compute_learning_speed(learning_points_rows) -> dict:
    """
    Average repetitions to mastery from learning_points where repetitions >= 5.
    Classification: fast (<8), moderate (8-15), slow (>15).
    """
    mastered = [row["repetitions"] for row in learning_points_rows if row["repetitions"] >= 5]

    if not mastered:
        return {
            "avg_repetitions_to_mastery": None,
            "classification": "unknown",
        }

    avg_reps = sum(mastered) / len(mastered)

    if avg_reps < 8:
        classification = "fast"
    elif avg_reps <= 15:
        classification = "moderate"
    else:
        classification = "slow"

    return {
        "avg_repetitions_to_mastery": round(avg_reps, 2),
        "classification": classification,
    }


def _compute_modality_strengths(skill_obs_rows) -> dict:
    """
    Average score per skill from session_skill_observations.
    Skills: grammar, vocabulary, speaking, reading, writing, listening.
    Thresholds: >=75 strong, >=50 moderate, <50 weak.
    """
    target_skills = ["grammar", "vocabulary", "speaking", "reading", "writing", "listening"]
    skill_scores: dict[str, list[float]] = {s: [] for s in target_skills}

    for row in skill_obs_rows:
        skill = (row["skill"] or "").lower().strip()
        score = row["score"]
        if skill in skill_scores and score is not None:
            skill_scores[skill].append(score)

    result = {}
    for skill in target_skills:
        scores = skill_scores[skill]
        if not scores:
            result[skill] = {"avg_score": None, "classification": "no_data"}
            continue

        avg = sum(scores) / len(scores)
        if avg >= 75:
            classification = "strong"
        elif avg >= 50:
            classification = "moderate"
        else:
            classification = "weak"

        result[skill] = {
            "avg_score": round(avg, 2),
            "classification": classification,
        }

    return result


def _compute_vocabulary_acquisition(vocab_rows) -> dict:
    """
    Vocabulary acquisition metrics from vocabulary_cards.
    """
    total_words = len(vocab_rows)
    mastered_words = sum(1 for row in vocab_rows if row["repetitions"] >= 5)

    # Words created in last 30 days (approximate weeks ~4)
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_words = 0
    for row in vocab_rows:
        created = row["created_at"] if "created_at" in row.keys() else None
        if created and str(created) >= thirty_days_ago:
            recent_words += 1
    words_per_week = round(recent_words / 4, 2)

    # Average ease factor
    ease_factors = [row["ease_factor"] for row in vocab_rows if row["ease_factor"] is not None]
    avg_ease_factor = round(sum(ease_factors) / len(ease_factors), 2) if ease_factors else None

    # Retention rate
    retention_rate = round(mastered_words / total_words, 4) if total_words > 0 else 0.0

    return {
        "total_words": total_words,
        "mastered_words": mastered_words,
        "words_per_week": words_per_week,
        "avg_ease_factor": avg_ease_factor,
        "retention_rate": retention_rate,
    }


def _compute_engagement_patterns(progress_rows, game_rows, challenge_rows, recall_rows) -> dict:
    """
    Engagement metrics across lessons, games, challenges, and recall sessions.
    """
    # Lessons completed and avg score
    lessons_completed = len(progress_rows)
    scores = [row["score"] for row in progress_rows if row["score"] is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    # Score trend: compare last 5 avg vs previous 5 avg
    score_trend = "stable"
    if len(scores) >= 10:
        recent_5 = scores[-5:]
        previous_5 = scores[-10:-5]
        recent_avg = sum(recent_5) / len(recent_5)
        previous_avg = sum(previous_5) / len(previous_5)
        diff = recent_avg - previous_avg
        if diff > 3:
            score_trend = "improving"
        elif diff < -3:
            score_trend = "declining"
        else:
            score_trend = "stable"
    elif len(scores) >= 6:
        mid = len(scores) // 2
        recent_half = scores[mid:]
        previous_half = scores[:mid]
        recent_avg = sum(recent_half) / len(recent_half)
        previous_avg = sum(previous_half) / len(previous_half)
        diff = recent_avg - previous_avg
        if diff > 3:
            score_trend = "improving"
        elif diff < -3:
            score_trend = "declining"
        else:
            score_trend = "stable"

    # Games played
    games_played = len(game_rows)

    # Challenges completed
    challenges_completed = sum(1 for row in challenge_rows if row["completed"])

    # Review completion rate
    total_recall = len(recall_rows)
    completed_recall = sum(1 for row in recall_rows if row["status"] == "completed")
    review_completion_rate = round(completed_recall / total_recall, 4) if total_recall > 0 else 0.0

    return {
        "lessons_completed": lessons_completed,
        "avg_score": avg_score,
        "score_trend": score_trend,
        "games_played": games_played,
        "challenges_completed": challenges_completed,
        "review_completion_rate": review_completion_rate,
    }


def _compute_optimal_challenge_level(progress_rows) -> dict:
    """
    Find the difficulty band where scores cluster in the 70-85% flow zone.
    """
    scores = [row["score"] for row in progress_rows if row["score"] is not None]

    if not scores:
        return {
            "sweet_spot_min": None,
            "sweet_spot_max": None,
            "current_avg_score": None,
            "recommendation": "maintain",
        }

    current_avg = sum(scores) / len(scores)

    # Find scores in the flow zone (70-85)
    flow_scores = [s for s in scores if 70 <= s <= 85]

    if flow_scores:
        sweet_spot_min = round(min(flow_scores), 2)
        sweet_spot_max = round(max(flow_scores), 2)
    else:
        sweet_spot_min = 70.0
        sweet_spot_max = 85.0

    # Recommendation based on where current average sits
    if current_avg > 85:
        recommendation = "increase_difficulty"
    elif current_avg < 70:
        recommendation = "decrease_difficulty"
    else:
        recommendation = "maintain"

    return {
        "sweet_spot_min": sweet_spot_min,
        "sweet_spot_max": sweet_spot_max,
        "current_avg_score": round(current_avg, 2),
        "recommendation": recommendation,
    }


def _compute_frustration_indicators(progress_rows, learning_points_rows, xp_log_rows) -> dict:
    """
    Detect signs of student frustration:
    - Declining scores (last 3 avg < previous 3 avg)
    - Skipped reviews (overdue learning points never reviewed)
    - Low engagement streak (consecutive days without activity)
    """
    # Declining scores: compare last 3 vs previous 3
    scores = [row["score"] for row in progress_rows if row["score"] is not None]
    declining_scores = False
    if len(scores) >= 6:
        last_3_avg = sum(scores[-3:]) / 3
        prev_3_avg = sum(scores[-6:-3]) / 3
        declining_scores = last_3_avg < prev_3_avg

    # Skipped reviews: learning_points where times_reviewed == 0 and overdue
    now_iso = datetime.now(timezone.utc).isoformat()
    skipped_reviews = 0
    for row in learning_points_rows:
        if row["times_reviewed"] == 0:
            next_review = row.get("next_review_date") if "next_review_date" in row.keys() else None
            if next_review and str(next_review) < now_iso:
                skipped_reviews += 1

    # Low engagement streak: consecutive days without activity from xp_log
    low_engagement_streak = _compute_inactivity_streak(xp_log_rows)

    return {
        "declining_scores": declining_scores,
        "skipped_reviews": skipped_reviews,
        "low_engagement_streak": low_engagement_streak,
    }


def _compute_inactivity_streak(xp_log_rows) -> int:
    """
    Count consecutive days (backwards from today) with no xp_log entries.
    """
    if not xp_log_rows:
        return 0

    # Collect unique dates with activity
    active_dates = set()
    for row in xp_log_rows:
        created = row["created_at"]
        if created:
            try:
                dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                active_dates.add(dt.date())
            except (ValueError, TypeError):
                # Try simpler parsing for date-only or other formats
                try:
                    dt = datetime.strptime(str(created)[:10], "%Y-%m-%d")
                    active_dates.add(dt.date())
                except (ValueError, TypeError):
                    pass

    if not active_dates:
        return 0

    # Count consecutive days backwards from today with no activity
    today = datetime.now(timezone.utc).date()
    streak = 0
    check_date = today
    while check_date not in active_dates:
        streak += 1
        check_date -= timedelta(days=1)
        # Safety: don't look back more than 365 days
        if streak > 365:
            break

    return streak


def _compute_error_patterns(progress_rows) -> list:
    """
    Top 5 most frequent areas_struggling from progress records.
    """
    all_struggles: list[str] = []
    for row in progress_rows:
        raw = row["areas_struggling"]
        areas = _safe_json_parse(raw, default=[])
        if isinstance(areas, list):
            for area in areas:
                if isinstance(area, str) and area.strip():
                    all_struggles.append(area.strip())

    if not all_struggles:
        return []

    counter = Counter(all_struggles)
    top_5 = counter.most_common(5)
    return [{"area": area, "count": count} for area, count in top_5]


def _compute_cefr_trajectory(cefr_rows, user_row) -> dict:
    """
    CEFR progression trajectory from cefr_history and current user level.
    """
    current_level = user_row["current_level"] if user_row else "unknown"

    levels_list = [row["level"] for row in cefr_rows]
    levels_history = levels_list[-5:] if levels_list else []

    # Determine trajectory from level ordering
    cefr_order = ["A1", "A2", "B1", "B2", "C1", "C2"]

    trajectory = "stable"
    if len(levels_history) >= 2:
        first_level = levels_history[0]
        last_level = levels_history[-1]
        first_idx = cefr_order.index(first_level) if first_level in cefr_order else -1
        last_idx = cefr_order.index(last_level) if last_level in cefr_order else -1

        if first_idx >= 0 and last_idx >= 0:
            if last_idx > first_idx:
                trajectory = "improving"
            elif last_idx < first_idx:
                trajectory = "declining"
            else:
                trajectory = "stable"

    return {
        "current_level": current_level,
        "levels_history": levels_history,
        "trajectory": trajectory,
    }


# ── Public retrieval helpers ──────────────────────────────────────────────


async def get_latest_dna(student_id: int, db) -> dict | None:
    """
    Fetch the most recent Learning DNA row for a student.
    Returns the parsed dna_json dict, or None if no DNA exists.
    """
    cursor = await db.execute(
        "SELECT dna_json, version, trigger_event, created_at "
        "FROM learning_dna WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    )
    row = await cursor.fetchone()

    if not row:
        return None

    dna = _safe_json_parse(row["dna_json"], default={})
    dna["_meta"] = {
        "version": row["version"],
        "trigger_event": row["trigger_event"],
        "created_at": row["created_at"],
    }
    return dna


async def get_or_compute_dna(student_id: int, db, max_age_hours: int = 24) -> dict:
    """
    Return existing DNA if fresh enough (within max_age_hours),
    otherwise recompute and store a new version.
    """
    cursor = await db.execute(
        "SELECT dna_json, version, trigger_event, created_at "
        "FROM learning_dna WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    )
    row = await cursor.fetchone()

    if row:
        created_at_str = row["created_at"]
        try:
            created_at = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            created_at = None

        if created_at:
            # Ensure both sides are naive UTC for comparison
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            age = datetime.utcnow() - created_at
            if age < timedelta(hours=max_age_hours):
                dna = _safe_json_parse(row["dna_json"], default={})
                dna["_meta"] = {
                    "version": row["version"],
                    "trigger_event": row["trigger_event"],
                    "created_at": row["created_at"],
                    "freshness": "cached",
                }
                return dna

    # DNA is stale or missing -- recompute
    dna = await compute_learning_dna(student_id, db, trigger_event="auto_refresh")
    dna["_meta"] = {"freshness": "recomputed"}
    return dna
