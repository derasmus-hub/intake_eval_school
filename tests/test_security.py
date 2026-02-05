"""
Unit tests for security features.
Run with: python tests/test_security.py
"""

import os
import sys
import subprocess

PASS = 0
FAIL = 0


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


print("\n=== Security Unit Tests ===\n")

# ── 1. JWT Secret Required ────────────────────────────────────────
print("=== 1. JWT Secret Validation ===")

# Test: Missing JWT_SECRET should cause startup failure
# We need to run from a temp dir to avoid .env being read
import tempfile
temp_dir = tempfile.mkdtemp()

env_no_secret = os.environ.copy()
env_no_secret.pop("JWT_SECRET", None)
env_no_secret["DATABASE_PATH"] = ":memory:"
# Add project to PYTHONPATH so imports work
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_no_secret["PYTHONPATH"] = project_dir

result = subprocess.run(
    [sys.executable, "-c", "from app.config import settings"],
    cwd=temp_dir,  # Run from temp dir to avoid .env
    env=env_no_secret,
    capture_output=True,
    text=True,
)
check("Missing JWT_SECRET causes exit", result.returncode != 0, f"returncode={result.returncode}")
check("Error message mentions JWT_SECRET", "JWT_SECRET" in result.stderr, f"stderr={result.stderr[:200]}")

# Test: Short JWT_SECRET should cause startup failure
env_short_secret = os.environ.copy()
env_short_secret["JWT_SECRET"] = "tooshort"  # Less than 32 chars
env_short_secret["DATABASE_PATH"] = ":memory:"
env_short_secret["PYTHONPATH"] = project_dir

result = subprocess.run(
    [sys.executable, "-c", "from app.config import settings"],
    cwd=temp_dir,
    env=env_short_secret,
    capture_output=True,
    text=True,
)
check("Short JWT_SECRET causes exit", result.returncode != 0, f"returncode={result.returncode}")
check("Error mentions 32 characters", "32" in result.stderr, f"stderr={result.stderr[:200]}")

# Test: Valid JWT_SECRET allows startup
env_valid_secret = os.environ.copy()
env_valid_secret["JWT_SECRET"] = "this-is-a-valid-jwt-secret-with-32plus-chars"
env_valid_secret["DATABASE_PATH"] = ":memory:"
env_valid_secret["PYTHONPATH"] = project_dir

result = subprocess.run(
    [sys.executable, "-c", "from app.config import settings; print('OK')"],
    cwd=temp_dir,
    env=env_valid_secret,
    capture_output=True,
    text=True,
)
check("Valid JWT_SECRET allows startup", result.returncode == 0 and "OK" in result.stdout, f"returncode={result.returncode}, stdout={result.stdout}")

# ── 2. Password Policy ────────────────────────────────────────────
print("\n=== 2. Password Policy ===")

# Import after ensuring JWT_SECRET is set
os.environ["JWT_SECRET"] = "test-jwt-secret-for-unit-tests-min32chars"
from pydantic import ValidationError
# We need to test the RegisterRequest model directly
# Use subprocess to avoid import issues
test_code = '''
import os
os.environ["JWT_SECRET"] = "test-jwt-secret-for-unit-tests-min32chars"
from app.routes.auth import RegisterRequest
from pydantic import ValidationError

# Test short password
try:
    RegisterRequest(name="Test", email="test@test.com", password="short")
    print("FAIL:short_accepted")
except ValidationError as e:
    print("PASS:short_rejected")

# Test 7 char password
try:
    RegisterRequest(name="Test", email="test@test.com", password="1234567")
    print("FAIL:7char_accepted")
except ValidationError as e:
    print("PASS:7char_rejected")

# Test 8 char password
try:
    RegisterRequest(name="Test", email="test@test.com", password="12345678")
    print("PASS:8char_accepted")
except ValidationError as e:
    print("FAIL:8char_rejected")
'''

result = subprocess.run(
    [sys.executable, "-c", test_code],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    capture_output=True,
    text=True,
)

output = result.stdout
check("Short password rejected by model", "PASS:short_rejected" in output, f"output={output}")
check("7-char password rejected by model", "PASS:7char_rejected" in output, f"output={output}")
check("8-char password accepted by model", "PASS:8char_accepted" in output, f"output={output}")

# ── 3. Rate Limiter Logic ─────────────────────────────────────────
print("\n=== 3. Rate Limiter Logic ===")

rate_limit_test = '''
import os
os.environ["JWT_SECRET"] = "test-jwt-secret-for-unit-tests-min32chars"
from app.middleware.rate_limit import RateLimiter

limiter = RateLimiter(max_attempts=3, window_seconds=60)
test_key = "test_ip_123"

# First 3 attempts should be allowed
for i in range(3):
    if not limiter.is_allowed(test_key):
        print(f"FAIL:blocked_early_{i}")
        exit(1)
print("PASS:first_3_allowed")

# 4th attempt should be blocked
if limiter.is_allowed(test_key):
    print("FAIL:4th_allowed")
else:
    print("PASS:4th_blocked")

# Check remaining is 0
remaining = limiter.get_remaining(test_key)
if remaining == 0:
    print("PASS:remaining_zero")
else:
    print(f"FAIL:remaining_{remaining}")

# Check retry_after is set
retry = limiter.get_retry_after(test_key)
if retry and retry > 0:
    print("PASS:retry_after_set")
else:
    print(f"FAIL:retry_after_{retry}")

# Reset should clear limits
limiter.reset(test_key)
if limiter.is_allowed(test_key):
    print("PASS:reset_works")
else:
    print("FAIL:reset_failed")
'''

result = subprocess.run(
    [sys.executable, "-c", rate_limit_test],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    capture_output=True,
    text=True,
)

output = result.stdout
check("First 3 attempts allowed", "PASS:first_3_allowed" in output, f"output={output}")
check("4th attempt blocked", "PASS:4th_blocked" in output, f"output={output}")
check("Remaining is 0 after limit", "PASS:remaining_zero" in output, f"output={output}")
check("Retry-after is set", "PASS:retry_after_set" in output, f"output={output}")
check("Reset clears limits", "PASS:reset_works" in output, f"output={output}")

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 50)
total = PASS + FAIL
print(f"  TOTAL: {total}  |  PASS: {PASS}  |  FAIL: {FAIL}")
if FAIL == 0:
    print("  ALL SECURITY TESTS PASSED")
else:
    print(f"  {FAIL} SECURITY TEST(S) FAILED")
print("=" * 50 + "\n")
sys.exit(0 if FAIL == 0 else 1)
