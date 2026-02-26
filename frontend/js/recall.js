let studentId = null;
let sessionId = null;
let questions = [];
let currentQuestionIndex = 0;
let userAnswers = {};

function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

async function init() {
    studentId = STATE.requireStudentId();
    if (!studentId) return; // redirect triggered

    // Set nav links
    const navVocab = document.getElementById('nav-vocab');
    const navConv = document.getElementById('nav-conversation');
    if (navVocab) navVocab.href = `vocab.html?student_id=${studentId}`;
    if (navConv) navConv.href = `conversation.html?student_id=${studentId}`;
    apiFetch(`/api/intake/${studentId}`).then(r=>r.json()).then(s=>{
        const el = document.getElementById('nav-student-name');
        if (el) el.innerHTML = `<strong>${s.name||''}</strong> (${s.current_level||''})`;
    }).catch(()=>{});

    try {
        const resp = await apiFetch(`/api/recall/${studentId}/check`);
        const data = await resp.json();

        if (!data.has_pending_recall) {
            document.getElementById('loading-screen').classList.add('hidden');
            document.getElementById('no-review').classList.remove('hidden');
            document.getElementById('no-review-link').href = `session.html?student_id=${studentId}&recall_done=true`;
            return;
        }

        await startQuiz();
    } catch (err) {
        document.getElementById('loading-screen').innerHTML =
            '<p>Error: ' + err.message + '</p>';
    }
}

async function startQuiz() {
    try {
        const resp = await apiFetch(`/api/recall/${studentId}/start`, { method: 'POST' });
        const data = await resp.json();

        if (!data.session_id || !data.questions || data.questions.length === 0) {
            document.getElementById('loading-screen').classList.add('hidden');
            document.getElementById('no-review').classList.remove('hidden');
            return;
        }

        sessionId = data.session_id;
        questions = data.questions;

        // Show encouragement
        document.getElementById('encouragement-text').textContent = data.encouragement || '';
        document.getElementById('encouragement-text-pl').textContent = data.encouragement_pl || '';

        document.getElementById('loading-screen').classList.add('hidden');
        document.getElementById('quiz-area').classList.remove('hidden');

        renderQuestion(0);
    } catch (err) {
        document.getElementById('loading-screen').innerHTML =
            '<p>Error starting quiz: ' + err.message + '</p>';
    }
}

function renderQuestion(index) {
    currentQuestionIndex = index;
    const q = questions[index];
    const total = questions.length;

    // Update progress
    const pct = Math.round(((index + 1) / total) * 100);
    document.getElementById('progress-fill').style.width = pct + '%';
    document.getElementById('progress-text').textContent = `Question ${index + 1} of ${total}`;

    // Nav buttons
    document.getElementById('prev-btn').disabled = (index === 0);
    if (index === total - 1) {
        document.getElementById('next-btn').classList.add('hidden');
        document.getElementById('submit-btn').classList.remove('hidden');
    } else {
        document.getElementById('next-btn').classList.remove('hidden');
        document.getElementById('submit-btn').classList.add('hidden');
    }

    const container = document.getElementById('question-container');
    const savedAnswer = userAnswers[q.point_id] || '';

    let html = `<div class="recall-question-card">`;
    html += `<p class="question-number">${escapeHtml(q.question_type.replace('_', ' ').toUpperCase())}</p>`;
    html += `<p class="question-text">${escapeHtml(q.question_text)}</p>`;
    html += `<p class="polish-text" style="margin-bottom:0.75rem;"><em>${escapeHtml(q.question_text_pl || '')}</em></p>`;

    if (q.question_type === 'multiple_choice' && q.options) {
        html += `<div class="recall-options">`;
        q.options.forEach((opt, i) => {
            const checked = savedAnswer === opt ? 'checked' : '';
            html += `
                <label class="answer-label">
                    <input type="radio" name="q_${q.point_id}" value="${escapeHtml(opt)}"
                           onchange="saveAnswer(${q.point_id}, this.value)" ${checked}>
                    ${escapeHtml(opt)}
                </label>`;
        });
        html += `</div>`;
    } else {
        html += `<input type="text" class="fill-blank-input" id="answer-input-${q.point_id}"
                    value="${escapeHtml(savedAnswer)}"
                    placeholder="Type your answer here..."
                    oninput="saveAnswer(${q.point_id}, this.value)">`;
    }

    // Hint button
    html += `
        <div class="recall-hint" style="margin-top:0.75rem;">
            <button onclick="showHint(${index})" class="btn btn-sm" id="hint-btn-${index}">
                Show Hint / Pokaz podpowiedz
            </button>
            <div id="hint-text-${index}" class="hidden" style="margin-top:0.5rem;">
                <p><strong>Hint:</strong> ${escapeHtml(q.hint || '')}</p>
                <p class="polish-text"><em>${escapeHtml(q.hint_pl || '')}</em></p>
            </div>
        </div>`;

    html += `</div>`;
    container.innerHTML = html;
}

function saveAnswer(pointId, value) {
    userAnswers[pointId] = value;
}

function showHint(index) {
    document.getElementById(`hint-text-${index}`).classList.remove('hidden');
    document.getElementById(`hint-btn-${index}`).classList.add('hidden');
}

function nextQuestion() {
    if (currentQuestionIndex < questions.length - 1) {
        renderQuestion(currentQuestionIndex + 1);
    }
}

function prevQuestion() {
    if (currentQuestionIndex > 0) {
        renderQuestion(currentQuestionIndex - 1);
    }
}

async function submitQuiz() {
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';

    const answers = questions.map(q => ({
        point_id: q.point_id,
        answer: userAnswers[q.point_id] || '',
    }));

    try {
        const resp = await apiFetch(`/api/recall/${sessionId}/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answers }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert('Error: ' + (err.detail || 'Unknown error'));
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Answers';
            return;
        }

        const result = await resp.json();
        showResults(result);
    } catch (err) {
        alert('Error: ' + err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Answers';
    }
}

function showResults(result) {
    document.getElementById('quiz-area').classList.add('hidden');
    document.getElementById('results-area').classList.remove('hidden');

    // Score
    document.getElementById('result-score').textContent = Math.round(result.overall_score) + '%';

    // Color the score
    const scoreEl = document.getElementById('result-score');
    if (result.overall_score >= 85) {
        scoreEl.style.color = '#2ecc71';
    } else if (result.overall_score >= 60) {
        scoreEl.style.color = '#f39c12';
    } else {
        scoreEl.style.color = '#e74c3c';
    }

    // Encouragement
    document.getElementById('result-encouragement').innerHTML = `
        <p>${escapeHtml(result.encouragement || '')}</p>
        <p class="polish-text"><em>${escapeHtml(result.encouragement_pl || '')}</em></p>
    `;

    // Per-question feedback
    const feedbackContainer = document.getElementById('result-feedback');
    const evaluations = result.evaluations || [];
    feedbackContainer.innerHTML = evaluations.map((ev, i) => {
        const q = questions.find(q => q.point_id === ev.point_id) || {};
        const scoreColor = ev.score >= 85 ? '#2ecc71' : ev.score >= 60 ? '#f39c12' : '#e74c3c';
        const answer = userAnswers[ev.point_id] || '(no answer)';
        return `
            <div class="recall-feedback">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                    <strong>${escapeHtml(q.question_text || 'Question ' + (i + 1))}</strong>
                    <span style="color:${scoreColor};font-weight:700;">${ev.score}%</span>
                </div>
                <p><strong>Your answer:</strong> ${escapeHtml(answer)}</p>
                <p><strong>Correct:</strong> ${escapeHtml(q.correct_answer || '')}</p>
                <p>${escapeHtml(ev.feedback || '')}</p>
                <p class="polish-text"><em>${escapeHtml(ev.feedback_pl || '')}</em></p>
            </div>
        `;
    }).join('');

    // Weak areas
    const weakAreas = result.weak_areas || [];
    if (weakAreas.length > 0) {
        const weakDiv = document.getElementById('result-weak-areas');
        weakDiv.classList.remove('hidden');
        document.getElementById('weak-areas-list').innerHTML =
            weakAreas.map(a => `<li>${escapeHtml(a)}</li>`).join('');
    }

    // Start Lesson button
    document.getElementById('start-lesson-btn').href =
        `session.html?student_id=${studentId}&recall_done=true`;
}

// Initialize on page load
init();
