CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    native_language TEXT DEFAULT 'Polish',
    current_level TEXT DEFAULT 'pending',
    goals TEXT,
    problem_areas TEXT,
    intake_data TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    filler TEXT DEFAULT 'student',
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learner_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    gaps TEXT,
    priorities TEXT,
    profile_summary TEXT,
    recommended_start_level TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    score REAL,
    notes TEXT,
    areas_improved TEXT,
    areas_struggling TEXT,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id),
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
    FOREIGN KEY (student_id) REFERENCES students(id)
);

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
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    FOREIGN KEY (student_id) REFERENCES students(id),
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
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS xp_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    source TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    game_type TEXT NOT NULL,
    score INTEGER NOT NULL,
    xp_earned INTEGER DEFAULT 0,
    data TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id)
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (teacher_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS teacher_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    recurrence_rule TEXT,
    is_available INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS teacher_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
