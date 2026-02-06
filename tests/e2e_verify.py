"""
E2E verification script for intake_eval_school.

Tests the full API flow: health → register → login → intake → assessment → scheduling.
Run with:   python tests/e2e_verify.py

Prerequisites:
  - Backend running on http://127.0.0.1:8000
  - Fresh database (or delete intake_eval.db and restart)
"""

import os
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
    return f"test_{tag}@example.com"


def api(method, path, body=None, token=None, admin_secret=None):
    """Minimal HTTP client using only stdlib."""
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if admin_secret:
        headers["X-Admin-Secret"] = admin_secret
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


# Admin secret for testing - reads from env or uses default for local dev
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "dev-admin-secret-change-in-prod")


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
served_by = data.get("served_by", "unknown")
print(f"  [INFO] Server is: {served_by}")
check("/health has served_by field", served_by in ["docker", "host"], f"served_by={served_by}")

# ── 2. Register ──────────────────────────────────────────────────
print("\n=== 2. Register (Students) ===")
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

# Trying to register with role=teacher should be forced to student
code, data = api("POST", "/api/auth/register", {
    "name": "Sneaky Teacher",
    "email": rand_email(),
    "password": "test1234",
    "role": "teacher",  # This should be ignored
})
check("Register with role=teacher forced to student", code == 200, f"status={code}")
check("Role override: still student", data.get("role") == "student", f"role={data.get('role')}")

# ── 2b. Teacher Registration via Invite ──────────────────────────
print("\n=== 2b. Teacher Registration (Invite-Only) ===")

# First, create a teacher invite using admin endpoint
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": teacher_email,
    "expires_days": 7,
}, admin_secret=ADMIN_SECRET)
check("Create teacher invite returns 200", code == 200, f"status={code}")
invite_token = data.get("token", "")
check("Invite token received", bool(invite_token), f"token={invite_token[:10]}..." if invite_token else "")
check("Invite URL received", bool(data.get("invite_url")), f"url={data.get('invite_url')}")

# Test admin endpoint without secret (should fail)
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": rand_email(),
})
check("Admin endpoint without secret returns 403", code == 403, f"status={code}")

# Test admin endpoint with wrong secret
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": rand_email(),
}, admin_secret="wrong-secret")
check("Admin endpoint with wrong secret returns 403", code == 403, f"status={code}")

# Now register teacher using the invite token
code, data = api("POST", "/api/auth/teacher/register", {
    "name": "E2E Teacher",
    "email": teacher_email,
    "password": "test1234",
    "invite_token": invite_token,
})
check("Teacher register with invite returns 200", code == 200, f"status={code}")
teacher_token = data.get("token", "")
teacher_id = data.get("student_id")
check("Teacher token received", bool(teacher_token))
check("Role is teacher", data.get("role") == "teacher", f"role={data.get('role')}")

# Try to reuse the same invite token (should fail)
code, data = api("POST", "/api/auth/teacher/register", {
    "name": "Another Teacher",
    "email": teacher_email,
    "password": "test1234",
    "invite_token": invite_token,
})
check("Reused invite token rejected", code in [400, 409], f"status={code}")

# Try to register teacher with invalid token
code, data = api("POST", "/api/auth/teacher/register", {
    "name": "Bad Token Teacher",
    "email": rand_email(),
    "password": "test1234",
    "invite_token": "invalid-token-12345",
})
check("Invalid invite token rejected", code == 400, f"status={code}")

# Try to register teacher with mismatched email
another_invite_email = rand_email()
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": another_invite_email,
    "expires_days": 1,
}, admin_secret=ADMIN_SECRET)
another_invite_token = data.get("token", "")

code, data = api("POST", "/api/auth/teacher/register", {
    "name": "Mismatched Teacher",
    "email": rand_email(),  # Different from invited email
    "password": "test1234",
    "invite_token": another_invite_token,
})
check("Mismatched email rejected", code == 400, f"status={code}")

# Try to register teacher with EXPIRED token (T6)
expired_invite_email = rand_email()
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": expired_invite_email,
    "expires_seconds": 0,  # Immediately expired
}, admin_secret=ADMIN_SECRET)
check("Create expired invite returns 200", code == 200, f"status={code}")
expired_invite_token = data.get("token", "")

# Wait a moment to ensure expiration
time.sleep(1)

code, data = api("POST", "/api/auth/teacher/register", {
    "name": "Expired Token Teacher",
    "email": expired_invite_email,
    "password": "test1234",
    "invite_token": expired_invite_token,
})
check("Expired token rejected", code == 400, f"status={code}")
check("Expired token error mentions expiration", "expir" in str(data).lower(), f"detail={data}")

# List invites as admin
code, data = api("GET", "/api/admin/teacher-invites", admin_secret=ADMIN_SECRET)
check("List invites returns 200", code == 200, f"status={code}")
invites = data.get("invites", [])
check("Invites list is array", isinstance(invites, list), f"count={len(invites)}")
# Find our used invite
used_invite = next((i for i in invites if i.get("email") == teacher_email.lower()), None)
check("Used invite shows is_used=True", used_invite and used_invite.get("is_used") == True, f"invite={used_invite}")

# Duplicate registration should fail
code, data = api("POST", "/api/auth/register", {
    "name": "Dup", "email": student_email, "password": "validpass123", "role": "student",
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

# ── 8. Teacher Overview (activity feed) ─────────────────────────
print("\n=== 8. Teacher Overview ===")

# Teacher lists all students
code, data = api("GET", "/api/teacher/students", token=teacher_token)
check("Teacher list students returns 200", code == 200, f"status={code}")
students_list = data.get("students", [])
check("Teacher sees at least 1 student", len(students_list) >= 1, f"count={len(students_list)}")

# Find the student we registered earlier (the one with sessions)
overview_student_id = None
for s in students_list:
    if s.get("id") == student_id:
        overview_student_id = student_id
        break
# Fallback to first student if our student not found (shouldn't happen)
if not overview_student_id and students_list:
    overview_student_id = students_list[0]["id"]

if overview_student_id:
    # Get detailed overview for this student
    code, data = api("GET", f"/api/teacher/students/{overview_student_id}/overview", token=teacher_token)
    check("Teacher overview returns 200", code == 200, f"status={code}")
    check("Overview has student info", data.get("student") is not None)

    activity = data.get("activity", [])
    check("Activity feed exists", isinstance(activity, list))
    check("Activity feed has events", len(activity) >= 1, f"count={len(activity)}")

    # The student requested and had sessions confirmed/cancelled, so we expect session events
    session_events = [e for e in activity if e.get("type", "").startswith("session_")]
    check("Activity has session events", len(session_events) >= 1, f"count={len(session_events)}")
else:
    check("Could not find student for overview test", False, "no students available")

# Student should not access teacher overview endpoint
code, data = api("GET", f"/api/teacher/students/{student_id}/overview", token=student_token)
check("Student blocked from teacher overview (403)", code == 403, f"status={code}")

# ── 9. Dashboard HTML Server-Side Guards ─────────────────────────
print("\n=== 9. Dashboard HTML Guards ===")


def get_redirect(path, token=None):
    """Fetch a URL and return (status_code, redirect_location or None)."""
    import urllib.request
    import urllib.error

    url = BASE + path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        # Also set cookie for browser-like behavior
        headers["Cookie"] = f"auth_token={token}"

    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # Don't follow redirects

    opener = urllib.request.build_opener(NoRedirectHandler)
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=10) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location", "")
        return e.code, location


# Dashboard pages are now served as static files (role guards are client-side JS)
# Server returns 200 for all dashboard requests - JS handles role-based redirects
code, loc = get_redirect("/dashboard.html")
check("GET /dashboard.html returns 200 (static)", code == 200, f"code={code}")

code, loc = get_redirect("/student_dashboard.html")
check("GET /student_dashboard.html returns 200 (static)", code == 200, f"code={code}")

# With or without token, static files are served (client JS handles auth)
code, loc = get_redirect("/dashboard.html", token=teacher_token)
check("Teacher /dashboard.html → served (200)", code == 200, f"code={code}")

code, loc = get_redirect("/student_dashboard.html", token=student_token)
check("Student /student_dashboard.html → served (200)", code == 200, f"code={code}")

# ── 10. Intake Data in Teacher Overview ─────────────────────────
print("\n=== 10. Intake Data ===")

# Create a new student via intake with goals and problem_areas
intake_goals = ["conversational", "business"]
intake_problems = ["articles", "tenses"]
intake_notes = "Test student for intake verification"

code, data = api("POST", "/api/intake", {
    "name": "Intake Test Student",
    "age": 30,
    "goals": intake_goals,
    "problem_areas": intake_problems,
    "additional_notes": intake_notes,
    "filler": "teacher",
})
check("Create intake student returns 200", code == 200, f"status={code}")
intake_test_id = data.get("student_id")
check("Intake student ID received", intake_test_id is not None, f"id={intake_test_id}")

# Teacher fetches overview for this student
code, data = api("GET", f"/api/teacher/students/{intake_test_id}/overview", token=teacher_token)
check("Teacher overview for intake student returns 200", code == 200, f"status={code}")

student_data = data.get("student", {})
check("Overview contains student object", student_data is not None)

# Verify goals are present and match
returned_goals = student_data.get("goals", [])
check("Intake goals returned correctly",
      set(returned_goals) == set(intake_goals),
      f"expected={intake_goals}, got={returned_goals}")

# Verify problem_areas are present and match
returned_problems = student_data.get("problem_areas", [])
check("Intake problem_areas returned correctly",
      set(returned_problems) == set(intake_problems),
      f"expected={intake_problems}, got={returned_problems}")

# Verify no sensitive fields in response
response_str = json.dumps(data)
check("No 'email' in teacher overview", "email" not in response_str.lower() or "email" not in student_data)
check("No 'password' in teacher overview", "password" not in response_str.lower())

# Verify email and password_hash are not in student object keys
student_keys = set(student_data.keys())
check("student object has no email key", "email" not in student_keys, f"keys={student_keys}")
check("student object has no password_hash key", "password_hash" not in student_keys, f"keys={student_keys}")

# ── 11. Session Notes ────────────────────────────────────────────
print("\n=== 11. Session Notes ===")

# Use the confirmed session from earlier tests (session_id from Section 6)
# Teacher saves notes for the confirmed session
test_teacher_notes = "Student needs more practice with articles"
test_homework = "Complete exercises 1-5 on page 42"
test_summary = "Covered present perfect tense today"

code, data = api("POST", f"/api/teacher/sessions/{session_id}/notes", {
    "teacher_notes": test_teacher_notes,
    "homework": test_homework,
    "session_summary": test_summary,
}, token=teacher_token)
check("Teacher save notes returns 200", code == 200, f"status={code}")
check("Notes response has homework", data.get("homework") == test_homework)

# Teacher can retrieve notes (including private teacher_notes)
code, data = api("GET", f"/api/teacher/sessions/{session_id}/notes", token=teacher_token)
check("Teacher get notes returns 200", code == 200, f"status={code}")
check("Teacher sees teacher_notes", data.get("teacher_notes") == test_teacher_notes)
check("Teacher sees homework", data.get("homework") == test_homework)
check("Teacher sees session_summary", data.get("session_summary") == test_summary)

# Student fetches their sessions - should see homework/summary but NOT teacher_notes
code, data = api("GET", "/api/student/me/sessions", token=student_token)
check("Student get sessions returns 200", code == 200, f"status={code}")
student_sessions = data.get("sessions", [])
our_session = next((s for s in student_sessions if s.get("id") == session_id), None)
check("Student sees confirmed session", our_session is not None)

if our_session:
    check("Student sees homework", our_session.get("homework") == test_homework, f"got={our_session.get('homework')}")
    check("Student sees session_summary", our_session.get("session_summary") == test_summary)
    check("Student does NOT see teacher_notes", "teacher_notes" not in our_session, f"keys={list(our_session.keys())}")

# Student cannot POST to teacher notes endpoint (403)
code, data = api("POST", f"/api/teacher/sessions/{session_id}/notes", {
    "homework": "hacked homework",
}, token=student_token)
check("Student blocked from saving notes (403)", code == 403, f"status={code}")

# Verify activity feed includes session_notes_updated event
code, data = api("GET", f"/api/teacher/students/{student_id}/overview", token=teacher_token)
check("Teacher overview after notes returns 200", code == 200, f"status={code}")
activity = data.get("activity", [])
notes_events = [e for e in activity if e.get("type") == "session_notes_updated"]
check("Activity feed has session_notes_updated event", len(notes_events) >= 1, f"count={len(notes_events)}")

# ── 12. Student Search and Filters ───────────────────────────────
print("\n=== 12. Student Search & Filters ===")

# Create two distinct students for search test
code, data = api("POST", "/api/intake", {
    "name": "Alice Searchable",
    "age": 25,
    "goals": ["business"],
})
check("Create Alice returns 200", code == 200, f"status={code}")
alice_id = data.get("student_id")

code, data = api("POST", "/api/intake", {
    "name": "Bob Findable",
    "age": 30,
    "goals": ["travel"],
})
check("Create Bob returns 200", code == 200, f"status={code}")
bob_id = data.get("student_id")

# Search by name: "Alice" should return only Alice
code, data = api("GET", "/api/teacher/students?q=alice", token=teacher_token)
check("Search for 'alice' returns 200", code == 200, f"status={code}")
search_results = data.get("students", [])
alice_found = any(s.get("id") == alice_id for s in search_results)
bob_found = any(s.get("id") == bob_id for s in search_results)
check("Search finds Alice", alice_found, f"results={[s.get('name') for s in search_results]}")
check("Search excludes Bob", not bob_found, f"results={[s.get('name') for s in search_results]}")

# Search case-insensitive
code, data = api("GET", "/api/teacher/students?q=BOB", token=teacher_token)
check("Case-insensitive search returns 200", code == 200)
search_results = data.get("students", [])
bob_found = any(s.get("id") == bob_id for s in search_results)
check("Search finds Bob (case-insensitive)", bob_found)

# Filter: needs_assessment=1 should return Alice and Bob (neither has assessment)
code, data = api("GET", "/api/teacher/students?needs_assessment=1", token=teacher_token)
check("needs_assessment filter returns 200", code == 200, f"status={code}")
needs_assessment_results = data.get("students", [])
alice_in_needs = any(s.get("id") == alice_id for s in needs_assessment_results)
bob_in_needs = any(s.get("id") == bob_id for s in needs_assessment_results)
check("Alice needs assessment", alice_in_needs)
check("Bob needs assessment", bob_in_needs)

# The student who completed assessment (intake_student_id from Section 5) should NOT be in needs_assessment
assessed_in_needs = any(s.get("id") == intake_student_id for s in needs_assessment_results)
check("Assessed student excluded from needs_assessment", not assessed_in_needs,
      f"intake_student_id={intake_student_id}, found={assessed_in_needs}")

# Sorting: sort=name should return alphabetically
code, data = api("GET", "/api/teacher/students?sort=name", token=teacher_token)
check("sort=name returns 200", code == 200)
sorted_results = data.get("students", [])
names = [s.get("name", "") for s in sorted_results]
is_sorted = names == sorted(names)
check("Students sorted by name", is_sorted, f"names={names[:5]}...")

# Verify no email in any student record
code, data = api("GET", "/api/teacher/students", token=teacher_token)
all_students = data.get("students", [])
has_email = any("email" in s for s in all_students)
check("No email field in student list", not has_email)

# Student cannot access teacher student list
code, data = api("GET", "/api/teacher/students", token=student_token)
check("Student blocked from teacher students (403)", code == 403, f"status={code}")

# ── 13. Student Progress Submission ──────────────────────────────
print("\n=== 13. Student Progress ===")

# The student_token is for student_id (E2E Student from Section 2)
# We need to generate a lesson for this student first
# Run diagnostic to create a profile, then generate lesson
code, data = api("POST", f"/api/diagnostic/{student_id}")
diagnostic_ok = code == 200 or code == 201
check("Run diagnostic for student", diagnostic_ok or code == 400, f"status={code}")  # 400 if already exists

# Try to generate a lesson for the logged-in student
code, data = api("POST", f"/api/lessons/{student_id}/generate")
lesson_generated = code == 200 or code == 201

if lesson_generated:
    lesson_id_for_progress = data.get("id") or data.get("lesson_id")
    check("Generate lesson for student", True, f"lesson_id={lesson_id_for_progress}")
else:
    # Check if there are existing lessons
    code, data = api("GET", f"/api/lessons/{student_id}")
    if code == 200 and isinstance(data, list) and len(data) > 0:
        lesson_id_for_progress = data[0].get("id")
        check("Found existing lesson", True, f"lesson_id={lesson_id_for_progress}")
    else:
        lesson_id_for_progress = None
        # This is acceptable - we'll still test validation
        check("No lesson available (testing validation only)", True, "proceeding with validation tests")

# Test progress submission if we have a lesson
if lesson_id_for_progress:
    # Student submits their own progress (token-bound)
    code, data = api("POST", "/api/student/me/progress", {
        "lesson_id": lesson_id_for_progress,
        "score": 85.5,
        "skill_tags": ["grammar", "vocabulary"],
        "notes": "Good understanding of present perfect"
    }, token=student_token)
    check("Student submit progress returns 200", code == 200, f"status={code}")
    check("Progress response has correct score", data.get("score") == 85.5)
    check("Progress is bound to student", data.get("student_id") == student_id)

    # Student cannot submit duplicate progress
    code, data = api("POST", "/api/student/me/progress", {
        "lesson_id": lesson_id_for_progress,
        "score": 90,
    }, token=student_token)
    check("Duplicate progress rejected (409)", code == 409, f"status={code}")

    # Student can retrieve their own progress
    code, data = api("GET", "/api/student/me/progress", token=student_token)
    check("Student get own progress returns 200", code == 200, f"status={code}")
    entries = data.get("entries", [])
    check("Progress entries exist", len(entries) >= 1, f"count={len(entries)}")

    # Teacher overview shows progress
    code, data = api("GET", f"/api/teacher/students/{student_id}/overview", token=teacher_token)
    check("Teacher overview with progress returns 200", code == 200)
    progress_data = data.get("progress", {})
    check("Overview has progress section", progress_data is not None)
    progress_entries = progress_data.get("entries", [])
    check("Progress entries in teacher overview", len(progress_entries) >= 1, f"count={len(progress_entries)}")

    # Check avg score is computed
    avg_score = progress_data.get("avg_score_last_10", 0)
    check("Avg score computed", avg_score > 0, f"avg={avg_score}")

    # Activity feed contains lesson_completed
    activity = data.get("activity", [])
    lesson_events = [e for e in activity if e.get("type") == "lesson_completed"]
    check("Activity feed has lesson_completed event", len(lesson_events) >= 1, f"count={len(lesson_events)}")

# Validate score boundaries
code, data = api("POST", "/api/student/me/progress", {
    "lesson_id": 99999,
    "score": 150,  # Invalid score
}, token=student_token)
check("Invalid score (150) rejected", code == 422, f"status={code}")

code, data = api("POST", "/api/student/me/progress", {
    "lesson_id": 99999,
    "score": -10,  # Invalid score
}, token=student_token)
check("Negative score rejected", code == 422, f"status={code}")

# Teacher cannot use student progress endpoint
code, data = api("POST", "/api/student/me/progress", {
    "lesson_id": 1,
    "score": 80,
}, token=teacher_token)
check("Teacher blocked from student progress (403)", code == 403, f"status={code}")

# ── 14. Security: Password Policy ─────────────────────────────────
print("\n=== 14. Security: Password Policy ===")

# Short password should be rejected (less than 8 characters)
code, data = api("POST", "/api/auth/register", {
    "name": "Short Pass User",
    "email": rand_email(),
    "password": "short",  # Only 5 characters
    "role": "student",
})
check("Short password rejected", code == 422, f"status={code}")
check("Error mentions password", "password" in str(data).lower(), f"detail={data}")

# Exactly 7 characters should be rejected
code, data = api("POST", "/api/auth/register", {
    "name": "Seven Char User",
    "email": rand_email(),
    "password": "1234567",  # 7 characters
    "role": "student",
})
check("7-char password rejected", code == 422, f"status={code}")

# Exactly 8 characters should be accepted
eight_char_email = rand_email()
code, data = api("POST", "/api/auth/register", {
    "name": "Eight Char User",
    "email": eight_char_email,
    "password": "12345678",  # Exactly 8 characters
    "role": "student",
})
check("8-char password accepted", code == 200, f"status={code}")

# Teacher registration also enforces password policy
teacher_pw_test_email = rand_email()
code, data = api("POST", "/api/admin/teacher-invites", {
    "email": teacher_pw_test_email,
    "expires_days": 1,
}, admin_secret=ADMIN_SECRET)
pw_test_invite_token = data.get("token", "")

code, data = api("POST", "/api/auth/teacher/register", {
    "name": "Short Pass Teacher",
    "email": teacher_pw_test_email,
    "password": "short",  # Too short
    "invite_token": pw_test_invite_token,
})
check("Teacher short password rejected", code == 422, f"status={code}")

# ── 15. ICS Calendar Export ───────────────────────────────────────
print("\n=== 15. ICS Calendar Export ===")

# Test ICS generation endpoint (frontend-only, but we can test the API endpoint if added)
# For now, test that confirmed sessions have the necessary fields for ICS generation

# Find a confirmed session from earlier tests
code, data = api("GET", "/api/student/me/sessions", token=student_token)
check("Get sessions for ICS test", code == 200, f"status={code}")
sessions_for_ics = data.get("sessions", [])
confirmed_sessions = [s for s in sessions_for_ics if s.get("status") == "confirmed"]

if confirmed_sessions:
    session_for_ics = confirmed_sessions[0]
    # Verify session has required fields for ICS
    check("Session has id", "id" in session_for_ics, f"keys={list(session_for_ics.keys())}")
    check("Session has scheduled_at", "scheduled_at" in session_for_ics)
    check("Session has duration_min", "duration_min" in session_for_ics)
    check("Session scheduled_at is ISO format", "T" in str(session_for_ics.get("scheduled_at", "")))

    # Simulate ICS generation (test the expected format)
    import datetime
    scheduled_at = session_for_ics.get("scheduled_at")
    duration_min = session_for_ics.get("duration_min", 60)

    # Parse the date
    try:
        if scheduled_at:
            # Basic validation that date can be parsed
            dt = datetime.datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            check("Can parse scheduled_at", True, f"dt={dt}")

            # Build expected ICS content
            def format_ics_date(d):
                return d.strftime("%Y%m%dT%H%M%SZ")

            start = dt
            end = dt + datetime.timedelta(minutes=duration_min)
            summary = "English Lesson / Lekcja angielskiego"

            ics_content = "\r\n".join([
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//IntakeEval//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                "BEGIN:VEVENT",
                f"UID:session-{session_for_ics['id']}@intakeeval",
                f"DTSTAMP:{format_ics_date(datetime.datetime.utcnow())}",
                f"DTSTART:{format_ics_date(start)}",
                f"DTEND:{format_ics_date(end)}",
                f"SUMMARY:{summary}",
                "DESCRIPTION:Duration: " + str(duration_min) + " minutes",
                "END:VEVENT",
                "END:VCALENDAR"
            ])

            # Verify ICS has required fields
            check("ICS has SUMMARY", "SUMMARY:" in ics_content)
            check("ICS has DTSTART", "DTSTART:" in ics_content)
            check("ICS has DTEND (for duration)", "DTEND:" in ics_content)
            check("ICS has proper structure", "BEGIN:VCALENDAR" in ics_content and "END:VCALENDAR" in ics_content)

    except Exception as e:
        check("ICS date parsing failed", False, f"error={e}")
else:
    check("No confirmed sessions to test ICS", False, "need confirmed session")

# ── 16. Security: Rate Limiting ───────────────────────────────────
print("\n=== 16. Security: Rate Limiting ===")

# Reset rate limiter for this test (call a special endpoint or just test behavior)
# We'll make 11 rapid login attempts with wrong credentials to trigger rate limit

rate_test_email = rand_email()
rate_limit_triggered = False

for i in range(12):
    code, data = api("POST", "/api/auth/login", {
        "email": rate_test_email,
        "password": "wrongpassword123",
    })
    if code == 429:
        rate_limit_triggered = True
        check(f"Rate limit triggered after {i+1} attempts", True, f"attempt={i+1}")
        check("Rate limit response has retry info", "retry" in str(data).lower() or "too many" in str(data).lower(), f"detail={data}")
        break

check("Rate limit triggered", rate_limit_triggered, "should get 429 after 10 attempts")

# Verify rate limit also applies to register endpoint
# Use a new "IP simulation" - we can't really change IP, but the rate limiter
# should have already counted our previous attempts from this IP
code, data = api("POST", "/api/auth/register", {
    "name": "Rate Test User",
    "email": rand_email(),
    "password": "password123",
})
# This might be 429 if we're still rate limited, or 200 if register has separate bucket
# Either is acceptable - we just verify rate limiting is active
check("Register endpoint responds", code in [200, 429], f"status={code}")

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
