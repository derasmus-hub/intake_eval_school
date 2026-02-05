let currentStudentId = null;
let students = [];
let searchDebounceTimer = null;

// Current filter/sort state
let filterState = {
    q: '',
    needs_assessment: false,
    inactive_days: 0,
    sort: ''
};

// ── Skeleton Loading Helpers ───────────────────────────────────────
function renderStudentListSkeleton(count = 3) {
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `
            <div class="skeleton-student-card">
                <div class="skeleton-student-info">
                    <div class="skeleton skeleton-text-long skeleton-text-lg"></div>
                    <div class="skeleton skeleton-text-med skeleton-text"></div>
                </div>
                <div class="skeleton skeleton-level"></div>
            </div>
        `;
    }
    return html;
}

function renderSessionListSkeleton(count = 2) {
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `
            <div class="skeleton-row">
                <div class="skeleton-content">
                    <div class="skeleton skeleton-text-long skeleton-text-lg"></div>
                    <div class="skeleton skeleton-text-med skeleton-text"></div>
                </div>
                <div class="skeleton skeleton-badge"></div>
            </div>
        `;
    }
    return html;
}

// ── ICS Calendar Export ────────────────────────────────────────────
function generateICS(session) {
    const start = new Date(session.scheduled_at);
    const durationMin = session.duration_min || 60;
    const end = new Date(start.getTime() + durationMin * 60 * 1000);

    // Format dates as ICS format: YYYYMMDDTHHMMSSZ
    const formatICSDate = (d) => {
        return d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    };

    const summary = session.student_name
        ? `English Lesson: ${session.student_name}`
        : 'English Lesson / Lekcja angielskiego';
    const description = [
        session.notes ? `Notes: ${session.notes}` : '',
        session.teacher_name ? `Teacher: ${session.teacher_name}` : '',
        session.student_name ? `Student: ${session.student_name}` : '',
        `Duration: ${durationMin} minutes`
    ].filter(Boolean).join('\\n');

    const ics = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//IntakeEval//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        `UID:session-${session.id}@intakeeval`,
        `DTSTAMP:${formatICSDate(new Date())}`,
        `DTSTART:${formatICSDate(start)}`,
        `DTEND:${formatICSDate(end)}`,
        `SUMMARY:${summary}`,
        `DESCRIPTION:${description}`,
        'END:VEVENT',
        'END:VCALENDAR'
    ].join('\r\n');

    return ics;
}

function downloadICS(session) {
    const ics = generateICS(session);
    const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lesson-${session.id}.ics`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Make it available globally for onclick handlers
window.downloadICS = downloadICS;

async function loadStudents() {
    const container = document.getElementById('student-list');
    // Show skeleton loading state
    container.innerHTML = renderStudentListSkeleton(3);

    try {
        // Build query string from filter state
        const params = new URLSearchParams();
        if (filterState.q) params.set('q', filterState.q);
        if (filterState.needs_assessment) params.set('needs_assessment', '1');
        if (filterState.inactive_days > 0) params.set('inactive_days', filterState.inactive_days.toString());
        if (filterState.sort) params.set('sort', filterState.sort);

        const queryStr = params.toString();
        const url = '/api/teacher/students' + (queryStr ? '?' + queryStr : '');

        const resp = await apiFetch(url);
        if (!resp.ok) {
            // Fallback to old endpoint for non-teachers
            const fallbackResp = await apiFetch('/api/students');
            students = await fallbackResp.json();
        } else {
            const data = await resp.json();
            students = data.students || [];
        }
        renderStudentList();

        // Auto-select the logged-in student so they see their data immediately
        var autoId = STATE.getStudentId();
        if (autoId && students.some(function (s) { return s.id === autoId; })) {
            selectStudent(autoId);
        }
    } catch (err) {
        container.innerHTML =
            '<p>Error loading students: ' + err.message + '</p>';
    }
}

function renderStudentFilters() {
    const section = document.getElementById('student-list-section');
    if (!section) return;

    // Check if filters already exist
    if (document.getElementById('student-filters')) return;

    const filtersHtml = `
        <div id="student-filters" class="student-filters">
            <div class="filter-row">
                <input type="text" id="student-search" placeholder="Search by name... / Szukaj po imieniu..." class="filter-search">
                <select id="student-sort" class="filter-select">
                    <option value="">Sort: Next Session</option>
                    <option value="name">Sort: Name</option>
                    <option value="created_at">Sort: Newest</option>
                    <option value="last_assessment_at">Sort: Last Assessed</option>
                </select>
            </div>
            <div class="filter-row filter-checkboxes">
                <label class="filter-checkbox">
                    <input type="checkbox" id="filter-needs-assessment">
                    <span>Needs Assessment / Wymaga oceny</span>
                </label>
                <label class="filter-checkbox">
                    <input type="checkbox" id="filter-inactive">
                    <span>Inactive 14+ days / Nieaktywny 14+ dni</span>
                </label>
            </div>
        </div>
    `;

    // Insert filters after the h2
    const h2 = section.querySelector('h2');
    if (h2) {
        h2.insertAdjacentHTML('afterend', filtersHtml);
        setupFilterListeners();
    }
}

function setupFilterListeners() {
    const searchInput = document.getElementById('student-search');
    const sortSelect = document.getElementById('student-sort');
    const needsAssessmentCb = document.getElementById('filter-needs-assessment');
    const inactiveCb = document.getElementById('filter-inactive');

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {
                filterState.q = searchInput.value.trim();
                loadStudents();
            }, 300);
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            filterState.sort = sortSelect.value;
            loadStudents();
        });
    }

    if (needsAssessmentCb) {
        needsAssessmentCb.addEventListener('change', () => {
            filterState.needs_assessment = needsAssessmentCb.checked;
            loadStudents();
        });
    }

    if (inactiveCb) {
        inactiveCb.addEventListener('change', () => {
            filterState.inactive_days = inactiveCb.checked ? 14 : 0;
            loadStudents();
        });
    }
}

function renderStudentList() {
    const container = document.getElementById('student-list');
    if (students.length === 0) {
        const hasFilters = filterState.q || filterState.needs_assessment || filterState.inactive_days > 0;
        if (hasFilters) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔍</div>
                    <h3>No students match your filters</h3>
                    <p>Brak uczniów pasujących do filtrów</p>
                    <p class="empty-state-hint">Try adjusting your search or filters above.</p>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">👥</div>
                    <h3>No students yet</h3>
                    <p>Brak uczniów</p>
                    <a href="index.html" class="btn btn-primary btn-sm">+ Add First Student / Dodaj ucznia</a>
                    <p class="empty-state-hint">Students will appear here once they complete the intake form.</p>
                </div>
            `;
        }
        return;
    }

    container.innerHTML = students.map(s => {
        // Build status indicators with unified badge classes
        let badges = '';
        if (!s.last_assessment_at) {
            badges += '<span class="session-badge session-badge-requested">Needs Assessment</span>';
        }
        if (s.next_session_at) {
            const sessionDate = new Date(s.next_session_at);
            const dateStr = sessionDate.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
            const statusClass = s.session_status === 'confirmed' ? 'session-badge-confirmed' : 'session-badge-requested';
            badges += `<span class="session-badge ${statusClass}">Session: ${dateStr}</span>`;
        }

        return `
            <div class="student-card" onclick="selectStudent(${s.id})">
                <div class="student-info">
                    <h3>${escapeHtml(s.name)}</h3>
                    <span class="meta">Age: ${s.age || 'N/A'} | Level: ${s.current_level || 'pending'}</span>
                    ${badges ? '<div class="student-badges">' + badges + '</div>' : ''}
                </div>
                <span class="level-badge">${s.current_level || '?'}</span>
            </div>
        `;
    }).join('');
}

async function selectStudent(id) {
    currentStudentId = id;
    STATE.setStudentId(id);
    const student = students.find(s => s.id === id);
    if (!student) return;

    document.getElementById('student-list-section').classList.add('hidden');
    document.getElementById('student-detail').classList.remove('hidden');
    document.getElementById('detail-student-name').textContent = student.name;
    document.getElementById('detail-student-meta').textContent =
        `Level: ${student.current_level} | Age: ${student.age || 'N/A'} | Problems: ${(student.problem_areas || []).join(', ')}`;

    // Set links for session, vocab, conversation, games, and profile pages
    document.getElementById('session-link').href = `session.html?student_id=${id}`;
    document.getElementById('vocab-link').href = `vocab.html?student_id=${id}`;
    document.getElementById('conversation-link').href = `conversation.html?student_id=${id}`;
    document.getElementById('games-link').href = `games.html?student_id=${id}`;
    document.getElementById('profile-link').href = `profile.html?student_id=${id}`;

    // Record activity for streak tracking
    apiFetch(`/api/gamification/${id}/activity`, {method: 'POST'}).then(r => r.json()).then(data => {
        if (data.new_achievements && data.new_achievements.length > 0 && typeof CELEBRATIONS !== 'undefined') {
            data.new_achievements.forEach((ach, i) => {
                setTimeout(() => CELEBRATIONS.showAchievement(ach), i * 1200);
            });
        }
    }).catch(() => {});

    switchTab('overview');
    loadOverview();
    loadProfile();
    loadLessons();
    loadProgress();
}

async function loadOverview() {
    const intakeEl = document.getElementById('overview-intake-content');
    const assessmentEl = document.getElementById('overview-assessment-content');
    const progressEl = document.getElementById('overview-progress-content');
    const activityEl = document.getElementById('overview-activity-content');

    if (!intakeEl || !assessmentEl || !activityEl) return; // elements not present

    intakeEl.innerHTML = '<p class="meta">Loading...</p>';
    assessmentEl.innerHTML = '<p class="meta">Loading...</p>';
    if (progressEl) progressEl.innerHTML = '<p class="meta">Loading...</p>';
    activityEl.innerHTML = '<p class="meta">Loading...</p>';

    try {
        const resp = await apiFetch(`/api/teacher/students/${currentStudentId}/overview`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            intakeEl.innerHTML = `<p class="meta">Error: ${err.detail || 'Could not load overview'}</p>`;
            assessmentEl.innerHTML = '<p class="meta">--</p>';
            if (progressEl) progressEl.innerHTML = '<p class="meta">--</p>';
            activityEl.innerHTML = '<p class="meta">--</p>';
            return;
        }

        const data = await resp.json();
        renderIntakeSummary(data.student, intakeEl);
        renderAssessmentSummary(data.latest_assessment, assessmentEl);
        if (progressEl) renderProgressSummary(data.progress, progressEl);
        renderActivityFeed(data.activity, activityEl);
    } catch (err) {
        intakeEl.innerHTML = `<p class="meta">Error: ${err.message}</p>`;
    }
}

function renderIntakeSummary(student, container) {
    if (!student) {
        container.innerHTML = '<p class="meta">No student data.</p>';
        return;
    }

    const goals = student.goals || [];
    const problemAreas = student.problem_areas || [];
    const notes = student.additional_notes;

    let html = '<div class="intake-summary">';

    // Goals
    html += '<div class="intake-field"><strong>Goals / Cele:</strong> ';
    if (goals.length > 0) {
        html += '<div class="chip-list">' + goals.map(g => `<span class="chip chip-goal">${escapeHtml(g)}</span>`).join(' ') + '</div>';
    } else {
        html += '<span class="meta">Not provided yet / Nie podano</span>';
    }
    html += '</div>';

    // Problem Areas
    html += '<div class="intake-field" style="margin-top:0.5rem;"><strong>Problem Areas / Trudności:</strong> ';
    if (problemAreas.length > 0) {
        html += '<div class="chip-list">' + problemAreas.map(p => `<span class="chip chip-problem">${escapeHtml(p)}</span>`).join(' ') + '</div>';
    } else {
        html += '<span class="meta">Not provided yet / Nie podano</span>';
    }
    html += '</div>';

    // Additional notes
    if (notes) {
        html += `<div class="intake-field" style="margin-top:0.5rem;"><strong>Notes / Uwagi:</strong><p style="margin:0.25rem 0 0 0;color:#555;">${escapeHtml(notes)}</p></div>`;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderAssessmentSummary(assessment, container) {
    if (!assessment) {
        container.innerHTML = '<p class="meta">No assessment completed yet. / Brak ukończonej oceny.</p>';
        return;
    }

    const level = assessment.determined_level || '--';
    const confidence = assessment.confidence_score ? Math.round(assessment.confidence_score * 100) + '%' : '--';
    const weakAreas = assessment.weak_areas || [];

    let html = `<p><strong>Level:</strong> ${escapeHtml(level)} <span class="meta">(Confidence: ${confidence})</span></p>`;

    if (weakAreas.length > 0) {
        html += '<p style="margin-top:0.5rem;"><strong>Weak Areas:</strong></p>';
        html += '<div class="chip-list">' + weakAreas.map(w => `<span class="chip chip-weak">${escapeHtml(w)}</span>`).join(' ') + '</div>';
    }

    container.innerHTML = html;
}

function renderActivityFeed(activity, container) {
    if (!activity || activity.length === 0) {
        container.innerHTML = '<p class="meta">No recent activity. / Brak ostatniej aktywności.</p>';
        return;
    }

    const html = activity.slice(0, 10).map(ev => {
        const type = ev.type || 'event';
        const detail = ev.detail || '';
        const at = ev.at ? new Date(ev.at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

        let icon = '📌';
        if (type.includes('session')) icon = '📅';
        else if (type.includes('assessment')) icon = '📝';
        else if (type.includes('lesson')) icon = '📚';

        return `<div class="activity-item"><span class="activity-icon">${icon}</span><span class="activity-detail">${escapeHtml(detail)}</span><span class="activity-time meta">${at}</span></div>`;
    }).join('');

    container.innerHTML = html;
}

function renderProgressSummary(progress, container) {
    if (!progress || !progress.entries || progress.entries.length === 0) {
        container.innerHTML = '<p class="meta">No lessons completed yet. / Brak ukończonych lekcji.</p>';
        return;
    }

    const entries = progress.entries;
    const avgScore = progress.avg_score_last_10 || 0;
    const lastActivity = progress.last_progress_at
        ? new Date(progress.last_progress_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
        : 'N/A';

    // Stats row
    let html = `
        <div class="progress-stats">
            <div class="stat-box">
                <span class="stat-value">${avgScore}%</span>
                <span class="stat-label">Avg Score (Last 10)</span>
            </div>
            <div class="stat-box">
                <span class="stat-value">${entries.length}</span>
                <span class="stat-label">Lessons Completed</span>
            </div>
            <div class="stat-box">
                <span class="stat-value">${lastActivity}</span>
                <span class="stat-label">Last Activity</span>
            </div>
        </div>
    `;

    // Last 10 lessons list
    html += '<div class="progress-list" style="margin-top:0.75rem;">';
    html += '<strong>Last 10 Lessons:</strong>';
    html += '<div style="margin-top:0.5rem;">';
    entries.forEach(e => {
        const date = e.completed_at ? new Date(e.completed_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '';
        const scoreClass = e.score >= 80 ? 'score-high' : e.score >= 60 ? 'score-mid' : 'score-low';
        const title = e.lesson_title ? escapeHtml(e.lesson_title) : `Lesson #${e.lesson_id}`;
        html += `
            <div class="progress-entry">
                <span class="progress-title">${title}</span>
                <span class="progress-score ${scoreClass}">${Math.round(e.score)}%</span>
                <span class="progress-date meta">${date}</span>
            </div>
        `;
    });
    html += '</div></div>';

    container.innerHTML = html;
}

function showStudentList() {
    currentStudentId = null;
    document.getElementById('student-list-section').classList.remove('hidden');
    document.getElementById('student-detail').classList.add('hidden');
}

function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));

    document.querySelectorAll('.tab').forEach(t => {
        if (t.textContent.toLowerCase().includes(name)) t.classList.add('active');
    });
    document.getElementById('tab-' + name).classList.add('active');

    if (name === 'analytics' && typeof loadAnalytics === 'function') {
        loadAnalytics();
    }
}

async function loadProfile() {
    const container = document.getElementById('profile-content');
    try {
        const resp = await apiFetch(`/api/diagnostic/${currentStudentId}`);
        if (resp.status === 404) {
            container.innerHTML = `
                <p>No diagnostic profile yet. / Brak profilu diagnostycznego.</p>
                <button onclick="runDiagnosticFromDashboard()" class="btn btn-secondary btn-sm">
                    Run Diagnostic / Uruchom diagnostykę
                </button>`;
            return;
        }
        const profile = await resp.json();
        renderProfile(profile);
    } catch (err) {
        container.innerHTML = '<p>Error loading profile.</p>';
    }
}

function renderProfile(profile) {
    const container = document.getElementById('profile-content');
    const gaps = profile.gaps || [];
    const priorities = profile.priorities || [];

    container.innerHTML = `
        <h3>Summary / Podsumowanie</h3>
        <p>${escapeHtml(profile.profile_summary || 'No summary')}</p>
        <p><strong>Recommended Level:</strong> ${profile.recommended_start_level || 'N/A'}</p>

        <h3>Priority Areas / Obszary priorytetowe</h3>
        <ul class="priority-list">
            ${priorities.map(p => `<li>${escapeHtml(p)}</li>`).join('')}
        </ul>

        <h3>Identified Gaps / Zidentyfikowane luki</h3>
        <ul class="gap-list">
            ${gaps.map(g => `
                <li>
                    <strong>${escapeHtml(g.area || '')}</strong> (${g.severity || 'N/A'})
                    <br>${escapeHtml(g.description || '')}
                    ${g.polish_context ? '<br><em>' + escapeHtml(g.polish_context) + '</em>' : ''}
                </li>
            `).join('')}
        </ul>

        <button onclick="runDiagnosticFromDashboard()" class="btn btn-sm" style="margin-top:1rem;">
            Re-run Diagnostic / Uruchom ponownie
        </button>
    `;
}

async function runDiagnosticFromDashboard() {
    const container = document.getElementById('profile-content');
    container.innerHTML = '<div class="loading">Running diagnostic analysis...</div>';

    try {
        const resp = await apiFetch(`/api/diagnostic/${currentStudentId}`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            container.innerHTML = '<p>Error: ' + (err.detail || 'Unknown error') + '</p>';
            return;
        }
        const profile = await resp.json();
        renderProfile(profile);
    } catch (err) {
        container.innerHTML = '<p>Error: ' + err.message + '</p>';
    }
}

async function loadLessons() {
    const container = document.getElementById('lessons-content');
    try {
        const resp = await apiFetch(`/api/lessons/${currentStudentId}`);
        const lessons = await resp.json();
        if (lessons.length === 0) {
            container.innerHTML = '<p>No lessons generated yet. / Brak wygenerowanych lekcji.</p>';
            return;
        }
        renderLessons(lessons);
    } catch (err) {
        container.innerHTML = '<p>Error loading lessons.</p>';
    }
}

function renderExerciseList(exercises) {
    if (!exercises || exercises.length === 0) return '';
    return `
        <ol class="exercise-list">
            ${exercises.map(ex => `
                <li>
                    <strong>[${ex.type || 'exercise'}]</strong> ${escapeHtml(ex.instruction || '')}
                    ${ex.instruction_pl ? '<br><em>' + escapeHtml(ex.instruction_pl) + '</em>' : ''}
                    <br>${escapeHtml(ex.content || '')}
                    <br><small>Answer: <span style="color:#888">${escapeHtml(ex.answer || '')}</span></small>
                </li>
            `).join('')}
        </ol>
    `;
}

function renderLessons(lessons) {
    const container = document.getElementById('lessons-content');
    container.innerHTML = lessons.map(lesson => {
        const content = lesson.content || {};
        const hasPhases = content.warm_up || content.presentation || content.controlled_practice || content.free_practice || content.wrap_up;

        let body = '';

        if (hasPhases) {
            // New 5-phase structure
            body = renderPhasedLesson(content);
        } else {
            // Legacy flat structure
            body = renderFlatLesson(content);
        }

        return `
            <div class="lesson-card">
                <h4>Lesson ${lesson.session_number}: ${escapeHtml(lesson.objective || content.objective || 'Untitled')}</h4>
                <p><strong>Difficulty:</strong> ${lesson.difficulty || content.difficulty || 'N/A'}
                   | <strong>Status:</strong> ${lesson.status}</p>

                ${body}

                ${lesson.status !== 'completed' ? `
                    <div style="margin-top:0.75rem; padding-top:0.75rem; border-top:1px solid #ddd;">
                        <h4>Submit Progress / Zapisz postępy:</h4>
                        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:end;">
                            <label>Score (0-100):
                                <input type="number" id="score-${lesson.id}" min="0" max="100" value="70" style="width:80px;padding:0.3rem;">
                            </label>
                            <label>Notes:
                                <input type="text" id="notes-${lesson.id}" placeholder="Teacher notes..." style="width:200px;padding:0.3rem;">
                            </label>
                            <button onclick="submitProgress(${lesson.id}, ${lesson.student_id})" class="btn btn-sm btn-secondary">Submit</button>
                        </div>
                    </div>
                ` : '<p style="color:#2ecc71;margin-top:0.5rem;"><strong>Completed</strong></p>'}
            </div>
        `;
    }).join('');
}

function renderPhasedLesson(content) {
    let html = '';

    // Warm-up
    if (content.warm_up) {
        const wu = content.warm_up;
        html += `
            <div class="lesson-phase phase-warmup">
                <div class="phase-header">
                    <span class="phase-badge warmup">1. Warm-Up</span>
                    ${wu.duration_minutes ? `<span class="phase-duration">${wu.duration_minutes} min</span>` : ''}
                </div>
                <p>${escapeHtml(wu.activity || wu.description || '')}</p>
                ${wu.materials && wu.materials.length ? `<p class="phase-meta">Materials: ${wu.materials.map(m => escapeHtml(m)).join(', ')}</p>` : ''}
            </div>
        `;
    }

    // Presentation
    if (content.presentation) {
        const pr = content.presentation;
        html += `
            <div class="lesson-phase phase-presentation">
                <div class="phase-header">
                    <span class="phase-badge presentation">2. Presentation</span>
                    ${pr.topic ? `<span class="phase-topic">${escapeHtml(pr.topic)}</span>` : ''}
                </div>
                <p>${escapeHtml(pr.explanation || '')}</p>
                ${pr.polish_explanation ? `<p class="polish-text"><em>${escapeHtml(pr.polish_explanation)}</em></p>` : ''}
                ${pr.examples && pr.examples.length ? `
                    <div class="phase-examples">
                        <strong>Examples:</strong>
                        <ul>${pr.examples.map(e => `<li>${escapeHtml(e)}</li>`).join('')}</ul>
                    </div>
                ` : ''}
                ${pr.visual_aid ? `<p class="phase-meta">Visual aid: ${escapeHtml(pr.visual_aid)}</p>` : ''}
            </div>
        `;
    }

    // Controlled Practice
    if (content.controlled_practice) {
        const cp = content.controlled_practice;
        html += `
            <div class="lesson-phase phase-controlled">
                <div class="phase-header">
                    <span class="phase-badge controlled">3. Controlled Practice</span>
                </div>
                ${cp.instructions ? `<p>${escapeHtml(cp.instructions)}</p>` : ''}
                ${cp.instructions_pl ? `<p class="polish-text"><em>${escapeHtml(cp.instructions_pl)}</em></p>` : ''}
                ${renderExerciseList(cp.exercises)}
            </div>
        `;
    }

    // Free Practice
    if (content.free_practice) {
        const fp = content.free_practice;
        html += `
            <div class="lesson-phase phase-free">
                <div class="phase-header">
                    <span class="phase-badge free">4. Free Practice</span>
                    ${fp.activity ? `<span class="phase-topic">${escapeHtml(fp.activity)}</span>` : ''}
                </div>
                <p>${escapeHtml(fp.description || '')}</p>
                ${fp.prompts && fp.prompts.length ? `
                    <ul>${fp.prompts.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>
                ` : ''}
                ${fp.success_criteria ? `<p class="phase-meta">Success criteria: ${escapeHtml(fp.success_criteria)}</p>` : ''}
            </div>
        `;
    }

    // Wrap-up
    if (content.wrap_up) {
        const wu = content.wrap_up;
        html += `
            <div class="lesson-phase phase-wrapup">
                <div class="phase-header">
                    <span class="phase-badge wrapup">5. Wrap-Up</span>
                </div>
                <p>${escapeHtml(wu.summary || '')}</p>
                ${wu.win_activity ? `<p><strong>Win activity:</strong> ${escapeHtml(wu.win_activity)}</p>` : ''}
                ${wu.homework ? `<p><strong>Homework:</strong> ${escapeHtml(wu.homework)}</p>` : ''}
                ${wu.next_preview ? `<p class="phase-meta">Coming next: ${escapeHtml(wu.next_preview)}</p>` : ''}
            </div>
        `;
    }

    return html;
}

function renderFlatLesson(content) {
    const exercises = content.exercises || [];
    const prompts = content.conversation_prompts || [];

    let html = '';

    if (content.polish_explanation) {
        html += `
            <h4>Wyjaśnienie po polsku:</h4>
            <p>${escapeHtml(content.polish_explanation)}</p>
        `;
    }

    if (exercises.length > 0) {
        html += `<h4>Exercises / Ćwiczenia:</h4>`;
        html += renderExerciseList(exercises);
    }

    if (prompts.length > 0) {
        html += `
            <h4>Conversation Prompts:</h4>
            <ul>${prompts.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>
        `;
    }

    if (content.win_activity) {
        html += `
            <h4>Win Activity:</h4>
            <p>${escapeHtml(content.win_activity)}</p>
        `;
    }

    return html;
}

async function generateLesson() {
    const container = document.getElementById('lessons-content');
    const prevContent = container.innerHTML;
    container.innerHTML = '<div class="loading">Generating lesson...</div>' + prevContent;

    try {
        const resp = await apiFetch(`/api/lessons/${currentStudentId}/generate`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            alert('Error: ' + (err.detail || 'Unknown error'));
            container.innerHTML = prevContent;
            return;
        }
        loadLessons();
    } catch (err) {
        alert('Error: ' + err.message);
        container.innerHTML = prevContent;
    }
}

async function submitProgress(lessonId, studentId) {
    const score = parseFloat(document.getElementById(`score-${lessonId}`).value);
    const notes = document.getElementById(`notes-${lessonId}`).value;

    if (isNaN(score) || score < 0 || score > 100) {
        alert('Please enter a valid score between 0 and 100.');
        return;
    }

    // Derive areas from score
    const areasImproved = score >= 70 ? ['general'] : [];
    const areasStruggling = score < 50 ? ['general'] : [];

    try {
        const resp = await apiFetch(`/api/progress/${lessonId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lesson_id: lessonId,
                student_id: studentId,
                score: score,
                notes: notes || null,
                areas_improved: areasImproved,
                areas_struggling: areasStruggling,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert('Error: ' + (err.detail || 'Unknown error'));
            return;
        }

        // Auto-extract learning points for recall system
        try {
            await apiFetch(`/api/lessons/${lessonId}/complete`, { method: 'POST' });
        } catch (e) {
            // Non-blocking — learning point extraction is best-effort
            console.warn('Learning point extraction failed:', e);
        }

        loadLessons();
        loadProgress();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function loadProgress() {
    const container = document.getElementById('progress-content');
    try {
        const resp = await apiFetch(`/api/progress/${currentStudentId}`);
        const summary = await resp.json();

        if (summary.total_lessons === 0) {
            container.innerHTML = '<p>No progress data yet. / Brak danych o postępach.</p>';
            return;
        }

        const skillBars = Object.entries(summary.skill_averages || {}).map(([skill, avg]) => `
            <div style="margin-bottom:0.5rem;">
                <div style="display:flex;justify-content:space-between;">
                    <span>${escapeHtml(skill)}</span>
                    <span>${avg}%</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width:${Math.min(100, avg)}%"></div>
                </div>
            </div>
        `).join('');

        container.innerHTML = `
            <div style="display:flex;gap:2rem;margin-bottom:1rem;">
                <div>
                    <p class="meta">Total Lessons</p>
                    <span class="score-display">${summary.total_lessons}</span>
                </div>
                <div>
                    <p class="meta">Average Score</p>
                    <span class="score-display">${summary.average_score}%</span>
                </div>
            </div>

            ${skillBars ? `<h3>Skill Averages / Średnie umiejętności</h3>${skillBars}` : ''}

            <h3>History / Historia</h3>
            ${summary.entries.map(e => `
                <div style="padding:0.5rem;background:#f8f9fa;margin-bottom:0.25rem;border-radius:4px;">
                    Lesson #${e.lesson_id} - Score: <strong>${e.score}%</strong>
                    ${e.notes ? ' - ' + escapeHtml(e.notes) : ''}
                </div>
            `).join('')}
        `;
    } catch (err) {
        container.innerHTML = '<p>Error loading progress.</p>';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

// ── Teacher session management ───────────────────────────────────

async function loadTeacherSessions() {
    var listEl = document.getElementById('teacher-sessions-list');
    if (!listEl) return; // not on teacher dashboard
    // Show skeleton loading
    listEl.innerHTML = renderSessionListSkeleton(2);

    try {
        var resp = await apiFetch('/api/teacher/sessions');
        if (!resp.ok) {
            listEl.innerHTML = '<p class="meta">Could not load sessions.</p>';
            return;
        }
        var data = await resp.json();
        var sessions = data.sessions || [];

        if (sessions.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📅</div>
                    <h3>No pending requests</h3>
                    <p>Brak oczekujących próśb</p>
                    <p class="empty-state-hint">Tell students to request a time via their dashboard.<br>
                       <em>Uczniowie mogą poprosić o sesję przez swój panel.</em></p>
                </div>
            `;
            return;
        }

        listEl.innerHTML = sessions.map(function(s) {
            var dt = new Date(s.scheduled_at);
            var dateStr = dt.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
            var timeStr = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

            // Use unified badge classes
            var badgeClass = s.status === 'confirmed' ? 'session-badge-confirmed'
                : s.status === 'requested' ? 'session-badge-requested'
                : s.status === 'cancelled' ? 'session-badge-cancelled' : '';
            var statusLabel = s.status === 'confirmed' ? 'Confirmed'
                : s.status === 'requested' ? 'Pending'
                : s.status === 'cancelled' ? 'Cancelled'
                : s.status.charAt(0).toUpperCase() + s.status.slice(1);

            var actions = '';
            if (s.status === 'requested') {
                actions = '<div style="display:flex;gap:0.4rem;margin-top:0.5rem;flex-wrap:wrap;">' +
                    '<button class="btn btn-sm btn-primary" onclick="confirmSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;">Confirm / Potwierdź</button>' +
                    '<button class="btn btn-sm" onclick="cancelSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:#e74c3c;color:white;">Cancel / Anuluj</button>' +
                    '</div>';
            } else if (s.status === 'confirmed') {
                // Store session data for ICS download
                var sessionData = JSON.stringify(s).replace(/'/g, "\\'").replace(/"/g, '&quot;');
                actions = '<div style="display:flex;gap:0.4rem;margin-top:0.5rem;flex-wrap:wrap;">' +
                    '<button class="btn btn-sm btn-secondary" onclick="openNotesModal(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;">Log Notes / Zapisz notatki</button>' +
                    '<button class="btn-calendar" onclick=\'downloadICS(' + JSON.stringify(s) + ')\'><span class="btn-calendar-icon"></span> Add to Calendar</button>' +
                    '<button class="btn btn-sm" onclick="cancelSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:#e74c3c;color:white;">Cancel / Anuluj</button>' +
                    '</div>';
            }

            return '<div style="padding:0.75rem;border:1px solid #eee;border-radius:6px;margin-bottom:0.5rem;">' +
                '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
                '<div>' +
                '<strong>' + escapeHtml(s.student_name || 'Student #' + s.student_id) + '</strong>' +
                (s.current_level ? ' <span class="level-badge" style="font-size:0.75rem;padding:0.1rem 0.4rem;">' + escapeHtml(s.current_level) + '</span>' : '') +
                '<br><span class="meta">' + dateStr + ' at ' + timeStr + ' &middot; ' + s.duration_min + ' min</span>' +
                (s.notes ? '<br><span class="meta" style="font-style:italic;">' + escapeHtml(s.notes) + '</span>' : '') +
                '</div>' +
                '<span class="session-badge ' + badgeClass + '">' + statusLabel + '</span>' +
                '</div>' +
                actions +
                '</div>';
        }).join('');

    } catch (err) {
        console.error('[dashboard] Error loading sessions:', err);
        listEl.innerHTML = '<p class="meta">Error loading sessions.</p>';
    }
}

async function confirmSession(sessionId) {
    try {
        var resp = await apiFetch('/api/teacher/sessions/' + sessionId + '/confirm', { method: 'POST' });
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { detail: 'Failed' }; });
            alert('Error: ' + (err.detail || 'Could not confirm'));
            return;
        }
        loadTeacherSessions();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function cancelSession(sessionId) {
    if (!confirm('Cancel this session? / Anulowac te sesje?')) return;
    try {
        var resp = await apiFetch('/api/teacher/sessions/' + sessionId + '/cancel', { method: 'POST' });
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { detail: 'Failed' }; });
            alert('Error: ' + (err.detail || 'Could not cancel'));
            return;
        }
        loadTeacherSessions();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ── Session Notes Modal ───────────────────────────────────────────

let notesModalSessionId = null;

function openNotesModal(sessionId) {
    notesModalSessionId = sessionId;

    // Create modal if it doesn't exist
    let modal = document.getElementById('notes-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'notes-modal';
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Session Notes / Notatki z sesji</h3>
                    <button onclick="closeNotesModal()" class="modal-close">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label for="notes-teacher">Private Teacher Notes / Prywatne notatki nauczyciela:</label>
                        <textarea id="notes-teacher" rows="3" placeholder="Only you can see this..."></textarea>
                    </div>
                    <div class="form-group">
                        <label for="notes-homework">Homework (visible to student) / Praca domowa:</label>
                        <textarea id="notes-homework" rows="2" placeholder="Homework assignment..."></textarea>
                    </div>
                    <div class="form-group">
                        <label for="notes-summary">Session Summary (visible to student) / Podsumowanie:</label>
                        <textarea id="notes-summary" rows="2" placeholder="Brief summary of what was covered..."></textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button onclick="closeNotesModal()" class="btn btn-sm" style="background:#95a5a6;color:white;">Cancel / Anuluj</button>
                    <button onclick="saveSessionNotes()" class="btn btn-sm btn-primary" id="save-notes-btn">Save / Zapisz</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    // Load existing notes
    loadExistingNotes(sessionId);

    modal.classList.add('visible');
}

function closeNotesModal() {
    const modal = document.getElementById('notes-modal');
    if (modal) modal.classList.remove('visible');
    notesModalSessionId = null;
}

async function loadExistingNotes(sessionId) {
    try {
        const resp = await apiFetch(`/api/teacher/sessions/${sessionId}/notes`);
        if (resp.ok) {
            const data = await resp.json();
            document.getElementById('notes-teacher').value = data.teacher_notes || '';
            document.getElementById('notes-homework').value = data.homework || '';
            document.getElementById('notes-summary').value = data.session_summary || '';
        }
    } catch (err) {
        console.warn('Could not load existing notes:', err);
    }
}

async function saveSessionNotes() {
    if (!notesModalSessionId) return;

    const btn = document.getElementById('save-notes-btn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const resp = await apiFetch(`/api/teacher/sessions/${notesModalSessionId}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                teacher_notes: document.getElementById('notes-teacher').value || null,
                homework: document.getElementById('notes-homework').value || null,
                session_summary: document.getElementById('notes-summary').value || null,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            alert('Error: ' + (err.detail || 'Could not save notes'));
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }

        btn.textContent = 'Saved!';
        setTimeout(() => {
            closeNotesModal();
            btn.disabled = false;
            btn.textContent = originalText;
            // Refresh sessions list
            loadTeacherSessions();
        }, 800);
    } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// Initialize filters and load students on page load
renderStudentFilters();
loadStudents();

// Load teacher sessions if the panel exists
if (document.getElementById('teacher-sessions-list')) {
    loadTeacherSessions();
}
