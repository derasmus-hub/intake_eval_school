/**
 * Mini-Games JavaScript
 * Word Match, Sentence Builder, Error Hunt, Speed Translate
 */

var studentId = STATE.requireStudentId();
if (!studentId) { /* redirect triggered */ }
let currentGame = null;
let gameTimer = null;
let gameSeconds = 0;
let gameCorrect = 0;
let gameTotal = 0;
let gameData = null;

async function startGame(type) {
    const content = document.getElementById('game-content');
    content.innerHTML = '<div class="loading">Generating game... / Generowanie gry...</div>';

    document.getElementById('game-selection').classList.add('hidden');
    document.getElementById('game-area').classList.remove('hidden');
    document.getElementById('game-results').classList.add('hidden');

    currentGame = type;
    gameCorrect = 0;
    gameTotal = 0;
    gameSeconds = 0;

    try {
        const resp = await apiFetch(`/api/games/${studentId}/${type}`);
        gameData = await resp.json();

        startTimer(gameData.time_limit || 60);

        switch (type) {
            case 'word-match': renderWordMatch(gameData); break;
            case 'sentence-builder': renderSentenceBuilder(gameData); break;
            case 'error-hunt': renderErrorHunt(gameData); break;
            case 'speed-translate': renderSpeedTranslate(gameData); break;
        }
    } catch (err) {
        content.innerHTML = '<p>Error loading game: ' + err.message + '</p>';
    }
}

function exitGame() {
    clearInterval(gameTimer);
    document.getElementById('game-selection').classList.remove('hidden');
    document.getElementById('game-area').classList.add('hidden');
    document.getElementById('game-results').classList.add('hidden');
    loadHistory();
}

function startTimer(limit) {
    clearInterval(gameTimer);
    gameSeconds = 0;
    updateTimerDisplay();

    gameTimer = setInterval(() => {
        gameSeconds++;
        updateTimerDisplay();
        if (gameSeconds >= limit) {
            clearInterval(gameTimer);
            endGame();
        }
    }, 1000);
}

function updateTimerDisplay() {
    const min = Math.floor(gameSeconds / 60);
    const sec = gameSeconds % 60;
    document.getElementById('game-timer').textContent = `${min}:${sec.toString().padStart(2, '0')}`;
}

function updateScoreDisplay() {
    document.getElementById('game-score-live').textContent = `${gameCorrect} / ${gameTotal}`;
}

// ===== WORD MATCH =====
function renderWordMatch(data) {
    const content = document.getElementById('game-content');
    const pairs = data.pairs || [];
    gameTotal = pairs.length;

    let selectedWord = null;
    let selectedTrans = null;
    let matched = new Set();

    const words = pairs.map(p => p.word).sort(() => Math.random() - 0.5);
    const translations = pairs.map(p => p.translation).sort(() => Math.random() - 0.5);

    content.innerHTML = `
        <div class="match-game">
            <p class="game-instruction">Match each English word with its Polish translation.<br><em>Dopasuj kazde angielskie slowo do jego polskiego tlumaczenia.</em></p>
            <div class="match-columns">
                <div class="match-col" id="words-col">
                    ${words.map(w => `<div class="match-item match-word" data-word="${escapeHtml(w)}" onclick="selectMatchItem(this, 'word')">${escapeHtml(w)}</div>`).join('')}
                </div>
                <div class="match-col" id="trans-col">
                    ${translations.map(t => `<div class="match-item match-trans" data-trans="${escapeHtml(t)}" onclick="selectMatchItem(this, 'trans')">${escapeHtml(t)}</div>`).join('')}
                </div>
            </div>
        </div>
    `;

    window._matchPairs = pairs;
    window._matchSelected = { word: null, trans: null };
    window._matchMatched = new Set();
}

function selectMatchItem(el, type) {
    if (el.classList.contains('matched')) return;

    // Deselect others of same type
    document.querySelectorAll(`.match-${type}`).forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');

    window._matchSelected[type] = type === 'word' ? el.dataset.word : el.dataset.trans;

    // Check if we have both selected
    if (window._matchSelected.word && window._matchSelected.trans) {
        const pair = window._matchPairs.find(p => p.word === window._matchSelected.word);
        if (pair && pair.translation === window._matchSelected.trans) {
            // Correct match
            gameCorrect++;
            document.querySelectorAll('.match-item.selected').forEach(e => {
                e.classList.remove('selected');
                e.classList.add('matched');
            });
            window._matchMatched.add(window._matchSelected.word);
        } else {
            // Wrong match
            document.querySelectorAll('.match-item.selected').forEach(e => {
                e.classList.add('wrong');
                setTimeout(() => e.classList.remove('wrong', 'selected'), 600);
            });
        }

        window._matchSelected = { word: null, trans: null };
        updateScoreDisplay();

        if (window._matchMatched.size === window._matchPairs.length) {
            setTimeout(() => endGame(), 500);
        }
    }
}

// ===== SENTENCE BUILDER =====
function renderSentenceBuilder(data) {
    const content = document.getElementById('game-content');
    const sentences = data.sentences || [];
    gameTotal = sentences.length;

    content.innerHTML = `
        <div class="sentence-game">
            <p class="game-instruction">Put the words in the correct order to form a sentence.<br><em>Uloz slowa w odpowiedniej kolejnosci, aby utworzyc zdanie.</em></p>
            <div id="sentence-items"></div>
        </div>
    `;

    window._sentenceIdx = 0;
    window._sentences = sentences;
    renderNextSentence();
}

function renderNextSentence() {
    const idx = window._sentenceIdx;
    const sentences = window._sentences;

    if (idx >= sentences.length) {
        endGame();
        return;
    }

    const s = sentences[idx];
    const words = s.sentence.split(' ').sort(() => Math.random() - 0.5);
    const container = document.getElementById('sentence-items');

    container.innerHTML = `
        <div class="sb-progress">Sentence ${idx + 1} of ${sentences.length}</div>
        ${s.translation_pl ? `<p class="sb-hint"><em>${escapeHtml(s.translation_pl)}</em></p>` : ''}
        ${s.hint ? `<p class="sb-hint">${escapeHtml(s.hint)}</p>` : ''}
        <div class="sb-answer-area" id="sb-answer"></div>
        <div class="sb-word-bank" id="sb-bank">
            ${words.map(w => `<span class="sb-word" onclick="addWord(this)">${escapeHtml(w)}</span>`).join('')}
        </div>
        <div class="sb-actions">
            <button onclick="clearSentence()" class="btn btn-sm">Clear / Wyczysc</button>
            <button onclick="checkSentence()" class="btn btn-sm btn-primary">Check / Sprawdz</button>
        </div>
    `;
}

function addWord(el) {
    if (el.classList.contains('used')) return;
    el.classList.add('used');
    const answer = document.getElementById('sb-answer');
    const word = document.createElement('span');
    word.className = 'sb-placed-word';
    word.textContent = el.textContent;
    word.onclick = function() {
        this.remove();
        el.classList.remove('used');
    };
    answer.appendChild(word);
}

function clearSentence() {
    document.getElementById('sb-answer').innerHTML = '';
    document.querySelectorAll('.sb-word').forEach(w => w.classList.remove('used'));
}

function checkSentence() {
    const placed = Array.from(document.querySelectorAll('.sb-placed-word')).map(w => w.textContent);
    const answer = placed.join(' ');
    const correct = window._sentences[window._sentenceIdx].sentence;

    if (answer.toLowerCase().trim() === correct.toLowerCase().trim()) {
        gameCorrect++;
        updateScoreDisplay();
    }

    window._sentenceIdx++;
    renderNextSentence();
}

// ===== ERROR HUNT =====
function renderErrorHunt(data) {
    const content = document.getElementById('game-content');
    const sentences = data.sentences || [];
    gameTotal = sentences.length;

    content.innerHTML = `
        <div class="error-hunt-game">
            <p class="game-instruction">Is the sentence correct or does it have an error?<br><em>Czy zdanie jest poprawne, czy zawiera blad?</em></p>
            <div id="eh-items"></div>
        </div>
    `;

    window._ehIdx = 0;
    window._ehSentences = sentences;
    renderNextError();
}

function renderNextError() {
    const idx = window._ehIdx;
    const sentences = window._ehSentences;

    if (idx >= sentences.length) {
        endGame();
        return;
    }

    const s = sentences[idx];
    const container = document.getElementById('eh-items');

    container.innerHTML = `
        <div class="sb-progress">Sentence ${idx + 1} of ${sentences.length}</div>
        <div class="eh-sentence">"${escapeHtml(s.sentence)}"</div>
        <div class="eh-actions">
            <button onclick="ehAnswer(true)" class="btn btn-danger">Has Error / Ma blad</button>
            <button onclick="ehAnswer(false)" class="btn btn-secondary">Correct / Poprawne</button>
        </div>
        <div id="eh-feedback" class="hidden"></div>
    `;
}

function ehAnswer(saidError) {
    const s = window._ehSentences[window._ehIdx];
    const correct = saidError === s.has_error;

    if (correct) gameCorrect++;
    updateScoreDisplay();

    const fb = document.getElementById('eh-feedback');
    fb.classList.remove('hidden');
    fb.className = `eh-feedback ${correct ? 'correct' : 'wrong'}`;

    if (s.has_error) {
        fb.innerHTML = `
            <p>${correct ? 'Correct!' : 'Wrong!'} This sentence has an error.</p>
            <p>Corrected: <strong>${escapeHtml(s.corrected || '')}</strong></p>
            <p>${escapeHtml(s.explanation || '')}</p>
            ${s.explanation_pl ? `<p><em>${escapeHtml(s.explanation_pl)}</em></p>` : ''}
        `;
    } else {
        fb.innerHTML = `<p>${correct ? 'Correct!' : 'Wrong!'} This sentence is correct.</p>`;
    }

    setTimeout(() => {
        window._ehIdx++;
        renderNextError();
    }, 2000);
}

// ===== SPEED TRANSLATE =====
function renderSpeedTranslate(data) {
    const content = document.getElementById('game-content');
    const phrases = data.phrases || [];
    gameTotal = phrases.length;

    content.innerHTML = `
        <div class="speed-translate-game">
            <p class="game-instruction">Translate the Polish phrase into English as fast as you can!<br><em>Przetlumacz polskie zdanie na angielski jak najszybciej!</em></p>
            <div id="st-items"></div>
        </div>
    `;

    window._stIdx = 0;
    window._stPhrases = phrases;
    renderNextTranslation();
}

function renderNextTranslation() {
    const idx = window._stIdx;
    const phrases = window._stPhrases;

    if (idx >= phrases.length) {
        endGame();
        return;
    }

    const p = phrases[idx];
    const container = document.getElementById('st-items');

    container.innerHTML = `
        <div class="sb-progress">Phrase ${idx + 1} of ${phrases.length}</div>
        <div class="st-polish">${escapeHtml(p.polish)}</div>
        ${p.hint ? `<div class="st-hint">Hint: ${escapeHtml(p.hint)}</div>` : ''}
        <input type="text" id="st-input" class="fill-blank-input" placeholder="Type English translation..."
               onkeydown="if(event.key==='Enter')checkTranslation()">
        <button onclick="checkTranslation()" class="btn btn-sm btn-primary" style="margin-top:0.5rem;">Check / Sprawdz</button>
        <div id="st-feedback" class="hidden"></div>
    `;

    document.getElementById('st-input').focus();
}

function checkTranslation() {
    const input = document.getElementById('st-input').value.trim().toLowerCase();
    const p = window._stPhrases[window._stIdx];
    const correct = p.english.toLowerCase().trim();

    // Simple similarity check
    const isCorrect = input === correct ||
        input.replace(/[?.!,]/g, '') === correct.replace(/[?.!,]/g, '') ||
        levenshtein(input, correct) <= 2;

    if (isCorrect) gameCorrect++;
    updateScoreDisplay();

    const fb = document.getElementById('st-feedback');
    fb.classList.remove('hidden');
    fb.className = `eh-feedback ${isCorrect ? 'correct' : 'wrong'}`;
    fb.innerHTML = `
        <p>${isCorrect ? 'Correct!' : 'Not quite.'}</p>
        <p>Answer: <strong>${escapeHtml(p.english)}</strong></p>
    `;

    setTimeout(() => {
        window._stIdx++;
        renderNextTranslation();
    }, 1500);
}

// Levenshtein distance for fuzzy matching
function levenshtein(a, b) {
    const m = a.length, n = b.length;
    const dp = Array.from({length: m + 1}, (_, i) => [i]);
    for (let j = 0; j <= n; j++) dp[0][j] = j;
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] :
                1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
        }
    }
    return dp[m][n];
}

// ===== END GAME =====
async function endGame() {
    clearInterval(gameTimer);

    const score = gameTotal > 0 ? Math.round((gameCorrect / gameTotal) * 100) : 0;

    document.getElementById('game-area').classList.add('hidden');
    document.getElementById('game-results').classList.remove('hidden');
    document.getElementById('final-score').textContent = score + '%';

    // Submit score
    try {
        const resp = await apiFetch(`/api/games/${studentId}/submit`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                game_type: currentGame,
                score: score,
                data: {correct: gameCorrect, total: gameTotal, time: gameSeconds}
            })
        });
        const result = await resp.json();

        document.getElementById('xp-earned-display').innerHTML =
            `<span class="game-xp-earned">+${result.xp_earned} XP</span>`;

        if (typeof CELEBRATIONS !== 'undefined') {
            CELEBRATIONS.showXpGain(result.xp_earned);
            if (score >= 90) {
                CELEBRATIONS.triggerConfetti();
            }
        }

        // Show feedback
        const fb = document.getElementById('game-feedback');
        let msg = '';
        if (score >= 90) msg = 'Excellent! / Doskonale!';
        else if (score >= 70) msg = 'Great job! / Swietna robota!';
        else if (score >= 50) msg = 'Good effort! / Dobra proba!';
        else msg = 'Keep practicing! / Cwicz dalej!';

        fb.innerHTML = `<p style="text-align:center;font-size:1.1rem;margin:1rem 0;">${msg}</p>
            <p style="text-align:center;color:#7f8c8d;">
                ${gameCorrect}/${gameTotal} correct in ${gameSeconds}s
            </p>`;
    } catch (err) {
        console.error('Error submitting score:', err);
    }
}

// ===== HISTORY =====
async function loadHistory() {
    try {
        const resp = await apiFetch(`/api/games/${studentId}/history`);
        const data = await resp.json();
        renderHistory(data);
    } catch (err) {
        document.getElementById('history-content').innerHTML = '<p>No game history yet.</p>';
    }
}

function renderHistory(data) {
    const container = document.getElementById('history-content');
    const recent = data.recent || [];

    if (recent.length === 0) {
        container.innerHTML = '<p>No games played yet. Pick a game above!<br><em>Brak rozegranych gier. Wybierz gre powyzej!</em></p>';
        return;
    }

    // Best scores
    const best = data.best_scores || {};
    let bestHtml = '<div class="game-best-scores">';
    for (const [type, info] of Object.entries(best)) {
        bestHtml += `<span class="best-score-chip">${type}: ${info.best}% (${info.times_played}x)</span>`;
    }
    bestHtml += '</div>';

    container.innerHTML = bestHtml + recent.slice(0, 5).map(r => `
        <div class="xp-entry">
            <span class="xp-source">${escapeHtml(r.game_type)}</span>
            <span class="xp-amount positive">${r.score}%</span>
            <span class="xp-detail">+${r.xp_earned} XP</span>
        </div>
    `).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

// Load history on page load
loadHistory();
