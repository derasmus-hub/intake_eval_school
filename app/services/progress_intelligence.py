"""Progress intelligence service.

Provides:
- CEFR level prediction based on current trajectory
- Plateau detection with intervention suggestions
- Weekly natural-language insight summaries
- Anonymized peer comparison
"""

import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)

# CEFR level ordering for comparison
CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
CEFR_FROM_ORDER = {v: k for k, v in CEFR_ORDER.items()}


def _safe_json_parse(raw, default=None):
    """Parse a JSON string from a DB column, returning default on failure."""
    if not raw:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


async def predict_level_progression(student_id: int, db) -> dict:
    """Predict when the student will reach the next CEFR level.

    Uses CEFR history, lesson frequency, average scores, and learning DNA
    to estimate pace and produce a predicted date for the next level transition.
    """
    # Fetch CEFR history
    cursor = await db.execute(
        "SELECT level, recorded_at FROM cefr_history "
        "WHERE student_id = ? ORDER BY recorded_at ASC",
        (student_id,),
    )
    cefr_rows = await cursor.fetchall()

    # Fetch progress stats
    cursor = await db.execute(
        "SELECT COUNT(*) as total, AVG(score) as avg_score FROM progress WHERE student_id = ?",
        (student_id,),
    )
    stats_row = await cursor.fetchone()
    total_lessons = stats_row["total"] if stats_row else 0
    avg_score = round(stats_row["avg_score"], 2) if stats_row and stats_row["avg_score"] is not None else 0.0

    # Fetch current level
    cursor = await db.execute(
        "SELECT current_level FROM users WHERE id = ?",
        (student_id,),
    )
    user_row = await cursor.fetchone()
    current_level = user_row["current_level"] if user_row else "A1"

    # Fetch lessons completed in the last 30 days to derive weekly rate
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM progress "
        "WHERE student_id = ? AND completed_at >= datetime('now', '-30 days')",
        (student_id,),
    )
    recent_row = await cursor.fetchone()
    recent_count = recent_row["cnt"] if recent_row else 0
    lessons_per_week = round(recent_count / 4, 2)

    # Fetch latest learning DNA
    cursor = await db.execute(
        "SELECT dna_json FROM learning_dna WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    )
    dna_row = await cursor.fetchone()
    dna = _safe_json_parse(dna_row["dna_json"], default={}) if dna_row else {}

    # Determine next CEFR level
    current_order = CEFR_ORDER.get(current_level, 1)
    if current_order < 6:
        next_level = CEFR_FROM_ORDER[current_order + 1]
    else:
        next_level = "C2"  # Already at maximum

    # Calculate average days between historical level changes
    avg_days_between_levels = None
    if len(cefr_rows) >= 2:
        dates = []
        for row in cefr_rows:
            try:
                dt = datetime.fromisoformat(str(row["recorded_at"]).replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                dates.append(dt)
            except (ValueError, TypeError):
                pass
        if len(dates) >= 2:
            deltas = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            avg_days_between_levels = sum(deltas) / len(deltas)

    # Determine pace based on heuristics
    factors = []

    if avg_score >= 80 and lessons_per_week >= 2:
        pace = "accelerated"
        estimated_weeks = 8
        factors.append("High average score (>=80) and strong lesson frequency (>=2/week)")
    elif avg_score >= 65 and lessons_per_week >= 1:
        pace = "normal"
        estimated_weeks = 14
        factors.append("Solid average score (>=65) with regular lesson frequency (>=1/week)")
    else:
        pace = "slow"
        estimated_weeks = 24
        if avg_score < 65:
            factors.append(f"Average score ({avg_score}) below 65 suggests material difficulty")
        if lessons_per_week < 1:
            factors.append(f"Low lesson frequency ({lessons_per_week}/week) slows progression")

    # Adjust based on DNA insights if available
    if dna:
        learning_speed = dna.get("learning_speed", {})
        classification = learning_speed.get("classification", "unknown")
        if classification == "fast":
            estimated_weeks = max(4, estimated_weeks - 3)
            factors.append("Learning DNA indicates fast acquisition speed")
        elif classification == "slow":
            estimated_weeks += 4
            factors.append("Learning DNA indicates slower acquisition speed")

        frustration = dna.get("frustration_indicators", {})
        if frustration.get("declining_scores"):
            estimated_weeks += 2
            factors.append("Recent score decline may slow progression")
        if frustration.get("low_engagement_streak", 0) > 7:
            estimated_weeks += 3
            factors.append("Extended inactivity streak detected")

    # Adjust using historical data if available
    if avg_days_between_levels is not None:
        historical_weeks = round(avg_days_between_levels / 7)
        # Blend historical and heuristic estimates (weighted average)
        estimated_weeks = round((estimated_weeks + historical_weeks) / 2)
        factors.append(f"Historical level transitions averaged {round(avg_days_between_levels)} days")

    # Determine confidence level
    if total_lessons >= 20 and len(cefr_rows) >= 2:
        confidence = "high"
    elif total_lessons >= 10:
        confidence = "medium"
    else:
        confidence = "low"
        factors.append("Limited data — prediction may change with more lessons")

    # Already at C2
    if current_level == "C2":
        return {
            "current_level": "C2",
            "next_level": "C2",
            "pace": pace,
            "lessons_per_week": lessons_per_week,
            "avg_score": avg_score,
            "estimated_weeks_to_next": 0,
            "predicted_date": None,
            "confidence": confidence,
            "factors": ["Student has reached the highest CEFR level (C2)"],
        }

    predicted_date = (datetime.now(timezone.utc) + timedelta(weeks=estimated_weeks)).strftime("%Y-%m-%d")

    return {
        "current_level": current_level,
        "next_level": next_level,
        "pace": pace,
        "lessons_per_week": lessons_per_week,
        "avg_score": avg_score,
        "estimated_weeks_to_next": estimated_weeks,
        "predicted_date": predicted_date,
        "confidence": confidence,
        "factors": factors,
    }


async def detect_plateau(student_id: int, db) -> dict:
    """Detect learning plateaus and suggest targeted interventions.

    Analyzes the last 20 progress entries to determine if scores have
    stagnated, and recommends specific changes based on lesson variety
    and score patterns.
    """
    # Fetch last 20 progress entries
    cursor = await db.execute(
        "SELECT score, completed_at FROM progress "
        "WHERE student_id = ? ORDER BY completed_at DESC LIMIT 20",
        (student_id,),
    )
    progress_rows = await cursor.fetchall()

    scores = [row["score"] for row in progress_rows if row["score"] is not None]

    # Not enough data
    if len(scores) < 10:
        return {
            "is_plateau": False,
            "plateau_duration_lessons": 0,
            "avg_score_during_plateau": 0.0,
            "score_variance": 0.0,
            "interventions": [],
        }

    # Analyze the last 10 scores (most recent first from the query,
    # so scores[0] is most recent)
    last_10 = scores[:10]

    try:
        score_stdev = statistics.stdev(last_10)
    except statistics.StatisticsError:
        score_stdev = 0.0

    score_mean = statistics.mean(last_10)

    # Split into two halves: first half = more recent (indices 0-4),
    # second half = older (indices 5-9)
    recent_half = last_10[:5]
    older_half = last_10[5:]
    recent_mean = statistics.mean(recent_half)
    older_mean = statistics.mean(older_half)

    # Plateau: low variance AND no meaningful improvement between halves
    improvement = recent_mean - older_mean
    is_plateau = score_stdev < 5 and abs(improvement) < 2

    # Determine how far back the plateau extends
    plateau_duration = 0
    if is_plateau:
        plateau_duration = 10
        # Check if earlier scores (11-20) are also part of the plateau
        if len(scores) > 10:
            remaining = scores[10:]
            remaining_mean = statistics.mean(remaining)
            if abs(remaining_mean - score_mean) < 3:
                plateau_duration = len(scores)

    # Fetch recent lesson topics for variety analysis
    cursor = await db.execute(
        "SELECT DISTINCT objective FROM lessons "
        "WHERE student_id = ? ORDER BY session_number DESC LIMIT 10",
        (student_id,),
    )
    topic_rows = await cursor.fetchall()
    recent_topics = [row["objective"] for row in topic_rows if row["objective"]]

    # Build interventions if plateau detected
    interventions = []
    if is_plateau:
        # Check for lack of topic variety
        if len(recent_topics) <= 3:
            interventions.append({
                "type": "change_format",
                "description": "Try conversation-heavy lessons instead of grammar drills",
            })

        # Check if scores suggest material is too easy (high plateau)
        if score_mean >= 80:
            interventions.append({
                "type": "increase_challenge",
                "description": "Current material may be too easy — increase difficulty or move to next CEFR sub-level",
            })

        # Check if scores suggest material is too hard (low plateau)
        if score_mean < 60:
            interventions.append({
                "type": "decrease_challenge",
                "description": "Scores suggest material may be too difficult — consider reviewing foundational topics",
            })

        # Check for skill diversity in topics
        grammar_keywords = {"grammar", "tense", "verb", "article", "preposition", "conjugation"}
        topic_text = " ".join(recent_topics).lower()
        grammar_heavy = sum(1 for kw in grammar_keywords if kw in topic_text)

        if grammar_heavy >= 3:
            interventions.append({
                "type": "skill_shift",
                "description": "Focus on writing/speaking instead of reading/grammar to activate different learning pathways",
            })

        # Always suggest a general approach if no specific one was found
        if not interventions:
            interventions.append({
                "type": "change_format",
                "description": "Try conversation-heavy lessons instead of grammar drills",
            })
            interventions.append({
                "type": "skill_shift",
                "description": "Focus on writing/speaking instead of reading/grammar",
            })
            interventions.append({
                "type": "increase_challenge",
                "description": "Current material may be too easy",
            })

    return {
        "is_plateau": is_plateau,
        "plateau_duration_lessons": plateau_duration,
        "avg_score_during_plateau": round(score_mean, 2) if is_plateau else 0.0,
        "score_variance": round(score_stdev, 2),
        "interventions": interventions,
    }


async def generate_weekly_summary(student_id: int, db) -> dict:
    """Generate a natural-language weekly progress summary using AI.

    Aggregates the last 7 days of progress, vocabulary, XP, games, and
    recall data, then asks the AI to produce an encouraging but honest
    summary in both English and Polish.
    """
    # Progress entries from last 7 days
    cursor = await db.execute(
        "SELECT score, areas_improved, areas_struggling FROM progress "
        "WHERE student_id = ? AND completed_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    progress_rows = await cursor.fetchall()

    lessons_completed = len(progress_rows)
    progress_scores = [row["score"] for row in progress_rows if row["score"] is not None]
    avg_score = round(statistics.mean(progress_scores), 2) if progress_scores else 0.0

    all_improved = []
    all_struggling = []
    for row in progress_rows:
        improved = _safe_json_parse(row["areas_improved"], default=[])
        struggling = _safe_json_parse(row["areas_struggling"], default=[])
        if isinstance(improved, list):
            all_improved.extend(improved)
        if isinstance(struggling, list):
            all_struggling.extend(struggling)

    # Vocabulary cards added this week
    cursor = await db.execute(
        "SELECT COUNT(*) as new_words FROM vocabulary_cards "
        "WHERE student_id = ? AND created_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    vocab_new_row = await cursor.fetchone()
    new_words = vocab_new_row["new_words"] if vocab_new_row else 0

    # Vocabulary cards mastered this week
    cursor = await db.execute(
        "SELECT COUNT(*) as mastered FROM vocabulary_cards "
        "WHERE student_id = ? AND repetitions >= 5 AND created_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    vocab_mastered_row = await cursor.fetchone()
    mastered_words = vocab_mastered_row["mastered"] if vocab_mastered_row else 0

    # XP earned this week
    cursor = await db.execute(
        "SELECT COALESCE(SUM(amount), 0) as xp FROM xp_log "
        "WHERE student_id = ? AND created_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    xp_row = await cursor.fetchone()
    xp_earned = xp_row["xp"] if xp_row else 0

    # Games played this week
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM game_scores "
        "WHERE student_id = ? AND played_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    games_row = await cursor.fetchone()
    games_played = games_row["cnt"] if games_row else 0

    # Recall sessions this week
    cursor = await db.execute(
        "SELECT overall_score FROM recall_sessions "
        "WHERE student_id = ? AND status = 'completed' AND completed_at >= datetime('now', '-7 days')",
        (student_id,),
    )
    recall_rows = await cursor.fetchall()
    recall_scores = [row["overall_score"] for row in recall_rows if row["overall_score"] is not None]

    # Student info
    cursor = await db.execute(
        "SELECT name, current_level, goals FROM users WHERE id = ?",
        (student_id,),
    )
    user_row = await cursor.fetchone()
    student_name = user_row["name"] if user_row else "Student"
    current_level = user_row["current_level"] if user_row else "unknown"
    goals = _safe_json_parse(user_row["goals"], default=[]) if user_row else []

    # Latest learning DNA
    cursor = await db.execute(
        "SELECT dna_json FROM learning_dna WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    )
    dna_row = await cursor.fetchone()
    dna = _safe_json_parse(dna_row["dna_json"], default={}) if dna_row else {}

    # Calculate streak days (consecutive days with XP activity in last 7 days)
    cursor = await db.execute(
        "SELECT DISTINCT DATE(created_at) as active_date FROM xp_log "
        "WHERE student_id = ? AND created_at >= datetime('now', '-7 days') "
        "ORDER BY active_date DESC",
        (student_id,),
    )
    active_date_rows = await cursor.fetchall()
    streak_days = len(active_date_rows)

    # Build data summary for AI
    data_summary = {
        "student_name": student_name,
        "current_level": current_level,
        "goals": goals,
        "lessons_completed": lessons_completed,
        "avg_score": avg_score,
        "areas_improved": list(set(all_improved)),
        "areas_struggling": list(set(all_struggling)),
        "new_words": new_words,
        "mastered_words": mastered_words,
        "xp_earned": xp_earned,
        "games_played": games_played,
        "recall_scores": recall_scores,
        "streak_days": streak_days,
        "dna_highlights": {
            "learning_speed": dna.get("learning_speed", {}),
            "score_trend": dna.get("engagement_patterns", {}).get("score_trend", "unknown"),
            "frustration_indicators": dna.get("frustration_indicators", {}),
        },
    }

    system_prompt = (
        "You are an educational progress analyst for a Polish-speaking English student. "
        "Generate a concise, encouraging but honest weekly progress summary. "
        "Write in third person using the student's name. Include specific data points. "
        "Be actionable.\n\n"
        "You MUST respond with valid JSON in this exact format:\n"
        "{\n"
        '  "summary_text": "English summary text...",\n'
        '  "summary_text_pl": "Polish translation of the summary...",\n'
        '  "highlights": ["highlight1", "highlight2"],\n'
        '  "areas_for_focus": ["area1", "area2"],\n'
        '  "recommendation": "Next week recommendation...",\n'
        '  "stats": {\n'
        '    "lessons_completed": 0,\n'
        '    "avg_score": 0.0,\n'
        '    "words_learned": 0,\n'
        '    "xp_earned": 0,\n'
        '    "streak_days": 0\n'
        "  }\n"
        "}"
    )

    user_message = (
        f"Generate a weekly progress summary for this student based on the following data:\n\n"
        f"{json.dumps(data_summary, indent=2, ensure_ascii=False)}"
    )

    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="cheap",
            temperature=0.6,
            json_mode=True,
        )
        result = json.loads(result_text)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to generate weekly summary for student %d: %s", student_id, e)
        # Return a fallback summary built from raw data
        result = {
            "summary_text": (
                f"{student_name} completed {lessons_completed} lessons this week "
                f"with an average score of {avg_score}%. "
                f"{new_words} new vocabulary words were added."
            ),
            "summary_text_pl": (
                f"{student_name} ukonczyl(a) {lessons_completed} lekcji w tym tygodniu "
                f"ze srednim wynikiem {avg_score}%. "
                f"Dodano {new_words} nowych slow."
            ),
            "highlights": [],
            "areas_for_focus": list(set(all_struggling))[:3],
            "recommendation": "Continue regular practice to maintain momentum.",
            "stats": {
                "lessons_completed": lessons_completed,
                "avg_score": avg_score,
                "words_learned": new_words,
                "xp_earned": xp_earned,
                "streak_days": streak_days,
            },
        }

    # Ensure stats are populated even if AI omitted them
    if "stats" not in result or not isinstance(result.get("stats"), dict):
        result["stats"] = {}

    result["stats"].setdefault("lessons_completed", lessons_completed)
    result["stats"].setdefault("avg_score", avg_score)
    result["stats"].setdefault("words_learned", new_words)
    result["stats"].setdefault("xp_earned", xp_earned)
    result["stats"].setdefault("streak_days", streak_days)

    return result


async def get_peer_comparison(student_id: int, db) -> dict:
    """Generate an anonymized comparison of the student against peers at the same CEFR level.

    Compares average scores and vocabulary counts, categorizing the student's
    standing as above_average, average, or below_average.
    """
    # Get student's current level
    cursor = await db.execute(
        "SELECT current_level FROM users WHERE id = ?",
        (student_id,),
    )
    user_row = await cursor.fetchone()
    current_level = user_row["current_level"] if user_row else "A1"

    # Get anonymized peer stats at same level
    cursor = await db.execute(
        "SELECT AVG(p.score) as peer_avg_score, "
        "COUNT(DISTINCT p.student_id) as peer_count "
        "FROM progress p "
        "JOIN users u ON u.id = p.student_id "
        "WHERE u.current_level = ? AND u.id != ?",
        (current_level, student_id),
    )
    peer_row = await cursor.fetchone()
    peer_avg_score = round(peer_row["peer_avg_score"], 2) if peer_row and peer_row["peer_avg_score"] is not None else 0.0
    peer_count = peer_row["peer_count"] if peer_row else 0

    # Get student's own average score
    cursor = await db.execute(
        "SELECT AVG(score) as my_avg FROM progress WHERE student_id = ?",
        (student_id,),
    )
    my_row = await cursor.fetchone()
    my_avg_score = round(my_row["my_avg"], 2) if my_row and my_row["my_avg"] is not None else 0.0

    # Get peer vocabulary counts (average across peers at same level)
    cursor = await db.execute(
        "SELECT AVG(vocab_count) as peer_avg_vocab FROM ("
        "  SELECT COUNT(*) as vocab_count FROM vocabulary_cards "
        "  WHERE student_id IN (SELECT id FROM users WHERE current_level = ? AND id != ?) "
        "  GROUP BY student_id"
        ")",
        (current_level, student_id),
    )
    peer_vocab_row = await cursor.fetchone()
    peer_avg_vocab = round(peer_vocab_row["peer_avg_vocab"], 2) if peer_vocab_row and peer_vocab_row["peer_avg_vocab"] is not None else 0.0

    # Get student's own vocabulary count
    cursor = await db.execute(
        "SELECT COUNT(*) as my_vocab FROM vocabulary_cards WHERE student_id = ?",
        (student_id,),
    )
    my_vocab_row = await cursor.fetchone()
    my_vocab = my_vocab_row["my_vocab"] if my_vocab_row else 0

    # Determine percentile categories
    def _classify(student_val, peer_val):
        if peer_val == 0:
            return "average"
        ratio = student_val / peer_val if peer_val else 1.0
        if ratio >= 1.10:
            return "above_average"
        elif ratio <= 0.90:
            return "below_average"
        return "average"

    score_percentile = _classify(my_avg_score, peer_avg_score)
    vocab_percentile = _classify(my_vocab, peer_avg_vocab)

    # Identify strengths and growth opportunities
    strengths_vs_peers = []
    growth_opportunities = []

    if score_percentile == "above_average":
        strengths_vs_peers.append("Quiz and lesson scores are above the peer average")
    elif score_percentile == "below_average":
        growth_opportunities.append("Quiz and lesson scores are below the peer average — consider extra practice")

    if vocab_percentile == "above_average":
        strengths_vs_peers.append("Vocabulary bank is larger than most peers at this level")
    elif vocab_percentile == "below_average":
        growth_opportunities.append("Vocabulary bank is smaller than peers — try adding more flashcards")

    # Add a neutral note if no peers exist
    if peer_count == 0:
        strengths_vs_peers.append("No peer data available yet for comparison")

    return {
        "level": current_level,
        "peer_count": peer_count,
        "comparison": {
            "avg_score": {
                "student": my_avg_score,
                "peers": peer_avg_score,
                "percentile": score_percentile,
            },
            "vocabulary": {
                "student": my_vocab,
                "peers_avg": peer_avg_vocab,
                "percentile": vocab_percentile,
            },
        },
        "strengths_vs_peers": strengths_vs_peers,
        "growth_opportunities": growth_opportunities,
    }
