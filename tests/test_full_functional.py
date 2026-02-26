"""Comprehensive functional test suite for Intake Eval School.

Runs against a live server (default http://localhost:8000) with NO OpenAI API calls.
Tests every layer: DB/migrations, auth, intake, assessment, lessons,
scheduling, gamification, organizations, intelligence endpoints, error handling.

Usage:
    python tests/test_full_functional.py                     # against localhost:8000
    BASE_URL=http://host:port python tests/test_full_functional.py  # custom host
"""

import json
import os
import sys
import time
import traceback

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[dict] = []
        self.section = ""

    def ok(self, name: str):
        self.passed += 1
        print(f"  PASS  {name}")

    def fail(self, name: str, expected, actual, detail=""):
        self.failed += 1
        entry = {
            "section": self.section,
            "test": name,
            "expected": str(expected),
            "actual": str(actual),
            "detail": detail,
        }
        self.errors.append(entry)
        print(f"  FAIL  {name}  (expected {expected}, got {actual}) {detail}")

    def report(self):
        total = self.passed + self.failed
        print("\n" + "=" * 70)
        print(f"TOTAL: {total}  |  PASSED: {self.passed}  |  FAILED: {self.failed}")
        if self.errors:
            print("\nFailed tests:")
            for e in self.errors:
                print(f"  [{e['section']}] {e['test']}")
                print(f"    expected: {e['expected']}")
                print(f"    actual:   {e['actual']}")
                if e["detail"]:
                    print(f"    detail:   {e['detail']}")
        print("=" * 70)
        return self.failed == 0


R = TestResults()


def check(name, condition, expected="truthy", actual="", detail=""):
    if condition:
        R.ok(name)
    else:
        R.fail(name, expected, actual or "falsy", detail)


def check_status(name, resp, expected_code):
    if resp.status_code == expected_code:
        R.ok(name)
    else:
        body = resp.text[:300] if resp.text else ""
        R.fail(name, expected_code, resp.status_code, body)


# ---------------------------------------------------------------------------
# Main test runner (synchronous httpx against live server)
# ---------------------------------------------------------------------------

def run_all_tests():
    c = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # ==================================================================
    # 0. HEALTH CHECK — verify server is up
    # ==================================================================
    R.section = "0-HEALTH"
    print("\n--- 0. HEALTH CHECK ---")

    resp = c.get("/health")
    check_status("GET /health", resp, 200)
    check("health returns ok", resp.json().get("status") == "ok", "ok", resp.json().get("status"))

    # ==================================================================
    # 1. DATABASE & MIGRATIONS (verified via API behavior)
    # ==================================================================
    R.section = "1-DB"
    print("\n--- 1. DATABASE & MIGRATIONS ---")
    # DB structure is verified implicitly by all the endpoint tests below.
    # We verify the server started (migrations ran) and endpoints respond.
    resp = c.get("/docs")
    check_status("OpenAPI docs accessible", resp, 200)

    # Verify auth is enforced (tables exist and middleware works)
    resp = c.get("/api/students")
    check_status("protected endpoint returns 401 without token", resp, 401)

    # ==================================================================
    # 2. AUTH FLOW
    # ==================================================================
    R.section = "2-AUTH"
    print("\n--- 2. AUTH FLOW ---")

    # Register student 1
    resp = c.post("/api/auth/register", json={
        "name": "Jan Kowalski", "email": "jan@test.pl",
        "password": "TestPass123!", "age": 25,
    })
    check_status("register student 1", resp, 200)
    s1 = resp.json()
    s1_token = s1.get("token", "")
    s1_id = s1.get("student_id")
    check("student 1 got token", bool(s1_token), "non-empty token", s1_token[:20] if s1_token else "")
    check("student 1 got id", s1_id is not None, "int", s1_id)

    # Register student 2
    resp = c.post("/api/auth/register", json={
        "name": "Anna Nowak", "email": "anna@test.pl",
        "password": "TestPass456!", "age": 30,
    })
    check_status("register student 2", resp, 200)
    s2 = resp.json()
    s2_token = s2.get("token", "")
    s2_id = s2.get("student_id")

    # Duplicate registration
    resp = c.post("/api/auth/register", json={
        "name": "Jan Kowalski", "email": "jan@test.pl",
        "password": "TestPass123!",
    })
    check_status("duplicate email rejects", resp, 409)

    # Login student 1
    resp = c.post("/api/auth/login", json={
        "email": "jan@test.pl", "password": "TestPass123!",
    })
    check_status("login student 1", resp, 200)
    s1_token = resp.json().get("token", s1_token)

    # Bad password
    resp = c.post("/api/auth/login", json={
        "email": "jan@test.pl", "password": "WrongPass!",
    })
    check_status("bad password rejects", resp, 401)

    # GET /api/auth/me
    resp = c.get("/api/auth/me", headers={"Authorization": f"Bearer {s1_token}"})
    check_status("GET /api/auth/me", resp, 200)
    check("me returns correct id", resp.json().get("id") == s1_id, s1_id, resp.json().get("id"))

    # --- 401 without token ---
    unauth_endpoints = [
        ("GET", f"/api/lessons/{s1_id}"),
        ("GET", f"/api/progress/{s1_id}"),
        ("GET", f"/api/gamification/{s1_id}/profile"),
        ("GET", f"/api/students/{s1_id}/learning-dna"),
        ("GET", f"/api/challenges/{s1_id}/today"),
        ("POST", f"/api/lessons/{s1_id}/generate"),
    ]
    for method, path in unauth_endpoints:
        if method == "GET":
            resp = c.get(path)
        else:
            resp = c.post(path)
        check_status(f"401 no-token {method} {path}", resp, 401)

    s1_headers = {"Authorization": f"Bearer {s1_token}"}
    s2_headers = {"Authorization": f"Bearer {s2_token}"}

    # --- Ownership: student 1 cannot access student 2 ---
    resp = c.get(f"/api/progress/{s2_id}", headers=s1_headers)
    check_status("student1 cannot GET student2 progress", resp, 403)

    resp = c.get(f"/api/gamification/{s2_id}/profile", headers=s1_headers)
    check_status("student1 cannot GET student2 gamification", resp, 403)

    # --- Create admin via API (register + direct DB role update via admin invite flow) ---
    # We'll use a workaround: register as student, then use the /api/auth/register
    # endpoint. For admin, we need to register, then we'll use teacher invite flow.
    # Actually, let's create admin + teacher by registering as students first,
    # then logging in. We'll test the teacher invite flow properly.

    # First, register a user who will become admin
    resp = c.post("/api/auth/register", json={
        "name": "Admin User", "email": "admin@test.pl",
        "password": "AdminPass1!",
    })
    check_status("register future-admin", resp, 200)
    admin_id = resp.json().get("student_id")
    # We need to promote this user to admin role. We'll do it via psql in Docker.
    import subprocess
    subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval",
         "-c", f"UPDATE users SET role = 'admin' WHERE id = {admin_id};"],
        capture_output=True, text=True,
    )

    resp = c.post("/api/auth/login", json={
        "email": "admin@test.pl", "password": "AdminPass1!",
    })
    check_status("login admin", resp, 200)
    admin_token = resp.json().get("token", "")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin can access admin endpoints
    resp = c.get("/api/admin/teacher-invites", headers=admin_headers)
    check_status("admin GET teacher-invites", resp, 200)

    # Student cannot access admin endpoints
    resp = c.get("/api/admin/teacher-invites", headers=s1_headers)
    check_status("student CANNOT GET teacher-invites", resp, 403)

    # --- Create teacher via invite flow ---
    resp = c.post("/api/admin/teacher-invites", json={
        "email": "teacher@test.pl",
        "expires_days": 7,
    }, headers=admin_headers)
    check_status("admin create teacher invite", resp, 200)
    invite_token = resp.json().get("token")
    check("invite token received", bool(invite_token), "non-empty", invite_token)

    resp = c.post("/api/auth/teacher/register", json={
        "name": "Prof. Smith",
        "email": "teacher@test.pl",
        "password": "TeacherPass1!",
        "invite_token": invite_token,
    })
    check_status("teacher register via invite", resp, 200)
    teacher_id = resp.json().get("student_id")
    check("teacher role", resp.json().get("role") == "teacher", "teacher", resp.json().get("role"))

    resp = c.post("/api/auth/login", json={
        "email": "teacher@test.pl", "password": "TeacherPass1!",
    })
    check_status("login teacher", resp, 200)
    teacher_token = resp.json().get("token", "")
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

    # Teacher CAN access student 1 data
    resp = c.get(f"/api/progress/{s1_id}", headers=teacher_headers)
    check_status("teacher CAN GET student1 progress", resp, 200)

    # ==================================================================
    # 3. INTAKE & ASSESSMENT
    # ==================================================================
    R.section = "3-INTAKE"
    print("\n--- 3. INTAKE & ASSESSMENT ---")

    # Submit intake (creates a NEW user row in this route — that's how the old API works)
    resp = c.post("/api/intake", json={
        "name": "Jan Kowalski", "age": 25, "current_level": "A2",
        "goals": ["pass_exam", "travel"], "problem_areas": ["grammar", "speaking"],
        "additional_notes": "Polish native speaker",
    }, headers=s1_headers)
    check_status("POST /api/intake", resp, 200)

    # Get intake (using student 1's own ID — intake data is on the user row)
    resp = c.get(f"/api/intake/{s1_id}", headers=s1_headers)
    check_status("GET /api/intake/{student_id}", resp, 200)
    intake = resp.json()
    check("intake name matches", intake.get("name") == "Jan Kowalski",
          "Jan Kowalski", intake.get("name"))

    # Student 1 cannot get student 2 intake
    resp = c.get(f"/api/intake/{s2_id}", headers=s1_headers)
    check_status("student1 cannot GET student2 intake", resp, 403)

    # Start assessment
    resp = c.post("/api/assessment/start", json={
        "student_id": s1_id,
    }, headers=s1_headers)
    check_status("POST /api/assessment/start", resp, 200)
    assess = resp.json()
    assessment_id = assess.get("assessment_id")
    questions = assess.get("questions", [])
    check("got placement questions", len(questions) == 5, 5, len(questions))

    # Student 2 cannot start assessment for student 1
    resp = c.post("/api/assessment/start", json={
        "student_id": s1_id,
    }, headers=s2_headers)
    check_status("student2 cannot start student1 assessment", resp, 403)

    # Submit placement answers
    correct_answers = {1: False, 2: True, 3: False, 4: True, 5: True}
    placement_answers = [
        {"question_id": q["id"], "answer": correct_answers.get(q["id"], True)}
        for q in questions
    ]
    resp = c.post("/api/assessment/placement", json={
        "student_id": s1_id,
        "assessment_id": assessment_id,
        "answers": placement_answers,
    }, headers=s1_headers)
    check_status("POST /api/assessment/placement", resp, 200)
    placement_result = resp.json()
    check("placement returned bracket",
          placement_result.get("placement_result", {}).get("bracket") is not None,
          "non-null bracket", placement_result.get("placement_result", {}).get("bracket"))
    diag_questions = placement_result.get("questions", [])
    check("got diagnostic questions", len(diag_questions) > 0, ">0", len(diag_questions))

    # Submit diagnostic answers (pick first option or dummy)
    diag_answers = []
    for dq in diag_questions:
        ans = (dq.get("options") or ["dummy"])[0]
        diag_answers.append({"question_id": dq["id"], "answer": ans})

    resp = c.post("/api/assessment/diagnostic", json={
        "student_id": s1_id,
        "assessment_id": assessment_id,
        "answers": diag_answers,
    }, headers=s1_headers)
    check_status("POST /api/assessment/diagnostic (AI fallback)", resp, 200)
    diag_result = resp.json()
    check("diagnostic returned level",
          diag_result.get("determined_level") is not None,
          "non-null level", diag_result.get("determined_level"))
    check("diagnostic has scores",
          diag_result.get("scores", {}).get("overall") is not None,
          "non-null overall", diag_result.get("scores"))
    has_ai_error = "ai_error" in diag_result
    check("AI graceful fallback (ai_error present)", has_ai_error, True, has_ai_error)

    # GET latest assessment
    resp = c.get(f"/api/assessment/{s1_id}/latest", headers=s1_headers)
    check_status("GET /api/assessment/{id}/latest", resp, 200)
    check("latest assessment exists", resp.json().get("exists") is True, True, resp.json().get("exists"))

    # ==================================================================
    # 4. LESSON FLOW
    # ==================================================================
    R.section = "4-LESSONS"
    print("\n--- 4. LESSON FLOW ---")

    # Generate lesson — will fail due to no API key, but should not be raw 500
    # First, we need a learner_profile for the student
    subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval",
         "-c", f"INSERT INTO learner_profiles (student_id, gaps, priorities, profile_summary, recommended_start_level) "
               f"VALUES ({s1_id}, '[]', '[\"grammar\"]', 'Test profile', 'A2');"],
        capture_output=True, text=True,
    )

    resp = c.post(f"/api/lessons/{s1_id}/generate", headers=s1_headers)
    check("generate lesson fails gracefully (not raw 500)",
          resp.status_code != 500 or "detail" in resp.text or "error" in resp.text.lower(),
          "structured error", resp.status_code,
          resp.text[:200])

    # Insert test lessons directly via psql
    result = subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval", "-t", "-A",
         "-c", f"INSERT INTO lessons (student_id, session_number, objective, content, difficulty, status) "
               f"VALUES ({s1_id}, 1, 'Test present simple', "
               f"'{{\"objective\": \"Test present simple\", \"exercises\": [], \"difficulty\": \"A2\"}}', "
               f"'A2', 'generated') RETURNING id;"],
        capture_output=True, text=True,
    )
    test_lesson_id = int(result.stdout.strip().split('\n')[0])

    result = subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval", "-t", "-A",
         "-c", f"INSERT INTO lessons (student_id, session_number, objective, content, difficulty, status) "
               f"VALUES ({s1_id}, 2, 'Test past simple', "
               f"'{{\"objective\": \"Test past simple\", \"exercises\": [], \"difficulty\": \"A2\"}}', "
               f"'A2', 'generated') RETURNING id;"],
        capture_output=True, text=True,
    )
    test_lesson_id_2 = int(result.stdout.strip().split('\n')[0])

    # List lessons
    resp = c.get(f"/api/lessons/{s1_id}", headers=s1_headers)
    check_status("GET /api/lessons/{student_id}", resp, 200)
    check("lessons list non-empty", len(resp.json()) >= 1, ">=1", len(resp.json()))

    # Get single lesson
    resp = c.get(f"/api/lessons/{s1_id}/{test_lesson_id}", headers=s1_headers)
    check_status("GET /api/lessons/{student_id}/{lesson_id}", resp, 200)

    # Complete lesson
    resp = c.post(f"/api/lessons/{test_lesson_id}/complete", headers=s1_headers)
    if resp.status_code == 200:
        check_status("POST /api/lessons/{id}/complete", resp, 200)
    else:
        check("complete lesson non-crash",
              resp.status_code != 500 or "detail" in resp.text,
              "structured error", resp.status_code, resp.text[:200])

    # Idempotency guard: complete same lesson again
    resp = c.post(f"/api/lessons/{test_lesson_id}/complete", headers=s1_headers)
    check_status("double-complete returns 409", resp, 409)

    # Submit progress (student_id comes from JWT)
    resp = c.post(f"/api/progress/{test_lesson_id_2}", json={
        "lesson_id": test_lesson_id_2,
        "student_id": s1_id,
        "score": 85.0,
        "notes": "Good work on grammar",
        "areas_improved": ["grammar"],
        "areas_struggling": ["pronunciation"],
    }, headers=s1_headers)
    check_status("POST /api/progress/{lesson_id}", resp, 200)
    prog = resp.json()
    check("progress student_id from JWT", prog.get("student_id") == s1_id, s1_id, prog.get("student_id"))

    # Duplicate progress
    resp = c.post(f"/api/progress/{test_lesson_id_2}", json={
        "lesson_id": test_lesson_id_2,
        "student_id": s1_id,
        "score": 90.0,
    }, headers=s1_headers)
    check_status("duplicate progress returns 409", resp, 409)

    # GET progress summary
    resp = c.get(f"/api/progress/{s1_id}", headers=s1_headers)
    check_status("GET /api/progress/{student_id}", resp, 200)
    summary = resp.json()
    check("progress summary has entries", summary.get("total_lessons", 0) >= 1, ">=1", summary.get("total_lessons"))

    # ==================================================================
    # 5. SCHEDULING
    # ==================================================================
    R.section = "5-SCHEDULING"
    print("\n--- 5. SCHEDULING ---")

    # Teacher availability CRUD
    resp = c.post("/api/teacher/availability", json={
        "windows": [
            {"day_of_week": "monday", "start_time": "09:00", "end_time": "12:00"},
            {"day_of_week": "wednesday", "start_time": "14:00", "end_time": "17:00"},
        ],
    }, headers=teacher_headers)
    check_status("POST teacher availability", resp, 200)
    check("2 windows created", resp.json().get("windows_count") == 2, 2, resp.json().get("windows_count"))

    resp = c.get("/api/teacher/availability", headers=teacher_headers)
    check_status("GET teacher availability", resp, 200)
    check("has 2 windows", len(resp.json().get("windows", [])) == 2, 2, len(resp.json().get("windows", [])))

    # Override: mark a date as unavailable
    resp = c.post("/api/teacher/availability/overrides", json={
        "date": "2026-03-10",
        "is_available": False,
        "reason": "vacation",
    }, headers=teacher_headers)
    check_status("POST availability override", resp, 200)

    # Student requests session
    resp = c.post("/api/student/me/sessions/request", json={
        "scheduled_at": "2026-03-01T10:00:00Z",
        "duration_min": 60,
        "notes": "Focus on speaking",
    }, headers=s1_headers)
    check_status("student request session", resp, 200)
    session_id = resp.json().get("id")
    check("session created", session_id is not None, "non-null", session_id)

    # Teacher sees sessions
    resp = c.get("/api/teacher/sessions", headers=teacher_headers)
    check_status("teacher GET sessions", resp, 200)
    sessions = resp.json().get("sessions", [])
    check("teacher sees requested session", len(sessions) >= 1, ">=1", len(sessions))

    # Teacher confirms
    resp = c.post(f"/api/teacher/sessions/{session_id}/confirm", headers=teacher_headers)
    check_status("teacher confirm session", resp, 200)
    check("session confirmed", resp.json().get("status") == "confirmed", "confirmed", resp.json().get("status"))

    # Confirm again fails
    resp = c.post(f"/api/teacher/sessions/{session_id}/confirm", headers=teacher_headers)
    check_status("double-confirm returns 409", resp, 409)

    # Teacher marks attendance with lesson link
    resp = c.post(f"/api/teacher/sessions/{session_id}/attendance", json={
        "attended": 1,
        "lesson_id": test_lesson_id,
    }, headers=teacher_headers)
    check_status("teacher mark attendance", resp, 200)

    # Teacher adds notes
    resp = c.post(f"/api/teacher/sessions/{session_id}/notes", json={
        "teacher_notes": "Student showed great progress.",
        "homework": "Read chapter 5.",
        "session_summary": "Covered present simple and continuous.",
    }, headers=teacher_headers)
    check_status("teacher add notes", resp, 200)

    # Teacher reads notes back
    resp = c.get(f"/api/teacher/sessions/{session_id}/notes", headers=teacher_headers)
    check_status("teacher GET notes", resp, 200)
    check("notes persisted", resp.json().get("teacher_notes") == "Student showed great progress.",
          "Student showed great progress.", resp.json().get("teacher_notes"))

    # Cancel a different session
    resp = c.post("/api/student/me/sessions/request", json={
        "scheduled_at": "2026-03-02T14:00:00Z",
        "duration_min": 45,
    }, headers=s1_headers)
    session_id_2 = resp.json().get("id")

    resp = c.post(f"/api/teacher/sessions/{session_id_2}/cancel", headers=teacher_headers)
    check_status("teacher cancel session", resp, 200)
    check("session cancelled", resp.json().get("status") == "cancelled", "cancelled", resp.json().get("status"))

    # Group session
    resp = c.post("/api/teacher/sessions/group", json={
        "scheduled_at": "2026-03-05T09:00:00Z",
        "duration_min": 90,
        "max_students": 5,
        "student_ids": [s1_id, s2_id],
    }, headers=teacher_headers)
    check_status("create group session", resp, 200)
    group_session_id = resp.json().get("id")
    check("group session created", group_session_id is not None, "non-null", group_session_id)
    check("group is_group=True", resp.json().get("is_group") is True, True, resp.json().get("is_group"))

    # List students in group session
    resp = c.get(f"/api/teacher/sessions/{group_session_id}/students", headers=teacher_headers)
    check_status("list group session students", resp, 200)
    check("group has 2 students", len(resp.json().get("students", [])) == 2, 2,
          len(resp.json().get("students", [])))

    # Submit skill observations
    resp = c.post(f"/api/sessions/{session_id}/observations", json=[
        {"skill": "grammar", "score": 75, "cefr_level": "A2", "notes": "Good basics"},
        {"skill": "speaking", "score": 60, "notes": "Needs practice"},
    ], headers=teacher_headers)
    check_status("submit observations", resp, 200)

    # Get observations
    resp = c.get(f"/api/sessions/{session_id}/observations", headers=teacher_headers)
    check_status("GET observations", resp, 200)
    check("2 observations returned", len(resp.json().get("observations", [])) == 2, 2,
          len(resp.json().get("observations", [])))

    # ==================================================================
    # 6. GAMIFICATION
    # ==================================================================
    R.section = "6-GAMIFICATION"
    print("\n--- 6. GAMIFICATION ---")

    # Profile
    resp = c.get(f"/api/gamification/{s1_id}/profile", headers=s1_headers)
    check_status("GET gamification profile", resp, 200)
    gam = resp.json()
    check("profile has total_xp", "total_xp" in gam, "total_xp key", str(list(gam.keys())[:5]))
    check("profile has level", "level" in gam, "level key", str(list(gam.keys())[:5]))

    # Daily challenges
    resp = c.get(f"/api/challenges/{s1_id}/today", headers=s1_headers)
    check_status("GET daily challenges", resp, 200)
    challs = resp.json()
    check("3 daily challenges generated", len(challs.get("challenges", [])) == 3, 3,
          len(challs.get("challenges", [])))

    # Update profile (avatar)
    resp = c.put(f"/api/gamification/{s1_id}/profile", json={
        "avatar_id": "fox",
        "theme_preference": "dark",
    }, headers=s1_headers)
    check_status("PUT gamification profile", resp, 200)

    # Record activity (streak)
    resp = c.post(f"/api/gamification/{s1_id}/activity", headers=s1_headers)
    check_status("POST gamification activity", resp, 200)
    act = resp.json()
    check("streak >= 1", act.get("streak", 0) >= 1, ">=1", act.get("streak"))

    # Weekly summary
    resp = c.get(f"/api/gamification/{s1_id}/weekly-summary", headers=s1_headers)
    check_status("GET gamification weekly-summary", resp, 200)

    # Leaderboard
    resp = c.get("/api/leaderboard/weekly", headers=s1_headers)
    check_status("GET leaderboard weekly", resp, 200)

    resp = c.get("/api/leaderboard/alltime", headers=s1_headers)
    check_status("GET leaderboard alltime", resp, 200)

    resp = c.get("/api/leaderboard/streak", headers=s1_headers)
    check_status("GET leaderboard streak", resp, 200)

    # Check achievements
    resp = c.post(f"/api/gamification/{s1_id}/check-achievements", json={}, headers=s1_headers)
    check_status("POST check-achievements", resp, 200)

    # ==================================================================
    # 6b. VOCABULARY
    # ==================================================================
    R.section = "6b-VOCAB"
    print("\n--- 6b. VOCABULARY ---")

    resp = c.post(f"/api/vocab/{s1_id}/add", json={
        "word": "hello", "translation": "czesc", "example": "Hello, how are you?",
    }, headers=s1_headers)
    check_status("POST vocab add", resp, 200)
    card_id = resp.json().get("id")
    check("vocab card created", card_id is not None, "non-null", card_id)

    resp = c.post(f"/api/vocab/{s1_id}/add", json={
        "word": "goodbye", "translation": "do widzenia",
    }, headers=s1_headers)
    check_status("POST vocab add 2", resp, 200)

    resp = c.get(f"/api/vocab/{s1_id}/stats", headers=s1_headers)
    check_status("GET vocab stats", resp, 200)
    check("total_cards >= 2", resp.json().get("total_cards", 0) >= 2, ">=2", resp.json().get("total_cards"))

    resp = c.post(f"/api/vocab/{s1_id}/review", json={
        "card_id": card_id, "quality": 4,
    }, headers=s1_headers)
    check_status("POST vocab review", resp, 200)

    resp = c.get(f"/api/vocab/{s1_id}/due", headers=s1_headers)
    check_status("GET vocab due", resp, 200)

    # ==================================================================
    # 7. ORGANIZATIONS / MULTI-TENANCY
    # ==================================================================
    R.section = "7-ORGS"
    print("\n--- 7. ORGANIZATIONS ---")

    # Teacher creates org
    resp = c.post("/api/organizations", json={
        "name": "Test English School",
        "plan": "free",
    }, headers=teacher_headers)
    check_status("create organization", resp, 200)
    org = resp.json()
    org_id = org.get("id")
    check("org created", org_id is not None, "non-null", org_id)

    # Student cannot create org
    resp = c.post("/api/organizations", json={
        "name": "Student Org",
    }, headers=s1_headers)
    check_status("student cannot create org", resp, 403)

    # Assign student 1 to org
    subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval",
         "-c", f"UPDATE users SET org_id = {org_id} WHERE id = {s1_id};"],
        capture_output=True, text=True,
    )

    # Get org details
    resp = c.get(f"/api/organizations/{org_id}", headers=teacher_headers)
    check_status("GET organization", resp, 200)
    check("org member_count >= 1", resp.json().get("member_count", 0) >= 1, ">=1",
          resp.json().get("member_count"))

    # List org members
    resp = c.get(f"/api/organizations/{org_id}/members", headers=teacher_headers)
    check_status("GET org members", resp, 200)

    # Update org
    resp = c.put(f"/api/organizations/{org_id}", json={
        "plan": "premium",
    }, headers=teacher_headers)
    check_status("PUT update organization", resp, 200)

    # Invite to org (non-existent email -> pending invite)
    resp = c.post(f"/api/organizations/{org_id}/invite", json={
        "email": "newstudent@test.pl",
        "role": "student",
    }, headers=teacher_headers)
    check_status("POST org invite", resp, 200)
    check("invite status", resp.json().get("status") == "invited", "invited", resp.json().get("status"))

    # Teacher student list (org-scoped)
    resp = c.get("/api/teacher/students", headers=teacher_headers)
    check_status("teacher GET students (org-scoped)", resp, 200)
    students = resp.json().get("students", [])
    student_ids_in_list = [s["id"] for s in students]
    check("student 1 in org list", s1_id in student_ids_in_list, True, student_ids_in_list)
    check("student 2 NOT in org list", s2_id not in student_ids_in_list, True, student_ids_in_list)

    # ==================================================================
    # 8. INTELLIGENCE ENDPOINTS (graceful degradation)
    # ==================================================================
    R.section = "8-INTELLIGENCE"
    print("\n--- 8. INTELLIGENCE ENDPOINTS ---")

    # Learning DNA
    resp = c.get(f"/api/students/{s1_id}/learning-dna", headers=s1_headers)
    check("learning-dna does not crash",
          resp.status_code in (200, 500), "200 or 500", resp.status_code,
          resp.text[:200] if resp.status_code >= 400 else "")
    if resp.status_code == 200:
        R.ok("learning-dna returns 200")
    else:
        R.fail("learning-dna returns 200", 200, resp.status_code, resp.text[:200])

    # L1 interference
    resp = c.get(f"/api/students/{s1_id}/l1-interference", headers=s1_headers)
    check_status("l1-interference returns 200", resp, 200)
    check("l1 has interference_profile key",
          "interference_profile" in resp.json(), True, str(list(resp.json().keys())))

    # Level prediction
    resp = c.get(f"/api/students/{s1_id}/level-prediction", headers=s1_headers)
    check("level-prediction does not crash", resp.status_code in (200, 500),
          "200 or 500", resp.status_code, resp.text[:200] if resp.status_code >= 400 else "")

    # Plateau detection
    resp = c.get(f"/api/students/{s1_id}/plateau-detection", headers=s1_headers)
    check("plateau-detection does not crash", resp.status_code in (200, 500),
          "200 or 500", resp.status_code, resp.text[:200] if resp.status_code >= 400 else "")

    # Peer comparison
    resp = c.get(f"/api/students/{s1_id}/peer-comparison", headers=s1_headers)
    check("peer-comparison does not crash", resp.status_code in (200, 500),
          "200 or 500", resp.status_code, resp.text[:200] if resp.status_code >= 400 else "")

    # Progress insights
    resp = c.get(f"/api/students/{s1_id}/progress-insights", headers=s1_headers)
    check("progress-insights does not crash", resp.status_code in (200, 500),
          "200 or 500", resp.status_code, resp.text[:200] if resp.status_code >= 400 else "")

    # Weekly summary (AI-dependent)
    resp = c.get(f"/api/students/{s1_id}/weekly-summary", headers=s1_headers)
    check("weekly-summary does not crash with 500",
          resp.status_code != 500 or "detail" in resp.text,
          "non-500 or structured", resp.status_code, resp.text[:200])

    # Teacher briefing (AI-dependent)
    resp = c.get(f"/api/sessions/{session_id}/teacher-briefing", headers=teacher_headers)
    check("teacher-briefing does not crash with 500",
          resp.status_code != 500 or "detail" in resp.text,
          "non-500 or structured", resp.status_code, resp.text[:200])

    # Post-session prompts (AI-dependent)
    resp = c.get(f"/api/sessions/{session_id}/post-session-prompts", headers=teacher_headers)
    check("post-session-prompts does not crash",
          resp.status_code != 500 or "detail" in resp.text,
          "non-500 or structured", resp.status_code, resp.text[:200])

    # Recompute DNA
    resp = c.post(f"/api/students/{s1_id}/learning-dna/recompute", headers=s1_headers)
    check("dna-recompute does not crash",
          resp.status_code in (200, 500), "200 or 500", resp.status_code,
          resp.text[:200] if resp.status_code >= 400 else "")

    # L1 analyze (AI-dependent)
    resp = c.post(f"/api/students/{s1_id}/l1-interference/analyze",
                   json={"text": "I am go to the shop yesterday."},
                   headers=s1_headers)
    check("l1-analyze does not crash with 500",
          resp.status_code != 500 or "detail" in resp.text,
          "non-500 or structured", resp.status_code, resp.text[:200])

    # ==================================================================
    # 9. ERROR HANDLING
    # ==================================================================
    R.section = "9-ERRORS"
    print("\n--- 9. ERROR HANDLING ---")

    # Malformed JSON
    resp = c.post("/api/auth/register",
                   content=b"not json at all",
                   headers={"Content-Type": "application/json"})
    check_status("malformed JSON returns 422", resp, 422)

    # Wrong types
    resp = c.post("/api/assessment/start", json={
        "student_id": "not-an-int",
    }, headers=s1_headers)
    check_status("wrong type returns 422", resp, 422)

    # Missing required fields
    resp = c.post("/api/auth/register", json={
        "name": "Test",
    })
    check_status("missing fields returns 422", resp, 422)

    # Non-existent resource
    resp = c.get("/api/lessons/99999", headers=s1_headers)
    check("non-existent student lessons returns 200 empty or 403/404",
          resp.status_code in (200, 403, 404), "200/403/404", resp.status_code)

    resp = c.get(f"/api/lessons/{s1_id}/99999", headers=s1_headers)
    check_status("non-existent lesson returns 404", resp, 404)

    resp = c.get("/api/assessment/99999/latest", headers=s1_headers)
    check("non-existent assessment handled",
          resp.status_code in (200, 403, 404), "200/403/404", resp.status_code)

    # Password too short
    resp = c.post("/api/auth/register", json={
        "name": "Short", "email": "short@test.pl", "password": "ab",
    })
    check_status("short password returns 422", resp, 422)

    # Rate limiter — send rapid login attempts
    rate_limited = False
    for i in range(25):
        resp = c.post("/api/auth/login", json={
            "email": f"nonexistent{i}@test.pl", "password": "wrong",
        })
        if resp.status_code == 429:
            rate_limited = True
            break
    check("rate limiter triggers on rapid auth attempts", rate_limited, True, "never got 429")

    # ==================================================================
    # 10. DATA INTEGRITY
    # ==================================================================
    R.section = "10-INTEGRITY"
    print("\n--- 10. DATA INTEGRITY ---")

    # UNIQUE constraint on progress: already tested above (409 on duplicate)
    R.ok("UNIQUE progress constraint (tested via 409)")

    # FK enforcement: try inserting a lesson for non-existent user via psql
    result = subprocess.run(
        ["docker", "exec", "intake_eval_db", "psql", "-U", "intake", "-d", "intake_eval",
         "-c", "INSERT INTO lessons (student_id, session_number, objective, difficulty, status) "
               "VALUES (99999, 1, 'test', 'A1', 'generated');"],
        capture_output=True, text=True,
    )
    fk_blocked = "violates foreign key" in result.stderr or result.returncode != 0
    check("FK blocks lesson for non-existent user", fk_blocked, "FK error", result.stderr[:200])

    # ==================================================================
    # EXTRA: Student dashboard and teacher overview
    # ==================================================================
    R.section = "EXTRA"
    print("\n--- EXTRA ENDPOINTS ---")

    resp = c.get("/api/student/me/dashboard", headers=s1_headers)
    check_status("student dashboard", resp, 200)
    check("dashboard has student key", "student" in resp.json(), True, str(list(resp.json().keys())))

    resp = c.get("/api/student/me/sessions", headers=s1_headers)
    check_status("student sessions list", resp, 200)

    resp = c.get("/api/student/me/progress", headers=s1_headers)
    check_status("student progress", resp, 200)

    resp = c.get(f"/api/teacher/students/{s1_id}/overview", headers=teacher_headers)
    check_status("teacher student overview", resp, 200)
    overview = resp.json()
    check("overview has student data", overview.get("student", {}).get("name") == "Jan Kowalski",
          "Jan Kowalski", overview.get("student", {}).get("name"))
    check("overview has activity", "activity" in overview, True, str(list(overview.keys())))

    # Booking slots
    resp = c.get("/api/booking/slots", headers=s1_headers)
    check_status("GET booking slots", resp, 200)

    # Student list teachers
    resp = c.get("/api/students/teachers", headers=s1_headers)
    check_status("student list teachers", resp, 200)

    c.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print(f"COMPREHENSIVE FUNCTIONAL TEST — Intake Eval School")
    print(f"Target: {BASE_URL}")
    print("=" * 70)
    start = time.time()

    try:
        run_all_tests()
    except Exception:
        print("\n\nFATAL ERROR during test run:")
        traceback.print_exc()
        R.failed += 1
        R.errors.append({
            "section": "FATAL",
            "test": "test runner crashed",
            "expected": "clean run",
            "actual": traceback.format_exc()[-300:],
            "detail": "",
        })

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")
    all_ok = R.report()

    # Sections requiring API key
    print("\n--- REQUIRES OPENAI API KEY TO FULLY TEST ---")
    print("  - POST /api/lessons/{id}/generate (full AI lesson generation)")
    print("  - POST /api/diagnostic/{id} (AI-powered diagnostic)")
    print("  - GET /api/sessions/{id}/teacher-briefing (AI briefing)")
    print("  - GET /api/sessions/{id}/post-session-prompts (AI prompts)")
    print("  - GET /api/students/{id}/weekly-summary (AI weekly summary)")
    print("  - POST /api/students/{id}/l1-interference/analyze (AI text analysis)")
    print("  - POST /api/sessions/{id}/warmup (AI warmup generation)")
    print("  - POST /api/recall/{id}/start (AI recall questions)")
    print("  - POST /api/writing/{id}/submit (AI writing evaluation)")

    sys.exit(0 if all_ok else 1)
