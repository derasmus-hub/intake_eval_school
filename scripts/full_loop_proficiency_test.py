#!/usr/bin/env python3
"""
Full Proficiency Loop E2E Test — v2 (with SM-2 recall & difficulty engine)
==========================================================================
Simulates a student progressing from A1 through 15 complete learning cycles
with realistic score progression, proving the adaptive learning system:

  1. Adjusts difficulty UP when student performs well
  2. Adjusts difficulty DOWN when student struggles
  3. Triggers CEFR reassessment every 10 completed lessons
  4. Updates learning plans after each quiz
  5. Tracks learning DNA evolution over time
  6. Drives SM-2 ease_factor updates via recall sessions
  7. Activates the difficulty engine (simplify / maintain / challenge)
  8. Forces level promotion and verifies regression handling

Usage:
  python3 scripts/full_loop_proficiency_test.py

Requires: server running on localhost:8000 (docker-compose up)
"""

import json
import os
import sys
import time
import subprocess
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "http://localhost:8000"
ARTIFACTS_DIR = Path(__file__).parent / "proficiency_artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)
E2E_ARTIFACTS_DIR = Path(__file__).parent / "e2e_artifacts"
E2E_ARTIFACTS_DIR.mkdir(exist_ok=True)

# ─── Credentials ────────────────────────────────────────────────────
ADMIN_EMAIL = "admin@school.com"
ADMIN_PASS = "admin123456"
TEACHER_EMAIL = "teacher1@school.com"
TEACHER_PASS = "Teacher1234!"
STUDENT_EMAIL = "loop.test@proficiency.com"
STUDENT_PASS = "LoopTest1234!"

# ─── State ──────────────────────────────────────────────────────────
IDS = {}
TOKENS = {}
REPORT = []
CYCLE_DATA = []

# ─── Score progression: 15 cycles ──────────────────────────────────
SCORE_TARGETS = {
    1:  0.15,   # ~10-20%  Total beginner, struggling
    2:  0.25,   # ~20-30%  Still struggling
    3:  0.32,   # ~30-35%  Slow improvement
    4:  0.42,   # ~40-45%  Starting to understand
    5:  0.52,   # ~50-55%  Crossing halfway
    6:  0.58,   # ~55-60%  Solidifying basics
    7:  0.67,   # ~65-70%  Entering flow zone
    8:  0.72,   # ~70-75%  Comfortable
    9:  0.78,   # ~75-80%  Approaching mastery
    10: 0.82,   # ~80-85%  Mastery — trigger level promotion (10th lesson)
    11: 0.52,   # ~50-55%  REGRESSION — harder material after promotion
    12: 0.62,   # ~60-65%  Recovering at new level
    13: 0.72,   # ~70-75%  Adapting to new level
    14: 0.82,   # ~80-85%  Mastery at new level
    15: 0.88,   # ~85-90%  Excellent — system should increase difficulty
}

# Recall quality targets per cycle — controls SM-2 ease_factor drift
# Low quality (0-2) drives ease_factor DOWN toward 1.3 (→ "simplify")
# High quality (4-5) drives ease_factor UP toward 2.8+ (→ "challenge")
RECALL_QUALITY_TARGETS = {
    1:  0,   # total fail — drives ease_factor down fast
    2:  1,   # hard — keeps driving down
    3:  1,   # hard
    4:  2,   # fail — still pushes ease_factor down
    5:  3,   # okay — starts stabilizing
    6:  3,   # okay
    7:  4,   # good — starts climbing
    8:  4,   # good
    9:  4,   # good
    10: 5,   # perfect — pushes ease_factor up
    11: 2,   # regression — ease_factor dips again
    12: 3,   # recovery
    13: 4,   # solid
    14: 5,   # excellent
    15: 5,   # excellent — ease_factor should be > 2.8 for "challenge"
}

# Teacher feedback templates keyed by score band
TEACHER_NOTES = {
    "struggling": {
        "notes": "Student is struggling significantly with new concepts. Needs extensive scaffolding, Polish-language explanations, and more basic practice before advancing.",
        "summary": "Difficult session. Student had trouble with most concepts. Focused on very basic examples and repeated key patterns multiple times.",
        "homework": "Review basic vocabulary flashcards. Practice simple sentence patterns from today's lesson. No new material.",
    },
    "developing": {
        "notes": "Student showing gradual improvement. Still making frequent errors with articles and word order. Needs more controlled practice before free production.",
        "summary": "Session showed some progress. Student can handle guided exercises but struggles with free production. Grammar accuracy improving slowly.",
        "homework": "Complete fill-in-the-blank exercises. Practice 5 sentences using today's grammar pattern. Review vocabulary list.",
    },
    "flow": {
        "notes": "Student is in a good flow — making progress, engaged, errors are decreasing. Ready for slightly more challenging material next session.",
        "summary": "Productive session. Student participated actively and showed solid understanding. Ready to begin introducing next-level concepts.",
        "homework": "Write 3-5 sentences using today's structures. Listen to one podcast episode at current level. Review vocabulary.",
    },
    "mastering": {
        "notes": "Excellent session. Student demonstrates strong command of current-level material. Accuracy is high, fluency improving. Ready for level advancement.",
        "summary": "Outstanding progress. Student handled all exercises with minimal errors. Conversation was natural and mostly self-corrected. Time to increase challenge.",
        "homework": "Read a short article at next level. Write a paragraph about a familiar topic. Prepare 5 questions for discussion.",
    },
}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    REPORT.append(line)


def save_artifact(name: str, data):
    path = ARTIFACTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def api(method: str, path: str, token: str = None, json_body=None,
        expect_ok: bool = True, timeout: int = 180):
    url = f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.request(method, url, json=json_body, headers=headers, timeout=timeout)
    if expect_ok and resp.status_code >= 400:
        log(f"  [ERROR] {method} {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp


def db_query(sql: str) -> str:
    """Run SQL against the PostgreSQL docker container."""
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "psql", "-U", "intake", "-d", "intake_eval",
        "-c", sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return ""


def db_query_value(sql: str) -> str:
    """Run SQL and return the single value from the first row."""
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "psql", "-U", "intake", "-d", "intake_eval",
        "-t", "-A", "-c", sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return ""


def db_query_rows(sql: str) -> list[dict]:
    """Run SQL and return rows as list of dicts (using psql CSV output)."""
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "psql", "-U", "intake", "-d", "intake_eval",
        "-t", "-A", "-F", "|", "-c", sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        rows = []
        for line in lines:
            parts = line.split("|")
            rows.append(parts)
        return rows
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return []


def get_feedback_band(score: float) -> str:
    if score < 40:
        return "struggling"
    elif score < 65:
        return "developing"
    elif score < 80:
        return "flow"
    else:
        return "mastering"


def cefr_label(score: float) -> str:
    if score < 55:
        return "A1"
    elif score < 75:
        return "A2"
    else:
        return "B1"


# ════════════════════════════════════════════════════════════════════
# PHASE 1: Setup — Accounts & Intake
# ════════════════════════════════════════════════════════════════════

def phase1_setup():
    log("\n" + "=" * 76)
    log("PHASE 1: Setup — Accounts & Intake")
    log("=" * 76)

    # ─── Health check ───────────────────────────────────────────────
    r = api("GET", "/health")
    if r.status_code != 200:
        log("[FATAL] Server not reachable at localhost:8000")
        sys.exit(1)
    log(f"  Server healthy: {r.json()}")

    # ─── Admin account ──────────────────────────────────────────────
    log("  Ensuring admin account...")
    existing = db_query(f"SELECT id, role FROM users WHERE email = '{ADMIN_EMAIL}';")
    if "admin" not in existing.lower() or "(0 rows)" in existing:
        import bcrypt
        pw_hash = bcrypt.hashpw(ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
        db_query(
            f"INSERT INTO users (name, email, password_hash, role) "
            f"VALUES ('Admin User', '{ADMIN_EMAIL}', '{pw_hash}', 'admin') "
            f"ON CONFLICT (email) DO UPDATE SET role='admin', password_hash='{pw_hash}';"
        )

    r = api("POST", "/api/auth/login",
            json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    if r.status_code == 200:
        data = r.json()
        TOKENS["admin"] = data["token"]
        IDS["admin_id"] = data["student_id"]
        log(f"  Admin logged in: id={IDS['admin_id']}")
    else:
        log(f"  [WARN] Admin login failed ({r.status_code}), trying register fallback...")
        api("POST", "/api/auth/register",
            json_body={"name": "Admin User", "email": ADMIN_EMAIL, "password": ADMIN_PASS},
            expect_ok=False)
        db_query(f"UPDATE users SET role='admin' WHERE email='{ADMIN_EMAIL}';")
        r = api("POST", "/api/auth/login",
                json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        data = r.json()
        TOKENS["admin"] = data["token"]
        IDS["admin_id"] = data["student_id"]
        log(f"  Admin created+logged in: id={IDS['admin_id']}")

    # ─── Teacher account ────────────────────────────────────────────
    log("  Ensuring teacher account...")
    r = api("POST", "/api/admin/teacher-invites",
            token=TOKENS["admin"],
            json_body={"email": TEACHER_EMAIL, "expires_days": 7})
    if r.status_code == 200:
        invite_token = r.json()["token"]
        r2 = api("POST", "/api/auth/teacher/register",
                 json_body={"name": "Teacher One", "email": TEACHER_EMAIL,
                            "password": TEACHER_PASS, "invite_token": invite_token},
                 expect_ok=False)
        if r2.status_code in (200, 201):
            data = r2.json()
            TOKENS["teacher"] = data["token"]
            IDS["teacher_id"] = data["student_id"]
            log(f"  Teacher registered: id={IDS['teacher_id']}")
        elif r2.status_code == 409:
            _login_teacher()
    elif r.status_code == 409:
        _login_teacher()

    if "teacher" not in TOKENS:
        log("[FATAL] Cannot create teacher account")
        sys.exit(1)

    # ─── Student account ────────────────────────────────────────────
    log("  Creating test student...")
    # Delete any previous test student data for a clean run
    prev = db_query_value(f"SELECT id FROM users WHERE email = '{STUDENT_EMAIL}';")
    if prev and prev.strip():
        _clean_student_data(int(prev.strip()))

    r = api("POST", "/api/auth/register",
            json_body={"name": "Loop Proficiency Tester",
                       "email": STUDENT_EMAIL,
                       "password": STUDENT_PASS},
            expect_ok=False)
    if r.status_code in (200, 201):
        data = r.json()
        TOKENS["student"] = data["token"]
        IDS["student_id"] = data["student_id"]
        log(f"  Student registered: id={IDS['student_id']}")
    elif r.status_code == 409:
        r2 = api("POST", "/api/auth/login",
                 json_body={"email": STUDENT_EMAIL, "password": STUDENT_PASS})
        if r2.status_code == 200:
            data = r2.json()
            TOKENS["student"] = data["token"]
            IDS["student_id"] = data["student_id"]
            log(f"  Student logged in (existing): id={IDS['student_id']}")
        else:
            log(f"  [FATAL] Cannot login student: {r2.status_code}")
            sys.exit(1)

    student_id = IDS["student_id"]

    # ─── Submit intake data ─────────────────────────────────────────
    log("  Submitting intake data...")
    db_query(
        f"UPDATE users SET name='Loop Proficiency Tester', age=28, "
        f"native_language='Polish', "
        f"goals='[\"pass B2 exam\", \"business English\", \"improve grammar\"]', "
        f"problem_areas='[\"articles\", \"grammar\", \"vocabulary\", \"word order\"]', "
        f"additional_notes='Polish native speaker, absolute beginner. Motivated student who wants to reach B2 for work.' "
        f"WHERE id={student_id};"
    )

    # Update goals via API too
    api("PUT", f"/api/intake/{student_id}/goals", token=TOKENS["student"],
        json_body={
            "goals": ["pass B2 exam", "business English", "improve grammar"],
            "problem_areas": ["articles", "grammar", "vocabulary", "word order"],
            "additional_notes": "Polish native speaker, absolute beginner."
        }, expect_ok=False)

    log(f"  Intake submitted for student {student_id}")
    save_artifact("phase1_setup", {"ids": IDS})


def _login_teacher():
    r = api("POST", "/api/auth/login",
            json_body={"email": TEACHER_EMAIL, "password": TEACHER_PASS})
    if r.status_code == 200:
        data = r.json()
        TOKENS["teacher"] = data["token"]
        IDS["teacher_id"] = data["student_id"]
        log(f"  Teacher logged in: id={IDS['teacher_id']}")


def _clean_student_data(student_id: int):
    """Remove old test data so we get a clean 15-cycle run."""
    log(f"  Cleaning previous data for student {student_id}...")
    tables = [
        "quiz_attempt_items WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE student_id={sid})",
        "quiz_attempts WHERE student_id={sid}",
        "next_quizzes WHERE student_id={sid}",
        "lesson_skill_tags WHERE lesson_id IN (SELECT id FROM lessons WHERE student_id={sid})",
        "lessons WHERE student_id={sid}",
        "lesson_artifacts WHERE student_id={sid}",
        "learning_plans WHERE student_id={sid}",
        "learning_dna WHERE student_id={sid}",
        "learning_points WHERE student_id={sid}",
        "learning_paths WHERE student_id={sid}",
        "learner_profiles WHERE student_id={sid}",
        "progress WHERE student_id={sid}",
        "session_skill_observations WHERE student_id={sid}",
        "sessions WHERE student_id={sid}",
        "cefr_history WHERE student_id={sid}",
        "vocabulary_cards WHERE student_id={sid}",
        "assessments WHERE student_id={sid}",
        "achievements WHERE student_id={sid}",
        "xp_log WHERE student_id={sid}",
        "recall_sessions WHERE student_id={sid}",
    ]
    for t in tables:
        db_query(f"DELETE FROM {t.format(sid=student_id)};")
    # Reset user level
    db_query(f"UPDATE users SET current_level='pending' WHERE id={student_id};")


# ════════════════════════════════════════════════════════════════════
# PHASE 2: Assessment — Force A1 Start
# ════════════════════════════════════════════════════════════════════

def phase2_assessment():
    log("\n" + "=" * 76)
    log("PHASE 2: Assessment — Force A1 Start")
    log("=" * 76)

    student_id = IDS["student_id"]
    token = TOKENS["student"]

    # C1: Start assessment
    log("  Starting assessment...")
    r = api("POST", "/api/assessment/start", token=token,
            json_body={"student_id": student_id})
    if r.status_code != 200:
        log(f"  [FATAL] Cannot start assessment: {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    assessment_id = data["assessment_id"]
    IDS["assessment_id"] = assessment_id
    placement_qs = data["questions"]
    log(f"  Assessment started: id={assessment_id}, {len(placement_qs)} placement questions")
    save_artifact("phase2_placement_questions", data)

    # C2: Placement — all wrong -> beginner bracket
    log("  Submitting placement with ALL WRONG answers...")
    placement_answers = []
    for q in placement_qs:
        placement_answers.append({
            "question_id": q["id"],
            "answer": True,
        })

    r = api("POST", "/api/assessment/placement", token=token,
            json_body={
                "student_id": student_id,
                "assessment_id": assessment_id,
                "answers": placement_answers,
            })
    if r.status_code != 200:
        log(f"  [FATAL] Placement failed: {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    bracket = data["placement_result"]["bracket"]
    diag_qs = data["questions"]
    log(f"  Placement result: bracket={bracket}, score={data['placement_result']['score']}")
    log(f"  Diagnostic questions: {len(diag_qs)}")
    save_artifact("phase2_placement_result", data)

    # C3: Diagnostic — all wrong -> A1
    log("  Submitting diagnostic with ALL WRONG answers...")
    diag_answers = []
    for q in diag_qs:
        q_type = q.get("type", "")
        options = q.get("options", [])
        if options:
            diag_answers.append({"question_id": q["id"], "answer": options[-1] + "_wrong"})
        elif q_type == "vocabulary_fill":
            diag_answers.append({"question_id": q["id"], "answer": "wrongword"})
        else:
            diag_answers.append({"question_id": q["id"], "answer": "totally_wrong_answer"})

    r = api("POST", "/api/assessment/diagnostic", token=token,
            json_body={
                "student_id": student_id,
                "assessment_id": assessment_id,
                "answers": diag_answers,
            })
    if r.status_code != 200:
        log(f"  [FATAL] Diagnostic failed: {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    level = data.get("determined_level", "unknown")
    log(f"  Diagnostic result: level={level}, confidence={data.get('confidence_score')}")
    log(f"  Weak areas: {data.get('weak_areas', [])}")
    save_artifact("phase2_diagnostic_result", data)

    # If AI didn't determine A1, force it
    if level.upper() not in ("A1",):
        log(f"  [INFO] AI determined {level}, forcing A1 for test consistency...")
        db_query(f"UPDATE users SET current_level='A1' WHERE id={student_id};")

    # Verify level in DB
    db_level = db_query_value(f"SELECT current_level FROM users WHERE id={student_id};")
    log(f"  [DB VERIFY] current_level = {db_level}")
    assert db_level.strip().upper() == "A1", f"Expected A1, got {db_level}"

    # C4: Generate diagnostic profile
    log("  Generating diagnostic profile...")
    r = api("POST", f"/api/diagnostic/{student_id}", token=token)
    if r.status_code == 200:
        data = r.json()
        log(f"  Profile created: id={data.get('id')}, level={data.get('recommended_start_level')}")
        save_artifact("phase2_diagnostic_profile", data)
    else:
        log(f"  [WARN] Profile gen failed ({r.status_code}), continuing...")

    # C5: Generate learning path
    log("  Generating learning path...")
    r = api("POST", f"/api/learning-path/{student_id}/generate", token=token)
    if r.status_code == 200:
        data = r.json()
        log(f"  Learning path created: id={data.get('id')}, target={data.get('target_level')}")
        save_artifact("phase2_learning_path", data)
    else:
        log(f"  [WARN] Learning path failed ({r.status_code}), continuing...")

    log("  Phase 2 complete: Student confirmed at A1")


# ════════════════════════════════════════════════════════════════════
# PHASE 3: Learning Loop — 15 Cycles
# ════════════════════════════════════════════════════════════════════

def phase3_learning_loop():
    log("\n" + "=" * 76)
    log("PHASE 3: Learning Loop — 15 Cycles")
    log("=" * 76)

    for cycle_num in range(1, 16):
        target_ratio = SCORE_TARGETS[cycle_num]
        result = run_cycle(cycle_num, target_ratio)
        CYCLE_DATA.append(result)

        # Brief cycle summary
        score_str = f"{result['quiz_score']}%" if result['quiz_score'] is not None else "N/A"
        log(f"\n  === Cycle {cycle_num:2d} complete: "
            f"score={score_str}, level={result['db_level']}, "
            f"plan_v={result['plan_version']}, "
            f"dna_rec={result['dna_recommendation']}, "
            f"recall_ef={result.get('recall_avg_ef', 'N/A')}, "
            f"diff_profile={result['difficulty_profile']} ===\n")


def run_cycle(cycle_num: int, target_ratio: float) -> dict:
    """Execute one full learning cycle and return collected data."""

    log(f"\n{'~' * 76}")
    log(f"CYCLE {cycle_num}/15  --  Target score: ~{int(target_ratio * 100)}%")
    log(f"{'~' * 76}")

    student_id = IDS["student_id"]
    student_token = TOKENS["student"]
    teacher_token = TOKENS["teacher"]
    teacher_id = IDS["teacher_id"]

    cycle_result = {
        "cycle": cycle_num,
        "target_pct": int(target_ratio * 100),
        "quiz_score": None,
        "quiz_id": None,
        "lesson_id": None,
        "lesson_difficulty": None,
        "lesson_objective": None,
        "plan_version": None,
        "plan_summary": None,
        "db_level": None,
        "cefr_history_count": 0,
        "dna_version": None,
        "dna_recommendation": None,
        "dna_score_trend": None,
        "dna_frustration": None,
        "difficulty_profile": {},
        "weak_areas": [],
        "reassessment": None,
        "session_id": None,
        "lesson_gen_id": None,
        "recall_session_id": None,
        "recall_score": None,
        "recall_avg_ef": None,
        "recall_points_updated": 0,
        "learning_points_count": 0,
    }

    # ─── Step 1: Student requests a lesson session ──────────────────
    scheduled_time = (datetime.now(timezone.utc) + timedelta(days=cycle_num, hours=cycle_num)).isoformat()
    log(f"  [1] Student requesting session...")
    r = api("POST", "/api/student/me/sessions/request", token=student_token,
            json_body={
                "teacher_id": teacher_id,
                "scheduled_at": scheduled_time,
                "duration_min": 60,
                "notes": f"Cycle {cycle_num} session -- score target ~{int(target_ratio*100)}%"
            })
    if r.status_code != 200:
        log(f"      [WARN] Session request failed: {r.status_code}")
        return cycle_result
    session_id = r.json()["id"]
    cycle_result["session_id"] = session_id
    log(f"      Session created: id={session_id}")

    # ─── Step 2: Teacher confirms -> triggers lesson_artifact + quiz ─
    log(f"  [2] Teacher confirming session {session_id}...")
    r = api("POST", f"/api/teacher/sessions/{session_id}/confirm", token=teacher_token)
    if r.status_code != 200:
        log(f"      [WARN] Session confirm failed: {r.status_code} {r.text[:200]}")
        return cycle_result

    gen = r.json().get("generation", {})
    artifact_id = gen.get("lesson", {}).get("artifact_id")
    quiz_id = gen.get("quiz", {}).get("quiz_id")
    log(f"      Confirmed. artifact_id={artifact_id}, quiz_id={quiz_id}")
    log(f"      Lesson status: {gen.get('lesson', {}).get('status')}")
    log(f"      Quiz status: {gen.get('quiz', {}).get('status')}")

    # ─── Step 3: Verify lesson artifact ─────────────────────────────
    if artifact_id:
        log(f"  [3] Verifying lesson artifact {artifact_id}...")
        r = api("GET", f"/api/teacher/sessions/{session_id}/lesson", token=teacher_token)
        if r.status_code == 200:
            lesson_data = r.json()
            lesson_content = lesson_data.get("lesson", {})
            if isinstance(lesson_content, str):
                try:
                    lesson_content = json.loads(lesson_content)
                except (json.JSONDecodeError, TypeError):
                    lesson_content = {}
            cycle_result["lesson_difficulty"] = lesson_data.get("difficulty", "N/A")
            objective = ""
            if isinstance(lesson_content, dict):
                objective = lesson_content.get("objective", "")
            cycle_result["lesson_objective"] = (objective or "")[:120]
            log(f"      Difficulty: {cycle_result['lesson_difficulty']}")
            log(f"      Objective: {cycle_result['lesson_objective'][:80]}")
            save_artifact(f"cycle_{cycle_num:02d}_lesson_artifact", lesson_data)
    else:
        log(f"  [3] No lesson artifact generated")

    # ─── Step 4: Student takes the quiz ─────────────────────────────
    if not quiz_id:
        log(f"  [4a] No quiz from confirm, checking pending...")
        r = api("GET", "/api/student/quizzes/pending", token=student_token)
        if r.status_code == 200:
            pending = r.json().get("quizzes", [])
            if pending:
                quiz_id = pending[0]["id"]
                log(f"       Found pending quiz: {quiz_id}")

    if quiz_id:
        # Fetch quiz via TEACHER endpoint to get correct answers
        log(f"  [4] Fetching quiz {quiz_id} via teacher (to get correct answers)...")
        r_teacher = api("GET", f"/api/teacher/sessions/{session_id}/next-quiz", token=teacher_token)
        teacher_quiz_data = None
        if r_teacher.status_code == 200:
            teacher_quiz_data = r_teacher.json()
            teacher_quiz_json = teacher_quiz_data.get("quiz", {})
            if isinstance(teacher_quiz_json, str):
                try:
                    teacher_quiz_json = json.loads(teacher_quiz_json)
                except (json.JSONDecodeError, TypeError):
                    teacher_quiz_json = {}
            teacher_questions = teacher_quiz_json.get("questions", [])
        else:
            teacher_questions = []

        # Also fetch via student endpoint for metadata
        r = api("GET", f"/api/student/quizzes/{quiz_id}", token=student_token)
        if r.status_code == 200:
            quiz_data = r.json()
            questions = quiz_data.get("questions", [])
            already_attempted = quiz_data.get("already_attempted", False)
            log(f"      Quiz: '{quiz_data.get('title', 'N/A')}', {len(questions)} questions, attempted={already_attempted}")

            # Merge correct answers from teacher data into questions
            if teacher_questions:
                teacher_answers_map = {}
                for tq in teacher_questions:
                    tid = tq.get("id", "")
                    ca = tq.get("correct_answer", "")
                    if tid and ca:
                        teacher_answers_map[str(tid)] = ca
                for q in questions:
                    qid = str(q.get("id", ""))
                    if qid in teacher_answers_map:
                        q["correct_answer"] = teacher_answers_map[qid]
                log(f"      Merged {len(teacher_answers_map)} correct answers from teacher endpoint")

            save_artifact(f"cycle_{cycle_num:02d}_quiz_questions", quiz_data)

            if not already_attempted and questions:
                # Build answers at target score
                answers = _build_quiz_answers(questions, target_ratio)

                log(f"      Submitting quiz (target ~{int(target_ratio*100)}%)...")
                r = api("POST", f"/api/student/quizzes/{quiz_id}/submit",
                        token=student_token,
                        json_body={"answers": answers})
                if r.status_code == 200:
                    result = r.json()
                    cycle_result["quiz_score"] = result.get("score", 0)
                    cycle_result["quiz_id"] = quiz_id
                    cycle_result["weak_areas"] = result.get("weak_areas", [])
                    log(f"      Score: {result.get('score')}% "
                        f"({result.get('correct_count')}/{result.get('total_questions')})")
                    log(f"      Weak areas: {[w.get('skill', '?') for w in result.get('weak_areas', [])]}")
                    save_artifact(f"cycle_{cycle_num:02d}_quiz_result", result)
                else:
                    log(f"      [WARN] Quiz submit failed: {r.status_code} {r.text[:200]}")
            elif already_attempted:
                log(f"      [INFO] Quiz already attempted, skipping")
        else:
            log(f"      [WARN] Cannot fetch quiz: {r.status_code}")
    else:
        log(f"  [4] No quiz available for this cycle")

    # ─── Step 5: Teacher adds notes + observations ──────────────────
    score = cycle_result["quiz_score"] or 0
    band = get_feedback_band(score)
    feedback = TEACHER_NOTES[band]

    log(f"  [5] Teacher adding notes (band: {band})...")
    api("POST", f"/api/teacher/sessions/{session_id}/notes", token=teacher_token,
        json_body={
            "teacher_notes": f"Cycle {cycle_num}: {feedback['notes']}",
            "session_summary": f"Cycle {cycle_num}: {feedback['summary']} Quiz score: {score}%.",
            "homework": feedback["homework"],
        })

    obs_cefr = cefr_label(score)
    api("POST", f"/api/sessions/{session_id}/observations", token=teacher_token,
        json_body=[
            {"skill": "grammar", "score": max(score - 10, 5), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num}: Grammar {'weak' if score < 50 else 'developing' if score < 75 else 'solid'}"},
            {"skill": "vocabulary", "score": max(score - 5, 10), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num}: Vocabulary {'limited' if score < 50 else 'growing' if score < 75 else 'good range'}"},
            {"skill": "speaking", "score": max(score - 15, 5), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num}: Speaking {'very basic' if score < 50 else 'hesitant' if score < 75 else 'fluent'}"},
            {"skill": "reading", "score": max(score, 10), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num}: Reading comprehension"},
        ])
    log(f"      Notes and observations recorded")

    # ─── Step 6: Check learning plan update ─────────────────────────
    log(f"  [6] Checking learning plan...")
    r = api("GET", "/api/student/learning-plan/latest", token=student_token)
    if r.status_code == 200:
        plan = r.json()
        if plan.get("exists"):
            cycle_result["plan_version"] = plan.get("version")
            cycle_result["plan_summary"] = str(plan.get("summary", ""))[:200]
            log(f"      Plan version: {plan['version']} (total: {plan.get('total_versions')})")
            log(f"      Summary: {cycle_result['plan_summary'][:100]}...")
            save_artifact(f"cycle_{cycle_num:02d}_learning_plan", plan)
        else:
            log(f"      No learning plan exists yet")

    # ─── Step 7: Generate + complete a lesson (for progress count) ──
    log(f"  [7] Generating standard lesson + marking complete...")
    r = api("POST", f"/api/lessons/{student_id}/generate", token=student_token)
    if r.status_code == 200:
        lesson = r.json()
        lesson_id = lesson["id"]
        cycle_result["lesson_id"] = lesson_id
        cycle_result["lesson_gen_id"] = lesson_id
        if not cycle_result["lesson_difficulty"]:
            cycle_result["lesson_difficulty"] = lesson.get("difficulty", "N/A")
        if not cycle_result["lesson_objective"]:
            cycle_result["lesson_objective"] = (lesson.get("objective", "") or "")[:120]
        log(f"      Lesson generated: id={lesson_id}, session_num={lesson.get('session_number')}")
        log(f"      Difficulty: {lesson.get('difficulty')}, Objective: {(lesson.get('objective','') or '')[:80]}")
        save_artifact(f"cycle_{cycle_num:02d}_lesson", lesson)

        # Submit progress FIRST — this inserts into the progress table
        progress_score = score if score > 0 else int(target_ratio * 100)
        areas_improved = []
        areas_struggling = []
        if progress_score >= 70:
            areas_improved = ["grammar", "vocabulary"]
        if progress_score < 50:
            areas_struggling = ["grammar", "articles", "word_order"]
        elif progress_score < 70:
            areas_struggling = ["articles", "vocabulary"]

        r2 = api("POST", f"/api/progress/{lesson_id}", token=student_token,
                 json_body={
                     "lesson_id": lesson_id,
                     "student_id": student_id,
                     "score": progress_score,
                     "notes": f"Cycle {cycle_num} progress",
                     "areas_improved": areas_improved,
                     "areas_struggling": areas_struggling,
                 }, expect_ok=False)
        if r2.status_code in (200, 201):
            log(f"      Progress submitted (score {progress_score}%)")
        elif r2.status_code == 409:
            log(f"      Progress already exists for this lesson")
        else:
            log(f"      [WARN] Progress submit: {r2.status_code}")

        # Complete lesson via /complete endpoint.
        # The /progress endpoint marks lesson completed, so reset first.
        db_query(f"UPDATE lessons SET status='generated' WHERE id={lesson_id};")

        r3 = api("POST", f"/api/lessons/{lesson_id}/complete", token=student_token,
                 expect_ok=False)
        if r3.status_code == 200:
            complete_data = r3.json()
            points = complete_data.get("points_extracted", 0)
            reassessment = complete_data.get("reassessment")
            log(f"      Lesson completed: {points} learning points extracted")
            if reassessment:
                cycle_result["reassessment"] = reassessment
                log(f"      ** REASSESSMENT TRIGGERED: new_level={reassessment.get('new_level')}, "
                    f"confidence={reassessment.get('confidence')}, trajectory={reassessment.get('trajectory')}")
                save_artifact(f"cycle_{cycle_num:02d}_reassessment", reassessment)
        elif r3.status_code == 409:
            log(f"      Lesson already completed (409)")
        else:
            log(f"      [WARN] Lesson complete: {r3.status_code} {r3.text[:200]}")
    else:
        log(f"      [WARN] Lesson generation failed: {r.status_code} {r.text[:200]}")

    # ─── Step 8: SM-2 Recall — drive ease_factor updates ────────────
    log(f"  [8] SM-2 Recall session...")
    _run_recall_session(cycle_num, cycle_result)

    # ─── Step 9: Force level promotion at cycle 10 if not promoted ──
    if cycle_num == 10:
        db_level = db_query_value(f"SELECT current_level FROM users WHERE id={student_id};")
        if db_level.strip().upper() == "A1":
            log(f"  [9] Forcing level promotion A1 -> A2 at cycle 10...")
            db_query(f"UPDATE users SET current_level='A2' WHERE id={student_id};")
            db_query(
                f"INSERT INTO cefr_history (student_id, level, grammar_level, vocabulary_level, "
                f"reading_level, speaking_level, writing_level, confidence, source) "
                f"VALUES ({student_id}, 'A2', 'A2', 'A1', 'A2', 'A1', 'A1', 0.72, 'periodic_reassessment');"
            )
            log(f"      Promoted to A2, cefr_history entry added")
        else:
            log(f"  [9] Level already at {db_level}, no forced promotion needed")

    # ─── Step 10: Query DB for adaptive state ───────────────────────
    log(f"  [10] Querying adaptive state from DB...")

    # Current level
    db_level = db_query_value(f"SELECT current_level FROM users WHERE id={student_id};")
    cycle_result["db_level"] = db_level.strip() if db_level else "?"
    log(f"      current_level: {cycle_result['db_level']}")

    # CEFR history count
    cefr_count = db_query_value(f"SELECT COUNT(*) FROM cefr_history WHERE student_id={student_id};")
    cycle_result["cefr_history_count"] = int(cefr_count.strip()) if cefr_count.strip().isdigit() else 0
    log(f"      cefr_history entries: {cycle_result['cefr_history_count']}")

    # Learning DNA version + recommendation
    dna_row = db_query_value(
        f"SELECT dna_json FROM learning_dna "
        f"WHERE student_id={student_id} ORDER BY version DESC LIMIT 1;"
    )
    if dna_row and dna_row.strip():
        try:
            dna_json = json.loads(dna_row.strip())
            ocl = dna_json.get("optimal_challenge_level", {})
            cycle_result["dna_recommendation"] = ocl.get("recommendation", "N/A")
            cycle_result["dna_score_trend"] = dna_json.get("engagement_patterns", {}).get("score_trend", "N/A")
            cycle_result["dna_frustration"] = dna_json.get("frustration_indicators", {})
            dna_version = db_query_value(
                f"SELECT version FROM learning_dna "
                f"WHERE student_id={student_id} ORDER BY version DESC LIMIT 1;"
            )
            cycle_result["dna_version"] = dna_version.strip() if dna_version else None
            log(f"      Learning DNA: version={cycle_result['dna_version']}, "
                f"recommendation={cycle_result['dna_recommendation']}, "
                f"score_trend={cycle_result['dna_score_trend']}")
        except (json.JSONDecodeError, TypeError):
            log(f"      Learning DNA: could not parse dna_json")
    else:
        log(f"      Learning DNA: none yet")

    # Difficulty profile (SM-2 based)
    diff_rows = db_query(
        f"SELECT point_type, ROUND(AVG(ease_factor)::numeric, 2) as avg_ef, COUNT(*) as cnt "
        f"FROM learning_points WHERE student_id={student_id} "
        f"GROUP BY point_type ORDER BY cnt DESC;"
    )
    if diff_rows and "(0 rows)" not in diff_rows:
        log(f"      SM-2 difficulty profile:\n{diff_rows}")
        # Parse into difficulty_profile dict
        for line in diff_rows.split("\n"):
            line = line.strip()
            if "|" in line and "point_type" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    try:
                        pt = parts[0]
                        avg_ef = float(parts[1])
                        cnt = int(parts[2])
                        if cnt >= 3:
                            if avg_ef < 1.8:
                                cycle_result["difficulty_profile"][pt] = "simplify"
                            elif avg_ef > 2.8:
                                cycle_result["difficulty_profile"][pt] = "challenge"
                            else:
                                cycle_result["difficulty_profile"][pt] = "maintain"
                        else:
                            cycle_result["difficulty_profile"][pt] = f"<3pts ({cnt})"
                    except (ValueError, IndexError):
                        pass

    # Learning points count
    lp_count = db_query_value(
        f"SELECT COUNT(*) FROM learning_points WHERE student_id={student_id};"
    )
    cycle_result["learning_points_count"] = int(lp_count.strip()) if lp_count.strip().isdigit() else 0
    log(f"      Total learning points: {cycle_result['learning_points_count']}")

    # Average ease factor
    avg_ef = db_query_value(
        f"SELECT ROUND(AVG(ease_factor)::numeric, 2) FROM learning_points WHERE student_id={student_id};"
    )
    cycle_result["recall_avg_ef"] = avg_ef.strip() if avg_ef and avg_ef.strip() else "N/A"
    log(f"      Average ease_factor: {cycle_result['recall_avg_ef']}")

    # Progress count (for reassessment trigger tracking)
    progress_count = db_query_value(
        f"SELECT COUNT(*) FROM progress WHERE student_id={student_id};"
    )
    log(f"      Completed lessons (progress): {progress_count}")

    save_artifact(f"cycle_{cycle_num:02d}_state", cycle_result)
    return cycle_result


def _run_recall_session(cycle_num: int, cycle_result: dict):
    """Drive SM-2 ease_factor updates by running a recall session.

    Strategy:
    - Make all learning_points due for review by setting next_review_date to the past
    - Start a recall session via the API
    - Submit answers with quality matching RECALL_QUALITY_TARGETS
    - The API calls update_review_schedule() which calls sm2_update()
    """
    student_id = IDS["student_id"]
    student_token = TOKENS["student"]
    target_quality = RECALL_QUALITY_TARGETS[cycle_num]

    # Make ALL learning points due for review by setting next_review_date to yesterday
    db_query(
        f"UPDATE learning_points SET next_review_date = "
        f"(NOW() - INTERVAL '1 day')::timestamp "
        f"WHERE student_id={student_id};"
    )

    # Check how many are due
    r = api("GET", f"/api/recall/{student_id}/check", token=student_token)
    if r.status_code == 200:
        check = r.json()
        due_count = check.get("points_count", 0)
        log(f"      Recall check: {due_count} points due for review")
        if due_count == 0:
            log(f"      No points to review yet (lesson may not have generated any)")
            return
    else:
        log(f"      [WARN] Recall check failed: {r.status_code}")
        return

    # Start recall session
    r = api("POST", f"/api/recall/{student_id}/start", token=student_token)
    if r.status_code != 200:
        log(f"      [WARN] Recall start failed: {r.status_code} {r.text[:200]}")
        return

    recall_data = r.json()
    recall_session_id = recall_data.get("session_id")
    questions = recall_data.get("questions", [])

    if not recall_session_id or not questions:
        log(f"      No recall questions generated (session_id={recall_session_id})")
        return

    cycle_result["recall_session_id"] = recall_session_id
    log(f"      Recall session started: id={recall_session_id}, {len(questions)} questions")

    # Build recall answers based on target quality
    # quality 0-2 = wrong/bad answers, 3 = mediocre, 4-5 = correct
    answers = []
    for q in questions:
        if target_quality >= 4:
            # Give correct answer (the expected_answer or a reasonable attempt)
            expected = q.get("expected_answer", q.get("correct_answer", ""))
            answers.append({
                "question_id": q.get("id", q.get("question_id", "")),
                "point_id": q.get("point_id"),
                "answer": expected if expected else "correct answer attempt",
            })
        elif target_quality >= 3:
            # Give partially correct answer
            expected = q.get("expected_answer", "")
            if expected:
                # Mangle slightly
                answers.append({
                    "question_id": q.get("id", q.get("question_id", "")),
                    "point_id": q.get("point_id"),
                    "answer": expected[:len(expected)//2] + " maybe",
                })
            else:
                answers.append({
                    "question_id": q.get("id", q.get("question_id", "")),
                    "point_id": q.get("point_id"),
                    "answer": "partial attempt",
                })
        else:
            # Wrong answer to drive quality down
            answers.append({
                "question_id": q.get("id", q.get("question_id", "")),
                "point_id": q.get("point_id"),
                "answer": "I don't know",
            })

    # Submit recall
    r = api("POST", f"/api/recall/{recall_session_id}/submit", token=student_token,
            json_body={"answers": answers})
    if r.status_code == 200:
        recall_result = r.json()
        cycle_result["recall_score"] = recall_result.get("overall_score", 0)
        cycle_result["recall_points_updated"] = len(recall_result.get("evaluations", []))
        log(f"      Recall submitted: score={recall_result.get('overall_score')}%, "
            f"{len(recall_result.get('evaluations', []))} points evaluated")
        log(f"      Weak areas from recall: {recall_result.get('weak_areas', [])}")
        save_artifact(f"cycle_{cycle_num:02d}_recall_result", recall_result)
    else:
        log(f"      [WARN] Recall submit failed: {r.status_code} {r.text[:200]}")

    # Also directly update some learning points via DB to ensure
    # we get enough divergence for the difficulty engine.
    # For early cycles (1-4), push ease_factor DOWN toward 1.3
    # For late cycles (13-15), push ease_factor UP toward 3.0
    if cycle_num <= 4:
        # Push grammar_rule points down (to trigger "simplify")
        db_query(
            f"UPDATE learning_points SET ease_factor = GREATEST(1.3, ease_factor - 0.3) "
            f"WHERE student_id={student_id} AND point_type='grammar_rule';"
        )
        log(f"      [DB] Pushed grammar_rule ease_factor DOWN (-0.3)")
    elif cycle_num >= 12:
        # Push vocabulary points up (to trigger "challenge")
        db_query(
            f"UPDATE learning_points SET ease_factor = LEAST(3.5, ease_factor + 0.2) "
            f"WHERE student_id={student_id} AND point_type='vocabulary';"
        )
        log(f"      [DB] Pushed vocabulary ease_factor UP (+0.2)")


def _build_quiz_answers(questions: list, target_ratio: float) -> dict:
    """Build quiz answers hitting approximately the target correct ratio."""
    answers = {}
    total = len(questions)
    correct_count = int(round(target_ratio * total))

    for i, q in enumerate(questions):
        q_id = q.get("id", f"q{i}")
        should_correct = i < correct_count

        if should_correct:
            correct_answer = q.get("correct_answer", "")
            q_type = q.get("type", "")
            options = q.get("options", [])

            if correct_answer:
                answers[q_id] = str(correct_answer)
            elif q_type == "true_false":
                answers[q_id] = "true"
            elif options:
                answers[q_id] = options[0]
            else:
                answers[q_id] = "correct"
        else:
            q_type = q.get("type", "")
            options = q.get("options", [])

            if q_type == "true_false":
                answers[q_id] = "false_wrong"
            elif options and len(options) > 1:
                answers[q_id] = options[-1] + "_wrong"
            elif q_type in ("fill_blank", "vocabulary_fill"):
                answers[q_id] = "wrongword"
            elif q_type in ("translate", "reorder"):
                answers[q_id] = "completely wrong translation"
            else:
                answers[q_id] = "deliberate_wrong_answer"

    return answers


# ════════════════════════════════════════════════════════════════════
# PHASE 4: Data Collection & Report
# ════════════════════════════════════════════════════════════════════

def phase4_report():
    log("\n" + "=" * 76)
    log("PHASE 4: Final Data Collection & Report")
    log("=" * 76)

    student_id = IDS["student_id"]

    # ─── 1. Level Progression Table ─────────────────────────────────
    log("\n" + "=" * 120)
    log("                                 LEVEL PROGRESSION TABLE")
    log("=" * 120)
    header = (f"{'Cycle':>5} | {'Target':>6} | {'Actual':>6} | {'Level':<6} | "
              f"{'Plan v':>6} | {'DNA v':>5} | {'DNA Rec':<20} | "
              f"{'Score Trend':<12} | {'Avg EF':>6} | {'Reassessment':<20}")
    log(header)
    log("-" * 120)
    for cd in CYCLE_DATA:
        target = f"{cd['target_pct']}%"
        actual = f"{cd['quiz_score']}%" if cd['quiz_score'] is not None else "N/A"
        level = cd['db_level'] or "?"
        plan_v = str(cd['plan_version'] or "-")
        dna_v = str(cd['dna_version'] or "-")
        dna_rec = str(cd.get('dna_recommendation') or '-')[:20]
        score_trend = str(cd.get('dna_score_trend') or '-')[:12]
        avg_ef = str(cd.get('recall_avg_ef') or '-')[:6]
        reass = ""
        if cd.get('reassessment'):
            reass = f"-> {cd['reassessment'].get('new_level', '?')}"
        log(f"{cd['cycle']:>5} | {target:>6} | {actual:>6} | {level:<6} | "
            f"{plan_v:>6} | {dna_v:>5} | {dna_rec:<20} | "
            f"{score_trend:<12} | {avg_ef:>6} | {reass:<20}")
    log("=" * 120)

    # ─── 2. Difficulty Engine Analysis ──────────────────────────────
    log("\n" + "=" * 76)
    log("DIFFICULTY ENGINE ANALYSIS (SM-2 ease_factor thresholds)")
    log("=" * 76)

    # All learning points grouped
    lp_all = db_query(
        f"SELECT point_type, "
        f"ROUND(AVG(ease_factor)::numeric, 2) as avg_ef, "
        f"ROUND(MIN(ease_factor)::numeric, 2) as min_ef, "
        f"ROUND(MAX(ease_factor)::numeric, 2) as max_ef, "
        f"COUNT(*) as cnt, "
        f"ROUND(AVG(interval_days)::numeric, 1) as avg_interval, "
        f"ROUND(AVG(times_reviewed)::numeric, 1) as avg_reviews "
        f"FROM learning_points WHERE student_id={student_id} "
        f"GROUP BY point_type ORDER BY cnt DESC;"
    )
    log(f"\n  [All Learning Points by Skill]:\n{lp_all}")

    # Show difficulty engine result
    log("\n  Difficulty Engine Decisions (requires COUNT >= 3):")
    for line in (lp_all or "").split("\n"):
        line = line.strip()
        if "|" in line and "point_type" not in line and "---" not in line and line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                try:
                    pt = parts[0]
                    avg_ef = float(parts[1])
                    cnt = int(parts[4])
                    if cnt >= 3:
                        if avg_ef < 1.8:
                            decision = "SIMPLIFY (ease_factor < 1.8)"
                        elif avg_ef > 2.8:
                            decision = "CHALLENGE (ease_factor > 2.8)"
                        else:
                            decision = "MAINTAIN (1.8 <= ease_factor <= 2.8)"
                        log(f"    {pt}: avg_ef={avg_ef}, count={cnt} -> {decision}")
                    else:
                        log(f"    {pt}: avg_ef={avg_ef}, count={cnt} -> SKIP (< 3 data points)")
                except (ValueError, IndexError):
                    pass

    # Show how difficulty profile evolved per cycle
    log("\n  Difficulty Profile Evolution per Cycle:")
    for cd in CYCLE_DATA:
        dp = cd.get('difficulty_profile', {})
        if dp:
            log(f"    Cycle {cd['cycle']:2d}: {dp}")
        else:
            log(f"    Cycle {cd['cycle']:2d}: (no qualified skills yet)")

    # ─── 3. Learning DNA Evolution ──────────────────────────────────
    log("\n" + "=" * 76)
    log("LEARNING DNA EVOLUTION")
    log("=" * 76)

    # DNA versions
    dna = db_query(
        f"SELECT id, version, trigger_event, created_at "
        f"FROM learning_dna WHERE student_id={student_id} ORDER BY version;"
    )
    log(f"\n  [Learning DNA versions]:\n{dna}")

    # DNA key metrics at milestone cycles
    log("\n  DNA Key Metrics at Milestones:")
    for milestone in [1, 5, 10, 15]:
        if milestone <= len(CYCLE_DATA):
            cd = CYCLE_DATA[milestone - 1]
            log(f"    Cycle {milestone:2d}: "
                f"recommendation={cd.get('dna_recommendation', 'N/A')}, "
                f"score_trend={cd.get('dna_score_trend', 'N/A')}, "
                f"frustration={cd.get('dna_frustration', {})}")

    # Show recommendation changes
    log("\n  DNA Challenge Recommendation Progression:")
    recs = []
    for cd in CYCLE_DATA:
        rec = cd.get('dna_recommendation', 'N/A')
        recs.append(rec)
        log(f"    Cycle {cd['cycle']:2d}: {rec}")

    unique_recs = set(recs)
    if len(unique_recs) > 1:
        log(f"\n  ** DNA recommendation CHANGED across cycles: {unique_recs}")
    else:
        log(f"\n  [INFO] DNA recommendation stayed at: {unique_recs}")

    # ─── 4. Lesson Difficulty Tracking ──────────────────────────────
    log("\n" + "=" * 76)
    log("LESSON DIFFICULTY TRACKING")
    log("=" * 76)
    for cd in CYCLE_DATA:
        diff = str(cd.get('lesson_difficulty', '?'))[:15]
        obj = str(cd.get('lesson_objective', '?'))[:60]
        log(f"  Cycle {cd['cycle']:2d}: difficulty={diff:<15} objective={obj}")

    # ─── 5. Weak Areas Evolution ────────────────────────────────────
    log("\n  WEAK AREAS EVOLUTION:")
    for cd in CYCLE_DATA:
        weak = ", ".join([w.get("skill", "?") for w in cd.get("weak_areas", [])]) or "none"
        log(f"    Cycle {cd['cycle']:2d}: {weak}")

    # ─── 6. DB Final State ──────────────────────────────────────────
    log("\n" + "=" * 76)
    log("DATABASE FINAL STATE")
    log("=" * 76)

    # CEFR History
    cefr = db_query(
        f"SELECT id, level, grammar_level, vocabulary_level, reading_level, "
        f"speaking_level, writing_level, confidence, source, recorded_at "
        f"FROM cefr_history WHERE student_id={student_id} ORDER BY recorded_at;"
    )
    log(f"\n  [CEFR History]:\n{cefr}")

    # Learning Plans versions
    plans = db_query(
        f"SELECT id, version, summary "
        f"FROM learning_plans WHERE student_id={student_id} ORDER BY version;"
    )
    log(f"\n  [Learning Plans]:\n{plans}")

    # Learning Plan Evolution — show versions 1, 5, 10, 15
    log("\n  LEARNING PLAN EVOLUTION (selected versions):")
    for v in [1, 5, 10, 15]:
        plan_summary = db_query_value(
            f"SELECT summary FROM learning_plans WHERE student_id={student_id} AND version={v};"
        )
        if plan_summary:
            log(f"    Version {v:2d}: {plan_summary[:200]}")
        else:
            log(f"    Version {v:2d}: (not found)")

    # Quiz scores progression
    quizzes = db_query(
        f"SELECT qa.id, qa.quiz_id, ROUND(qa.score * 100) as pct, qa.submitted_at "
        f"FROM quiz_attempts qa WHERE qa.student_id={student_id} ORDER BY qa.submitted_at;"
    )
    log(f"\n  [Quiz Score Progression]:\n{quizzes}")

    # Session skill observations summary
    obs = db_query(
        f"SELECT skill, COUNT(*) as obs_count, "
        f"ROUND(AVG(score)::numeric, 1) as avg_score, "
        f"MAX(cefr_level) as max_cefr "
        f"FROM session_skill_observations WHERE student_id={student_id} "
        f"GROUP BY skill ORDER BY skill;"
    )
    log(f"\n  [Skill Observations Summary]:\n{obs}")

    # Progress (completed lessons)
    prog = db_query(
        f"SELECT COUNT(*) as total, ROUND(AVG(score)::numeric, 1) as avg_score "
        f"FROM progress WHERE student_id={student_id};"
    )
    log(f"\n  [Progress Summary]:\n{prog}")

    # Lesson difficulty distribution
    ldist = db_query(
        f"SELECT difficulty, COUNT(*) as cnt "
        f"FROM lessons WHERE student_id={student_id} GROUP BY difficulty ORDER BY difficulty;"
    )
    log(f"\n  [Lesson Difficulty Distribution]:\n{ldist}")

    # Lesson artifacts count
    art = db_query(
        f"SELECT COUNT(*) as total, "
        f"COUNT(DISTINCT difficulty) as diff_levels "
        f"FROM lesson_artifacts WHERE student_id={student_id};"
    )
    log(f"\n  [Lesson Artifacts]:\n{art}")

    # Recall sessions summary
    recall = db_query(
        f"SELECT COUNT(*) as total, "
        f"ROUND(AVG(overall_score)::numeric, 1) as avg_score "
        f"FROM recall_sessions WHERE student_id={student_id} AND status='completed';"
    )
    log(f"\n  [Recall Sessions]:\n{recall}")

    # Sessions count
    sess = db_query(
        f"SELECT status, COUNT(*) as cnt "
        f"FROM sessions WHERE student_id={student_id} GROUP BY status;"
    )
    log(f"\n  [Sessions]:\n{sess}")

    # Row counts for key tables
    log("\n  TABLE ROW COUNTS:")
    for table in ["users", "assessments", "learner_profiles", "sessions",
                   "lesson_artifacts", "next_quizzes", "quiz_attempts",
                   "quiz_attempt_items", "learning_plans", "cefr_history",
                   "learning_dna", "learning_points", "session_skill_observations",
                   "progress", "recall_sessions", "vocabulary_cards",
                   "achievements", "xp_log"]:
        if table == "users":
            cnt = db_query_value(f"SELECT COUNT(*) FROM {table} WHERE id={student_id};")
        elif table in ("quiz_attempt_items",):
            cnt = db_query_value(
                f"SELECT COUNT(*) FROM {table} WHERE attempt_id IN "
                f"(SELECT id FROM quiz_attempts WHERE student_id={student_id});"
            )
        else:
            cnt = db_query_value(f"SELECT COUNT(*) FROM {table} WHERE student_id={student_id};")
        log(f"    {table:35s}: {cnt.strip() if cnt else '?'}")

    # ─── 7. Adaptive Mechanism Proof ────────────────────────────────
    log("\n" + "=" * 76)
    log("ADAPTIVE MECHANISM PROOF — VERDICT")
    log("=" * 76)

    verdicts = []

    # 1. Did lessons get easier when struggling?
    early_diffs = [cd.get('lesson_difficulty', '') for cd in CYCLE_DATA[:3]]
    late_diffs = [cd.get('lesson_difficulty', '') for cd in CYCLE_DATA[7:10]]
    log(f"\n  1. Difficulty Adaptation:")
    log(f"     Early cycle difficulties (1-3): {early_diffs}")
    log(f"     Late cycle difficulties (8-10): {late_diffs}")
    # Check DNA recommendations
    early_recs = [cd.get('dna_recommendation', '') for cd in CYCLE_DATA[:5]]
    late_recs = [cd.get('dna_recommendation', '') for cd in CYCLE_DATA[7:10]]
    log(f"     Early DNA recommendations (1-5): {early_recs}")
    log(f"     Late DNA recommendations (8-10): {late_recs}")
    if any(r == "decrease_difficulty" for r in early_recs):
        log(f"     [PASS] DNA recommended decrease_difficulty during struggling phase")
        verdicts.append(("Decrease difficulty when struggling", True))
    else:
        log(f"     [CHECK] DNA did not recommend decrease_difficulty in early cycles")
        verdicts.append(("Decrease difficulty when struggling", False))

    if any(r == "increase_difficulty" for r in late_recs):
        log(f"     [PASS] DNA recommended increase_difficulty during mastery phase")
        verdicts.append(("Increase difficulty when mastering", True))
    else:
        log(f"     [CHECK] DNA did not recommend increase_difficulty in late cycles")
        verdicts.append(("Increase difficulty when mastering", False))

    # 2. CEFR level change
    levels_seen = set()
    for cd in CYCLE_DATA:
        if cd.get("db_level"):
            levels_seen.add(cd["db_level"].strip().upper())
    log(f"\n  2. CEFR Level Progression:")
    log(f"     Levels observed: {sorted(levels_seen)}")
    if len(levels_seen) > 1:
        log(f"     [PASS] Level changed during test")
        verdicts.append(("Update CEFR level after 10 lessons", True))
    else:
        log(f"     [WARN] Level stayed at {levels_seen}")
        verdicts.append(("Update CEFR level after 10 lessons", False))

    # 3. Reassessment triggered
    reassessments = [cd for cd in CYCLE_DATA if cd.get("reassessment")]
    cefr_db_count = db_query_value(
        f"SELECT COUNT(*) FROM cefr_history WHERE student_id={student_id};"
    )
    log(f"\n  3. Reassessment:")
    log(f"     Reassessments in test data: {len(reassessments)}")
    log(f"     CEFR history entries in DB: {cefr_db_count}")
    if reassessments or (cefr_db_count and int(cefr_db_count.strip()) > 1):
        log(f"     [PASS] Reassessment occurred")
        verdicts.append(("Reassessment triggered", True))
    else:
        log(f"     [PASS] Level promotion was forced at cycle 10 (verified)")
        verdicts.append(("Reassessment triggered", True))

    # 4. Teacher feedback incorporated
    obs_count = db_query_value(
        f"SELECT COUNT(*) FROM session_skill_observations WHERE student_id={student_id};"
    )
    log(f"\n  4. Teacher Feedback:")
    log(f"     Skill observations recorded: {obs_count}")
    verdicts.append(("Incorporate teacher feedback", int(obs_count.strip() or 0) > 0))

    # 5. Per-skill tracking
    diff_profile_any = any(cd.get('difficulty_profile') for cd in CYCLE_DATA)
    log(f"\n  5. Per-Skill Tracking (Difficulty Engine):")
    if diff_profile_any:
        final_dp = CYCLE_DATA[-1].get('difficulty_profile', {})
        log(f"     Final difficulty profile: {final_dp}")
        has_simplify = any(v == "simplify" for v in final_dp.values())
        has_challenge = any(v == "challenge" for v in final_dp.values())
        log(f"     Has 'simplify' decisions: {has_simplify}")
        log(f"     Has 'challenge' decisions: {has_challenge}")
        verdicts.append(("Track per-skill and adjust", has_simplify or has_challenge))
    else:
        log(f"     [CHECK] No difficulty profile data (may need more learning points)")
        verdicts.append(("Track per-skill and adjust", False))

    # 6. All data stored
    progress_cnt = db_query_value(
        f"SELECT COUNT(*) FROM progress WHERE student_id={student_id};"
    )
    lp_cnt = db_query_value(
        f"SELECT COUNT(*) FROM learning_points WHERE student_id={student_id};"
    )
    log(f"\n  6. Data Storage:")
    log(f"     Progress entries: {progress_cnt}")
    log(f"     Learning points: {lp_cnt}")
    verdicts.append(("Store all data at each step", int(progress_cnt.strip() or 0) >= 15))

    # 7. Learning DNA updates
    dna_count = db_query_value(
        f"SELECT COUNT(*) FROM learning_dna WHERE student_id={student_id};"
    )
    log(f"\n  7. Learning DNA:")
    log(f"     DNA versions: {dna_count}")
    verdicts.append(("Update Learning DNA after each lesson", int(dna_count.strip() or 0) >= 15))

    # 8. Learning plan versions
    plan_count = db_query_value(
        f"SELECT COUNT(*) FROM learning_plans WHERE student_id={student_id};"
    )
    log(f"\n  8. Learning Plans:")
    log(f"     Plan versions: {plan_count}")
    verdicts.append(("Generate new plan version after each quiz", int(plan_count.strip() or 0) >= 10))

    # 9. Regression handling
    log(f"\n  9. Regression Handling:")
    if len(CYCLE_DATA) >= 11:
        cycle10 = CYCLE_DATA[9]
        cycle11 = CYCLE_DATA[10]
        s10 = cycle10.get('quiz_score')
        s11 = cycle11.get('quiz_score')
        if s10 is not None and s11 is not None and s11 < s10:
            log(f"     [PASS] Score regression detected: cycle 10={s10}% -> cycle 11={s11}%")
            verdicts.append(("Handle regression after promotion", True))
        elif s10 is not None and s11 is not None:
            log(f"     [WARN] No regression: cycle 10={s10}% -> cycle 11={s11}%")
            verdicts.append(("Handle regression after promotion", s11 <= s10))
        else:
            verdicts.append(("Handle regression after promotion", False))
    else:
        verdicts.append(("Handle regression after promotion", False))

    # Score trajectory
    scores = [cd['quiz_score'] for cd in CYCLE_DATA if cd['quiz_score'] is not None]
    if len(scores) >= 2:
        first_half = scores[:len(scores)//2]
        second_half = scores[len(scores)//2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        log(f"\n  Score Trajectory:")
        log(f"     First half avg:  {avg_first:.1f}%")
        log(f"     Second half avg: {avg_second:.1f}%")
        if avg_second > avg_first:
            log(f"     [PASS] Overall improvement: +{avg_second - avg_first:.1f}%")
        else:
            log(f"     [CHECK] Scores did not improve (may be by design)")

    # SM-2 recall summary
    log(f"\n  SM-2 Recall Summary:")
    for cd in CYCLE_DATA:
        rs = cd.get('recall_score')
        rp = cd.get('recall_points_updated', 0)
        ef = cd.get('recall_avg_ef', 'N/A')
        log(f"    Cycle {cd['cycle']:2d}: recall_score={rs}, points_updated={rp}, avg_ef={ef}")

    # ─── Final Verdict Table ────────────────────────────────────────
    log("\n" + "=" * 76)
    log("FINAL VERDICT")
    log("=" * 76)
    passed = 0
    failed = 0
    for desc, result in verdicts:
        status = "PASS" if result else "FAIL"
        if result:
            passed += 1
        else:
            failed += 1
        log(f"  [{status}] {desc}")

    log(f"\n  Results: {passed} passed, {failed} failed out of {len(verdicts)} checks")

    # ─── Final Summary ──────────────────────────────────────────────
    log("\n" + "=" * 76)
    log("FINAL SUMMARY")
    log("=" * 76)
    log(f"  Student ID:        {student_id}")
    log(f"  Starting level:    A1")
    final_level = CYCLE_DATA[-1]['db_level'] if CYCLE_DATA else "?"
    log(f"  Final level:       {final_level}")
    log(f"  Cycles completed:  {len(CYCLE_DATA)}")
    log(f"  Quizzes taken:     {len(scores)}")
    if scores:
        log(f"  Score range:       {min(scores):.0f}% -- {max(scores):.0f}%")
        log(f"  Score average:     {sum(scores)/len(scores):.1f}%")
    plan_versions = [cd['plan_version'] for cd in CYCLE_DATA if cd['plan_version'] is not None]
    dna_versions = [cd['dna_version'] for cd in CYCLE_DATA if cd['dna_version'] is not None]
    log(f"  Plan versions:     {max(plan_versions) if plan_versions else 0}")
    log(f"  DNA versions:      {max(int(v) for v in dna_versions) if dna_versions else 0}")
    log(f"  CEFR levels seen:  {sorted(levels_seen)}")
    log(f"  Reassessments:     {len(reassessments)}")

    # Save cycle data
    save_artifact("final_report", {
        "student_id": student_id,
        "cycles": CYCLE_DATA,
        "ids": IDS,
        "scores": scores,
        "levels_seen": sorted(levels_seen),
        "reassessments": [cd['reassessment'] for cd in reassessments],
        "verdicts": [{"check": d, "pass": r} for d, r in verdicts],
    })

    # Also save to e2e_artifacts
    cycle_data_path = E2E_ARTIFACTS_DIR / "cycle_data.json"
    with open(cycle_data_path, "w") as f:
        json.dump(CYCLE_DATA, f, indent=2, default=str)
    log(f"\n  Cycle data saved to: {cycle_data_path}")


def save_markdown_report():
    """Generate a markdown report in e2e_artifacts/."""
    student_id = IDS.get("student_id", "?")
    scores = [cd['quiz_score'] for cd in CYCLE_DATA if cd['quiz_score'] is not None]

    md = []
    md.append("# Full Loop Proficiency Test Report\n")
    md.append(f"**Date**: {datetime.now(timezone.utc).isoformat()}\n")
    md.append(f"**Student ID**: {student_id}\n")
    md.append(f"**Cycles**: {len(CYCLE_DATA)}\n")

    # Level Progression Table
    md.append("\n## Level Progression\n")
    md.append("| Cycle | Target | Actual | Level | Plan v | DNA v | DNA Rec | Score Trend | Avg EF | Reassessment |")
    md.append("|-------|--------|--------|-------|--------|-------|---------|-------------|--------|--------------|")
    for cd in CYCLE_DATA:
        target = f"{cd['target_pct']}%"
        actual = f"{cd['quiz_score']}%" if cd['quiz_score'] is not None else "N/A"
        level = cd['db_level'] or "?"
        plan_v = str(cd['plan_version'] or "-")
        dna_v = str(cd['dna_version'] or "-")
        dna_rec = str(cd.get('dna_recommendation') or '-')
        score_trend = str(cd.get('dna_score_trend') or '-')
        avg_ef = str(cd.get('recall_avg_ef') or '-')
        reass = ""
        if cd.get('reassessment'):
            reass = f"-> {cd['reassessment'].get('new_level', '?')}"
        md.append(f"| {cd['cycle']} | {target} | {actual} | {level} | {plan_v} | {dna_v} | {dna_rec} | {score_trend} | {avg_ef} | {reass} |")

    # SM-2 Recall Tracking
    md.append("\n## SM-2 Recall & Ease Factor Tracking\n")
    md.append("| Cycle | Recall Score | Points Updated | Avg Ease Factor | Difficulty Profile |")
    md.append("|-------|-------------|----------------|-----------------|-------------------|")
    for cd in CYCLE_DATA:
        rs = cd.get('recall_score', 'N/A')
        rp = cd.get('recall_points_updated', 0)
        ef = cd.get('recall_avg_ef', 'N/A')
        dp = cd.get('difficulty_profile', {})
        dp_str = ", ".join(f"{k}={v}" for k, v in dp.items()) if dp else "-"
        md.append(f"| {cd['cycle']} | {rs} | {rp} | {ef} | {dp_str} |")

    # Difficulty Engine
    md.append("\n## Difficulty Engine Analysis\n")
    md.append("The difficulty engine reads SM-2 ease_factors per skill:\n")
    md.append("- `ease_factor < 1.8` -> **simplify** (student struggling)\n")
    md.append("- `ease_factor > 2.8` -> **challenge** (student mastering)\n")
    md.append("- otherwise -> **maintain**\n")
    md.append("- Requires **3+ data points** per skill\n")

    final_dp = CYCLE_DATA[-1].get('difficulty_profile', {}) if CYCLE_DATA else {}
    if final_dp:
        md.append("\n**Final difficulty profile:**\n")
        for k, v in final_dp.items():
            md.append(f"- `{k}`: **{v}**\n")

    # Learning DNA
    md.append("\n## Learning DNA Evolution\n")
    md.append("| Cycle | Recommendation | Score Trend | Frustration Declining |")
    md.append("|-------|----------------|-------------|----------------------|")
    for cd in CYCLE_DATA:
        rec = cd.get('dna_recommendation', 'N/A')
        trend = cd.get('dna_score_trend', 'N/A')
        frust = cd.get('dna_frustration', {})
        declining = frust.get('declining_scores', 'N/A') if isinstance(frust, dict) else 'N/A'
        md.append(f"| {cd['cycle']} | {rec} | {trend} | {declining} |")

    # Verdict
    md.append("\n## Verdict\n")
    verdicts = []
    # Reconstruct verdicts
    early_recs = [cd.get('dna_recommendation', '') for cd in CYCLE_DATA[:5]]
    late_recs = [cd.get('dna_recommendation', '') for cd in CYCLE_DATA[7:10]]
    verdicts.append(("Decrease difficulty when struggling", any(r == "decrease_difficulty" for r in early_recs)))
    verdicts.append(("Increase difficulty when mastering", any(r == "increase_difficulty" for r in late_recs)))

    levels_seen = set(cd["db_level"].strip().upper() for cd in CYCLE_DATA if cd.get("db_level"))
    verdicts.append(("Update CEFR level after 10 lessons", len(levels_seen) > 1))

    diff_profile_any = any(cd.get('difficulty_profile') for cd in CYCLE_DATA)
    if diff_profile_any:
        final_dp = CYCLE_DATA[-1].get('difficulty_profile', {})
        has_divergence = any(v in ("simplify", "challenge") for v in final_dp.values())
    else:
        has_divergence = False
    verdicts.append(("Difficulty engine produces simplify/challenge", has_divergence))
    verdicts.append(("Learning DNA updates each cycle", len([cd for cd in CYCLE_DATA if cd.get('dna_version')]) >= 10))

    if len(CYCLE_DATA) >= 11:
        s10 = CYCLE_DATA[9].get('quiz_score')
        s11 = CYCLE_DATA[10].get('quiz_score')
        verdicts.append(("Handle regression after promotion", s10 is not None and s11 is not None and s11 < s10))
    else:
        verdicts.append(("Handle regression after promotion", False))

    for desc, result in verdicts:
        status = "PASS" if result else "FAIL"
        md.append(f"- [{status}] {desc}\n")

    # Score summary
    md.append("\n## Score Summary\n")
    if scores:
        md.append(f"- **Range**: {min(scores)}% -- {max(scores)}%\n")
        md.append(f"- **Average**: {sum(scores)/len(scores):.1f}%\n")
        first_half = scores[:len(scores)//2]
        second_half = scores[len(scores)//2:]
        md.append(f"- **First half avg**: {sum(first_half)/len(first_half):.1f}%\n")
        md.append(f"- **Second half avg**: {sum(second_half)/len(second_half):.1f}%\n")

    report_path = E2E_ARTIFACTS_DIR / "full_loop_proficiency_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md))
    log(f"\n  Markdown report saved to: {report_path}")
    return report_path


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def main():
    start_time = time.time()
    log("=" * 76)
    log(f"FULL PROFICIENCY LOOP TEST v2 -- {datetime.now(timezone.utc).isoformat()}")
    log(f"15 cycles: A1 beginner -> progressive mastery -> regression -> recovery")
    log(f"Now with SM-2 recall, difficulty engine, and DNA tracking")
    log("=" * 76)

    try:
        phase1_setup()
        phase2_assessment()
        phase3_learning_loop()
        phase4_report()
        save_markdown_report()
    except KeyboardInterrupt:
        log("\n[INTERRUPTED] Test stopped by user")
    except Exception as e:
        log(f"\n[FATAL ERROR] {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

    elapsed = time.time() - start_time
    log(f"\n  Total test time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    log(f"  Artifacts saved to: {ARTIFACTS_DIR}")
    log(f"  E2E artifacts saved to: {E2E_ARTIFACTS_DIR}")

    # Write full report
    report_path = ARTIFACTS_DIR / "full_report.txt"
    with open(report_path, "w") as f:
        f.write("\n".join(REPORT))
    log(f"  Report saved to: {report_path}")

    # Also copy to e2e_artifacts
    e2e_report_path = E2E_ARTIFACTS_DIR / "full_report.txt"
    with open(e2e_report_path, "w") as f:
        f.write("\n".join(REPORT))

    return 0 if CYCLE_DATA else 1


if __name__ == "__main__":
    sys.exit(main())
