let currentStudentId = null;
let currentStudentName = null;
let assessmentData = null; // filled when returning from assessment

// Check if returning from assessment (URL has student_id and from=assessment)
const urlParams = new URLSearchParams(window.location.search);
const returningStudentId = urlParams.get('student_id');
const returningFrom = urlParams.get('from');

if (returningStudentId && returningFrom === 'assessment') {
    // Returning from assessment — jump to step 3
    currentStudentId = parseInt(returningStudentId);
    resumeAtStep3();
}

// Step 1: Submit basic info
document.getElementById('step1-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const form = e.target;
    const data = {
        name: form.name.value,
        age: form.age.value ? parseInt(form.age.value) : null,
        filler: form.filler.value,
    };

    try {
        const resp = await apiFetch('/api/intake', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError('Error: ' + (err.detail || JSON.stringify(err)));
            return;
        }

        const result = await resp.json();
        currentStudentId = result.student_id;
        STATE.setStudentId(currentStudentId);
        currentStudentName = data.name;

        goToStep2();
    } catch (err) {
        showError('Network error: ' + err.message);
    }
});

function goToStep2() {
    // Update wizard progress
    document.getElementById('wizard-step-1').classList.remove('active');
    document.getElementById('wizard-step-1').classList.add('completed');
    document.getElementById('wizard-step-2').classList.add('active');

    // Hide step 1, show step 2
    document.getElementById('step1-content').classList.add('hidden');
    document.getElementById('step2-content').classList.remove('hidden');

    // Populate step 2 info
    document.getElementById('step2-student-name').textContent = currentStudentName || 'Student';
    document.getElementById('step2-student-id').textContent = currentStudentId;
    document.getElementById('assessment-link').href = `assessment.html?student_id=${currentStudentId}&return_to=intake`;

    // Show the "I've finished" button
    document.getElementById('step2-waiting').classList.remove('hidden');
}

async function checkAssessmentAndProceed() {
    // Check if assessment is completed
    try {
        const resp = await apiFetch(`/api/assessment/${currentStudentId}`);
        if (resp.ok) {
            assessmentData = await resp.json();
            if (assessmentData.status === 'completed') {
                // Update level in DB
                if (assessmentData.determined_level) {
                    await apiFetch(`/api/intake/${currentStudentId}/level`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ level: assessmentData.determined_level }),
                    });
                }
                goToStep3();
                return;
            }
        }
        // Assessment not found or not completed
        showError('Assessment not completed yet. Please finish the assessment first, or skip and set a manual level.');
    } catch (err) {
        showError('Could not check assessment status: ' + err.message);
    }
}

async function skipAssessment() {
    const selected = document.querySelector('input[name="manual_level"]:checked');
    if (!selected) {
        showError('Please select a level before skipping the assessment.');
        return;
    }

    try {
        await apiFetch(`/api/intake/${currentStudentId}/level`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level: selected.value }),
        });

        assessmentData = null; // no assessment data
        goToStep3();
    } catch (err) {
        showError('Error setting level: ' + err.message);
    }
}

function goToStep3() {
    // Update wizard progress
    document.getElementById('wizard-step-2').classList.remove('active');
    document.getElementById('wizard-step-2').classList.add('completed');
    document.getElementById('wizard-step-3').classList.add('active');

    // Hide step 2, show step 3
    document.getElementById('step2-content').classList.add('hidden');
    document.getElementById('step3-content').classList.remove('hidden');

    // If assessment was completed, show summary and pre-populate problem areas
    if (assessmentData && assessmentData.status === 'completed') {
        const summaryPanel = document.getElementById('assessment-summary');
        summaryPanel.classList.remove('hidden');

        document.getElementById('summary-level').textContent = assessmentData.determined_level || '--';
        const confidence = assessmentData.confidence_score
            ? Math.round(assessmentData.confidence_score * 100) + '%'
            : '--';
        document.getElementById('summary-confidence').textContent = confidence;

        // Show weak areas
        const weakDiv = document.getElementById('summary-weak-areas');
        if (assessmentData.weak_areas && assessmentData.weak_areas.length) {
            weakDiv.innerHTML = '<p style="margin-top:0.5rem;"><strong>Identified weak areas / Zidentyfikowane trudności:</strong></p><ul>' +
                assessmentData.weak_areas.map(a => `<li>${escapeHtml(a)}</li>`).join('') + '</ul>';

            // Update the problem areas description
            document.getElementById('problems-desc').innerHTML =
                'These areas were pre-selected based on your assessment. Adjust as needed.' +
                '<br><em>Te obszary zostały zaznaczone na podstawie testu. Możesz je zmienić.</em>';

            // Pre-check problem areas that match weak areas
            prePopulateProblemAreas(assessmentData.weak_areas);
        }
    }
}

function prePopulateProblemAreas(weakAreas) {
    // Map AI weak area descriptions to checkbox values
    const mapping = {
        'articles': 'articles',
        'prepositions': 'prepositions',
        'preposition': 'prepositions',
        'word order': 'word_order',
        'word_order': 'word_order',
        'pronunciation': 'th_sounds',
        'th sounds': 'th_sounds',
        'th_sounds': 'th_sounds',
        'tenses': 'tenses',
        'tense': 'tenses',
        'present perfect': 'tenses',
        'past simple': 'tenses',
        'present continuous': 'tenses',
        'false friends': 'false_friends',
        'false_friends': 'false_friends',
        'conditionals': 'conditionals',
        'conditional': 'conditionals',
        'phrasal verbs': 'phrasal_verbs',
        'phrasal_verbs': 'phrasal_verbs',
        'grammar': 'tenses',
        'vocabulary': 'false_friends',
        'reading': null,
        'reading comprehension': null,
    };

    const toCheck = new Set();
    for (const area of weakAreas) {
        const lower = area.toLowerCase();
        // Direct match
        if (mapping[lower] !== undefined && mapping[lower] !== null) {
            toCheck.add(mapping[lower]);
            continue;
        }
        // Partial match: check if any mapping key is contained in the area string
        for (const [key, val] of Object.entries(mapping)) {
            if (val && lower.includes(key)) {
                toCheck.add(val);
            }
        }
    }

    // Check the matching checkboxes
    for (const val of toCheck) {
        const cb = document.querySelector(`#step3-form input[name="problem_areas"][value="${val}"]`);
        if (cb) cb.checked = true;
    }
}

// Step 3: Submit goals
document.getElementById('step3-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const form = e.target;
    const goals = Array.from(form.querySelectorAll('input[name="goals"]:checked')).map(cb => cb.value);
    const problemAreas = Array.from(form.querySelectorAll('input[name="problem_areas"]:checked')).map(cb => cb.value);
    const additionalNotes = form.additional_notes.value || null;

    try {
        const resp = await apiFetch(`/api/intake/${currentStudentId}/goals`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                goals: goals,
                problem_areas: problemAreas,
                additional_notes: additionalNotes,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError('Error: ' + (err.detail || JSON.stringify(err)));
            return;
        }

        showFinalResult();
    } catch (err) {
        showError('Network error: ' + err.message);
    }
});

async function showFinalResult() {
    // Update wizard step 3 to completed
    document.getElementById('wizard-step-3').classList.remove('active');
    document.getElementById('wizard-step-3').classList.add('completed');

    // Hide step 3, show result
    document.getElementById('step3-content').classList.add('hidden');
    const resultPanel = document.getElementById('result');
    resultPanel.classList.remove('hidden');

    document.getElementById('final-student-id').textContent = currentStudentId;

    // Fetch current student data to show level
    try {
        const resp = await apiFetch(`/api/intake/${currentStudentId}`);
        if (resp.ok) {
            const student = await resp.json();
            document.getElementById('final-level').textContent = student.current_level || 'pending';
        }
    } catch {
        document.getElementById('final-level').textContent = assessmentData?.determined_level || 'pending';
    }
}

async function resumeAtStep3() {
    // Hide step 1
    document.getElementById('step1-content').classList.add('hidden');

    // Mark steps 1 and 2 as completed
    document.getElementById('wizard-step-1').classList.remove('active');
    document.getElementById('wizard-step-1').classList.add('completed');
    document.getElementById('wizard-step-2').classList.add('completed');

    // Load assessment data
    try {
        const resp = await apiFetch(`/api/assessment/${currentStudentId}`);
        if (resp.ok) {
            assessmentData = await resp.json();
            if (assessmentData.status === 'completed' && assessmentData.determined_level) {
                // Update level in DB
                await apiFetch(`/api/intake/${currentStudentId}/level`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ level: assessmentData.determined_level }),
                });
            }
        }
    } catch {
        // Assessment data not available — proceed without it
    }

    goToStep3();
}

async function runDiagnostic() {
    if (!currentStudentId) return;

    const diagResult = document.getElementById('diagnostic-result');
    const diagOutput = document.getElementById('diagnostic-output');
    diagResult.classList.remove('hidden');
    diagOutput.textContent = 'Running diagnostic analysis...';

    try {
        const resp = await apiFetch(`/api/diagnostic/${currentStudentId}`, {
            method: 'POST',
        });

        if (!resp.ok) {
            const err = await resp.json();
            diagOutput.textContent = 'Error: ' + (err.detail || JSON.stringify(err));
            return;
        }

        const profile = await resp.json();
        diagOutput.textContent = JSON.stringify(profile, null, 2);
    } catch (err) {
        diagOutput.textContent = 'Network error: ' + err.message;
    }
}

function showError(message) {
    const existing = document.querySelector('.error-banner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.innerHTML = `<strong>Error:</strong> ${escapeHtml(message)}`;
    document.querySelector('.container').prepend(banner);

    setTimeout(() => banner.remove(), 8000);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
