let currentStudentId = null;

document.getElementById('intake-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const form = e.target;
    const data = {
        name: form.name.value,
        age: form.age.value ? parseInt(form.age.value) : null,
        current_level: form.current_level.value,
        goals: Array.from(form.querySelectorAll('input[name="goals"]:checked')).map(cb => cb.value),
        problem_areas: Array.from(form.querySelectorAll('input[name="problem_areas"]:checked')).map(cb => cb.value),
        filler: form.filler.value,
        additional_notes: form.additional_notes.value || null,
    };

    try {
        const resp = await fetch('/api/intake', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert('Error: ' + (err.detail || JSON.stringify(err)));
            return;
        }

        const result = await resp.json();
        currentStudentId = result.student_id;

        form.classList.add('hidden');
        const resultPanel = document.getElementById('result');
        resultPanel.classList.remove('hidden');
        document.getElementById('student-id').textContent = currentStudentId;
    } catch (err) {
        alert('Network error: ' + err.message);
    }
});

async function runDiagnostic() {
    if (!currentStudentId) return;

    const diagResult = document.getElementById('diagnostic-result');
    const diagOutput = document.getElementById('diagnostic-output');
    diagResult.classList.remove('hidden');
    diagOutput.textContent = 'Running diagnostic analysis...';

    try {
        const resp = await fetch(`/api/diagnostic/${currentStudentId}`, {
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
