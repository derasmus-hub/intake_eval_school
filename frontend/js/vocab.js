var studentId = STATE.requireStudentId();

let dueCards = [];
let currentCardIndex = 0;
let isFlipped = false;

if (studentId) {
    loadStats();
    loadDueCards();
}

function showVocabSection(name) {
    document.querySelectorAll('.vocab-section').forEach(s => s.style.display = 'none');
    document.querySelectorAll('.vocab-tabs .tab').forEach(t => t.classList.remove('active'));

    document.getElementById('section-' + name).style.display = 'block';
    document.querySelectorAll('.vocab-tabs .tab').forEach(t => {
        if (t.textContent.toLowerCase().includes(name)) t.classList.add('active');
    });

    if (name === 'all') loadAllCards();
}

async function loadStats() {
    try {
        const resp = await apiFetch(`/api/vocab/${studentId}/stats`);
        const stats = await resp.json();

        document.getElementById('vocab-stats').innerHTML = `
            <div class="stat-item">
                <span class="stat-value">${stats.total_cards}</span>
                <span class="stat-label">Total / Lacznie</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${stats.due_now}</span>
                <span class="stat-label">Due / Do powtorki</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${stats.mastered}</span>
                <span class="stat-label">Mastered / Opanowane</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${stats.learning}</span>
                <span class="stat-label">Learning / W trakcie</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${stats.total_reviews}</span>
                <span class="stat-label">Reviews / Powtorki</span>
            </div>
        `;
    } catch (err) {
        document.getElementById('vocab-stats').innerHTML = '<p>Error loading stats.</p>';
    }
}

async function loadDueCards() {
    const area = document.getElementById('flashcard-area');
    try {
        const resp = await apiFetch(`/api/vocab/${studentId}/due`);
        const data = await resp.json();
        dueCards = data.cards;
        currentCardIndex = 0;

        if (dueCards.length === 0) {
            area.innerHTML = `
                <div class="detail-panel" style="text-align:center;">
                    <h3>No cards due for review!</h3>
                    <p>Brak kart do powtorki. Dodaj nowe karty lub wroc pozniej.</p>
                    <button onclick="showVocabSection('add')" class="btn btn-primary" style="margin-top:1rem;">
                        Add Cards / Dodaj karty
                    </button>
                </div>
            `;
            return;
        }

        renderFlashcard();
    } catch (err) {
        area.innerHTML = '<p>Error loading cards: ' + err.message + '</p>';
    }
}

function renderFlashcard() {
    const area = document.getElementById('flashcard-area');
    if (currentCardIndex >= dueCards.length) {
        area.innerHTML = `
            <div class="detail-panel" style="text-align:center;">
                <h3>Review Complete!</h3>
                <p>Powtorka zakonczona! Swietna robota.</p>
                <button onclick="loadDueCards()" class="btn btn-primary" style="margin-top:1rem;">
                    Check for More / Sprawdz ponownie
                </button>
            </div>
        `;
        loadStats();
        return;
    }

    const card = dueCards[currentCardIndex];
    isFlipped = false;

    area.innerHTML = `
        <div class="flashcard-progress">
            Card ${currentCardIndex + 1} of ${dueCards.length}
        </div>
        <div class="flashcard" onclick="flipCard()" id="flashcard">
            <div class="flashcard-front">
                <span class="flashcard-label">English</span>
                <h2>${escapeHtml(card.word)}</h2>
                ${card.example ? '<p class="flashcard-example">' + escapeHtml(card.example) + '</p>' : ''}
                <p class="meta">Click to reveal / Kliknij aby odkryc</p>
            </div>
            <div class="flashcard-back" style="display:none;">
                <span class="flashcard-label">Polski</span>
                <h2>${escapeHtml(card.translation)}</h2>
                ${card.example ? '<p class="flashcard-example">' + escapeHtml(card.example) + '</p>' : ''}
            </div>
        </div>
        <div class="flashcard-actions" id="flashcard-actions" style="display:none;">
            <button onclick="submitReview(0)" class="btn-review btn-again">Again / Jeszcze raz</button>
            <button onclick="submitReview(2)" class="btn-review btn-hard">Hard / Trudne</button>
            <button onclick="submitReview(3)" class="btn-review btn-ok">OK</button>
            <button onclick="submitReview(4)" class="btn-review btn-good">Good / Dobre</button>
            <button onclick="submitReview(5)" class="btn-review btn-easy">Easy / Latwe</button>
        </div>
    `;
}

function flipCard() {
    if (isFlipped) return;
    isFlipped = true;

    document.querySelector('.flashcard-front').style.display = 'none';
    document.querySelector('.flashcard-back').style.display = 'flex';
    document.getElementById('flashcard').classList.add('flipped');
    document.getElementById('flashcard-actions').style.display = 'flex';
}

async function submitReview(quality) {
    const card = dueCards[currentCardIndex];
    try {
        await apiFetch(`/api/vocab/${studentId}/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_id: card.id, quality: quality }),
        });

        currentCardIndex++;
        renderFlashcard();
    } catch (err) {
        alert('Error submitting review: ' + err.message);
    }
}

async function addCard(event) {
    event.preventDefault();
    const msg = document.getElementById('add-card-message');
    const word = document.getElementById('card-word').value.trim();
    const translation = document.getElementById('card-translation').value.trim();
    const example = document.getElementById('card-example').value.trim();

    try {
        const resp = await apiFetch(`/api/vocab/${studentId}/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word, translation, example: example || null }),
        });

        if (resp.status === 409) {
            msg.innerHTML = '<p style="color:#e74c3c;">Card already exists for this word.</p>';
            return;
        }
        if (!resp.ok) {
            const err = await resp.json();
            msg.innerHTML = '<p style="color:#e74c3c;">Error: ' + (err.detail || 'Unknown') + '</p>';
            return;
        }

        msg.innerHTML = '<p style="color:#2ecc71;">Card added! / Karta dodana!</p>';
        document.getElementById('add-card-form').reset();
        loadStats();
    } catch (err) {
        msg.innerHTML = '<p style="color:#e74c3c;">Error: ' + err.message + '</p>';
    }
}

async function loadAllCards() {
    const container = document.getElementById('all-cards-list');
    try {
        // Fetch all due cards (which returns up to 20) and stats
        const resp = await apiFetch(`/api/vocab/${studentId}/due`);
        const data = await resp.json();

        if (data.cards.length === 0) {
            container.innerHTML = '<p>No vocabulary cards yet. Add some! / Brak kart. Dodaj nowe!</p>';
            return;
        }

        container.innerHTML = data.cards.map(card => `
            <div class="vocab-card-row">
                <div class="vocab-word">${escapeHtml(card.word)}</div>
                <div class="vocab-translation">${escapeHtml(card.translation)}</div>
                <div class="vocab-meta">
                    Reviews: ${card.review_count} | Interval: ${card.interval_days}d
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<p>Error loading cards.</p>';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
