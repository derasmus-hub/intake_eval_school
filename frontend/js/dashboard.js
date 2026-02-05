let currentStudentId = null;
let students = [];

async function loadStudents() {
    try {
        const resp = await apiFetch('/api/students');
        students = await resp.json();
        renderStudentList();

        // Auto-select the logged-in student so they see their data immediately
        var autoId = STATE.getStudentId();
        if (autoId && students.some(function (s) { return s.id === autoId; })) {
            selectStudent(autoId);
        }
    } catch (err) {
        document.getElementById('student-list').innerHTML =
            '<p>Error loading students: ' + err.message + '</p>';
    }
}

function renderStudentList() {
    const container = document.getElementById('student-list');
    if (students.length === 0) {
        container.innerHTML = '<p>No students yet. <a href="index.html">Add one</a>.</p>';
        return;
    }

    container.innerHTML = students.map(s => `
        <div class="student-card" onclick="selectStudent(${s.id})">
            <div class="student-info">
                <h3>${escapeHtml(s.name)}</h3>
                <span class="meta">Age: ${s.age || 'N/A'} | Goals: ${(s.goals || []).join(', ') || 'None'}</span>
            </div>
            <span class="level-badge">${s.current_level}</span>
        </div>
    `).join('');
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

    switchTab('profile');
    loadProfile();
    loadLessons();
    loadProgress();
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
    listEl.innerHTML = '<p class="meta">Loading...</p>';

    try {
        var resp = await apiFetch('/api/teacher/sessions');
        if (!resp.ok) {
            listEl.innerHTML = '<p class="meta">Could not load sessions.</p>';
            return;
        }
        var data = await resp.json();
        var sessions = data.sessions || [];

        if (sessions.length === 0) {
            listEl.innerHTML = '<p class="meta">No session requests. / Brak prosb o sesje.</p>';
            return;
        }

        listEl.innerHTML = sessions.map(function(s) {
            var dt = new Date(s.scheduled_at);
            var dateStr = dt.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
            var timeStr = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
            var statusColor = s.status === 'confirmed' ? '#27ae60'
                : s.status === 'requested' ? '#f39c12'
                : s.status === 'cancelled' ? '#c0392b' : '#888';
            var statusLabel = s.status.charAt(0).toUpperCase() + s.status.slice(1);

            var actions = '';
            if (s.status === 'requested') {
                actions = '<div style="display:flex;gap:0.4rem;margin-top:0.5rem;">' +
                    '<button class="btn btn-sm btn-primary" onclick="confirmSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;">Confirm / Potwierdz</button>' +
                    '<button class="btn btn-sm" onclick="cancelSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:#e74c3c;color:white;">Cancel / Anuluj</button>' +
                    '</div>';
            } else if (s.status === 'confirmed') {
                actions = '<div style="margin-top:0.5rem;">' +
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
                '<span style="font-weight:600;color:' + statusColor + ';font-size:0.85rem;white-space:nowrap;">' + statusLabel + '</span>' +
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

// Load students on page load
loadStudents();

// Load teacher sessions if the panel exists
if (document.getElementById('teacher-sessions-list')) {
    loadTeacherSessions();
}
