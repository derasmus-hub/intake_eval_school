var studentId = STATE.requireStudentId();

let chatHistory = [];
let currentScenario = null;
let studentLevel = 'A1';

if (studentId) {
    loadScenarios();
}

async function loadScenarios() {
    try {
        const resp = await apiFetch(`/api/conversation/${studentId}/scenarios`);
        const data = await resp.json();
        studentLevel = data.level;

        const container = document.getElementById('scenarios-list');
        if (data.scenarios.length === 0) {
            container.innerHTML = '<p>No scenarios available.</p>';
            return;
        }

        container.innerHTML = data.scenarios.map((s, i) => `
            <div class="scenario-card" onclick="startScenario(${i})">
                <h4>${escapeHtml(s.title)}</h4>
                <p>${escapeHtml(s.description)}</p>
            </div>
        `).join('');

        // Store scenarios for later use
        window._scenarios = data.scenarios;
    } catch (err) {
        document.getElementById('scenarios-list').innerHTML =
            '<p>Error loading scenarios: ' + err.message + '</p>';
    }
}

function startScenario(index) {
    const scenario = window._scenarios[index];
    currentScenario = scenario;
    chatHistory = [];

    document.getElementById('scenario-select').classList.add('hidden');
    document.getElementById('chat-area').classList.remove('hidden');
    document.getElementById('chat-scenario-title').textContent = scenario.title;
    document.getElementById('chat-level-badge').textContent = studentLevel;
    document.getElementById('chat-messages').innerHTML = '';

    // Add the opener as the first assistant message
    if (scenario.opener) {
        chatHistory.push({ role: 'assistant', content: scenario.opener });
        appendMessage('assistant', scenario.opener);
    }

    document.getElementById('chat-input').focus();
}

function startFreeChat() {
    currentScenario = { title: 'Free Conversation', description: 'Free conversation practice.', opener: null };
    chatHistory = [];

    document.getElementById('scenario-select').classList.add('hidden');
    document.getElementById('chat-area').classList.remove('hidden');
    document.getElementById('chat-scenario-title').textContent = 'Free Conversation';
    document.getElementById('chat-level-badge').textContent = studentLevel;
    document.getElementById('chat-messages').innerHTML = '';

    appendMessage('system-info', 'Start typing to begin a free conversation. / Zacznij pisac aby rozpoczac rozmowe.');
    document.getElementById('chat-input').focus();
}

function endChat() {
    document.getElementById('scenario-select').classList.remove('hidden');
    document.getElementById('chat-area').classList.add('hidden');
    chatHistory = [];
    currentScenario = null;
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    appendMessage('user', message);

    const sendBtn = document.getElementById('send-btn');
    sendBtn.disabled = true;
    input.disabled = true;

    // Add a placeholder for the assistant response
    const assistantDiv = appendMessage('assistant', '');
    assistantDiv.classList.add('streaming');

    try {
        const resp = await apiFetch(`/api/conversation/${studentId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                scenario_title: currentScenario ? currentScenario.title : null,
                scenario_description: currentScenario ? currentScenario.description : null,
                history: chatHistory,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            assistantDiv.textContent = 'Error: ' + (err.detail || 'Unknown error');
            assistantDiv.classList.remove('streaming');
            sendBtn.disabled = false;
            input.disabled = false;
            return;
        }

        // Handle SSE stream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value, { stream: true });
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') continue;

                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.content) {
                            fullResponse += parsed.content;
                            assistantDiv.innerHTML = formatMessage(fullResponse);
                        }
                    } catch (e) {
                        // Skip parse errors for partial chunks
                    }
                }
            }
        }

        assistantDiv.classList.remove('streaming');

        // Add to history
        chatHistory.push({ role: 'user', content: message });
        chatHistory.push({ role: 'assistant', content: fullResponse });

        // Scroll to bottom
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (err) {
        assistantDiv.textContent = 'Error: ' + err.message;
        assistantDiv.classList.remove('streaming');
    }

    sendBtn.disabled = false;
    input.disabled = false;
    input.focus();
}

function appendMessage(role, content) {
    const chatMessages = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-message ' + role;

    if (role === 'system-info') {
        div.innerHTML = '<em>' + escapeHtml(content) + '</em>';
    } else if (role === 'user') {
        div.innerHTML = '<strong>You:</strong> ' + escapeHtml(content);
    } else {
        div.innerHTML = '<strong>Partner:</strong> ' + formatMessage(content);
    }

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function formatMessage(text) {
    if (!text) return '';

    // Escape HTML first
    let html = escapeHtml(text);

    // Highlight corrections: [correction: 'wrong' -> 'right']
    html = html.replace(
        /\[correction:\s*&#39;([^&]*)&#39;\s*-&gt;\s*&#39;([^&]*)&#39;\]/g,
        '<span class="correction"><s>$1</s> &rarr; <strong>$2</strong></span>'
    );

    // Also handle without quotes
    html = html.replace(
        /\[correction:\s*([^[\]]*?)\s*-&gt;\s*([^[\]]*?)\]/g,
        '<span class="correction"><s>$1</s> &rarr; <strong>$2</strong></span>'
    );

    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
