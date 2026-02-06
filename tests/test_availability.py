"""Tests for teacher availability endpoints."""

import pytest
from datetime import datetime, timedelta


class TestAvailabilityValidation:
    """Unit tests for validation helpers."""

    def test_time_format_validation(self):
        """Test HH:MM format validation."""
        from app.routes.availability import _validate_time_format

        # Valid times
        assert _validate_time_format("00:00") is True
        assert _validate_time_format("09:30") is True
        assert _validate_time_format("23:59") is True

        # Invalid times
        assert _validate_time_format("24:00") is False
        assert _validate_time_format("9:30") is True  # single digit hour ok
        assert _validate_time_format("invalid") is False
        assert _validate_time_format("") is False
        assert _validate_time_format("12:60") is False

    def test_date_format_validation(self):
        """Test YYYY-MM-DD format validation."""
        from app.routes.availability import _validate_date_format

        # Valid dates
        assert _validate_date_format("2026-02-10") is True
        assert _validate_date_format("2025-12-31") is True

        # Invalid dates
        assert _validate_date_format("02-10-2026") is False
        assert _validate_date_format("2026/02/10") is False
        assert _validate_date_format("invalid") is False

    def test_time_to_minutes(self):
        """Test time conversion to minutes."""
        from app.routes.availability import _time_to_minutes

        assert _time_to_minutes("00:00") == 0
        assert _time_to_minutes("01:00") == 60
        assert _time_to_minutes("09:30") == 570
        assert _time_to_minutes("23:59") == 1439


class TestDayMapping:
    """Test day of week constants."""

    def test_days_of_week(self):
        from app.routes.availability import DAYS_OF_WEEK, DAY_TO_INDEX

        assert len(DAYS_OF_WEEK) == 7
        assert DAYS_OF_WEEK[0] == "monday"
        assert DAYS_OF_WEEK[6] == "sunday"
        assert DAY_TO_INDEX["monday"] == 0
        assert DAY_TO_INDEX["friday"] == 4


# Integration tests require a running server and test database
# Run with: pytest tests/test_availability.py -v

@pytest.fixture
def sample_weekly_schedule():
    """Sample weekly schedule for testing."""
    return {
        "windows": [
            {"day_of_week": "monday", "start_time": "09:00", "end_time": "12:00"},
            {"day_of_week": "monday", "start_time": "14:00", "end_time": "17:00"},
            {"day_of_week": "wednesday", "start_time": "10:00", "end_time": "15:00"},
            {"day_of_week": "friday", "start_time": "09:00", "end_time": "11:00"},
        ]
    }


@pytest.fixture
def sample_override_unavailable():
    """Sample override marking a date as unavailable."""
    return {
        "date": "2026-02-14",
        "is_available": False,
        "reason": "Valentine's Day holiday"
    }


@pytest.fixture
def sample_override_custom():
    """Sample override with custom hours."""
    return {
        "date": "2026-02-16",
        "is_available": True,
        "windows": [
            {"start_time": "08:00", "end_time": "10:00"}
        ],
        "reason": "Early shift only"
    }


# Manual integration test placeholder
# These would require httpx/TestClient with actual auth tokens
class TestIntegrationPlaceholder:
    """
    Integration tests require:
    1. Test database setup
    2. Creating test teacher/student users
    3. Generating valid JWT tokens

    See manual test checklist in test file comments.
    """

    def test_placeholder(self):
        """Placeholder to ensure test file runs."""
        assert True


"""
=============================================================================
MANUAL TEST CHECKLIST
=============================================================================

Prerequisites:
1. Server running: cd intake_eval_school && docker-compose up
2. Create a teacher account (via invite system)
3. Create a student account
4. Get auth tokens for both

STEP 1: Get teacher token
-------------------------
# First create a teacher invite (requires ADMIN_SECRET)
curl -X POST http://localhost:8000/api/admin/teacher-invites \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: docker-dev-admin-secret-16ch" \
  -d '{"email": "teacher@test.com"}'

# Note the token from response, then register:
curl -X POST http://localhost:8000/api/auth/teacher/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Teacher", "email": "teacher@test.com", "password": "TestPass123!", "token": "<INVITE_TOKEN>"}'

# Login as teacher:
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "teacher@test.com", "password": "TestPass123!"}'
# Save the "token" from response as TEACHER_TOKEN

STEP 2: Get student token
-------------------------
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Student", "email": "student@test.com", "password": "TestPass123!"}'

curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "student@test.com", "password": "TestPass123!"}'
# Save the "token" from response as STUDENT_TOKEN

STEP 3: Teacher sets weekly availability
----------------------------------------
curl -X POST http://localhost:8000/api/teacher/availability \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TEACHER_TOKEN>" \
  -d '{
    "windows": [
      {"day_of_week": "monday", "start_time": "09:00", "end_time": "12:00"},
      {"day_of_week": "monday", "start_time": "14:00", "end_time": "17:00"},
      {"day_of_week": "wednesday", "start_time": "10:00", "end_time": "15:00"},
      {"day_of_week": "friday", "start_time": "09:00", "end_time": "11:00"}
    ]
  }'
# Expected: {"message": "Weekly schedule updated", "windows_count": 4}

STEP 4: Teacher views own availability
--------------------------------------
curl http://localhost:8000/api/teacher/availability \
  -H "Authorization: Bearer <TEACHER_TOKEN>"
# Expected: {"windows": [...], "overrides": []}

STEP 5: Teacher adds date override (unavailable)
------------------------------------------------
curl -X POST http://localhost:8000/api/teacher/availability/overrides \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TEACHER_TOKEN>" \
  -d '{
    "date": "2026-02-14",
    "is_available": false,
    "reason": "Holiday"
  }'
# Expected: {"message": "Override saved", "date": "2026-02-14", "is_available": false}

STEP 6: Teacher adds date override (custom hours)
-------------------------------------------------
curl -X POST http://localhost:8000/api/teacher/availability/overrides \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TEACHER_TOKEN>" \
  -d '{
    "date": "2026-02-16",
    "is_available": true,
    "windows": [{"start_time": "08:00", "end_time": "10:00"}],
    "reason": "Early shift"
  }'
# Expected: {"message": "Override saved", "date": "2026-02-16", "is_available": true}

STEP 7: Student lists teachers
------------------------------
curl http://localhost:8000/api/students/teachers \
  -H "Authorization: Bearer <STUDENT_TOKEN>"
# Expected: {"teachers": [{"id": <TEACHER_ID>, "name": "Test Teacher"}]}

STEP 8: Student views teacher availability (1 week)
---------------------------------------------------
# Use teacher_id from step 7
curl "http://localhost:8000/api/students/teacher-availability?teacher_id=<TEACHER_ID>&from=2026-02-09&to=2026-02-15" \
  -H "Authorization: Bearer <STUDENT_TOKEN>"
# Expected: {"teacher_id": ..., "teacher_name": "Test Teacher", "days": [
#   {"date": "2026-02-09", "windows": [...], "available": true/false},
#   ...
# ]}

STEP 9: Verify override is reflected
------------------------------------
# In step 8 response, check:
# - 2026-02-14 should have "available": false (holiday override)
# - Mondays should have windows from weekly schedule

STEP 10: Delete override
------------------------
curl -X DELETE "http://localhost:8000/api/teacher/availability/overrides?date=2026-02-14" \
  -H "Authorization: Bearer <TEACHER_TOKEN>"
# Expected: {"message": "Override removed", "date": "2026-02-14"}

STEP 11: Verify deletion
------------------------
curl http://localhost:8000/api/teacher/availability \
  -H "Authorization: Bearer <TEACHER_TOKEN>"
# Expected: overrides should no longer contain 2026-02-14

STEP 12: Error cases
--------------------
# Invalid date format:
curl -X POST http://localhost:8000/api/teacher/availability/overrides \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TEACHER_TOKEN>" \
  -d '{"date": "02-14-2026", "is_available": false}'
# Expected: 422 error

# Student cannot set availability:
curl -X POST http://localhost:8000/api/teacher/availability \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <STUDENT_TOKEN>" \
  -d '{"windows": []}'
# Expected: 403 "Teachers only"

# Teacher cannot use student endpoint:
curl "http://localhost:8000/api/students/teacher-availability?teacher_id=1&from=2026-02-01&to=2026-02-07" \
  -H "Authorization: Bearer <TEACHER_TOKEN>"
# Expected: 403 "Students only"

# Invalid teacher_id:
curl "http://localhost:8000/api/students/teacher-availability?teacher_id=99999&from=2026-02-01&to=2026-02-07" \
  -H "Authorization: Bearer <STUDENT_TOKEN>"
# Expected: 404 "Teacher not found"

# Date range too large:
curl "http://localhost:8000/api/students/teacher-availability?teacher_id=1&from=2026-01-01&to=2026-12-31" \
  -H "Authorization: Bearer <STUDENT_TOKEN>"
# Expected: 400 "Date range cannot exceed 90 days"

=============================================================================
POWERSHELL EQUIVALENTS (Windows)
=============================================================================

# Set availability (PowerShell):
$headers = @{
    "Content-Type" = "application/json"
    "Authorization" = "Bearer <TEACHER_TOKEN>"
}
$body = @{
    windows = @(
        @{day_of_week="monday"; start_time="09:00"; end_time="12:00"}
        @{day_of_week="wednesday"; start_time="10:00"; end_time="15:00"}
    )
} | ConvertTo-Json -Depth 3
Invoke-RestMethod -Uri "http://localhost:8000/api/teacher/availability" -Method POST -Headers $headers -Body $body

# Get availability (PowerShell):
$headers = @{"Authorization" = "Bearer <TEACHER_TOKEN>"}
Invoke-RestMethod -Uri "http://localhost:8000/api/teacher/availability" -Headers $headers

# Student query (PowerShell):
$headers = @{"Authorization" = "Bearer <STUDENT_TOKEN>"}
Invoke-RestMethod -Uri "http://localhost:8000/api/students/teacher-availability?teacher_id=1&from=2026-02-09&to=2026-02-15" -Headers $headers

=============================================================================
"""
