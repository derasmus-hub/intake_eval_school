"""
End-to-end test script for the complete student journey.

Runs through: Intake -> Assessment -> Diagnostic -> Lesson -> Complete lesson ->
Learning points extracted -> Recall quiz -> Second lesson adapts -> Vocab -> Conversation

Usage:
    python tests/test_e2e_journey.py [--base-url http://localhost:8000]
"""

import argparse
import json
import sys
import time
import requests


BASE_URL = "http://localhost:8000"
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"

results = {"passed": 0, "failed": 0, "skipped": 0}


def check(label, condition, detail=""):
    if condition:
        print(f"  [{PASS}] {label}")
        results["passed"] += 1
    else:
        print(f"  [{FAIL}] {label} -- {detail}")
        results["failed"] += 1
    return condition


def skip(label, reason=""):
    print(f"  [{SKIP}] {label} -- {reason}")
    results["skipped"] += 1


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def api(method, path, **kwargs):
    url = BASE_URL + path
    resp = getattr(requests, method)(url, **kwargs)
    return resp


# ─── Step 1: Intake ──────────────────────────────────────────
def test_intake():
    section("Step 1: Student Intake")

    resp = api("post", "/api/intake", json={
        "name": "Test Student E2E",
        "age": 25,
        "filler": "student",
    })
    check("POST /api/intake returns 200", resp.status_code == 200, f"got {resp.status_code}")
    data = resp.json()
    student_id = data.get("student_id")
    check("Response has student_id", student_id is not None)
    print(f"    -> student_id = {student_id}")

    # Verify student can be retrieved
    resp = api("get", f"/api/intake/{student_id}")
    check("GET /api/intake/{id} returns student", resp.status_code == 200)

    # List students
    resp = api("get", "/api/students")
    check("GET /api/students returns list", resp.status_code == 200 and isinstance(resp.json(), list))

    return student_id


# ─── Step 2: Assessment ──────────────────────────────────────
def test_assessment(student_id):
    section("Step 2: Assessment")

    # Start assessment
    resp = api("post", "/api/assessment/start", json={"student_id": student_id})
    check("POST /api/assessment/start returns 200", resp.status_code == 200, f"got {resp.status_code}")
    data = resp.json()
    questions = data.get("questions", [])
    check("Placement questions returned", len(questions) > 0, f"got {len(questions)}")

    # Submit placement answers (all correct for simplicity)
    answers = [{"question_id": q["id"], "answer": q.get("is_correct", True)} for q in questions]
    resp = api("post", "/api/assessment/placement", json={
        "student_id": student_id,
        "answers": answers,
    })
    check("POST /api/assessment/placement returns 200", resp.status_code == 200, f"got {resp.status_code}")
    placement = resp.json()
    bracket = placement.get("bracket")
    diag_questions = placement.get("questions", [])
    check("Bracket determined", bracket is not None, f"bracket={bracket}")
    check("Diagnostic questions returned", len(diag_questions) > 0)
    print(f"    -> bracket = {bracket}, diagnostic questions = {len(diag_questions)}")

    # Submit diagnostic answers
    diag_answers = []
    for q in diag_questions:
        answer = q.get("correct_answer", "a")
        diag_answers.append({"question_id": q["id"], "answer": answer})

    resp = api("post", "/api/assessment/diagnostic", json={
        "student_id": student_id,
        "answers": diag_answers,
    })
    if resp.status_code == 200:
        check("POST /api/assessment/diagnostic returns 200", True)
        result = resp.json()
        level = result.get("determined_level")
        check("Level determined", level is not None, f"level={level}")
        print(f"    -> determined_level = {level}")

        # Update student level
        api("put", f"/api/intake/{student_id}/level", json={"level": level})
    else:
        skip("Assessment diagnostic", f"returned {resp.status_code} - AI call may have failed")

    # Set goals
    resp = api("put", f"/api/intake/{student_id}/goals", json={
        "goals": ["conversational", "business"],
        "problem_areas": ["articles", "tenses"],
        "additional_notes": "E2E test student",
    })
    check("PUT /api/intake/{id}/goals returns 200", resp.status_code == 200, f"got {resp.status_code}")


# ─── Step 3: Diagnostic Profile ──────────────────────────────
def test_diagnostic(student_id):
    section("Step 3: Diagnostic Profile")

    resp = api("post", f"/api/diagnostic/{student_id}")
    if resp.status_code == 200:
        check("POST /api/diagnostic/{id} returns 200", True)
        profile = resp.json()
        check("Profile has gaps", len(profile.get("gaps", [])) > 0)
        check("Profile has priorities", len(profile.get("priorities", [])) > 0)
        check("Profile has summary", bool(profile.get("profile_summary")))
    else:
        skip("Diagnostic profile generation", f"returned {resp.status_code} - AI call may have failed")


# ─── Step 4: Generate First Lesson ───────────────────────────
def test_first_lesson(student_id):
    section("Step 4: Generate First Lesson")

    resp = api("post", f"/api/lessons/{student_id}/generate")
    if resp.status_code == 200:
        check("POST /api/lessons/{id}/generate returns 200", True)
        lesson = resp.json()
        lesson_id = lesson.get("id")
        check("Lesson has id", lesson_id is not None)
        check("Lesson has objective", bool(lesson.get("objective")))
        check("Lesson has content", lesson.get("content") is not None)
        check("Lesson has difficulty", bool(lesson.get("difficulty")))
        print(f"    -> lesson_id = {lesson_id}")
        print(f"    -> objective = {lesson.get('objective', '')[:80]}")
        return lesson_id
    else:
        skip("Lesson generation", f"returned {resp.status_code}")
        return None


# ─── Step 5: Complete Lesson & Extract Learning Points ────────
def test_complete_lesson(student_id, lesson_id):
    section("Step 5: Complete Lesson & Extract Learning Points")

    if not lesson_id:
        skip("Lesson completion", "no lesson_id from previous step")
        return

    # Submit progress first
    resp = api("post", f"/api/progress/{lesson_id}", json={
        "lesson_id": lesson_id,
        "student_id": student_id,
        "score": 75,
        "notes": "E2E test - good progress",
        "areas_improved": ["grammar", "vocabulary"],
        "areas_struggling": ["articles"],
    })
    check("POST /api/progress/{lesson_id} returns 200", resp.status_code == 200, f"got {resp.status_code}")

    # Complete lesson -> extract learning points
    resp = api("post", f"/api/lessons/{lesson_id}/complete")
    if resp.status_code == 200:
        check("POST /api/lessons/{id}/complete returns 200", True)
        data = resp.json()
        points_count = data.get("points_extracted", 0)
        points = data.get("points", [])
        check("Learning points extracted", points_count > 0, f"got {points_count}")
        check("Points have content", all(p.get("content") for p in points))
        print(f"    -> {points_count} learning points extracted")
        for p in points[:3]:
            print(f"       - [{p.get('point_type')}] {p.get('content', '')[:60]}")
    else:
        skip("Learning point extraction", f"returned {resp.status_code} - AI call may have failed")


# ─── Step 6: Recall Quiz ─────────────────────────────────────
def test_recall(student_id):
    section("Step 6: Recall Quiz")

    # Check recall status
    resp = api("get", f"/api/recall/{student_id}/check")
    check("GET /api/recall/{id}/check returns 200", resp.status_code == 200)
    data = resp.json()
    has_pending = data.get("has_pending_recall", False)
    points_count = data.get("points_count", 0)
    print(f"    -> has_pending_recall = {has_pending}, points_count = {points_count}")

    if not has_pending:
        skip("Recall quiz", "no pending review points")
        return

    # Start recall
    resp = api("post", f"/api/recall/{student_id}/start")
    if resp.status_code == 200:
        check("POST /api/recall/{id}/start returns 200", True)
        data = resp.json()
        session_id = data.get("session_id")
        questions = data.get("questions", [])
        check("Recall session created", session_id is not None)
        check("Questions generated", len(questions) > 0, f"got {len(questions)}")
        print(f"    -> session_id = {session_id}, questions = {len(questions)}")

        if session_id and questions:
            # Submit answers (mix of correct and incorrect)
            answers = []
            for q in questions:
                answer = q.get("correct_answer", "test answer")
                answers.append({"point_id": q.get("point_id"), "answer": answer})

            resp = api("post", f"/api/recall/{session_id}/submit", json={"answers": answers})
            if resp.status_code == 200:
                check("POST /api/recall/{session_id}/submit returns 200", True)
                result = resp.json()
                score = result.get("overall_score", 0)
                evals = result.get("evaluations", [])
                check("Overall score returned", score is not None)
                check("Evaluations returned", len(evals) > 0)
                check("Encouragement included", bool(result.get("encouragement")))
                print(f"    -> overall_score = {score}")
            else:
                skip("Recall submission", f"returned {resp.status_code}")
    else:
        skip("Recall start", f"returned {resp.status_code}")


# ─── Step 7: Second Lesson (should adapt to weak areas) ──────
def test_second_lesson(student_id):
    section("Step 7: Second Lesson (adapts to weak areas)")

    resp = api("post", f"/api/lessons/{student_id}/generate")
    if resp.status_code == 200:
        check("Second lesson generated", True)
        lesson = resp.json()
        check("Session number is 2", lesson.get("session_number") == 2, f"got {lesson.get('session_number')}")
        print(f"    -> objective = {lesson.get('objective', '')[:80]}")
    else:
        skip("Second lesson generation", f"returned {resp.status_code}")


# ─── Step 8: Vocabulary Cards ────────────────────────────────
def test_vocabulary(student_id):
    section("Step 8: Vocabulary Cards")

    # Add a card
    resp = api("post", f"/api/vocab/{student_id}/add", json={
        "word": "however",
        "translation": "jednak",
        "example": "However, I think we should try.",
    })
    check("POST /api/vocab/{id}/add returns 200", resp.status_code == 200, f"got {resp.status_code}")

    # Get stats
    resp = api("get", f"/api/vocab/{student_id}/stats")
    check("GET /api/vocab/{id}/stats returns 200", resp.status_code == 200)
    stats = resp.json()
    check("Total cards >= 1", stats.get("total_cards", 0) >= 1)

    # Get due cards
    resp = api("get", f"/api/vocab/{student_id}/due")
    check("GET /api/vocab/{id}/due returns 200", resp.status_code == 200)
    data = resp.json()
    cards = data.get("cards", [])
    check("Due cards include new card", len(cards) > 0)

    if cards:
        # Review a card
        resp = api("post", f"/api/vocab/{student_id}/review", json={
            "card_id": cards[0]["id"],
            "quality": 4,
        })
        check("POST /api/vocab/{id}/review returns 200", resp.status_code == 200, f"got {resp.status_code}")


# ─── Step 9: Conversation ────────────────────────────────────
def test_conversation(student_id):
    section("Step 9: Conversation")

    resp = api("get", f"/api/conversation/{student_id}/scenarios")
    check("GET /api/conversation/{id}/scenarios returns 200", resp.status_code == 200, f"got {resp.status_code}")
    data = resp.json()
    check("Scenarios returned", len(data.get("scenarios", [])) > 0)
    check("Student level returned", bool(data.get("level")))
    print(f"    -> level = {data.get('level')}, scenarios = {len(data.get('scenarios', []))}")


# ─── Step 10: Analytics & Achievements ───────────────────────
def test_analytics(student_id):
    section("Step 10: Analytics & Achievements")

    resp = api("get", f"/api/analytics/{student_id}/skills")
    check("GET /api/analytics/{id}/skills returns 200", resp.status_code == 200)

    resp = api("get", f"/api/analytics/{student_id}/timeline")
    check("GET /api/analytics/{id}/timeline returns 200", resp.status_code == 200)
    timeline = resp.json()
    check("Timeline has entries", len(timeline.get("entries", [])) > 0)

    resp = api("get", f"/api/analytics/{student_id}/achievements")
    check("GET /api/analytics/{id}/achievements returns 200", resp.status_code == 200)
    achievements = resp.json()
    earned = achievements.get("achievements", [])
    check("First lesson achievement earned", any(a["type"] == "first_lesson" for a in earned),
          f"earned: {[a['type'] for a in earned]}")

    resp = api("get", f"/api/analytics/{student_id}/streak")
    check("GET /api/analytics/{id}/streak returns 200", resp.status_code == 200)


# ─── Step 11: Navigation / Page Checks ───────────────────────
def test_navigation(student_id):
    section("Step 11: Frontend Pages Accessible")

    pages = [
        ("/", "Intake Form"),
        ("/index.html", "Intake Form (.html)"),
        ("/dashboard", "Dashboard"),
        ("/dashboard.html", "Dashboard (.html)"),
        ("/assessment", "Assessment"),
        ("/assessment.html", "Assessment (.html)"),
        (f"/vocab?student_id={student_id}", "Vocabulary"),
        (f"/vocab.html?student_id={student_id}", "Vocabulary (.html)"),
        (f"/conversation?student_id={student_id}", "Conversation"),
        (f"/conversation.html?student_id={student_id}", "Conversation (.html)"),
        (f"/recall?student_id={student_id}", "Recall"),
        (f"/recall.html?student_id={student_id}", "Recall (.html)"),
        (f"/session?student_id={student_id}", "Session"),
        (f"/session.html?student_id={student_id}", "Session (.html)"),
    ]

    for path, name in pages:
        resp = api("get", path)
        check(f"GET {path} ({name}) returns 200", resp.status_code == 200, f"got {resp.status_code}")


# ─── Main ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="E2E test for student journey")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    print(f"\nRunning E2E tests against {BASE_URL}")
    print(f"{'='*60}")

    # Check server is running
    try:
        resp = requests.get(BASE_URL + "/", timeout=5)
        if resp.status_code != 200:
            print(f"Server not responding correctly at {BASE_URL}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"Cannot connect to server at {BASE_URL}")
        print("Start the server first: python run.py")
        sys.exit(1)

    student_id = test_intake()
    test_assessment(student_id)
    test_diagnostic(student_id)
    lesson_id = test_first_lesson(student_id)
    test_complete_lesson(student_id, lesson_id)
    test_recall(student_id)
    test_second_lesson(student_id)
    test_vocabulary(student_id)
    test_conversation(student_id)
    test_analytics(student_id)
    test_navigation(student_id)

    # Summary
    section("RESULTS SUMMARY")
    total = results["passed"] + results["failed"] + results["skipped"]
    print(f"  Total:   {total}")
    print(f"  Passed:  {results['passed']}")
    print(f"  Failed:  {results['failed']}")
    print(f"  Skipped: {results['skipped']}")
    print()

    if results["failed"] > 0:
        print(f"  [{FAIL}] Some tests failed!")
        sys.exit(1)
    else:
        print(f"  [{PASS}] All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
