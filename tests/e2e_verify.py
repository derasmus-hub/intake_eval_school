"""
E2E verification script for intake_eval_school.

Tests the full API flow: health → register → login → intake → assessment → scheduling.
Run with:   python tests/e2e_verify.py

Prerequisites:
  - Backend running on http://127.0.0.1:8000
  - Fresh database (or delete intake_eval.db and restart)
"""

import sys
import json
import urllib.request
import urllib.error
import time
import random
import string

BASE = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0


def rand_email():
    tag = "".join(random.choices(string.ascii_lowercase, k=6))
    return f"test_{tag}@e2e.local"


def api(method, path, body=None, token=None):
    """Minimal HTTP client using only stdlib."""
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body_text)
        except Exception:
            return e.code, {"detail": body_text[:300]}
    except Exception as e:
        return 0, {"detail": str(e)}


def check(label, ok, detail=""):
    global PASS, FAIL
    tag = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    extra = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {label}{extra}")
    return ok


# ── 1. Health ────────────────────────────────────────────────────
print("\n=== 1. Health Check ===")
code, data = api("GET", "/health")
check("GET /health returns 200", code == 200, f"status={code}")
check("/health body has status=ok", data.get("status") == "ok", json.dumps(data))

# ── 2. Register ──────────────────────────────────────────────────
print("\n=== 2. Register ===")
student_email = rand_email()
teacher_email = rand_email()

code, data = api("POST", "/api/auth/register", {
    "name": "E2E Student",
    "email": student_email,
    "password": "test1234",
    "role": "student",
})
check("Register student returns 200", code == 200, f"status={code}")
student_token = data.get("token", "")
student_id = data.get("student_id")
check("Student token received", bool(student_token))
check("Student ID received", student_id is not None, f"id={student_id}")
check("Role is student", data.get("role") == "student", f"role={data.get('role')}")

code, data = api("POST", "/api/auth/register", {
    "name": "E2E Teacher",
    "email": teacher_email,
    "password": "test1234",
    "role": "teacher",
})
check("Register teacher returns 200", code == 200, f"status={code}")
teacher_token = data.get("token", "")
teacher_id = data.get("student_id")
check("Teacher token received", bool(teacher_token))
check("Role is teacher", data.get("role") == "teacher", f"role={data.get('role')}")

# Duplicate registration should fail
code, data = api("POST", "/api/auth/register", {
    "name": "Dup", "email": student_email, "password": "x", "role": "student",
})
check("Duplicate email returns 409", code == 409, f"status={code}")

# ── 3. Login ─────────────────────────────────────────────────────
print("\n=== 3. Login ===")
code, data = api("POST", "/api/auth/login", {
    "email": student_email,
    "password": "test1234",
})
check("Login student returns 200", code == 200, f"status={code}")
login_token = data.get("token", "")
check("Login token received", bool(login_token))
check("Login returns role", data.get("role") == "student")

# /me endpoint
code, data = api("GET", "/api/auth/me", token=login_token)
check("GET /me returns 200", code == 200, f"status={code}")
check("/me has correct email", data.get("email") == student_email)
check("/me has correct role", data.get("role") == "student")

# ── 4. Intake ────────────────────────────────────────────────────
print("\n=== 4. Intake ===")
code, data = api("POST", "/api/intake", {
    "name": "E2E IntakeStudent",
    "age": 25,
    "current_level": "A2",
    "goals": ["speaking", "grammar"],
    "problem_areas": ["articles", "prepositions"],
    "filler": "student",
    "additional_notes": "E2E test student",
})
check("POST /api/intake returns 200", code == 200, f"status={code}")
intake_student_id = data.get("student_id")
check("Intake student_id received", intake_student_id is not None, f"id={intake_student_id}")

# Retrieve intake
code, data = api("GET", f"/api/intake/{intake_student_id}")
check("GET /api/intake/{id} returns 200", code == 200, f"status={code}")
check("Intake name correct", data.get("name") == "E2E IntakeStudent")

# ── 5. Assessment ────────────────────────────────────────────────
print("\n=== 5. Assessment (placement + diagnostic) ===")

# Start assessment
code, data = api("POST", "/api/assessment/start", {"student_id": intake_student_id})
check("Start assessment returns 200", code == 200, f"status={code}")
assessment_id = data.get("assessment_id")
questions = data.get("questions", [])
check("Assessment ID received", assessment_id is not None)
check("Placement questions received", len(questions) > 0, f"count={len(questions)}")

# Submit placement answers (answer True for all — simple strategy)
placement_answers = [{"question_id": q["id"], "answer": True} for q in questions]
code, data = api("POST", "/api/assessment/placement", {
    "student_id": intake_student_id,
    "assessment_id": assessment_id,
    "answers": placement_answers,
})
check("Submit placement returns 200", code == 200, f"status={code}")
bracket = data.get("placement_result", {}).get("bracket", "")
diag_questions = data.get("questions", [])
check("Bracket determined", bool(bracket), f"bracket={bracket}")
check("Diagnostic questions received", len(diag_questions) > 0, f"count={len(diag_questions)}")

# Submit diagnostic answers (answer with first option or "unknown")
diag_answers = []
for q in diag_questions:
    if q.get("options") and len(q["options"]) > 0:
        answer = q["options"][0]
    else:
        answer = "unknown"
    diag_answers.append({"question_id": q["id"], "answer": answer})

code, data = api("POST", "/api/assessment/diagnostic", {
    "student_id": intake_student_id,
    "assessment_id": assessment_id,
    "answers": diag_answers,
})
check("Submit diagnostic returns 200", code == 200, f"status={code}")
determined_level = data.get("determined_level")
check("Level determined", bool(determined_level), f"level={determined_level}")
check("Sub-skill breakdown present",
      isinstance(data.get("sub_skill_breakdown"), list),
      f"count={len(data.get('sub_skill_breakdown', []))}")

# Retrieve results
code, data = api("GET", f"/api/assessment/{intake_student_id}")
check("GET assessment results returns 200", code == 200, f"status={code}")
check("Assessment status is completed", data.get("status") == "completed")

# ── 6. Scheduling ────────────────────────────────────────────────
print("\n=== 6. Scheduling ===")

# Student requests a session
code, data = api("POST", "/api/student/me/sessions/request", {
    "scheduled_at": "2026-03-01T14:00:00Z",
    "duration_min": 60,
    "notes": "E2E test session",
}, token=student_token)
check("Student request session returns 200", code == 200, f"status={code}")
session_id = data.get("id")
check("Session ID received", session_id is not None, f"id={session_id}")
check("Session status is requested", data.get("status") == "requested")

# Student views sessions
code, data = api("GET", "/api/student/me/sessions", token=student_token)
check("Student list sessions returns 200", code == 200, f"status={code}")
sessions = data.get("sessions", [])
check("Student sees 1 session", len(sessions) >= 1, f"count={len(sessions)}")

# Teacher views requested sessions
code, data = api("GET", "/api/teacher/sessions?status=requested", token=teacher_token)
check("Teacher list requests returns 200", code == 200, f"status={code}")
teacher_sessions = data.get("sessions", [])
check("Teacher sees requested session", len(teacher_sessions) >= 1, f"count={len(teacher_sessions)}")

# Teacher confirms session
code, data = api("POST", f"/api/teacher/sessions/{session_id}/confirm", token=teacher_token)
check("Teacher confirm returns 200", code == 200, f"status={code}")
check("Session status is confirmed", data.get("status") == "confirmed")

# Student sees confirmed session
code, data = api("GET", "/api/student/me/sessions", token=student_token)
check("Student sees confirmed session", code == 200)
if data.get("sessions"):
    s = data["sessions"][0]
    check("Session has confirmed status", s.get("status") == "confirmed")
    check("Session has teacher name", s.get("teacher_name") == "E2E Teacher",
          f"teacher={s.get('teacher_name')}")

# Student requests another session, teacher cancels it
code, data = api("POST", "/api/student/me/sessions/request", {
    "scheduled_at": "2026-03-02T10:00:00Z",
    "duration_min": 45,
}, token=student_token)
session_id_2 = data.get("id")
check("Second session requested", code == 200 and session_id_2 is not None)

code, data = api("POST", f"/api/teacher/sessions/{session_id_2}/cancel", token=teacher_token)
check("Teacher cancel returns 200", code == 200, f"status={code}")
check("Session status is cancelled", data.get("status") == "cancelled")

# Teacher cannot confirm already-cancelled session
code, data = api("POST", f"/api/teacher/sessions/{session_id_2}/confirm", token=teacher_token)
check("Cannot confirm cancelled session (409)", code == 409, f"status={code}")

# ── 7. Role guards ───────────────────────────────────────────────
print("\n=== 7. Role Guards ===")

# Student should not access teacher endpoints
code, data = api("GET", "/api/teacher/sessions", token=student_token)
check("Student blocked from teacher sessions (403)", code == 403, f"status={code}")

# Teacher should not access student endpoints
code, data = api("GET", "/api/student/me/sessions", token=teacher_token)
check("Teacher blocked from student sessions (403)", code == 403, f"status={code}")

# No token should get 401
code, data = api("GET", "/api/auth/me")
check("No token on /me returns 401", code == 401, f"status={code}")

# ── Summary ──────────────────────────────────────────────────────
print("\n" + "=" * 50)
total = PASS + FAIL
print(f"  TOTAL: {total}  |  PASS: {PASS}  |  FAIL: {FAIL}")
if FAIL == 0:
    print("  ALL TESTS PASSED")
else:
    print(f"  {FAIL} TEST(S) FAILED")
print("=" * 50 + "\n")
sys.exit(0 if FAIL == 0 else 1)
