from datetime import datetime, timedelta


def sm2_update(
    ease_factor: float,
    interval_days: int,
    repetitions: int,
    quality: int,
) -> dict:
    """
    SM-2 spaced repetition algorithm.

    quality: 0-5 rating (0-2 = fail/hard, 3 = okay, 4 = good, 5 = perfect)

    Returns dict with updated ease_factor, interval_days, repetitions, next_review.
    """
    if quality < 0:
        quality = 0
    if quality > 5:
        quality = 5

    if quality >= 3:
        # Correct response
        if repetitions == 0:
            interval_days = 1
        elif repetitions == 1:
            interval_days = 6
        else:
            interval_days = round(interval_days * ease_factor)

        repetitions += 1

        ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        if ease_factor < 1.3:
            ease_factor = 1.3
    else:
        # Incorrect response — reset
        repetitions = 0
        interval_days = 1
        # ease_factor stays the same

    next_review = datetime.utcnow() + timedelta(days=interval_days)

    return {
        "ease_factor": round(ease_factor, 2),
        "interval_days": interval_days,
        "repetitions": repetitions,
        "next_review": next_review.isoformat(),
    }
