"""AI Intelligence Core routes.

Endpoints for:
- Student Learning DNA profiles
- Teacher pre-class briefings and post-session prompts
- Pre-class warm-up packages
- L1 interference profiles
- Progress intelligence (level prediction, plateau detection, weekly summaries, peer comparison)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from app.db.database import get_db
from app.routes.auth import get_current_user, require_student_owner, require_role

router = APIRouter(prefix="/api", tags=["intelligence"])


# ── Learning DNA ──────────────────────────────────────────────────────────


@router.get("/students/{student_id}/learning-dna")
async def get_learning_dna(student_id: int, request: Request, db=Depends(get_db)):
    """Get (or compute if stale) the Learning DNA profile for a student."""
    user = await require_student_owner(request, student_id, db)

    from app.services.learning_dna import get_or_compute_dna

    dna = await get_or_compute_dna(student_id, db)
    return {"student_id": student_id, "learning_dna": dna}


@router.post("/students/{student_id}/learning-dna/recompute")
async def recompute_learning_dna(student_id: int, request: Request, db=Depends(get_db)):
    """Force recompute the Learning DNA for a student."""
    user = await require_student_owner(request, student_id, db)

    from app.services.learning_dna import compute_learning_dna

    dna = await compute_learning_dna(student_id, db, trigger_event="manual_recompute")
    return {"student_id": student_id, "learning_dna": dna}


# ── L1 Interference ──────────────────────────────────────────────────────


@router.get("/students/{student_id}/l1-interference")
async def get_l1_interference(student_id: int, request: Request, db=Depends(get_db)):
    """Get the L1 interference profile for a student."""
    user = await require_student_owner(request, student_id, db)

    from app.services.l1_interference import get_student_interference_profile

    profile = await get_student_interference_profile(student_id, db)
    return {"student_id": student_id, "interference_profile": profile}


@router.post("/students/{student_id}/l1-interference/analyze")
async def analyze_text_for_l1(student_id: int, request: Request, db=Depends(get_db)):
    """Analyze a piece of student text for L1 interference patterns."""
    user = await require_student_owner(request, student_id, db)

    body = await request.json()
    text = body.get("text", "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    # Get student level
    cursor = await db.execute(
        "SELECT current_level FROM users WHERE id = ?", (student_id,)
    )
    student_row = await cursor.fetchone()
    student_level = student_row["current_level"] if student_row else "A1"

    from app.services.l1_interference import analyze_text_for_interference, record_interference_pattern

    patterns = await analyze_text_for_interference(text, student_level)

    # Record each detected pattern
    for p in patterns:
        await record_interference_pattern(
            student_id, db, p["category"], p["detail"]
        )

    return {"student_id": student_id, "detected_patterns": patterns}


# ── Teacher Intelligence ──────────────────────────────────────────────────


@router.get("/sessions/{session_id}/teacher-briefing")
async def get_teacher_briefing(session_id: int, request: Request, db=Depends(get_db)):
    """Generate a pre-class teacher briefing for a session."""
    user = await get_current_user(request, db)
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    from app.services.teacher_intelligence import generate_teacher_briefing

    briefing = await generate_teacher_briefing(session_id, db)
    return {"session_id": session_id, "briefing": briefing}


@router.get("/sessions/{session_id}/post-session-prompts")
async def get_post_session_prompts(session_id: int, request: Request, db=Depends(get_db)):
    """Generate post-session observation prompts for the teacher."""
    user = await get_current_user(request, db)
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    from app.services.teacher_intelligence import generate_post_session_prompts

    prompts = await generate_post_session_prompts(session_id, db)
    return {"session_id": session_id, "prompts": prompts}


# ── Pre-Class Warm-ups ───────────────────────────────────────────────────


@router.get("/sessions/{session_id}/warmup")
async def get_warmup(session_id: int, request: Request, db=Depends(get_db)):
    """Get (or generate) the pre-class warmup for a session."""
    user = await get_current_user(request, db)
    student_id = user["id"]

    # Teachers can view warmups for the session's student
    if user["role"] in ("teacher", "admin"):
        cursor = await db.execute(
            "SELECT student_id FROM sessions WHERE id = ?", (session_id,)
        )
        session_row = await cursor.fetchone()
        if not session_row:
            raise HTTPException(status_code=404, detail="Session not found")
        student_id = session_row["student_id"]

    from app.services.pre_class_engine import get_warmup_for_session, generate_warmup

    warmup = await get_warmup_for_session(session_id, student_id, db)
    if not warmup:
        warmup = await generate_warmup(student_id, session_id, db)

    return warmup


@router.post("/sessions/{session_id}/warmup/complete")
async def complete_warmup(session_id: int, request: Request, db=Depends(get_db)):
    """Submit warmup results."""
    user = await get_current_user(request, db)
    body = await request.json()

    results = body.get("results", {})
    confidence = body.get("confidence", 3)

    # Find the warmup
    from app.services.pre_class_engine import get_warmup_for_session, complete_warmup as do_complete

    warmup = await get_warmup_for_session(session_id, user["id"], db)
    if not warmup:
        raise HTTPException(status_code=404, detail="No warmup found for this session")

    warmup_id = warmup.get("warmup_id")
    if not warmup_id:
        raise HTTPException(status_code=404, detail="Warmup ID not found")

    result = await do_complete(warmup_id, db, results, confidence)
    return result


@router.post("/pre-class/generate-pending")
async def generate_pending_warmups(request: Request, db=Depends(get_db)):
    """Generate warmups for all upcoming sessions in the next 24 hours (admin/teacher)."""
    user = await get_current_user(request, db)
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    from app.services.pre_class_engine import generate_pending_warmups as do_generate

    results = await do_generate(db)
    return {"generated": results}


# ── Progress Intelligence ─────────────────────────────────────────────────


@router.get("/students/{student_id}/level-prediction")
async def get_level_prediction(student_id: int, request: Request, db=Depends(get_db)):
    """Predict when the student will reach the next CEFR level."""
    user = await require_student_owner(request, student_id, db)

    from app.services.progress_intelligence import predict_level_progression

    prediction = await predict_level_progression(student_id, db)
    return {"student_id": student_id, "prediction": prediction}


@router.get("/students/{student_id}/plateau-detection")
async def get_plateau_detection(student_id: int, request: Request, db=Depends(get_db)):
    """Detect learning plateaus and suggest interventions."""
    user = await require_student_owner(request, student_id, db)

    from app.services.progress_intelligence import detect_plateau

    plateau = await detect_plateau(student_id, db)
    return {"student_id": student_id, "plateau": plateau}


@router.get("/students/{student_id}/weekly-summary")
async def get_weekly_summary(student_id: int, request: Request, db=Depends(get_db)):
    """Generate a bilingual weekly progress summary."""
    user = await require_student_owner(request, student_id, db)

    from app.services.progress_intelligence import generate_weekly_summary

    summary = await generate_weekly_summary(student_id, db)
    return {"student_id": student_id, "summary": summary}


@router.get("/students/{student_id}/peer-comparison")
async def get_peer_comparison(student_id: int, request: Request, db=Depends(get_db)):
    """Get anonymized comparison against peers at the same CEFR level."""
    user = await require_student_owner(request, student_id, db)

    from app.services.progress_intelligence import get_peer_comparison

    comparison = await get_peer_comparison(student_id, db)
    return {"student_id": student_id, "comparison": comparison}


# ── Combined Progress Insights ────────────────────────────────────────────


@router.get("/students/{student_id}/progress-insights")
async def get_progress_insights(student_id: int, request: Request, db=Depends(get_db)):
    """Get combined progress insights: DNA interpretation, prediction, plateau detection."""
    user = await require_student_owner(request, student_id, db)

    from app.services.learning_dna import get_or_compute_dna
    from app.services.progress_intelligence import predict_level_progression, detect_plateau
    from app.services.l1_interference import get_student_interference_profile

    dna = await get_or_compute_dna(student_id, db)
    prediction = await predict_level_progression(student_id, db)
    plateau = await detect_plateau(student_id, db)
    l1_profile = await get_student_interference_profile(student_id, db)

    return {
        "student_id": student_id,
        "learning_dna": dna,
        "level_prediction": prediction,
        "plateau_detection": plateau,
        "l1_interference": l1_profile,
    }
