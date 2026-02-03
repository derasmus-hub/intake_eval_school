let currentStudentId = null;
let students = [];

async function loadStudents() {
    try {
        const resp = await fetch('/api/students');
        students = await resp.json();
        renderStudentList();
    } catch (err) {
        document.getElementById('student-list').innerHTML =
            '<p>Error loading students: ' + err.message + '</p>';
    }
}

function renderStudentList() {
    const container = document.getElementById('student-list');
    if (students.length === 0) {
        container.innerHTML = '<p>No students yet. <a href="/">Add one</a>.</p>';
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
    const student = students.find(s => s.id === id);
    if (!student) return;

    document.getElementById('student-list-section').classList.add('hidden');
    document.getElementById('student-detail').classList.remove('hidden');
    document.getElementById('detail-student-name').textContent = student.name;
    document.getElementById('detail-student-meta').textContent =
        `Level: ${student.current_level} | Age: ${student.age || 'N/A'} | Problems: ${(student.problem_areas || []).join(', ')}`;

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
}

async function loadProfile() {
    const container = document.getElementById('profile-content');
    try {
        const resp = await fetch(`/api/diagnostic/${currentStudentId}`);
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
        const resp = await fetch(`/api/diagnostic/${currentStudentId}`, { method: 'POST' });
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
        const resp = await fetch(`/api/lessons/${currentStudentId}`);
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

function renderLessons(lessons) {
    const container = document.getElementById('lessons-content');
    container.innerHTML = lessons.map(lesson => {
        const content = lesson.content || {};
        const exercises = content.exercises || [];
        const prompts = content.conversation_prompts || [];

        return `
            <div class="lesson-card">
                <h4>Lesson ${lesson.session_number}: ${escapeHtml(lesson.objective || content.objective || 'Untitled')}</h4>
                <p><strong>Difficulty:</strong> ${lesson.difficulty || content.difficulty || 'N/A'}
                   | <strong>Status:</strong> ${lesson.status}</p>

                ${content.polish_explanation ? `
                    <h4>Wyjaśnienie po polsku:</h4>
                    <p>${escapeHtml(content.polish_explanation)}</p>
                ` : ''}

                ${exercises.length > 0 ? `
                    <h4>Exercises / Ćwiczenia:</h4>
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
                ` : ''}

                ${prompts.length > 0 ? `
                    <h4>Conversation Prompts:</h4>
                    <ul>${prompts.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>
                ` : ''}

                ${content.win_activity ? `
                    <h4>Win Activity:</h4>
                    <p>${escapeHtml(content.win_activity)}</p>
                ` : ''}

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

async function generateLesson() {
    const container = document.getElementById('lessons-content');
    const prevContent = container.innerHTML;
    container.innerHTML = '<div class="loading">Generating lesson...</div>' + prevContent;

    try {
        const resp = await fetch(`/api/lessons/${currentStudentId}/generate`, { method: 'POST' });
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
        const resp = await fetch(`/api/progress/${lessonId}`, {
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

        loadLessons();
        loadProgress();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function loadProgress() {
    const container = document.getElementById('progress-content');
    try {
        const resp = await fetch(`/api/progress/${currentStudentId}`);
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

// Load students on page load
loadStudents();
