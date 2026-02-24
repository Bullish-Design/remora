const eventsList = document.getElementById('events-list');
const blockedAgents = document.getElementById('blocked-agents');
const agentStatus = document.getElementById('agent-status');
const results = document.getElementById('results');
const connectionStatus = document.getElementById('connection-status');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const clearEventsBtn = document.getElementById('clear-events');

const agents = new Map();
const blocked = new Map();
const resultsList = [];
let ws = null;
let eventCount = 0;

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function addEvent(event) {
    eventCount++;
    
    const div = document.createElement('div');
    div.className = `event ${event.category}_${event.action}`;
    
    const time = new Date(event.timestamp).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    
    let html = `
        <span class="event-time">${time}</span>
        <span class="event-type">${event.category}:${event.action}</span>
    `;
    
    if (event.agent_id) {
        html += `<span class="event-agent">@${escapeHtml(event.agent_id)}</span>`;
    }
    
    if (event.payload && Object.keys(event.payload).length > 0) {
        const payloadStr = JSON.stringify(event.payload, null, 2);
        html += `<div class="event-payload">${escapeHtml(payloadStr)}</div>`;
    }
    
    div.innerHTML = html;
    eventsList.insertBefore(div, eventsList.firstChild);
    
    if (eventsList.children.length > 200) {
        eventsList.removeChild(eventsList.lastChild);
    }
}

function updateAgentStatus(event) {
    const id = event.agent_id;
    if (!id) return;
    
    if (!agents.has(id)) {
        agents.set(id, { 
            state: 'pending', 
            name: event.payload?.name || id,
            events: [] 
        });
    }
    
    const agent = agents.get(id);
    agent.state = event.action;
    agent.lastEvent = event;
    
    renderAgents();
    updateProgress();
}

function handleBlocked(event) {
    const id = event.agent_id;
    const question = event.payload?.question || 'Unknown question';
    const key = `${id}:${question}`;
    
    blocked.set(key, { 
        agent_id: id, 
        question, 
        options: event.payload?.options 
    });
    
    renderBlocked();
}

function handleResumed(event) {
    const id = event.agent_id;
    const question = event.payload?.question;
    
    if (question) {
        const key = `${id}:${question}`;
        blocked.delete(key);
        renderBlocked();
    }
}

function handleCompleted(event) {
    const id = event.agent_id;
    
    if (event.payload) {
        resultsList.unshift({
            agent_id: id,
            content: event.payload.result || JSON.stringify(event.payload, null, 2),
            timestamp: new Date()
        });
        
        if (resultsList.length > 50) {
            resultsList.pop();
        }
        
        renderResults();
    }
    
    updateProgress();
}

function renderAgents() {
    if (agents.size === 0) {
        agentStatus.innerHTML = '<div class="empty-state">No agents running</div>';
        return;
    }
    
    agentStatus.innerHTML = Array.from(agents.entries()).map(([id, a]) => `
        <div class="agent-item">
            <span class="state-indicator ${a.state}"></span>
            <span class="agent-name">${escapeHtml(a.name || id)}</span>
            <span class="agent-state">${a.state}</span>
        </div>
    `).join('');
}

function renderBlocked() {
    if (blocked.size === 0) {
        blockedAgents.innerHTML = '<div class="empty-state">No agents waiting for input</div>';
        return;
    }
    
    blockedAgents.innerHTML = Array.from(blocked.entries()).map(([key, b]) => `
        <div class="blocked-agent" data-key="${escapeHtml(key)}">
            <div class="agent-id">@${escapeHtml(b.agent_id)}</div>
            <div class="question">${escapeHtml(b.question)}</div>
            <div class="response-form">
                ${b.options && b.options.length > 0 ? `
                    <select id="answer-${key.replace(/[^a-zA-Z0-9]/g, '_')}">
                        ${b.options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('')}
                    </select>
                ` : `
                    <input type="text" 
                           id="answer-${key.replace(/[^a-zA-Z0-9]/g, '_')}" 
                           placeholder="Your response..." 
                           autocomplete="off" />
                `}
                <button onclick="respond('${escapeHtml(key)}')">Send</button>
            </div>
        </div>
    `).join('');
}

function renderResults() {
    if (resultsList.length === 0) {
        results.innerHTML = '<div class="empty-state">No results yet</div>';
        return;
    }
    
    results.innerHTML = resultsList.map(r => `
        <div class="result-item">
            <div class="result-agent">${escapeHtml(r.agent_id)}</div>
            <div class="result-content">${escapeHtml(r.content)}</div>
        </div>
    `).join('');
}

function updateProgress() {
    const total = agents.size;
    const completed = Array.from(agents.values()).filter(a => 
        a.state === 'completed' || a.state === 'failed' || a.state === 'cancelled'
    ).length;
    
    if (total === 0) {
        progressFill.style.width = '0%';
        progressText.textContent = 'Ready';
    } else {
        const percent = Math.round((completed / total) * 100);
        progressFill.style.width = `${percent}%`;
        progressText.textContent = `${completed}/${total} agents completed`;
    }
}

async function respond(key) {
    const select = document.querySelector(`#answer-${key.replace(/[^a-zA-Z0-9]/g, '_')}`);
    const input = document.querySelector(`#answer-${key.replace(/[^a-zA-Z0-9]/g, '_')}`);
    
    const answer = (select || input)?.value;
    if (!answer) return;
    
    const [agent_id, question] = key.split(':');
    
    try {
        const response = await fetch(`/agent/${encodeURIComponent(agent_id)}/respond`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                question: question,
                answer: answer 
            })
        });
        
        if (response.ok) {
            blocked.delete(key);
            renderBlocked();
        }
    } catch (error) {
        console.error('Failed to send response:', error);
    }
}

function handleEvent(event) {
    addEvent(event);
    
    if (event.category === 'agent') {
        updateAgentStatus(event);
        
        if (event.action === 'blocked') {
            handleBlocked(event);
        } else if (event.action === 'resumed') {
            handleResumed(event);
        } else if (event.action === 'completed') {
            handleCompleted(event);
        }
    } else if (event.category === 'graph') {
        if (event.action === 'started') {
            progressFill.style.width = '0%';
            progressText.textContent = 'Starting...';
        } else if (event.action === 'completed') {
            progressFill.style.width = '100%';
            progressText.textContent = 'Completed';
        } else if (event.action === 'failed') {
            progressFill.style.width = '100%';
            progressFill.style.background = '#f85149';
            progressText.textContent = 'Failed: ' + (event.payload?.error || 'Unknown error');
        }
    }
}

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/events`);
    
    ws.onopen = () => {
        connectionStatus.textContent = 'Connected';
        connectionStatus.classList.add('connected');
    };
    
    ws.onclose = () => {
        connectionStatus.textContent = 'Disconnected';
        connectionStatus.classList.remove('connected');
        setTimeout(connect, 2000);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onmessage = (e) => {
        try {
            const event = JSON.parse(e.data);
            handleEvent(event);
        } catch (error) {
            console.error('Failed to parse event:', error);
        }
    };
}

if (clearEventsBtn) {
    clearEventsBtn.addEventListener('click', () => {
        eventsList.innerHTML = '';
        eventCount = 0;
    });
}

window.respond = respond;
connect();
