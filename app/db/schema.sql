CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',
    owner_id INTEGER,
    settings TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug
    ON organizations(slug);

CREATE TABLE IF NOT EXISTS org_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_org_invites_email
    ON org_invites(email);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    native_language TEXT DEFAULT 'Polish',
    current_level TEXT DEFAULT 'pending',
    goals TEXT,
    problem_areas TEXT,
    intake_data TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    additional_notes TEXT,
    email TEXT UNIQUE,
    password_hash TEXT,
    total_xp INTEGER DEFAULT 0,
    xp_level INTEGER DEFAULT 1,
    streak INTEGER DEFAULT 0,
    freeze_tokens INTEGER DEFAULT 0,
    last_activity_date TEXT,
    avatar_id TEXT DEFAULT 'default',
    theme_preference TEXT DEFAULT 'light',
    display_title TEXT,
    org_id INTEGER REFERENCES organizations(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);

CREATE TABLE IF NOT EXISTS learner_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    gaps TEXT,
    priorities TEXT,
    profile_summary TEXT,
    recommended_start_level TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    session_number INTEGER DEFAULT 1,
    objective TEXT,
    content TEXT,
    difficulty TEXT,
    status TEXT DEFAULT 'generated',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS lesson_skill_tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id  INTEGER NOT NULL,
    tag_type   TEXT NOT NULL,
    tag_value  TEXT NOT NULL,
    cefr_level TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);

CREATE INDEX IF NOT EXISTS idx_lesson_skill_tags_lesson
    ON lesson_skill_tags(lesson_id);
CREATE INDEX IF NOT EXISTS idx_lesson_skill_tags_value
    ON lesson_skill_tags(tag_type, tag_value);

CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    score REAL,
    notes TEXT,
    areas_improved TEXT,
    areas_struggling TEXT,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    stage TEXT NOT NULL DEFAULT 'placement',
    bracket TEXT,
    responses TEXT,
    ai_analysis TEXT,
    determined_level TEXT,
    confidence_score REAL,
    sub_skill_breakdown TEXT,
    weak_areas TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cefr_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL,
    level           TEXT NOT NULL,
    grammar_level   TEXT,
    vocabulary_level TEXT,
    reading_level   TEXT,
    speaking_level  TEXT,
    writing_level   TEXT,
    confidence      REAL,
    source          TEXT DEFAULT 'assessment',
    assessment_id   INTEGER,
    recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id)
);

CREATE INDEX IF NOT EXISTS idx_cefr_history_student
    ON cefr_history(student_id);

CREATE TABLE IF NOT EXISTS learning_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    title TEXT,
    target_level TEXT,
    current_level TEXT,
    overview TEXT,
    weeks TEXT,
    milestones TEXT,
    week_progress TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'progress',
    xp_reward INTEGER DEFAULT 0,
    icon TEXT,
    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS vocabulary_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    translation TEXT NOT NULL,
    example TEXT,
    ease_factor REAL DEFAULT 2.5,
    interval_days INTEGER DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    review_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS learning_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    point_type TEXT NOT NULL,
    content TEXT NOT NULL,
    polish_explanation TEXT,
    example_sentence TEXT,
    importance_weight INTEGER DEFAULT 3,
    ease_factor REAL DEFAULT 2.5,
    interval_days INTEGER DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    times_reviewed INTEGER DEFAULT 0,
    last_recall_score REAL,
    next_review_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);

CREATE TABLE IF NOT EXISTS recall_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    questions TEXT,
    answers TEXT,
    overall_score REAL,
    evaluations TEXT,
    weak_areas TEXT,
    status TEXT DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS daily_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    challenge_type TEXT NOT NULL,
    title TEXT NOT NULL,
    title_pl TEXT,
    description TEXT,
    target INTEGER DEFAULT 1,
    progress INTEGER DEFAULT 0,
    reward_xp INTEGER DEFAULT 30,
    completed INTEGER DEFAULT 0,
    claimed INTEGER DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS xp_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    source TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    game_type TEXT NOT NULL,
    score INTEGER NOT NULL,
    xp_earned INTEGER DEFAULT 0,
    data TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    teacher_id INTEGER,
    scheduled_at TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 60,
    status TEXT NOT NULL DEFAULT 'requested',
    notes TEXT,
    teacher_notes TEXT,
    homework TEXT,
    session_summary TEXT,
    lesson_id INTEGER,
    attended INTEGER DEFAULT 0,
    is_group INTEGER DEFAULT 0,
    max_students INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (teacher_id) REFERENCES users(id),
    FOREIGN KEY (lesson_id) REFERENCES lessons(id)
);

CREATE TABLE IF NOT EXISTS session_skill_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL,
    student_id   INTEGER NOT NULL,
    teacher_id   INTEGER NOT NULL,
    skill        TEXT NOT NULL,
    score        REAL,
    cefr_level   TEXT,
    notes        TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (teacher_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_skill_obs_session
    ON session_skill_observations(session_id);
CREATE INDEX IF NOT EXISTS idx_skill_obs_student
    ON session_skill_observations(student_id);

CREATE TABLE IF NOT EXISTS session_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    attended INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_students_unique
    ON session_students(session_id, student_id);
CREATE INDEX IF NOT EXISTS idx_session_students_student
    ON session_students(student_id);

CREATE TABLE IF NOT EXISTS teacher_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    recurrence_rule TEXT,
    is_available INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS teacher_weekly_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    day_of_week TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS teacher_availability_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    is_available INTEGER NOT NULL DEFAULT 1,
    custom_windows TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id),
    UNIQUE(teacher_id, date)
);

CREATE INDEX IF NOT EXISTS idx_weekly_windows_teacher
    ON teacher_weekly_windows(teacher_id);
CREATE INDEX IF NOT EXISTS idx_overrides_teacher_date
    ON teacher_availability_overrides(teacher_id, date);

CREATE TABLE IF NOT EXISTS teacher_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ══════════════════════════════════════════════════════════════════════════════
-- LEARNING LOOP TABLES
-- These tables support the closed learning feedback loop:
-- intake → learning plan → lesson → quiz → results → updated plan → next lesson
-- ══════════════════════════════════════════════════════════════════════════════

-- Versioned learning plans for each student
CREATE TABLE IF NOT EXISTS learning_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    plan_json TEXT NOT NULL,
    summary TEXT,
    source_intake_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (source_intake_id) REFERENCES assessments(id)
);

-- Lesson artifacts generated during sessions
CREATE TABLE IF NOT EXISTS lesson_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id INTEGER NOT NULL,
    teacher_id INTEGER,
    lesson_json TEXT NOT NULL,
    topics_json TEXT,
    difficulty TEXT,
    prompt_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (teacher_id) REFERENCES users(id)
);

-- Quizzes generated from lesson artifacts
CREATE TABLE IF NOT EXISTS next_quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id INTEGER NOT NULL,
    quiz_json TEXT NOT NULL,
    derived_from_lesson_artifact_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (derived_from_lesson_artifact_id) REFERENCES lesson_artifacts(id)
);

-- Quiz attempts by students
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    session_id INTEGER,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP,
    score REAL,
    results_json TEXT,
    FOREIGN KEY (quiz_id) REFERENCES next_quizzes(id),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Individual question responses within a quiz attempt
CREATE TABLE IF NOT EXISTS quiz_attempt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0,
    student_answer TEXT,
    expected_answer TEXT,
    skill_tag TEXT,
    time_spent INTEGER,
    FOREIGN KEY (attempt_id) REFERENCES quiz_attempts(id)
);

-- Writing submissions and AI evaluations
CREATE TABLE IF NOT EXISTS writing_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    prompt_topic TEXT,
    submitted_text TEXT NOT NULL,
    evaluation_json TEXT,
    cefr_level TEXT,
    overall_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_writing_submissions_student
    ON writing_submissions(student_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- AI INTELLIGENCE CORE TABLES
-- ══════════════════════════════════════════════════════════════════════════════

-- Living Learning DNA profile (recalculated after every interaction)
CREATE TABLE IF NOT EXISTS learning_dna (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    dna_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    trigger_event TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_learning_dna_student
    ON learning_dna(student_id);

-- Per-student Polish → English L1 interference tracking
CREATE TABLE IF NOT EXISTS l1_interference_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    pattern_category TEXT NOT NULL,
    pattern_detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'exhibited',
    occurrences INTEGER DEFAULT 1,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    overcome_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_l1_tracking_student
    ON l1_interference_tracking(student_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_l1_tracking_unique
    ON l1_interference_tracking(student_id, pattern_category, pattern_detail);

-- Pre-class warm-up packages
CREATE TABLE IF NOT EXISTS pre_class_warmups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    warmup_json TEXT NOT NULL,
    results_json TEXT,
    confidence_rating INTEGER,
    status TEXT NOT NULL DEFAULT 'generated',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_warmups_session
    ON pre_class_warmups(session_id);
CREATE INDEX IF NOT EXISTS idx_warmups_student
    ON pre_class_warmups(student_id);
