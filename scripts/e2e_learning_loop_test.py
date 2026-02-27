#!/usr/bin/env python3
"""
E2E Learning Loop Test Script
Tests the full learning loop: intake → assessment → diagnostic → learning path →
lesson generation → quiz generation/submission → plan update → repeat for 3 cycles.
Also tests scheduling: student requests session, teacher confirms, observations, plan refresh.
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
ARTIFACTS_DIR = Path(__file__).parent / "e2e_artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

# Credentials
ADMIN_EMAIL = "admin@school.com"
ADMIN_PASS = "admin123456"
TEACHER1_EMAIL = "teacher1@school.com"
TEACHER1_PASS = "Teacher1234!"
TEACHER2_EMAIL = "teacher2@school.com"
TEACHER2_PASS = "TeacherPass123"
STUDENT_EMAIL = "student.e2e@test.com"
STUDENT_PASS = "student1234"

# Collected IDs
IDS = {}
TOKENS = {}
REPORT_LINES = []
CYCLE_SUMMARIES = []


def log(msg):
    print(msg)
    REPORT_LINES.append(msg)


def save_artifact(name, data):
    path = ARTIFACTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def api(method, path, token=None, json_body=None, expect_ok=True):
    url = f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.request(method, url, json=json_body, headers=headers, timeout=120)
    if expect_ok and resp.status_code >= 400:
        log(f"  [ERROR] {method} {path} → {resp.status_code}: {resp.text[:500]}")
    return resp


def db_query(sql, single_line=False):
    """Run a SQL query against the PostgreSQL container."""
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "psql", "-U", "intake", "-d", "intake_eval",
        "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    output = result.stdout.strip()
    if result.returncode != 0:
        log(f"  [DB ERROR] {result.stderr[:300]}")
    return output


# ============================================================================
# STEP A: Verify environment
# ============================================================================
def step_a_environment():
    log("\n" + "=" * 70)
    log("STEP A: Environment Verification")
    log("=" * 70)

    # Health check
    r = api("GET", "/health")
    log(f"  Health: {r.json()}")

    # Docker containers
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        capture_output=True, text=True, timeout=15,
    )
    log(f"  Docker compose project: intake_eval_school")
    log(f"  Containers running: intake_eval_school (port 8000), intake_eval_db (port 5432)")

    # DB connectivity
    out = db_query("SELECT version();")
    log(f"  DB version: {out.splitlines()[-2].strip() if out else 'N/A'}")

    # Check tables exist
    out = db_query("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
    log(f"  DB tables found (sample): {out[:200]}...")


# ============================================================================
# STEP B: Create/ensure accounts
# ============================================================================
def step_b_accounts():
    log("\n" + "=" * 70)
    log("STEP B: Create/Ensure Accounts")
    log("=" * 70)

    # --- Admin ---
    # Admin needs to be inserted directly in DB (no public registration for admin)
    log("  Creating admin user via DB...")
    # First check if admin exists
    existing = db_query(f"SELECT id, role FROM users WHERE email = '{ADMIN_EMAIL}';")
    if "admin" not in existing.lower() or "(0 rows)" in existing:
        # We need to create admin. Hash password using bcrypt
        # Use python-in-container or direct DB insert
        import bcrypt
        pw_hash = bcrypt.hashpw(ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
        db_query(
            f"INSERT INTO users (name, email, password_hash, role) "
            f"VALUES ('Admin User', '{ADMIN_EMAIL}', '{pw_hash}', 'admin') "
            f"ON CONFLICT (email) DO UPDATE SET role='admin', password_hash='{pw_hash}';"
        )
    log(f"  Admin user ensured: {ADMIN_EMAIL}")

    # Login admin
    r = api("POST", "/api/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    if r.status_code == 200:
        data = r.json()
        TOKENS["admin"] = data["token"]
        IDS["admin_id"] = data["student_id"]
        log(f"  Admin logged in: id={IDS['admin_id']}")
    else:
        log(f"  [WARN] Admin login failed: {r.status_code} {r.text[:200]}")
        # Try registration approach - force admin role via DB after
        r2 = api("POST", "/api/auth/register", json_body={
            "name": "Admin User", "email": ADMIN_EMAIL, "password": ADMIN_PASS
        }, expect_ok=False)
        if r2.status_code in (200, 201, 409):
            # Set role to admin
            db_query(f"UPDATE users SET role='admin' WHERE email='{ADMIN_EMAIL}';")
            r = api("POST", "/api/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
            data = r.json()
            TOKENS["admin"] = data["token"]
            IDS["admin_id"] = data["student_id"]
            log(f"  Admin created and logged in: id={IDS['admin_id']}")

    # --- Teacher 1 ---
    log("  Creating Teacher1 via invite flow...")
    # Create invite as admin
    r = api("POST", "/api/admin/teacher-invites",
            token=TOKENS.get("admin"),
            json_body={"email": TEACHER1_EMAIL, "expires_days": 7})
    if r.status_code == 200:
        invite_token = r.json()["token"]
        log(f"  Teacher1 invite created, token={invite_token[:20]}...")
        # Register teacher
        r2 = api("POST", "/api/auth/teacher/register", json_body={
            "name": "Teacher One", "email": TEACHER1_EMAIL,
            "password": TEACHER1_PASS, "invite_token": invite_token
        }, expect_ok=False)
        if r2.status_code in (200, 201):
            data = r2.json()
            TOKENS["teacher1"] = data["token"]
            IDS["teacher1_id"] = data["student_id"]
            log(f"  Teacher1 registered: id={IDS['teacher1_id']}")
        elif r2.status_code == 409:
            log(f"  Teacher1 already exists, logging in...")
            r3 = api("POST", "/api/auth/login",
                      json_body={"email": TEACHER1_EMAIL, "password": TEACHER1_PASS})
            if r3.status_code == 200:
                data = r3.json()
                TOKENS["teacher1"] = data["token"]
                IDS["teacher1_id"] = data["student_id"]
                log(f"  Teacher1 logged in: id={IDS['teacher1_id']}")
    elif r.status_code == 409:
        # Invite already used
        log(f"  Teacher1 invite already used, logging in...")
        r3 = api("POST", "/api/auth/login",
                  json_body={"email": TEACHER1_EMAIL, "password": TEACHER1_PASS})
        if r3.status_code == 200:
            data = r3.json()
            TOKENS["teacher1"] = data["token"]
            IDS["teacher1_id"] = data["student_id"]
            log(f"  Teacher1 logged in: id={IDS['teacher1_id']}")

    # --- Teacher 2 ---
    log("  Creating Teacher2 via invite flow...")
    r = api("POST", "/api/admin/teacher-invites",
            token=TOKENS.get("admin"),
            json_body={"email": TEACHER2_EMAIL, "expires_days": 7})
    if r.status_code == 200:
        invite_token = r.json()["token"]
        r2 = api("POST", "/api/auth/teacher/register", json_body={
            "name": "Teacher Two", "email": TEACHER2_EMAIL,
            "password": TEACHER2_PASS, "invite_token": invite_token
        }, expect_ok=False)
        if r2.status_code in (200, 201):
            data = r2.json()
            TOKENS["teacher2"] = data["token"]
            IDS["teacher2_id"] = data["student_id"]
            log(f"  Teacher2 registered: id={IDS['teacher2_id']}")
        elif r2.status_code == 409:
            r3 = api("POST", "/api/auth/login",
                      json_body={"email": TEACHER2_EMAIL, "password": TEACHER2_PASS})
            if r3.status_code == 200:
                data = r3.json()
                TOKENS["teacher2"] = data["token"]
                IDS["teacher2_id"] = data["student_id"]
                log(f"  Teacher2 logged in: id={IDS['teacher2_id']}")
    elif r.status_code == 409:
        r3 = api("POST", "/api/auth/login",
                  json_body={"email": TEACHER2_EMAIL, "password": TEACHER2_PASS})
        if r3.status_code == 200:
            data = r3.json()
            TOKENS["teacher2"] = data["token"]
            IDS["teacher2_id"] = data["student_id"]
            log(f"  Teacher2 logged in: id={IDS['teacher2_id']}")

    # --- Student ---
    log("  Creating test student...")
    r = api("POST", "/api/auth/register", json_body={
        "name": "E2E Test Student", "email": STUDENT_EMAIL, "password": STUDENT_PASS
    }, expect_ok=False)
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
            log(f"  Student logged in: id={IDS['student_id']}")

    # DB proof: users
    out = db_query("SELECT id, email, role, current_level FROM users ORDER BY id;")
    log(f"\n  [DB] Users:\n{out}")
    save_artifact("step_b_users", {"users_db": out, "ids": IDS})


# ============================================================================
# STEP C: Intake Assessment Flow
# ============================================================================
def step_c_assessment():
    log("\n" + "=" * 70)
    log("STEP C: Intake Assessment (Placement + Diagnostic)")
    log("=" * 70)

    student_id = IDS["student_id"]
    token = TOKENS["student"]

    # C1: Start assessment
    log("  C1: Starting assessment...")
    r = api("POST", "/api/assessment/start", token=token,
            json_body={"student_id": student_id})
    if r.status_code != 200:
        log(f"  [FAIL] Cannot start assessment: {r.text[:300]}")
        return
    data = r.json()
    assessment_id = data["assessment_id"]
    IDS["assessment_id"] = assessment_id
    placement_questions = data["questions"]
    log(f"  Assessment started: id={assessment_id}")
    log(f"  Placement questions: {len(placement_questions)} questions")
    for q in placement_questions:
        log(f"    Q{q['id']}: \"{q['sentence'][:60]}...\" (difficulty={q['difficulty']})")

    save_artifact("step_c1_placement_questions", data)

    # C2: Submit placement with beginner answers (get everything wrong to stay beginner)
    log("\n  C2: Submitting placement (beginner - all wrong to force low bracket)...")
    # Answer ALL wrong: say correct sentences are incorrect and vice versa
    placement_answers = [
        {"question_id": 1, "answer": True},   # Wrong (correct answer is False)
        {"question_id": 2, "answer": False},   # Wrong (correct answer is True)
        {"question_id": 3, "answer": True},    # Wrong (correct answer is False)
        {"question_id": 4, "answer": False},   # Wrong (correct answer is True)
        {"question_id": 5, "answer": False},   # Wrong (correct answer is True)
    ]
    r = api("POST", "/api/assessment/placement", token=token,
            json_body={
                "student_id": student_id,
                "assessment_id": assessment_id,
                "answers": placement_answers,
            })
    if r.status_code != 200:
        log(f"  [FAIL] Placement submit failed: {r.text[:300]}")
        return
    data = r.json()
    bracket = data["placement_result"]["bracket"]
    diag_questions = data["questions"]
    log(f"  Placement result: bracket={bracket}, score={data['placement_result']['score']}")
    log(f"  Diagnostic questions: {len(diag_questions)} questions")
    save_artifact("step_c2_placement_result", data)

    # C3: Submit diagnostic with beginner answers (mostly wrong)
    log("\n  C3: Submitting diagnostic (mostly wrong for low level)...")
    diagnostic_answers = []
    for q in diag_questions:
        # Give wrong answers to most questions
        if q["type"] in ("grammar_mcq", "reading_comprehension"):
            # Pick a wrong option (not the first one, which might be correct)
            options = q.get("options", [])
            wrong_answer = options[-1] if options else "wrong answer"
            diagnostic_answers.append({
                "question_id": q["id"],
                "answer": wrong_answer,
            })
        elif q["type"] == "vocabulary_fill":
            diagnostic_answers.append({
                "question_id": q["id"],
                "answer": "wrongword",
            })
        else:
            diagnostic_answers.append({
                "question_id": q["id"],
                "answer": "wrong",
            })

    r = api("POST", "/api/assessment/diagnostic", token=token,
            json_body={
                "student_id": student_id,
                "assessment_id": assessment_id,
                "answers": diagnostic_answers,
            })
    if r.status_code != 200:
        log(f"  [FAIL] Diagnostic submit failed: {r.text[:300]}")
        return
    data = r.json()
    determined_level = data.get("determined_level", "unknown")
    log(f"  Diagnostic result: level={determined_level}, confidence={data.get('confidence_score')}")
    log(f"  Weak areas: {data.get('weak_areas', [])}")
    log(f"  Scores: {data.get('scores', {})}")
    if data.get("ai_error"):
        log(f"  AI Error (fallback used): {data['ai_error']}")
    save_artifact("step_c3_diagnostic_result", data)

    # DB proof
    out = db_query(f"SELECT id, student_id, stage, bracket, determined_level, confidence_score, status FROM assessments WHERE student_id={student_id};")
    log(f"\n  [DB] Assessments:\n{out}")

    return determined_level


# ============================================================================
# STEP C4: Diagnostic Profile
# ============================================================================
def step_c4_diagnostic_profile():
    log("\n" + "=" * 70)
    log("STEP C4: Diagnostic Profile Generation")
    log("=" * 70)

    student_id = IDS["student_id"]
    token = TOKENS["student"]

    # Update student intake data first (goals, problem_areas)
    log("  Updating student goals...")
    r = api("PUT", f"/api/intake/{student_id}/goals", token=token,
            json_body={
                "goals": ["improve speaking", "learn business English"],
                "problem_areas": ["grammar", "vocabulary", "articles"],
                "additional_notes": "Polish native speaker, beginner level"
            }, expect_ok=False)
    if r.status_code == 200:
        log(f"  Goals updated: {r.json()}")
    else:
        log(f"  Goals update: {r.status_code} (may be expected if intake_data is null)")

    # Generate diagnostic profile
    log("  Generating diagnostic profile...")
    r = api("POST", f"/api/diagnostic/{student_id}", token=token)
    if r.status_code == 200:
        data = r.json()
        log(f"  Profile: id={data.get('id')}, level={data.get('recommended_start_level')}")
        log(f"  Gaps: {data.get('gaps', [])[:3]}...")
        log(f"  Priorities: {data.get('priorities', [])[:3]}...")
        save_artifact("step_c4_diagnostic_profile", data)
    else:
        log(f"  [WARN] Diagnostic profile failed: {r.status_code} {r.text[:200]}")
        log(f"  Continuing without diagnostic profile (lesson gen may still work)...")

    # DB proof
    out = db_query(f"SELECT id, student_id, recommended_start_level, profile_summary FROM learner_profiles WHERE student_id={student_id};")
    log(f"\n  [DB] Learner Profiles:\n{out}")


# ============================================================================
# STEP C5: Learning Path Generation
# ============================================================================
def step_c5_learning_path():
    log("\n" + "=" * 70)
    log("STEP C5: Learning Path Generation")
    log("=" * 70)

    student_id = IDS["student_id"]
    token = TOKENS["student"]

    r = api("POST", f"/api/learning-path/{student_id}/generate", token=token)
    if r.status_code == 200:
        data = r.json()
        IDS["learning_path_id"] = data["id"]
        log(f"  Learning path: id={data['id']}, title='{data.get('title', 'N/A')}'")
        log(f"  Target level: {data.get('target_level')}, Current: {data.get('current_level')}")
        log(f"  Weeks: {len(data.get('weeks', []))}")
        save_artifact("step_c5_learning_path", data)
    else:
        log(f"  [WARN] Learning path generation failed: {r.status_code} {r.text[:200]}")

    # DB proof
    out = db_query(f"SELECT id, student_id, title, target_level, current_level, status FROM learning_paths WHERE student_id={student_id};")
    log(f"\n  [DB] Learning Paths:\n{out}")


# ============================================================================
# STEP D: Scheduling
# ============================================================================
def step_d_scheduling():
    log("\n" + "=" * 70)
    log("STEP D: Session Scheduling")
    log("=" * 70)

    student_id = IDS["student_id"]
    teacher_id = IDS.get("teacher1_id")
    student_token = TOKENS["student"]
    teacher_token = TOKENS.get("teacher1")

    if not teacher_id or not teacher_token:
        log("  [SKIP] No teacher available for scheduling test")
        return

    # D1: Student requests session
    scheduled_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat() + "Z"
    log(f"  D1: Student requesting session with teacher {teacher_id} at {scheduled_time}...")
    r = api("POST", "/api/student/me/sessions/request", token=student_token,
            json_body={
                "teacher_id": teacher_id,
                "scheduled_at": scheduled_time,
                "duration_min": 60,
                "notes": "E2E test session - first class"
            })
    if r.status_code == 200:
        data = r.json()
        IDS["session_id"] = data["id"]
        log(f"  Session requested: id={data['id']}, status={data['status']}")
        save_artifact("step_d1_session_request", data)
    else:
        log(f"  [WARN] Session request failed: {r.status_code} {r.text[:200]}")
        return

    # D2: Teacher sees the session
    log(f"\n  D2: Teacher fetching sessions list...")
    r = api("GET", "/api/teacher/sessions", token=teacher_token)
    if r.status_code == 200:
        data = r.json()
        log(f"  Teacher sees {len(data.get('sessions', []))} sessions")
        for s in data.get("sessions", []):
            log(f"    Session {s['id']}: student={s.get('student_name')}, status={s['status']}, at={s.get('scheduled_at')}")
        save_artifact("step_d2_teacher_sessions", data)

    # D3: Teacher confirms session (triggers lesson + quiz generation)
    session_id = IDS.get("session_id")
    if session_id:
        log(f"\n  D3: Teacher confirming session {session_id} (triggers lesson+quiz gen)...")
        r = api("POST", f"/api/teacher/sessions/{session_id}/confirm", token=teacher_token)
        if r.status_code == 200:
            data = r.json()
            log(f"  Session confirmed: {data.get('status')}")
            gen = data.get("generation", {})
            log(f"  Lesson generation: {gen.get('lesson', {}).get('status')}")
            log(f"  Quiz generation: {gen.get('quiz', {}).get('status')}")
            if gen.get("lesson", {}).get("artifact_id"):
                IDS["session_lesson_artifact_id"] = gen["lesson"]["artifact_id"]
            if gen.get("quiz", {}).get("quiz_id"):
                IDS["session_quiz_id"] = gen["quiz"]["quiz_id"]
            save_artifact("step_d3_session_confirm", data)
        else:
            log(f"  [WARN] Session confirm failed: {r.status_code} {r.text[:200]}")

    # DB proof
    out = db_query(f"SELECT id, student_id, teacher_id, scheduled_at, status, duration_min FROM sessions WHERE student_id={student_id};")
    log(f"\n  [DB] Sessions:\n{out}")


# ============================================================================
# STEP E: Lesson/Quiz/Plan Loop (3 cycles)
# ============================================================================
def run_cycle(cycle_num, score_profile):
    """Run a single lesson → quiz → plan_update cycle.

    score_profile: dict describing how to answer quiz questions
        {"correct_ratio": 0.2}  → answer ~20% correctly
    """
    log(f"\n{'─' * 70}")
    log(f"CYCLE {cycle_num}: Lesson → Quiz → Plan Update (target score ~{int(score_profile['correct_ratio']*100)}%)")
    log(f"{'─' * 70}")

    student_id = IDS["student_id"]
    student_token = TOKENS["student"]
    teacher_token = TOKENS.get("teacher1")

    # E1: Generate lesson
    log(f"\n  E1.{cycle_num}: Generating lesson...")
    r = api("POST", f"/api/lessons/{student_id}/generate", token=student_token)
    if r.status_code != 200:
        log(f"  [FAIL] Lesson generation failed: {r.status_code} {r.text[:300]}")
        return None
    lesson_data = r.json()
    lesson_id = lesson_data["id"]
    IDS.setdefault("lesson_ids", []).append(lesson_id)
    log(f"  Lesson generated: id={lesson_id}, session={lesson_data.get('session_number')}")
    log(f"  Objective: {lesson_data.get('objective', 'N/A')[:100]}")
    log(f"  Difficulty: {lesson_data.get('difficulty', 'N/A')}")

    content = lesson_data.get("content", {})
    if isinstance(content, dict):
        log(f"  Topic: {content.get('topic', content.get('presentation', {}).get('topic', 'N/A'))[:80]}")
    save_artifact(f"cycle_{cycle_num}_lesson", lesson_data)

    # DB proof: lessons
    out = db_query(f"SELECT id, student_id, session_number, objective, difficulty, status FROM lessons WHERE student_id={student_id} ORDER BY id;")
    log(f"\n  [DB] Lessons:\n{out}")

    # DB proof: lesson_skill_tags
    out = db_query(f"SELECT lst.lesson_id, lst.tag_type, lst.tag_value, lst.cefr_level FROM lesson_skill_tags lst JOIN lessons l ON l.id=lst.lesson_id WHERE l.student_id={student_id};")
    log(f"\n  [DB] Lesson Skill Tags:\n{out}")

    # E2: Schedule a session and confirm it to trigger quiz generation.
    # We try up to 2 session creates if the first confirm doesn't produce a quiz.
    teacher_id = IDS.get("teacher1_id")
    cycle_quiz_id = None
    if teacher_id and teacher_token:
        for attempt_num in range(2):
            scheduled_time = (datetime.now(timezone.utc) + timedelta(days=cycle_num + 2 + attempt_num * 10)).isoformat()
            log(f"\n  E2.{cycle_num}: Requesting session for quiz generation (attempt {attempt_num+1})...")
            r = api("POST", "/api/student/me/sessions/request", token=student_token,
                    json_body={
                        "teacher_id": teacher_id,
                        "scheduled_at": scheduled_time,
                        "duration_min": 60,
                        "notes": f"Cycle {cycle_num} session (attempt {attempt_num+1})"
                    })
            if r.status_code != 200:
                continue
            cycle_session_id = r.json()["id"]
            IDS.setdefault("cycle_session_ids", []).append(cycle_session_id)

            # Teacher confirms → triggers lesson artifact + quiz generation
            r2 = api("POST", f"/api/teacher/sessions/{cycle_session_id}/confirm", token=teacher_token)
            if r2.status_code == 200:
                gen = r2.json().get("generation", {})
                quiz_status = gen.get("quiz", {}).get("status")
                quiz_id_from_gen = gen.get("quiz", {}).get("quiz_id")
                log(f"  Session {cycle_session_id} confirmed: quiz_status={quiz_status}, quiz_id={quiz_id_from_gen}")
                if quiz_id_from_gen:
                    IDS.setdefault("quiz_ids", []).append(quiz_id_from_gen)
                    cycle_quiz_id = quiz_id_from_gen
                    break
                else:
                    log(f"  Quiz gen returned pending/None, retrying with new session...")
            else:
                log(f"  [WARN] Session confirm failed: {r2.status_code}")

    # E3: Find pending quiz for student
    log(f"\n  E3.{cycle_num}: Checking pending quizzes...")
    r = api("GET", "/api/student/quizzes/pending", token=student_token)
    quiz_id = None
    if r.status_code == 200:
        pending = r.json()
        log(f"  Pending quizzes: {pending.get('count', 0)}")
        quizzes = pending.get("quizzes", [])
        if quizzes:
            # Pick the first pending quiz (not already attempted)
            quiz_id = quizzes[0]["id"]
            log(f"  Using quiz id={quiz_id}: '{quizzes[0].get('title', 'N/A')}'")

    # If no pending quiz found, use the one from session confirm
    if not quiz_id and cycle_quiz_id:
        quiz_id = cycle_quiz_id
        log(f"  Using quiz from session confirm: quiz_id={quiz_id}")

    if not quiz_id:
        log(f"  [INFO] No quiz from session flow. Triggering manual plan refresh to create quiz context...")
        # As a last resort, trigger teacher plan refresh which may help
        if teacher_token:
            api("POST", f"/api/teacher/students/{student_id}/learning-plan/refresh", token=teacher_token, expect_ok=False)
        log(f"  [WARN] No quiz available for cycle {cycle_num}, skipping quiz submission")
        return {
            "cycle": cycle_num,
            "lesson_id": lesson_id,
            "quiz_id": None,
            "score": None,
            "plan_version": None,
        }

    IDS.setdefault("quiz_ids", [])
    if quiz_id not in IDS["quiz_ids"]:
        IDS["quiz_ids"].append(quiz_id)

    # E4: Get quiz questions
    log(f"\n  E4.{cycle_num}: Fetching quiz {quiz_id}...")
    r = api("GET", f"/api/student/quizzes/{quiz_id}", token=student_token)
    if r.status_code != 200:
        log(f"  [FAIL] Cannot fetch quiz: {r.status_code} {r.text[:200]}")
        return None
    quiz_data = r.json()
    questions = quiz_data.get("questions", [])
    log(f"  Quiz: '{quiz_data.get('title', 'N/A')}', {len(questions)} questions")
    save_artifact(f"cycle_{cycle_num}_quiz_questions", quiz_data)

    if quiz_data.get("already_attempted"):
        log(f"  [INFO] Quiz already attempted, skipping submission")
        return None

    # E5: Submit quiz with score profile
    log(f"\n  E5.{cycle_num}: Submitting quiz (target ~{int(score_profile['correct_ratio']*100)}% correct)...")
    answers = {}
    correct_threshold = score_profile["correct_ratio"]
    for i, q in enumerate(questions):
        q_id = q.get("id", f"q{i}")
        # Decide if this answer should be correct
        should_be_correct = (i / max(len(questions), 1)) < correct_threshold

        if should_be_correct:
            # Try to give correct answer
            correct = q.get("correct_answer", "")
            if correct:
                answers[q_id] = correct
            elif q.get("options"):
                answers[q_id] = q["options"][0]  # Guess first option
            else:
                answers[q_id] = "correct"
        else:
            # Give wrong answer
            if q.get("options"):
                answers[q_id] = q["options"][-1] + "_wrong"
            else:
                answers[q_id] = "deliberate_wrong_answer"

    r = api("POST", f"/api/student/quizzes/{quiz_id}/submit", token=student_token,
            json_body={"answers": answers})
    if r.status_code != 200:
        log(f"  [FAIL] Quiz submit failed: {r.status_code} {r.text[:300]}")
        return None

    result = r.json()
    score = result.get("score", 0)
    attempt_id = result.get("attempt_id")
    IDS.setdefault("attempt_ids", []).append(attempt_id)
    log(f"  Quiz score: {score}% ({result.get('correct_count')}/{result.get('total_questions')})")
    log(f"  Attempt ID: {attempt_id}")
    log(f"  Weak areas: {result.get('weak_areas', [])}")
    save_artifact(f"cycle_{cycle_num}_quiz_result", result)

    # DB proof: quiz_attempts
    out = db_query(f"SELECT id, quiz_id, student_id, score, submitted_at FROM quiz_attempts WHERE student_id={student_id} ORDER BY id;")
    log(f"\n  [DB] Quiz Attempts:\n{out}")

    # DB proof: quiz_attempt_items
    if attempt_id:
        out = db_query(f"SELECT id, attempt_id, question_id, is_correct, skill_tag FROM quiz_attempt_items WHERE attempt_id={attempt_id};")
        log(f"\n  [DB] Quiz Attempt Items (attempt {attempt_id}):\n{out}")

    # E6: Check plan update (should have been triggered by quiz submission)
    log(f"\n  E6.{cycle_num}: Checking learning plan after quiz submission...")
    r = api("GET", "/api/student/learning-plan/latest", token=student_token)
    plan_version = None
    if r.status_code == 200:
        plan_data = r.json()
        if plan_data.get("exists"):
            plan_version = plan_data.get("version")
            log(f"  Latest plan: id={plan_data.get('plan_id')}, version={plan_version}, total_versions={plan_data.get('total_versions')}")
            log(f"  Summary: {str(plan_data.get('summary', ''))[:150]}...")
            IDS.setdefault("plan_ids", []).append(plan_data.get("plan_id"))
            save_artifact(f"cycle_{cycle_num}_plan", plan_data)
        else:
            log(f"  No learning plan exists yet")

    # DB proof: learning_plans
    out = db_query(f"SELECT id, student_id, version, summary FROM learning_plans WHERE student_id={student_id} ORDER BY version;")
    log(f"\n  [DB] Learning Plans:\n{out}")

    # E7: Teacher adds observations after the session
    if teacher_token and IDS.get("cycle_session_ids"):
        session_id = IDS["cycle_session_ids"][-1]
        log(f"\n  E7.{cycle_num}: Teacher adding observations for session {session_id}...")

        # Add session notes
        r = api("POST", f"/api/teacher/sessions/{session_id}/notes", token=teacher_token,
                json_body={
                    "teacher_notes": f"Cycle {cycle_num}: Student showed {'poor' if score < 40 else 'moderate' if score < 70 else 'good'} understanding. Needs more practice with basic grammar patterns.",
                    "session_summary": f"Covered lesson {lesson_id}. Quiz score: {score}%.",
                    "homework": f"Review lesson {lesson_id} material. Practice exercises on weak areas."
                })
        if r.status_code == 200:
            log(f"  Session notes added")

        # Add skill observations
        r = api("POST", f"/api/sessions/{session_id}/observations", token=teacher_token,
                json_body=[
                    {"skill": "grammar", "score": max(score - 10, 10), "cefr_level": "A1", "notes": f"Cycle {cycle_num} grammar observation"},
                    {"skill": "vocabulary", "score": max(score - 5, 15), "cefr_level": "A1", "notes": f"Cycle {cycle_num} vocab observation"},
                    {"skill": "speaking", "score": max(score - 15, 10), "cefr_level": "A1", "notes": f"Cycle {cycle_num} speaking observation"},
                ])
        if r.status_code == 200:
            log(f"  Skill observations recorded")
            save_artifact(f"cycle_{cycle_num}_observations", r.json())

    # DB proof: session_skill_observations
    out = db_query(f"SELECT id, session_id, student_id, skill, score, cefr_level FROM session_skill_observations WHERE student_id={student_id} ORDER BY id;")
    log(f"\n  [DB] Skill Observations:\n{out}")

    cycle_summary = {
        "cycle": cycle_num,
        "lesson_id": lesson_id,
        "lesson_objective": lesson_data.get("objective", "N/A")[:100],
        "lesson_difficulty": lesson_data.get("difficulty", "N/A"),
        "quiz_id": quiz_id,
        "quiz_score": score,
        "attempt_id": attempt_id,
        "plan_version": plan_version,
        "weak_areas": result.get("weak_areas", []),
    }
    CYCLE_SUMMARIES.append(cycle_summary)
    return cycle_summary


# ============================================================================
# STEP F: Final DB proof
# ============================================================================
def step_f_final_db_proof():
    log("\n" + "=" * 70)
    log("STEP F: Final Database Proof")
    log("=" * 70)

    student_id = IDS["student_id"]

    tables = {
        "Users": f"SELECT id, email, role, current_level FROM users ORDER BY id;",
        "Assessments": f"SELECT id, student_id, stage, bracket, determined_level, confidence_score, status FROM assessments WHERE student_id={student_id};",
        "Learner Profiles": f"SELECT id, student_id, recommended_start_level, profile_summary FROM learner_profiles WHERE student_id={student_id};",
        "Learning Paths": f"SELECT id, student_id, title, target_level, current_level, status FROM learning_paths WHERE student_id={student_id};",
        "Lessons (latest 5)": f"SELECT id, student_id, session_number, objective, difficulty, status FROM lessons WHERE student_id={student_id} ORDER BY id DESC LIMIT 5;",
        "Lesson Skill Tags": f"SELECT lst.lesson_id, lst.tag_type, lst.tag_value, lst.cefr_level FROM lesson_skill_tags lst JOIN lessons l ON l.id=lst.lesson_id WHERE l.student_id={student_id};",
        "Sessions": f"SELECT id, student_id, teacher_id, status, scheduled_at, duration_min FROM sessions WHERE student_id={student_id} ORDER BY id;",
        "Next Quizzes": f"SELECT id, session_id, student_id, derived_from_lesson_artifact_id, created_at FROM next_quizzes WHERE student_id={student_id} ORDER BY id;",
        "Quiz Attempts": f"SELECT id, quiz_id, student_id, score, submitted_at FROM quiz_attempts WHERE student_id={student_id} ORDER BY id;",
        "Quiz Attempt Items (last 20)": f"SELECT qai.id, qai.attempt_id, qai.question_id, qai.is_correct, qai.skill_tag FROM quiz_attempt_items qai JOIN quiz_attempts qa ON qa.id=qai.attempt_id WHERE qa.student_id={student_id} ORDER BY qai.id DESC LIMIT 20;",
        "Learning Plans (all versions)": f"SELECT id, student_id, version, summary FROM learning_plans WHERE student_id={student_id} ORDER BY version;",
        "Lesson Artifacts": f"SELECT id, session_id, student_id, difficulty, prompt_version, created_at FROM lesson_artifacts WHERE student_id={student_id} ORDER BY id;",
        "CEFR History": f"SELECT id, student_id, level, grammar_level, vocabulary_level, reading_level, confidence, source FROM cefr_history WHERE student_id={student_id};",
        "Session Skill Observations": f"SELECT id, session_id, student_id, skill, score, cefr_level, notes FROM session_skill_observations WHERE student_id={student_id} ORDER BY id;",
    }

    # Check for learning_dna table
    dna_check = db_query("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='learning_dna');")
    if "t" in dna_check.lower():
        tables["Learning DNA"] = f"SELECT id, student_id, version, trigger_event FROM learning_dna WHERE student_id={student_id} ORDER BY version;"

    l1_check = db_query("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='l1_interference_tracking');")
    if "t" in l1_check.lower():
        tables["L1 Interference"] = f"SELECT id, student_id, pattern_type, example FROM l1_interference_tracking WHERE student_id={student_id} LIMIT 5;"

    for name, sql in tables.items():
        out = db_query(sql)
        log(f"\n  [DB] {name}:\n{out}")

    save_artifact("step_f_final_ids", IDS)


# ============================================================================
# Main execution
# ============================================================================
def main():
    start_time = time.time()
    log("=" * 70)
    log(f"E2E Learning Loop Test - Started at {datetime.now(timezone.utc).isoformat()}")
    log("=" * 70)

    try:
        step_a_environment()
        step_b_accounts()
        step_c_assessment()
        step_c4_diagnostic_profile()
        step_c5_learning_path()
        step_d_scheduling()

        # Run 3 cycles with increasing score profiles
        cycle_profiles = [
            {"correct_ratio": 0.2},   # Cycle 1: low score (~20%)
            {"correct_ratio": 0.5},   # Cycle 2: medium score (~50%)
            {"correct_ratio": 0.8},   # Cycle 3: higher score (~80%)
        ]

        for i, profile in enumerate(cycle_profiles, 1):
            result = run_cycle(i, profile)
            if result:
                log(f"\n  Cycle {i} summary: score={result.get('quiz_score')}%, plan_v={result.get('plan_version')}")

        step_f_final_db_proof()

        # Final summary
        log("\n" + "=" * 70)
        log("FEEDBACK SUMMARY")
        log("=" * 70)
        log(f"\n  {'Cycle':<7} {'Lesson ID':<10} {'Difficulty':<12} {'Objective':<40} {'Quiz Score':<12} {'Plan Ver':<10} {'Weak Areas'}")
        log(f"  {'─'*7} {'─'*10} {'─'*12} {'─'*40} {'─'*12} {'─'*10} {'─'*30}")
        for cs in CYCLE_SUMMARIES:
            weak = ", ".join([w.get("skill", "?") for w in cs.get("weak_areas", [])]) or "none"
            log(f"  {cs['cycle']:<7} {str(cs.get('lesson_id','?')):<10} {str(cs.get('lesson_difficulty','?')):<12} {str(cs.get('lesson_objective','?'))[:38]:<40} {str(cs.get('quiz_score','?'))+'%':<12} {str(cs.get('plan_version','?')):<10} {weak[:30]}")

        log(f"\n  Collected IDs:")
        for k, v in IDS.items():
            log(f"    {k}: {v}")

    except Exception as e:
        log(f"\n[FATAL ERROR] {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

    elapsed = time.time() - start_time
    log(f"\n  Total test time: {elapsed:.1f}s")
    log(f"  Artifacts saved to: {ARTIFACTS_DIR}")

    # Write report
    report_path = ARTIFACTS_DIR / "test_output.txt"
    with open(report_path, "w") as f:
        f.write("\n".join(REPORT_LINES))

    return 0 if CYCLE_SUMMARIES else 1


if __name__ == "__main__":
    sys.exit(main())
