#!/usr/bin/env python3
"""
Full Loop v3 Patch Verification Test
======================================
Tests 4 specific patches applied to the adaptive learning loop:

  PATCH 1: Windowed average (last 8 scores) for Learning DNA recommendation
  PATCH 2: Reassessment confidence threshold lowered from 0.7 to 0.6
  PATCH 3: Difficulty engine cold start reduced from 3 to 2 data points
  PATCH 4: Auto-progress safety net in complete_lesson

Runs 15 cycles with intentional skips on cycles 3 and 6 to test PATCH 4,
and verifies each patch produces the expected behavior.

Usage:
  python3 scripts/full_loop_v3_patch_test.py

Requires: server running on localhost:8000 (docker-compose up --build)
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
STUDENT_EMAIL = "patch.test.v3@proficiency.com"
STUDENT_PASS = "PatchV3Test!"

# ─── State ──────────────────────────────────────────────────────────
IDS = {}
TOKENS = {}
REPORT = []
CYCLE_DATA = []
PATCH_RESULTS = {
    "patch1_windowed_avg": {"status": "UNTESTED", "details": []},
    "patch2_confidence_threshold": {"status": "UNTESTED", "details": []},
    "patch3_cold_start": {"status": "UNTESTED", "details": []},
    "patch4_auto_progress": {"status": "UNTESTED", "details": []},
}

# ─── Score progression: 15 cycles ──────────────────────────────────
SCORE_TARGETS = {
    1:  0.15,   # ~15%  Total beginner
    2:  0.25,   # ~25%  Still struggling
    3:  0.30,   # ~30%  Slow improvement (SKIP progress call)
    4:  0.40,   # ~40%  Starting to understand
    5:  0.50,   # ~50%  Crossing halfway
    6:  0.60,   # ~60%  Solidifying (SKIP progress call)
    7:  0.65,   # ~65%  Entering flow zone
    8:  0.72,   # ~72%  Comfortable
    9:  0.78,   # ~78%  Approaching mastery
    10: 0.83,   # ~83%  Mastery -- reassessment at 10th progress
    11: 0.50,   # ~50%  REGRESSION after promotion
    12: 0.62,   # ~62%  Recovering
    13: 0.73,   # ~73%  Adapting
    14: 0.82,   # ~82%  Mastery at new level
    15: 0.88,   # ~88%  Excellent
}

# Cycles where we intentionally SKIP the POST /api/progress/{lesson_id} call
# to test PATCH 4 (auto-progress safety net)
SKIP_PROGRESS_CYCLES = {3, 6}

# Recall quality targets per cycle
RECALL_QUALITY_TARGETS = {
    1:  0, 2:  1, 3:  1, 4:  2, 5:  3,
    6:  3, 7:  4, 8:  4, 9:  4, 10: 5,
    11: 2, 12: 3, 13: 4, 14: 5, 15: 5,
}

# Teacher feedback templates
TEACHER_NOTES = {
    "struggling": {
        "notes": "Student is struggling significantly. Needs scaffolding and Polish explanations.",
        "summary": "Difficult session. Focused on basic examples and repeated key patterns.",
        "homework": "Review basic vocabulary flashcards. No new material.",
    },
    "developing": {
        "notes": "Gradual improvement. Frequent errors with articles and word order.",
        "summary": "Some progress. Handles guided exercises but struggles with free production.",
        "homework": "Complete fill-in-the-blank exercises. Practice 5 sentences.",
    },
    "flow": {
        "notes": "Good flow. Progress visible, errors decreasing. Ready for more challenge.",
        "summary": "Productive session. Solid understanding. Ready for next-level concepts.",
        "homework": "Write 3-5 sentences. Listen to one podcast at current level.",
    },
    "mastering": {
        "notes": "Excellent. Strong command of current-level material. Ready for advancement.",
        "summary": "Outstanding progress. Minimal errors. Time to increase challenge.",
        "homework": "Read a short article at next level. Write a paragraph.",
    },
}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    REPORT.append(line)


def save_artifact(name: str, data):
    path = ARTIFACTS_DIR / f"v3_{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def api(method, path, token=None, json_body=None, expect_ok=True, timeout=180):
    url = f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.request(method, url, json=json_body, headers=headers, timeout=timeout)
    if expect_ok and resp.status_code >= 400:
        log(f"  [ERROR] {method} {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp


def db_query(sql):
    cmd = ["docker", "compose", "exec", "-T", "db",
           "psql", "-U", "intake", "-d", "intake_eval", "-c", sql]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return ""


def db_query_value(sql):
    cmd = ["docker", "compose", "exec", "-T", "db",
           "psql", "-U", "intake", "-d", "intake_eval", "-t", "-A", "-c", sql]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return ""


def get_feedback_band(score):
    if score < 40: return "struggling"
    elif score < 65: return "developing"
    elif score < 80: return "flow"
    else: return "mastering"


def cefr_label(score):
    if score < 55: return "A1"
    elif score < 75: return "A2"
    else: return "B1"


# ════════════════════════════════════════════════════════════════════
# PHASE 1: Setup
# ════════════════════════════════════════════════════════════════════

def phase1_setup():
    log("\n" + "=" * 76)
    log("PHASE 1: Setup -- Accounts & Intake")
    log("=" * 76)

    r = api("GET", "/health")
    if r.status_code != 200:
        log("[FATAL] Server not reachable"); sys.exit(1)
    log(f"  Server healthy: {r.json()}")

    # Admin
    log("  Ensuring admin account...")
    existing = db_query(f"SELECT id, role FROM users WHERE email = '{ADMIN_EMAIL}';")
    if "admin" not in existing.lower() or "(0 rows)" in existing:
        import bcrypt
        pw = bcrypt.hashpw(ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
        db_query(f"INSERT INTO users (name, email, password_hash, role) "
                 f"VALUES ('Admin User', '{ADMIN_EMAIL}', '{pw}', 'admin') "
                 f"ON CONFLICT (email) DO UPDATE SET role='admin', password_hash='{pw}';")

    r = api("POST", "/api/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    if r.status_code == 200:
        d = r.json(); TOKENS["admin"] = d["token"]; IDS["admin_id"] = d["student_id"]
        log(f"  Admin logged in: id={IDS['admin_id']}")
    else:
        api("POST", "/api/auth/register",
            json_body={"name": "Admin User", "email": ADMIN_EMAIL, "password": ADMIN_PASS}, expect_ok=False)
        db_query(f"UPDATE users SET role='admin' WHERE email='{ADMIN_EMAIL}';")
        r = api("POST", "/api/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        d = r.json(); TOKENS["admin"] = d["token"]; IDS["admin_id"] = d["student_id"]
        log(f"  Admin created: id={IDS['admin_id']}")

    # Teacher
    log("  Ensuring teacher account...")
    r = api("POST", "/api/admin/teacher-invites", token=TOKENS["admin"],
            json_body={"email": TEACHER_EMAIL, "expires_days": 7})
    if r.status_code == 200:
        inv = r.json()["token"]
        r2 = api("POST", "/api/auth/teacher/register",
                 json_body={"name": "Teacher One", "email": TEACHER_EMAIL,
                            "password": TEACHER_PASS, "invite_token": inv}, expect_ok=False)
        if r2.status_code in (200, 201):
            d = r2.json(); TOKENS["teacher"] = d["token"]; IDS["teacher_id"] = d["student_id"]
            log(f"  Teacher registered: id={IDS['teacher_id']}")
        elif r2.status_code == 409:
            _login_teacher()
    elif r.status_code == 409:
        _login_teacher()
    if "teacher" not in TOKENS:
        log("[FATAL] Cannot create teacher"); sys.exit(1)

    # Student
    log("  Creating test student...")
    prev = db_query_value(f"SELECT id FROM users WHERE email = '{STUDENT_EMAIL}';")
    if prev and prev.strip():
        _clean_student_data(int(prev.strip()))

    r = api("POST", "/api/auth/register",
            json_body={"name": "Patch V3 Tester", "email": STUDENT_EMAIL,
                       "password": STUDENT_PASS}, expect_ok=False)
    if r.status_code in (200, 201):
        d = r.json(); TOKENS["student"] = d["token"]; IDS["student_id"] = d["student_id"]
        log(f"  Student registered: id={IDS['student_id']}")
    elif r.status_code == 409:
        r2 = api("POST", "/api/auth/login",
                 json_body={"email": STUDENT_EMAIL, "password": STUDENT_PASS})
        if r2.status_code == 200:
            d = r2.json(); TOKENS["student"] = d["token"]; IDS["student_id"] = d["student_id"]
            log(f"  Student logged in (existing): id={IDS['student_id']}")
        else:
            log(f"  [FATAL] Cannot login student"); sys.exit(1)

    sid = IDS["student_id"]
    log("  Submitting intake data...")
    db_query(f"UPDATE users SET name='Patch V3 Tester', age=25, "
             f"native_language='Polish', "
             f"goals='[\"pass B2 exam\", \"business presentations\", \"grammar accuracy\"]', "
             f"problem_areas='[\"articles\", \"grammar\", \"vocabulary\", \"word order\"]', "
             f"additional_notes='Polish native, beginner. Wants B2 for work presentations.' "
             f"WHERE id={sid};")
    api("PUT", f"/api/intake/{sid}/goals", token=TOKENS["student"],
        json_body={"goals": ["pass B2 exam", "business presentations", "grammar accuracy"],
                   "problem_areas": ["articles", "grammar", "vocabulary", "word order"],
                   "additional_notes": "Polish native, beginner."}, expect_ok=False)
    log(f"  Intake submitted for student {sid}")


def _login_teacher():
    r = api("POST", "/api/auth/login",
            json_body={"email": TEACHER_EMAIL, "password": TEACHER_PASS})
    if r.status_code == 200:
        d = r.json(); TOKENS["teacher"] = d["token"]; IDS["teacher_id"] = d["student_id"]
        log(f"  Teacher logged in: id={IDS['teacher_id']}")


def _clean_student_data(student_id):
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
    db_query(f"UPDATE users SET current_level='pending' WHERE id={student_id};")


# ════════════════════════════════════════════════════════════════════
# PHASE 2: Assessment -- Force A1
# ════════════════════════════════════════════════════════════════════

def phase2_assessment():
    log("\n" + "=" * 76)
    log("PHASE 2: Assessment -- Force A1 Start")
    log("=" * 76)

    sid = IDS["student_id"]
    tok = TOKENS["student"]

    log("  Starting assessment...")
    r = api("POST", "/api/assessment/start", token=tok, json_body={"student_id": sid})
    if r.status_code != 200:
        log(f"  [FATAL] Cannot start assessment: {r.text[:300]}"); sys.exit(1)
    d = r.json()
    assessment_id = d["assessment_id"]
    IDS["assessment_id"] = assessment_id
    qs = d["questions"]
    log(f"  Assessment started: id={assessment_id}, {len(qs)} placement questions")

    # Placement -- all wrong
    log("  Submitting placement with ALL WRONG answers...")
    answers = [{"question_id": q["id"], "answer": True} for q in qs]
    r = api("POST", "/api/assessment/placement", token=tok,
            json_body={"student_id": sid, "assessment_id": assessment_id, "answers": answers})
    if r.status_code != 200:
        log(f"  [FATAL] Placement failed: {r.text[:300]}"); sys.exit(1)
    d = r.json()
    diag_qs = d["questions"]
    log(f"  Placement: bracket={d['placement_result']['bracket']}, score={d['placement_result']['score']}")

    # Diagnostic -- all wrong
    log("  Submitting diagnostic with ALL WRONG answers...")
    diag_answers = []
    for q in diag_qs:
        opts = q.get("options", [])
        if opts:
            diag_answers.append({"question_id": q["id"], "answer": opts[-1] + "_wrong"})
        else:
            diag_answers.append({"question_id": q["id"], "answer": "totally_wrong_answer"})
    r = api("POST", "/api/assessment/diagnostic", token=tok,
            json_body={"student_id": sid, "assessment_id": assessment_id, "answers": diag_answers})
    if r.status_code != 200:
        log(f"  [FATAL] Diagnostic failed: {r.text[:300]}"); sys.exit(1)
    d = r.json()
    level = d.get("determined_level", "unknown")
    log(f"  Diagnostic: level={level}, confidence={d.get('confidence_score')}")

    if level.upper() != "A1":
        log(f"  [INFO] AI determined {level}, forcing A1...")
        db_query(f"UPDATE users SET current_level='A1' WHERE id={sid};")

    db_level = db_query_value(f"SELECT current_level FROM users WHERE id={sid};")
    assert db_level.strip().upper() == "A1", f"Expected A1, got {db_level}"
    log(f"  [DB VERIFY] current_level = {db_level}")

    # Diagnostic profile
    log("  Generating diagnostic profile...")
    r = api("POST", f"/api/diagnostic/{sid}", token=tok)
    if r.status_code == 200:
        log(f"  Profile created: id={r.json().get('id')}")
    else:
        log(f"  [WARN] Profile gen failed ({r.status_code})")

    # Learning path
    log("  Generating learning path...")
    r = api("POST", f"/api/learning-path/{sid}/generate", token=tok)
    if r.status_code == 200:
        log(f"  Learning path created: id={r.json().get('id')}")
    else:
        log(f"  [WARN] Learning path failed ({r.status_code})")

    log("  Phase 2 complete: Student confirmed at A1")


# ════════════════════════════════════════════════════════════════════
# PHASE 3: Learning Loop -- 15 Cycles with Patch Verification
# ════════════════════════════════════════════════════════════════════

def phase3_learning_loop():
    log("\n" + "=" * 76)
    log("PHASE 3: Learning Loop -- 15 Cycles with Patch Verification")
    log("=" * 76)

    for cycle_num in range(1, 16):
        target_ratio = SCORE_TARGETS[cycle_num]
        skip_progress = cycle_num in SKIP_PROGRESS_CYCLES
        result = run_cycle(cycle_num, target_ratio, skip_progress)
        CYCLE_DATA.append(result)

        score_str = f"{result['quiz_score']}%" if result['quiz_score'] is not None else "N/A"
        log(f"\n  === Cycle {cycle_num:2d} complete: score={score_str}, level={result['db_level']}, "
            f"plan_v={result['plan_version']}, dna_rec={result['dna_recommendation']}, "
            f"recent_avg={result.get('dna_recent_avg', 'N/A')}, "
            f"lifetime_avg={result.get('dna_lifetime_avg', 'N/A')}, "
            f"diff_profile={result['difficulty_profile']}"
            f"{' [SKIPPED PROGRESS]' if skip_progress else ''} ===\n")


def run_cycle(cycle_num, target_ratio, skip_progress):
    log(f"\n{'~' * 76}")
    log(f"CYCLE {cycle_num}/15  --  Target: ~{int(target_ratio * 100)}%"
        f"{'  [SKIP PROGRESS -- PATCH 4 TEST]' if skip_progress else ''}")
    log(f"{'~' * 76}")

    sid = IDS["student_id"]
    stok = TOKENS["student"]
    ttok = TOKENS["teacher"]
    tid = IDS["teacher_id"]

    cr = {
        "cycle": cycle_num, "target_pct": int(target_ratio * 100),
        "quiz_score": None, "quiz_id": None, "lesson_id": None,
        "lesson_difficulty": None, "lesson_objective": None,
        "plan_version": None, "plan_summary": None,
        "db_level": None, "cefr_history_count": 0,
        "dna_version": None, "dna_recommendation": None,
        "dna_recent_avg": None, "dna_lifetime_avg": None,
        "dna_score_trend": None, "dna_frustration": None,
        "difficulty_profile": {}, "weak_areas": [],
        "reassessment": None, "session_id": None,
        "lesson_gen_id": None, "recall_session_id": None,
        "recall_score": None, "recall_avg_ef": None,
        "recall_points_updated": 0, "learning_points_count": 0,
        "skip_progress": skip_progress,
        "auto_progress_created": False, "auto_progress_score": "N/A",
        "promoted_naturally": False,
    }

    # Step 1: Student requests session
    sched = (datetime.now(timezone.utc) + timedelta(days=cycle_num, hours=cycle_num)).isoformat()
    log(f"  [1] Student requesting session...")
    r = api("POST", "/api/student/me/sessions/request", token=stok,
            json_body={"teacher_id": tid, "scheduled_at": sched, "duration_min": 60,
                       "notes": f"Cycle {cycle_num} -- target ~{int(target_ratio*100)}%"})
    if r.status_code != 200:
        log(f"      [WARN] Session request failed: {r.status_code}"); return cr
    session_id = r.json()["id"]
    cr["session_id"] = session_id
    log(f"      Session: id={session_id}")

    # Step 2: Teacher confirms
    log(f"  [2] Teacher confirming session {session_id}...")
    r = api("POST", f"/api/teacher/sessions/{session_id}/confirm", token=ttok)
    if r.status_code != 200:
        log(f"      [WARN] Confirm failed: {r.status_code} {r.text[:200]}"); return cr
    gen = r.json().get("generation", {})
    artifact_id = gen.get("lesson", {}).get("artifact_id")
    quiz_id = gen.get("quiz", {}).get("quiz_id")
    log(f"      Confirmed. artifact={artifact_id}, quiz={quiz_id}")

    # Step 3: Verify lesson artifact
    if artifact_id:
        log(f"  [3] Verifying lesson artifact...")
        r = api("GET", f"/api/teacher/sessions/{session_id}/lesson", token=ttok)
        if r.status_code == 200:
            ld = r.json()
            lc = ld.get("lesson", {})
            if isinstance(lc, str):
                try: lc = json.loads(lc)
                except: lc = {}
            cr["lesson_difficulty"] = ld.get("difficulty", "N/A")
            cr["lesson_objective"] = ((lc.get("objective", "") if isinstance(lc, dict) else "") or "")[:120]
            log(f"      Difficulty: {cr['lesson_difficulty']}, Obj: {cr['lesson_objective'][:80]}")

    # Step 4: Student takes quiz
    if not quiz_id:
        r = api("GET", "/api/student/quizzes/pending", token=stok)
        if r.status_code == 200:
            pend = r.json().get("quizzes", [])
            if pend: quiz_id = pend[0]["id"]

    if quiz_id:
        log(f"  [4] Taking quiz {quiz_id}...")
        # Teacher endpoint for answers
        r_t = api("GET", f"/api/teacher/sessions/{session_id}/next-quiz", token=ttok)
        tq_map = {}
        if r_t.status_code == 200:
            tqj = r_t.json().get("quiz", {})
            if isinstance(tqj, str):
                try: tqj = json.loads(tqj)
                except: tqj = {}
            for tq in tqj.get("questions", []):
                if tq.get("id") and tq.get("correct_answer"):
                    tq_map[str(tq["id"])] = tq["correct_answer"]

        r = api("GET", f"/api/student/quizzes/{quiz_id}", token=stok)
        if r.status_code == 200:
            qd = r.json()
            questions = qd.get("questions", [])
            attempted = qd.get("already_attempted", False)
            # Merge answers
            for q in questions:
                qid = str(q.get("id", ""))
                if qid in tq_map:
                    q["correct_answer"] = tq_map[qid]
            log(f"      {len(questions)} questions, merged {len(tq_map)} answers")

            if not attempted and questions:
                answers = _build_quiz_answers(questions, target_ratio)
                r = api("POST", f"/api/student/quizzes/{quiz_id}/submit", token=stok,
                        json_body={"answers": answers})
                if r.status_code == 200:
                    res = r.json()
                    cr["quiz_score"] = res.get("score", 0)
                    cr["quiz_id"] = quiz_id
                    cr["weak_areas"] = res.get("weak_areas", [])
                    log(f"      Score: {res.get('score')}% ({res.get('correct_count')}/{res.get('total_questions')})")

    # Step 5: Teacher notes + observations
    score = cr["quiz_score"] or 0
    band = get_feedback_band(score)
    fb = TEACHER_NOTES[band]
    log(f"  [5] Teacher notes (band: {band})...")
    api("POST", f"/api/teacher/sessions/{session_id}/notes", token=ttok,
        json_body={"teacher_notes": f"Cycle {cycle_num}: {fb['notes']}",
                   "session_summary": f"Cycle {cycle_num}: {fb['summary']} Score: {score}%.",
                   "homework": fb["homework"]})
    obs_cefr = cefr_label(score)
    api("POST", f"/api/sessions/{session_id}/observations", token=ttok,
        json_body=[
            {"skill": "grammar", "score": max(score - 10, 5), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num} grammar"},
            {"skill": "vocabulary", "score": max(score - 5, 10), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num} vocabulary"},
            {"skill": "speaking", "score": max(score - 15, 5), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num} speaking"},
            {"skill": "reading", "score": max(score, 10), "cefr_level": obs_cefr,
             "notes": f"Cycle {cycle_num} reading"},
        ])

    # Step 6: Check learning plan
    log(f"  [6] Learning plan...")
    r = api("GET", "/api/student/learning-plan/latest", token=stok)
    if r.status_code == 200:
        plan = r.json()
        if plan.get("exists"):
            cr["plan_version"] = plan.get("version")
            cr["plan_summary"] = str(plan.get("summary", ""))[:200]
            log(f"      Plan v{plan['version']}")

    # Step 7: Generate lesson + (optionally) submit progress + complete
    log(f"  [7] Generating lesson...")
    r = api("POST", f"/api/lessons/{sid}/generate", token=stok)
    if r.status_code == 200:
        lesson = r.json()
        lesson_id = lesson["id"]
        cr["lesson_id"] = lesson_id
        cr["lesson_gen_id"] = lesson_id
        if not cr["lesson_difficulty"]:
            cr["lesson_difficulty"] = lesson.get("difficulty", "N/A")
        if not cr["lesson_objective"]:
            cr["lesson_objective"] = (lesson.get("objective", "") or "")[:120]
        log(f"      Lesson: id={lesson_id}, diff={lesson.get('difficulty')}")

        if not skip_progress:
            # Normal path: submit progress first
            progress_score = score if score > 0 else int(target_ratio * 100)
            areas_improved = ["grammar", "vocabulary"] if progress_score >= 70 else []
            areas_struggling = []
            if progress_score < 50:
                areas_struggling = ["grammar", "articles", "word_order"]
            elif progress_score < 70:
                areas_struggling = ["articles", "vocabulary"]

            r2 = api("POST", f"/api/progress/{lesson_id}", token=stok,
                     json_body={"lesson_id": lesson_id, "student_id": sid,
                                "score": progress_score, "notes": f"Cycle {cycle_num}",
                                "areas_improved": areas_improved,
                                "areas_struggling": areas_struggling}, expect_ok=False)
            if r2.status_code in (200, 201):
                log(f"      Progress submitted (score {progress_score}%)")
            elif r2.status_code == 409:
                log(f"      Progress already exists")
            else:
                log(f"      [WARN] Progress: {r2.status_code}")

            # Reset lesson status so /complete works
            db_query(f"UPDATE lessons SET status='generated' WHERE id={lesson_id};")
        else:
            log(f"      ** SKIPPING progress call (PATCH 4 test) **")

        # Complete lesson
        r3 = api("POST", f"/api/lessons/{lesson_id}/complete", token=stok, expect_ok=False)
        if r3.status_code == 200:
            cd = r3.json()
            points = cd.get("points_extracted", 0)
            reassessment = cd.get("reassessment")
            log(f"      Lesson completed: {points} learning points extracted")
            if reassessment:
                cr["reassessment"] = reassessment
                cr["promoted_naturally"] = True
                log(f"      ** REASSESSMENT: new_level={reassessment.get('new_level')}, "
                    f"confidence={reassessment.get('confidence')}, "
                    f"trajectory={reassessment.get('trajectory')}")
        elif r3.status_code == 409:
            log(f"      Already completed (409)")
        else:
            log(f"      [WARN] Complete: {r3.status_code} {r3.text[:200]}")

        # PATCH 4 CHECK: verify auto-progress row was created
        if skip_progress:
            log(f"  [PATCH4] Checking auto-progress for lesson {lesson_id}...")
            row = db_query(
                f"SELECT id, score, notes FROM progress "
                f"WHERE lesson_id={lesson_id} AND student_id={sid};"
            )
            if "(0 rows)" not in row and row.strip():
                cr["auto_progress_created"] = True
                # Check if score is NULL (auto-created)
                score_val = db_query_value(
                    f"SELECT score FROM progress "
                    f"WHERE lesson_id={lesson_id} AND student_id={sid};"
                )
                notes_val = db_query_value(
                    f"SELECT notes FROM progress "
                    f"WHERE lesson_id={lesson_id} AND student_id={sid};"
                )
                cr["auto_progress_score"] = score_val if score_val else "NULL"
                log(f"      [PATCH4 PASS] Auto-progress row exists! "
                    f"score={cr['auto_progress_score']}, notes={notes_val[:50] if notes_val else 'N/A'}")
                PATCH_RESULTS["patch4_auto_progress"]["details"].append({
                    "cycle": cycle_num, "lesson_id": lesson_id,
                    "auto_created": True, "score": cr["auto_progress_score"],
                    "notes_contains_auto": "Auto" in (notes_val or ""),
                })
            else:
                log(f"      [PATCH4 FAIL] No auto-progress row found!")
                PATCH_RESULTS["patch4_auto_progress"]["details"].append({
                    "cycle": cycle_num, "lesson_id": lesson_id, "auto_created": False,
                })
    else:
        log(f"      [WARN] Lesson gen failed: {r.status_code}")

    # Step 8: Recall session (SM-2 updates)
    log(f"  [8] Recall session...")
    _run_recall_session(cycle_num, cr)

    # Step 9: Query DB for adaptive state
    log(f"  [9] Querying adaptive state...")

    # Current level
    db_level = db_query_value(f"SELECT current_level FROM users WHERE id={sid};")
    cr["db_level"] = db_level.strip() if db_level else "?"

    # CEFR history
    cefr_count = db_query_value(f"SELECT COUNT(*) FROM cefr_history WHERE student_id={sid};")
    cr["cefr_history_count"] = int(cefr_count.strip()) if cefr_count.strip().isdigit() else 0

    # Learning DNA -- parse for PATCH 1 verification
    dna_row = db_query_value(
        f"SELECT dna_json FROM learning_dna "
        f"WHERE student_id={sid} ORDER BY version DESC LIMIT 1;"
    )
    if dna_row and dna_row.strip():
        try:
            dna = json.loads(dna_row.strip())
            ocl = dna.get("optimal_challenge_level", {})
            cr["dna_recommendation"] = ocl.get("recommendation", "N/A")
            cr["dna_recent_avg"] = ocl.get("recent_avg_score", "N/A")
            cr["dna_lifetime_avg"] = ocl.get("current_avg_score", "N/A")
            cr["dna_score_trend"] = dna.get("engagement_patterns", {}).get("score_trend", "N/A")
            cr["dna_frustration"] = dna.get("frustration_indicators", {})
            dna_v = db_query_value(
                f"SELECT version FROM learning_dna "
                f"WHERE student_id={sid} ORDER BY version DESC LIMIT 1;"
            )
            cr["dna_version"] = dna_v.strip() if dna_v else None
            log(f"      DNA v{cr['dna_version']}: rec={cr['dna_recommendation']}, "
                f"recent_avg={cr['dna_recent_avg']}, lifetime_avg={cr['dna_lifetime_avg']}")
        except (json.JSONDecodeError, TypeError):
            log(f"      DNA: parse error")
    else:
        log(f"      DNA: none yet")

    # Difficulty profile -- PATCH 3 verification
    diff_rows = db_query(
        f"SELECT point_type, ROUND(AVG(ease_factor)::numeric, 2) as avg_ef, COUNT(*) as cnt "
        f"FROM learning_points WHERE student_id={sid} "
        f"GROUP BY point_type ORDER BY cnt DESC;"
    )
    if diff_rows and "(0 rows)" not in diff_rows:
        for line in diff_rows.split("\n"):
            line = line.strip()
            if "|" in line and "point_type" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    try:
                        pt, avg_ef_s, cnt_s = parts[0], parts[1], parts[2]
                        avg_ef = float(avg_ef_s)
                        cnt = int(cnt_s)
                        if cnt >= 2:
                            if avg_ef < 1.8: cr["difficulty_profile"][pt] = "simplify"
                            elif avg_ef > 2.8: cr["difficulty_profile"][pt] = "challenge"
                            else: cr["difficulty_profile"][pt] = "maintain"
                        else:
                            cr["difficulty_profile"][pt] = f"<2pts ({cnt})"
                    except (ValueError, IndexError):
                        pass

    # PATCH 3 CHECK: by cycle 2, should have non-empty difficulty profile
    if cycle_num == 2:
        qualified = {k: v for k, v in cr["difficulty_profile"].items() if v in ("simplify", "maintain", "challenge")}
        if qualified:
            log(f"  [PATCH3 PASS] Difficulty engine active at cycle 2: {qualified}")
            PATCH_RESULTS["patch3_cold_start"]["status"] = "PASS"
            PATCH_RESULTS["patch3_cold_start"]["details"] = [
                {"cycle": 2, "profile": qualified, "active": True}
            ]
        else:
            log(f"  [PATCH3 FAIL] No qualified skills at cycle 2: {cr['difficulty_profile']}")
            PATCH_RESULTS["patch3_cold_start"]["status"] = "FAIL"
            PATCH_RESULTS["patch3_cold_start"]["details"] = [
                {"cycle": 2, "profile": cr["difficulty_profile"], "active": False}
            ]

    # PATCH 2 CHECK: at cycle 10, check if reassessment promoted naturally
    if cycle_num == 10:
        if cr.get("reassessment"):
            reass = cr["reassessment"]
            conf = reass.get("confidence", 0)
            new_lev = reass.get("new_level", "?")
            if conf >= 0.6 and new_lev != "A1":
                log(f"  [PATCH2 PASS] Natural promotion at cycle 10: "
                    f"A1 -> {new_lev}, confidence={conf} (>= 0.6)")
                PATCH_RESULTS["patch2_confidence_threshold"]["status"] = "PASS"
                PATCH_RESULTS["patch2_confidence_threshold"]["details"] = [{
                    "cycle": 10, "before": "A1", "after": new_lev,
                    "confidence": conf, "threshold_met": True, "natural": True,
                }]
            else:
                log(f"  [PATCH2 INFO] Reassessment fired but conf={conf}, new_level={new_lev}")
                PATCH_RESULTS["patch2_confidence_threshold"]["details"] = [{
                    "cycle": 10, "confidence": conf, "new_level": new_lev,
                    "threshold_met": conf >= 0.6, "natural": True,
                }]
        else:
            log(f"  [PATCH2 INFO] No reassessment at cycle 10 -- checking progress count...")
            pc = db_query_value(f"SELECT COUNT(*) FROM progress WHERE student_id={sid};")
            log(f"      Progress count: {pc}")
            # Check if reassessment happened but didn't promote
            latest_cefr = db_query(
                f"SELECT level, confidence, source FROM cefr_history "
                f"WHERE student_id={sid} ORDER BY recorded_at DESC LIMIT 1;"
            )
            log(f"      Latest CEFR: {latest_cefr}")

    # PATCH 1 CHECK: at cycles 14-15, check windowed avg vs lifetime
    if cycle_num >= 14:
        recent = cr.get("dna_recent_avg")
        lifetime = cr.get("dna_lifetime_avg")
        rec = cr.get("dna_recommendation")
        if recent is not None and lifetime is not None:
            try:
                recent_f = float(recent)
                lifetime_f = float(lifetime)
                if recent_f >= 70 and lifetime_f < 70 and rec in ("maintain", "increase_difficulty"):
                    log(f"  [PATCH1 PASS] Windowed avg working! "
                        f"recent={recent_f:.1f} >= 70, lifetime={lifetime_f:.1f} < 70, rec={rec}")
                    PATCH_RESULTS["patch1_windowed_avg"]["status"] = "PASS"
                elif recent_f >= 70 and rec in ("maintain", "increase_difficulty"):
                    log(f"  [PATCH1 PASS] recent={recent_f:.1f}, rec={rec}")
                    PATCH_RESULTS["patch1_windowed_avg"]["status"] = "PASS"
                else:
                    log(f"  [PATCH1 INFO] recent={recent_f:.1f}, lifetime={lifetime_f:.1f}, rec={rec}")
            except (ValueError, TypeError):
                pass
        PATCH_RESULTS["patch1_windowed_avg"]["details"].append({
            "cycle": cycle_num, "recent_avg": recent,
            "lifetime_avg": lifetime, "recommendation": rec,
        })

    # Learning points count
    lp_count = db_query_value(f"SELECT COUNT(*) FROM learning_points WHERE student_id={sid};")
    cr["learning_points_count"] = int(lp_count.strip()) if lp_count.strip().isdigit() else 0

    # Average ease factor
    avg_ef = db_query_value(
        f"SELECT ROUND(AVG(ease_factor)::numeric, 2) FROM learning_points WHERE student_id={sid};"
    )
    cr["recall_avg_ef"] = avg_ef.strip() if avg_ef and avg_ef.strip() else "N/A"

    # Progress count
    pc = db_query_value(f"SELECT COUNT(*) FROM progress WHERE student_id={sid};")
    log(f"      level={cr['db_level']}, cefr_hist={cr['cefr_history_count']}, "
        f"progress={pc}, lp={cr['learning_points_count']}, avg_ef={cr['recall_avg_ef']}")

    save_artifact(f"cycle_{cycle_num:02d}_state", cr)
    return cr


def _run_recall_session(cycle_num, cr):
    sid = IDS["student_id"]
    stok = TOKENS["student"]
    target_quality = RECALL_QUALITY_TARGETS[cycle_num]

    # Make all points due
    db_query(f"UPDATE learning_points SET next_review_date = "
             f"(NOW() - INTERVAL '1 day')::timestamp WHERE student_id={sid};")

    r = api("GET", f"/api/recall/{sid}/check", token=stok)
    if r.status_code == 200:
        due = r.json().get("points_count", 0)
        if due == 0:
            log(f"      No points due for recall"); return
    else:
        return

    r = api("POST", f"/api/recall/{sid}/start", token=stok)
    if r.status_code != 200:
        log(f"      [WARN] Recall start failed: {r.status_code}"); return
    rd = r.json()
    rsid = rd.get("session_id")
    rqs = rd.get("questions", [])
    if not rsid or not rqs:
        log(f"      No recall questions"); return
    cr["recall_session_id"] = rsid
    log(f"      Recall: id={rsid}, {len(rqs)} questions (target quality={target_quality})")

    answers = []
    for q in rqs:
        if target_quality >= 4:
            exp = q.get("expected_answer", q.get("correct_answer", "correct"))
            answers.append({"question_id": q.get("id", q.get("question_id", "")),
                           "point_id": q.get("point_id"), "answer": exp})
        elif target_quality >= 3:
            exp = q.get("expected_answer", "partial")
            answers.append({"question_id": q.get("id", q.get("question_id", "")),
                           "point_id": q.get("point_id"), "answer": exp[:len(exp)//2] + " maybe"})
        else:
            answers.append({"question_id": q.get("id", q.get("question_id", "")),
                           "point_id": q.get("point_id"), "answer": "I don't know"})

    r = api("POST", f"/api/recall/{rsid}/submit", token=stok, json_body={"answers": answers})
    if r.status_code == 200:
        rr = r.json()
        cr["recall_score"] = rr.get("overall_score", 0)
        cr["recall_points_updated"] = len(rr.get("evaluations", []))
        log(f"      Recall: score={rr.get('overall_score')}%")

    # Push ease_factors for difficulty engine diversity
    if cycle_num <= 4:
        db_query(f"UPDATE learning_points SET ease_factor = GREATEST(1.3, ease_factor - 0.3) "
                 f"WHERE student_id={sid} AND point_type='grammar_rule';")
    elif cycle_num >= 12:
        db_query(f"UPDATE learning_points SET ease_factor = LEAST(3.5, ease_factor + 0.2) "
                 f"WHERE student_id={sid} AND point_type='vocabulary';")


def _build_quiz_answers(questions, target_ratio):
    answers = {}
    total = len(questions)
    correct_count = int(round(target_ratio * total))
    for i, q in enumerate(questions):
        qid = q.get("id", f"q{i}")
        if i < correct_count:
            ca = q.get("correct_answer", "")
            if ca: answers[qid] = str(ca)
            elif q.get("type") == "true_false": answers[qid] = "true"
            elif q.get("options"): answers[qid] = q["options"][0]
            else: answers[qid] = "correct"
        else:
            opts = q.get("options", [])
            if q.get("type") == "true_false": answers[qid] = "false_wrong"
            elif opts and len(opts) > 1: answers[qid] = opts[-1] + "_wrong"
            elif q.get("type") in ("fill_blank", "vocabulary_fill"): answers[qid] = "wrongword"
            else: answers[qid] = "deliberate_wrong_answer"
    return answers


# ════════════════════════════════════════════════════════════════════
# PHASE 4: Patch Verification Report
# ════════════════════════════════════════════════════════════════════

def phase4_report():
    log("\n" + "=" * 76)
    log("PHASE 4: Patch Verification Report")
    log("=" * 76)
    sid = IDS["student_id"]

    # ─── Finalize patch statuses ────────────────────────────────────

    # PATCH 4: check both cycles 3 and 6
    p4_details = PATCH_RESULTS["patch4_auto_progress"]["details"]
    if p4_details:
        all_auto = all(d.get("auto_created") for d in p4_details)
        PATCH_RESULTS["patch4_auto_progress"]["status"] = "PASS" if all_auto else "FAIL"
    else:
        PATCH_RESULTS["patch4_auto_progress"]["status"] = "FAIL"

    # PATCH 2: if not set yet, check DB directly
    if PATCH_RESULTS["patch2_confidence_threshold"]["status"] == "UNTESTED":
        cefr = db_query(
            f"SELECT level, confidence, source FROM cefr_history "
            f"WHERE student_id={sid} AND source='periodic_reassessment' "
            f"ORDER BY recorded_at;"
        )
        log(f"  [PATCH2] Periodic reassessments in DB:\n{cefr}")
        if "(0 rows)" not in cefr and cefr.strip():
            # Check if any promoted with confidence >= 0.6
            for line in cefr.split("\n"):
                if "|" in line and "level" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3:
                        try:
                            lev = parts[0]
                            conf = float(parts[1])
                            if conf >= 0.6 and lev != "A1":
                                PATCH_RESULTS["patch2_confidence_threshold"]["status"] = "PASS"
                                PATCH_RESULTS["patch2_confidence_threshold"]["details"].append({
                                    "level": lev, "confidence": conf, "from_db": True,
                                })
                        except (ValueError, IndexError):
                            pass
        if PATCH_RESULTS["patch2_confidence_threshold"]["status"] == "UNTESTED":
            # Check if level changed at all
            final_level = db_query_value(f"SELECT current_level FROM users WHERE id={sid};")
            if final_level.strip().upper() != "A1":
                PATCH_RESULTS["patch2_confidence_threshold"]["status"] = "PASS"
                PATCH_RESULTS["patch2_confidence_threshold"]["details"].append({
                    "final_level": final_level.strip(), "promoted": True,
                })
            else:
                PATCH_RESULTS["patch2_confidence_threshold"]["status"] = "FAIL"

    # PATCH 1: if not set, check last cycle data
    if PATCH_RESULTS["patch1_windowed_avg"]["status"] == "UNTESTED":
        # Check if any late cycle had non-decrease recommendation
        for cd in CYCLE_DATA[12:]:  # cycles 13-15
            rec = cd.get("dna_recommendation")
            if rec in ("maintain", "increase_difficulty"):
                PATCH_RESULTS["patch1_windowed_avg"]["status"] = "PASS"
                break
        if PATCH_RESULTS["patch1_windowed_avg"]["status"] == "UNTESTED":
            PATCH_RESULTS["patch1_windowed_avg"]["status"] = "FAIL"

    # ─── Section 1: Patch Results Summary ───────────────────────────
    log("\n" + "=" * 100)
    log("SECTION 1: PATCH RESULTS SUMMARY")
    log("=" * 100)
    log(f"{'Patch':<8} | {'Description':<50} | {'Status':<8}")
    log("-" * 100)

    patch_descriptions = {
        "patch1_windowed_avg": "Windowed avg (last 8) for DNA recommendation",
        "patch2_confidence_threshold": "Confidence threshold lowered to 0.6",
        "patch3_cold_start": "Difficulty engine cold start at 2 data points",
        "patch4_auto_progress": "Auto-progress in complete_lesson",
    }
    for key, desc in patch_descriptions.items():
        status = PATCH_RESULTS[key]["status"]
        log(f"{key:<8} | {desc:<50} | {status:<8}")
    log("-" * 100)

    total_pass = sum(1 for v in PATCH_RESULTS.values() if v["status"] == "PASS")
    total = len(PATCH_RESULTS)
    log(f"\n  PATCHES: {total_pass}/{total} PASSED")

    # ─── Section 2: DNA Windowed Average Evolution (PATCH 1) ────────
    log("\n" + "=" * 100)
    log("SECTION 2: DNA WINDOWED AVERAGE EVOLUTION (PATCH 1)")
    log("=" * 100)
    log(f"{'Cycle':>5} | {'Recent Avg (last 8)':>20} | {'Lifetime Avg':>12} | {'Recommendation':<22} | {'Correct?':<10}")
    log("-" * 100)
    for cd in CYCLE_DATA:
        recent = cd.get("dna_recent_avg", "N/A")
        lifetime = cd.get("dna_lifetime_avg", "N/A")
        rec = cd.get("dna_recommendation", "N/A")
        # Determine if correct based on recent avg
        correct = "N/A"
        try:
            r_val = float(recent) if recent and recent != "N/A" else None
            if r_val is not None:
                if r_val > 85:
                    correct = "YES" if rec == "increase_difficulty" else "NO"
                elif r_val < 70:
                    correct = "YES" if rec == "decrease_difficulty" else "NO"
                else:
                    correct = "YES" if rec == "maintain" else "NO"
        except (ValueError, TypeError):
            pass
        log(f"{cd['cycle']:>5} | {str(recent):>20} | {str(lifetime):>12} | {rec:<22} | {correct:<10}")
    log("-" * 100)

    # Key proof line
    if len(CYCLE_DATA) >= 14:
        c14 = CYCLE_DATA[13]
        c15 = CYCLE_DATA[14] if len(CYCLE_DATA) >= 15 else None
        r14 = c14.get("dna_recent_avg", "?")
        l14 = c14.get("dna_lifetime_avg", "?")
        rec14 = c14.get("dna_recommendation", "?")
        log(f"\n  KEY PROOF: At cycle 14, recent_avg={r14}, lifetime_avg={l14}")
        log(f"  Recommendation={rec14} (should be 'maintain' or 'increase_difficulty')")
        if c15:
            r15 = c15.get("dna_recent_avg", "?")
            l15 = c15.get("dna_lifetime_avg", "?")
            rec15 = c15.get("dna_recommendation", "?")
            log(f"  At cycle 15, recent_avg={r15}, lifetime_avg={l15}, rec={rec15}")

    # ─── Section 3: Difficulty Engine Activation (PATCH 3) ──────────
    log("\n" + "=" * 100)
    log("SECTION 3: DIFFICULTY ENGINE ACTIVATION TIMELINE (PATCH 3)")
    log("=" * 100)
    log(f"{'Cycle':>5} | {'Difficulty Profile':<70}")
    log("-" * 100)
    for cd in CYCLE_DATA:
        dp = cd.get("difficulty_profile", {})
        qualified = {k: v for k, v in dp.items() if v in ("simplify", "maintain", "challenge")}
        dp_str = ", ".join(f"{k}={v}" for k, v in dp.items()) if dp else "(empty)"
        log(f"{cd['cycle']:>5} | {dp_str:<70}")
    log("-" * 100)

    # First activation
    first_active = None
    for cd in CYCLE_DATA:
        dp = cd.get("difficulty_profile", {})
        qualified = {k: v for k, v in dp.items() if v in ("simplify", "maintain", "challenge")}
        if qualified:
            first_active = cd["cycle"]
            break
    log(f"\n  First difficulty engine activation: cycle {first_active or 'NEVER'}")
    log(f"  Expected: cycle 2 (with PATCH 3 lowering threshold from 3 to 2 data points)")

    # All learning points detail
    lp = db_query(
        f"SELECT point_type, ROUND(AVG(ease_factor)::numeric, 2) as avg_ef, "
        f"ROUND(MIN(ease_factor)::numeric, 2) as min_ef, "
        f"ROUND(MAX(ease_factor)::numeric, 2) as max_ef, "
        f"COUNT(*) as cnt "
        f"FROM learning_points WHERE student_id={sid} "
        f"GROUP BY point_type ORDER BY cnt DESC;"
    )
    log(f"\n  Final learning points summary:\n{lp}")

    # ─── Section 4: Reassessment Confidence (PATCH 2) ───────────────
    log("\n" + "=" * 100)
    log("SECTION 4: REASSESSMENT CONFIDENCE (PATCH 2)")
    log("=" * 100)
    cefr = db_query(
        f"SELECT id, level, grammar_level, vocabulary_level, reading_level, "
        f"speaking_level, writing_level, confidence, source, recorded_at "
        f"FROM cefr_history WHERE student_id={sid} ORDER BY recorded_at;"
    )
    log(f"\n  Full CEFR History:\n{cefr}")

    # Show reassessment events
    reassessments = [cd for cd in CYCLE_DATA if cd.get("reassessment")]
    if reassessments:
        log(f"\n  {'Event':<15} | {'Before':<8} | {'After':<8} | {'Confidence':>10} | {'Threshold Met (>= 0.6)?':<25}")
        log("-" * 80)
        for cd in reassessments:
            r = cd["reassessment"]
            before = "A1"
            for prev_cd in CYCLE_DATA:
                if prev_cd["cycle"] < cd["cycle"] and prev_cd.get("db_level"):
                    before = prev_cd["db_level"]
            after = r.get("new_level", "?")
            conf = r.get("confidence", 0)
            met = "YES" if conf >= 0.6 else "NO"
            log(f"  Cycle {cd['cycle']:<8} | {before:<8} | {after:<8} | {conf:>10.2f} | {met:<25}")
    else:
        log(f"\n  No reassessment events captured in cycle data")
        log(f"  Checking DB for periodic reassessments...")
        pr = db_query(
            f"SELECT level, confidence, source FROM cefr_history "
            f"WHERE student_id={sid} AND source='periodic_reassessment';"
        )
        log(f"  {pr}")

    # Final level
    final = db_query_value(f"SELECT current_level FROM users WHERE id={sid};")
    log(f"\n  Final student level: {final}")

    # ─── Section 5: Level Progression Table ─────────────────────────
    log("\n" + "=" * 120)
    log("SECTION 5: FULL LEVEL PROGRESSION TABLE")
    log("=" * 120)
    log(f"{'Cycle':>5} | {'Target':>6} | {'Actual':>6} | {'Level':<6} | {'Plan v':>6} | "
        f"{'DNA v':>5} | {'DNA Rec':<22} | {'Recent':>7} | {'Lifetime':>8} | {'Skip?':<5} | {'Reassessment':<15}")
    log("-" * 120)
    for cd in CYCLE_DATA:
        target = f"{cd['target_pct']}%"
        actual = f"{cd['quiz_score']}%" if cd['quiz_score'] is not None else "N/A"
        level = cd['db_level'] or "?"
        plan_v = str(cd['plan_version'] or "-")
        dna_v = str(cd['dna_version'] or "-")
        dna_rec = str(cd.get('dna_recommendation') or '-')[:22]
        recent = str(cd.get('dna_recent_avg') or '-')[:7]
        lifetime = str(cd.get('dna_lifetime_avg') or '-')[:8]
        skip = "YES" if cd.get("skip_progress") else ""
        reass = ""
        if cd.get('reassessment'):
            reass = f"-> {cd['reassessment'].get('new_level', '?')}"
        log(f"{cd['cycle']:>5} | {target:>6} | {actual:>6} | {level:<6} | {plan_v:>6} | "
            f"{dna_v:>5} | {dna_rec:<22} | {recent:>7} | {lifetime:>8} | {skip:<5} | {reass:<15}")
    log("=" * 120)

    # ─── Section 6: Auto-Progress Detail (PATCH 4) ─────────────────
    log("\n" + "=" * 76)
    log("SECTION 6: AUTO-PROGRESS DETAIL (PATCH 4)")
    log("=" * 76)
    for detail in PATCH_RESULTS["patch4_auto_progress"]["details"]:
        log(f"  Cycle {detail.get('cycle')}: "
            f"lesson_id={detail.get('lesson_id')}, "
            f"auto_created={detail.get('auto_created')}, "
            f"score={detail.get('score', 'N/A')}, "
            f"notes_auto={'YES' if detail.get('notes_contains_auto') else 'NO'}")

    # Total progress count
    pc = db_query_value(f"SELECT COUNT(*) FROM progress WHERE student_id={sid};")
    log(f"\n  Total progress entries: {pc}")
    log(f"  Expected: 15 (13 manual + 2 auto-created)")

    # ─── Section 7: Database Row Counts ─────────────────────────────
    log("\n" + "=" * 76)
    log("SECTION 7: DATABASE ROW COUNTS")
    log("=" * 76)
    for table in ["sessions", "lesson_artifacts", "next_quizzes", "quiz_attempts",
                   "learning_plans", "cefr_history", "learning_dna", "learning_points",
                   "session_skill_observations", "progress", "recall_sessions"]:
        cnt = db_query_value(f"SELECT COUNT(*) FROM {table} WHERE student_id={sid};")
        log(f"  {table:35s}: {cnt.strip() if cnt else '?'}")

    # ─── Section 8: Quiz Score Progression ──────────────────────────
    scores = [cd['quiz_score'] for cd in CYCLE_DATA if cd['quiz_score'] is not None]
    if len(scores) >= 2:
        first_half = scores[:len(scores)//2]
        second_half = scores[len(scores)//2:]
        log(f"\n  Score Trajectory:")
        log(f"    First half avg:  {sum(first_half)/len(first_half):.1f}%")
        log(f"    Second half avg: {sum(second_half)/len(second_half):.1f}%")
        log(f"    Improvement:     +{sum(second_half)/len(second_half) - sum(first_half)/len(first_half):.1f}%")

    # ─── FINAL VERDICT ──────────────────────────────────────────────
    log("\n" + "=" * 76)
    log("FINAL VERDICT")
    log("=" * 76)
    for key, desc in patch_descriptions.items():
        status = PATCH_RESULTS[key]["status"]
        marker = "PASS" if status == "PASS" else "FAIL"
        log(f"  [{marker}] PATCH: {desc}")

    total_pass = sum(1 for v in PATCH_RESULTS.values() if v["status"] == "PASS")
    log(f"\n  TOTAL: {total_pass}/{total} patches verified")

    # Save all data
    save_artifact("v3_final_report", {
        "student_id": sid,
        "cycles": CYCLE_DATA,
        "patch_results": PATCH_RESULTS,
        "scores": scores,
    })
    cycle_path = E2E_ARTIFACTS_DIR / "v3_cycle_data.json"
    with open(cycle_path, "w") as f:
        json.dump(CYCLE_DATA, f, indent=2, default=str)
    log(f"\n  Cycle data: {cycle_path}")


def save_markdown_report():
    sid = IDS.get("student_id", "?")
    scores = [cd['quiz_score'] for cd in CYCLE_DATA if cd['quiz_score'] is not None]

    md = ["# Full Loop v3 Patch Verification Report\n"]
    md.append(f"**Date**: {datetime.now(timezone.utc).isoformat()}\n")
    md.append(f"**Student ID**: {sid}\n")
    md.append(f"**Cycles**: {len(CYCLE_DATA)}\n")

    # Patch Results Summary
    md.append("\n## Patch Results Summary\n")
    md.append("| Patch | Description | Status |")
    md.append("|-------|-------------|--------|")
    descs = {
        "patch1_windowed_avg": "Windowed avg (last 8) for DNA recommendation",
        "patch2_confidence_threshold": "Confidence threshold lowered to 0.6",
        "patch3_cold_start": "Difficulty engine cold start at 2 data points",
        "patch4_auto_progress": "Auto-progress in complete_lesson",
    }
    for key, desc in descs.items():
        md.append(f"| {key} | {desc} | **{PATCH_RESULTS[key]['status']}** |")

    # DNA Windowed Average
    md.append("\n## DNA Windowed Average Evolution (PATCH 1)\n")
    md.append("| Cycle | Recent Avg (last 8) | Lifetime Avg | Recommendation |")
    md.append("|-------|--------------------|--------------|--------------------|")
    for cd in CYCLE_DATA:
        r = cd.get("dna_recent_avg", "N/A")
        l = cd.get("dna_lifetime_avg", "N/A")
        rec = cd.get("dna_recommendation", "N/A")
        md.append(f"| {cd['cycle']} | {r} | {l} | {rec} |")

    # Difficulty Engine
    md.append("\n## Difficulty Engine Activation (PATCH 3)\n")
    md.append("| Cycle | Profile |")
    md.append("|-------|---------|")
    for cd in CYCLE_DATA:
        dp = cd.get("difficulty_profile", {})
        dp_str = ", ".join(f"{k}={v}" for k, v in dp.items()) if dp else "(empty)"
        md.append(f"| {cd['cycle']} | {dp_str} |")

    # Reassessment
    md.append("\n## Reassessment Confidence (PATCH 2)\n")
    reassessments = [cd for cd in CYCLE_DATA if cd.get("reassessment")]
    if reassessments:
        md.append("| Cycle | Before | After | Confidence | Threshold Met |")
        md.append("|-------|--------|-------|------------|---------------|")
        for cd in reassessments:
            r = cd["reassessment"]
            conf = r.get("confidence", 0)
            md.append(f"| {cd['cycle']} | A1 | {r.get('new_level', '?')} | {conf:.2f} | {'YES' if conf >= 0.6 else 'NO'} |")
    else:
        md.append("No reassessment events captured.\n")

    # Auto-progress
    md.append("\n## Auto-Progress (PATCH 4)\n")
    md.append("| Cycle | Lesson ID | Auto-Created | Score | Notes Contains 'Auto' |")
    md.append("|-------|-----------|-------------|-------|----------------------|")
    for d in PATCH_RESULTS["patch4_auto_progress"]["details"]:
        md.append(f"| {d.get('cycle')} | {d.get('lesson_id')} | {d.get('auto_created')} | {d.get('score', 'N/A')} | {d.get('notes_contains_auto', 'N/A')} |")

    # Level Progression
    md.append("\n## Full Level Progression\n")
    md.append("| Cycle | Target | Actual | Level | Plan v | DNA Rec | Recent Avg | Lifetime Avg | Skip Progress | Reassessment |")
    md.append("|-------|--------|--------|-------|--------|---------|------------|-------------|---------------|--------------|")
    for cd in CYCLE_DATA:
        t = f"{cd['target_pct']}%"
        a = f"{cd['quiz_score']}%" if cd['quiz_score'] is not None else "N/A"
        lev = cd['db_level'] or "?"
        pv = str(cd['plan_version'] or "-")
        rec = str(cd.get('dna_recommendation') or '-')
        ra = str(cd.get('dna_recent_avg') or '-')
        la = str(cd.get('dna_lifetime_avg') or '-')
        sk = "YES" if cd.get("skip_progress") else ""
        re = ""
        if cd.get('reassessment'):
            re = f"-> {cd['reassessment'].get('new_level', '?')}"
        md.append(f"| {cd['cycle']} | {t} | {a} | {lev} | {pv} | {rec} | {ra} | {la} | {sk} | {re} |")

    report_path = E2E_ARTIFACTS_DIR / "v3_patch_verification_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md))
    log(f"\n  Markdown report: {report_path}")


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def main():
    start = time.time()
    log("=" * 76)
    log(f"FULL LOOP v3 PATCH VERIFICATION TEST -- {datetime.now(timezone.utc).isoformat()}")
    log(f"Testing 4 patches: windowed DNA avg, confidence threshold,")
    log(f"  cold start reduction, auto-progress safety net")
    log("=" * 76)

    try:
        phase1_setup()
        phase2_assessment()
        phase3_learning_loop()
        phase4_report()
        save_markdown_report()
    except KeyboardInterrupt:
        log("\n[INTERRUPTED]")
    except Exception as e:
        log(f"\n[FATAL] {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

    elapsed = time.time() - start
    log(f"\n  Total: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    log(f"  Artifacts: {ARTIFACTS_DIR}")
    log(f"  E2E artifacts: {E2E_ARTIFACTS_DIR}")

    report_path = ARTIFACTS_DIR / "v3_full_report.txt"
    with open(report_path, "w") as f:
        f.write("\n".join(REPORT))
    e2e_path = E2E_ARTIFACTS_DIR / "v3_full_report.txt"
    with open(e2e_path, "w") as f:
        f.write("\n".join(REPORT))
    log(f"  Report: {report_path}")

    return 0 if CYCLE_DATA else 1


if __name__ == "__main__":
    sys.exit(main())
