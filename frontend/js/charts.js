let skillChart = null;
let timelineChart = null;

async function loadAnalytics() {
    if (!currentStudentId) return;

    const container = document.getElementById('analytics-content');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading analytics...</div>';

    try {
        const [skillsResp, timelineResp, achievementsResp, streakResp] = await Promise.all([
            apiFetch(`/api/analytics/${currentStudentId}/skills`),
            apiFetch(`/api/analytics/${currentStudentId}/timeline`),
            apiFetch(`/api/analytics/${currentStudentId}/achievements`),
            apiFetch(`/api/analytics/${currentStudentId}/streak`),
        ]);

        const skills = await skillsResp.json();
        const timeline = await timelineResp.json();
        const achievements = await achievementsResp.json();
        const streak = await streakResp.json();

        renderAnalytics(skills, timeline, achievements, streak);
    } catch (err) {
        container.innerHTML = '<p>Error loading analytics: ' + err.message + '</p>';
    }
}

function renderAnalytics(skills, timeline, achievements, streak) {
    const container = document.getElementById('analytics-content');

    const hasData = timeline.entries && timeline.entries.length > 0;

    if (!hasData) {
        container.innerHTML = '<p>No analytics data yet. Complete some lessons first. / Brak danych. Najpierw ukończ kilka lekcji.</p>';
        return;
    }

    container.innerHTML = `
        <div class="analytics-grid">
            <div class="analytics-card streak-card">
                <div class="streak-number">${streak.current_streak}</div>
                <div class="streak-label">Day Streak / Seria dni</div>
                <div class="streak-meta">${streak.total_lessons} lessons | ${streak.study_days} study days</div>
            </div>

            <div class="analytics-card">
                <h3>Achievements / Osiągnięcia</h3>
                <div class="achievements-grid">
                    ${achievements.achievements.length > 0
                        ? achievements.achievements.map(a => `
                            <div class="achievement-badge ${achievements.newly_earned.includes(a.title) ? 'new' : ''}">
                                <span class="achievement-icon">${getAchievementIcon(a.type)}</span>
                                <span class="achievement-title">${escapeHtml(a.title)}</span>
                                <span class="achievement-desc">${escapeHtml(a.description)}</span>
                            </div>
                        `).join('')
                        : '<p class="meta">No achievements yet. Keep studying!</p>'
                    }
                </div>
            </div>
        </div>

        <div class="analytics-grid charts-grid">
            <div class="analytics-card">
                <h3>Skills Overview / Przegląd umiejętności</h3>
                <canvas id="skills-radar-chart" width="400" height="300"></canvas>
            </div>

            <div class="analytics-card">
                <h3>Score Timeline / Wyniki w czasie</h3>
                <canvas id="timeline-chart" width="400" height="300"></canvas>
            </div>
        </div>
    `;

    renderSkillsChart(skills);
    renderTimelineChart(timeline);
}

function renderSkillsChart(skills) {
    const canvas = document.getElementById('skills-radar-chart');
    if (!canvas) return;

    const labels = Object.keys(skills.skills);
    const data = labels.map(l => skills.skills[l].average);

    if (labels.length === 0) {
        canvas.parentElement.innerHTML += '<p class="meta">Not enough skill data yet.</p>';
        return;
    }

    if (skillChart) skillChart.destroy();

    skillChart = new Chart(canvas, {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Skill Level',
                data: data,
                backgroundColor: 'rgba(52, 152, 219, 0.2)',
                borderColor: 'rgba(52, 152, 219, 1)',
                borderWidth: 2,
                pointBackgroundColor: 'rgba(52, 152, 219, 1)',
            }],
        },
        options: {
            responsive: true,
            scales: {
                r: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { stepSize: 20 },
                },
            },
            plugins: {
                legend: { display: false },
            },
        },
    });
}

function renderTimelineChart(timeline) {
    const canvas = document.getElementById('timeline-chart');
    if (!canvas) return;

    const labels = timeline.entries.map((e, i) => `L${e.session_number || i + 1}`);
    const scores = timeline.entries.map(e => e.score);
    const movingAvg = timeline.moving_average;

    if (timelineChart) timelineChart.destroy();

    timelineChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Score',
                    data: scores,
                    borderColor: 'rgba(52, 152, 219, 1)',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Moving Avg',
                    data: movingAvg,
                    borderColor: 'rgba(231, 76, 60, 0.8)',
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                },
            ],
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: 'Score %' },
                },
            },
        },
    });
}

function getAchievementIcon(type) {
    const icons = {
        first_lesson: '\u2B50',
        five_lessons: '\uD83D\uDCDA',
        ten_lessons: '\uD83C\uDFC6',
        high_scorer: '\uD83C\uDF1F',
        perfect_score: '\uD83D\uDCAF',
        streak_3: '\uD83D\uDD25',
        streak_7: '\u26A1',
    };
    return icons[type] || '\uD83C\uDFC5';
}
