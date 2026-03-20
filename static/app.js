document.addEventListener('DOMContentLoaded', () => {
    // ─── DOM MAP ───
    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const stopBtn = document.getElementById('stop-btn');
    const typingIndicator = document.getElementById('typing-indicator');
    const chatList = document.getElementById('chat-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    
    // Modals
    const knowledgeModal = document.getElementById('knowledge-modal');
    const settingsModal = document.getElementById('settings-modal');
    const openKnowledgeBtn = document.getElementById('open-knowledge-btn');
    const openSettingsBtn = document.getElementById('open-settings-btn');
    const closeBtns = document.querySelectorAll('.close-modal');
    
    // Actions
    const uploadBtn = document.getElementById('upload-btn');
    const fileInput = document.getElementById('file-input');
    const rebuildBtn = document.getElementById('rebuild-btn');
    const apiKeyInput = document.getElementById('api-key-input');
    const updateKeyBtn = document.getElementById('update-key-btn');
    const clearAllChatsBtn = document.getElementById('clear-all-chats-btn');
    
    const docCountDisplay = document.getElementById('doc-count-display');
    const statusDot = document.querySelector('.status-dot');

    // ─── STATE ───
    let currentChatId = null;
    let chats = JSON.parse(localStorage.getItem('aurora_chats')) || [];
    let abortController = null;

    // ─── INIT ───
    marked.setOptions({ breaks: true });
    
    const savedKey = localStorage.getItem('genai_api_key');
    if (savedKey) {
        apiKeyInput.value = savedKey;
        syncApiKey(savedKey, false);
    }

    renderChatList();
    fetchDocuments();

    // ─── MODALS ───
    openKnowledgeBtn.onclick = () => knowledgeModal.classList.remove('hidden');
    openSettingsBtn.onclick = () => settingsModal.classList.remove('hidden');
    closeBtns.forEach(btn => btn.onclick = () => {
        knowledgeModal.classList.add('hidden');
        settingsModal.classList.add('hidden');
    });
    window.onclick = (e) => {
        if (e.target === knowledgeModal) knowledgeModal.classList.add('hidden');
        if (e.target === settingsModal) settingsModal.classList.add('hidden');
    };

    // ─── CONVERSATION LOGIC ───
    function createNewChat() {
        currentChatId = Date.now().toString();
        const newChat = {
            id: currentChatId,
            title: 'New Interface',
            messages: [],
            timestamp: new Date().toISOString()
        };
        chats.unshift(newChat);
        saveAndRender();
        clearDisplay();
    }

    function saveAndRender() {
        localStorage.setItem('aurora_chats', JSON.stringify(chats));
        renderChatList();
    }

    function renderChatList() {
        chatList.innerHTML = '';
        if (chats.length === 0) {
            chatList.innerHTML = '<div class="chat-item">No memories yet...</div>';
            return;
        }

        chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
            item.innerHTML = `
                <i class="fa-regular fa-comment-dots"></i>
                <span class="truncate">${chat.title}</span>
            `;
            item.onclick = () => loadChat(chat.id);
            chatList.appendChild(item);
        });
    }

    function loadChat(id) {
        currentChatId = id;
        const chat = chats.find(c => c.id === id);
        if (!chat) return;

        chatHistory.innerHTML = '';
        chat.messages.forEach(msg => {
            appendMessageToUI(msg.role, msg.content);
        });
        
        renderChatList();
        scrollToBottom();
    }

    function clearDisplay() {
        chatHistory.innerHTML = `
            <div class="welcome-hero">
                <div class="hero-icon"><i class="fa-solid fa-graduation-cap"></i></div>
                <h2>Aurora AI Mentor</h2>
                <p>I am your Advanced Research Assistant. I specialize in teaching about ai related topics only.</p>
                <div class="features">
                    <span><i class="fa-solid fa-brain"></i> Neural Concepts</span>
                    <span><i class="fa-solid fa-code"></i> Model Synthesis</span>
                    <span><i class="fa-solid fa-book-open"></i> AI Foundations</span>
                </div>
                <p class="small">Ask me anything about ML, Neural Networks, or NLP.</p>
            </div>
        `;
        scrollToBottom();
    }

    // Chat Search Logic
    const searchInput = document.createElement('input');
    searchInput.className = 'history-search';
    searchInput.placeholder = 'Search synapses...';
    document.querySelector('.sidebar-top').insertBefore(searchInput, chatList);

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        document.querySelectorAll('.chat-item').forEach(item => {
            const text = item.innerText.toLowerCase();
            item.classList.toggle('hidden', !text.includes(query));
        });
    });

    newChatBtn.onclick = createNewChat;
    
    // Initial State
    clearDisplay();

    clearAllChatsBtn.onclick = () => {
        if (confirm("Pruge all session data? This is permanent.")) {
            chats = [];
            currentChatId = null;
            saveAndRender();
            clearDisplay();
            settingsModal.classList.add('hidden');
        }
    };

    // ─── MESSAGING CORE ───
    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = userInput.scrollHeight + 'px';
        sendBtn.disabled = userInput.value.trim() === '';
    });

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if(!sendBtn.disabled) sendMessage();
        }
    });

    sendBtn.onclick = sendMessage;
    
    stopBtn.onclick = () => {
        if (abortController) {
            abortController.abort();
            showToast("Generation stopped", "info");
        }
    };

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;
        if (!currentChatId) createNewChat();
        const chat = chats.find(c => c.id === currentChatId);
        
        if (chat.messages.length === 0) {
            chat.title = text.length > 20 ? text.substring(0, 18) + '...' : text;
            renderChatList();
        }

        userInput.value = '';
        userInput.style.height = 'auto';
        sendBtn.disabled = true;
        sendBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');

        // User Message UI
        chat.messages.push({ role: 'user', content: text });
        appendMessageToUI('user', text);
        saveAndRender();

        typingIndicator.classList.remove('hidden');
        scrollToBottom();

        abortController = new AbortController();

        try {
            const response = await fetch('/chat_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text }),
                signal: abortController.signal
            });

            typingIndicator.classList.add('hidden');
            const { bubble: aiBubble, avatar: aiAvatar } = createAiBubbleContainer();
            let fullText = "";

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const lines = decoder.decode(value).split('\n');
                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        if (data.chunk) {
                            fullText += data.chunk;
                            aiBubble.innerHTML = marked.parse(fullText) + '<span class="cursor"></span>' + addCopyBtn();
                            scrollToBottom();
                        }
                    } catch(e) {}
                }
            }
            
            aiAvatar.classList.remove('thinking');
            aiBubble.innerHTML = marked.parse(fullText) + addCopyBtn();
            chat.messages.push({ role: 'assistant', content: fullText });
            saveAndRender();

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Stream aborted');
            } else {
                console.error('Fetch error:', error);
            }
            typingIndicator.classList.add('hidden');
        } finally {
            sendBtn.classList.remove('hidden');
            stopBtn.classList.add('hidden');
            abortController = null;
        }
    }

    function appendMessageToUI(sender, text) {
        const wrap = document.createElement('div');
        wrap.className = `message-wrapper ${sender}`;
        const icon = sender === 'user' ? 'fa-user' : 'fa-robot';
        const extra = sender === 'ai' ? addCopyBtn() : '';
        wrap.innerHTML = `
            <div class="message-box">
                <div class="avatar"><i class="fa-solid ${icon}"></i></div>
                <div class="bubble">${marked.parse(text)}${extra}</div>
            </div>
        `;
        chatHistory.appendChild(wrap);
    }

    function createAiBubbleContainer() {
        const wrap = document.createElement('div');
        wrap.className = `message-wrapper ai`;
        wrap.innerHTML = `
            <div class="message-box">
                <div class="avatar thinking"><i class="fa-solid fa-robot"></i></div>
                <div class="bubble"></div>
            </div>
        `;
        chatHistory.appendChild(wrap);
        return { 
            bubble: wrap.querySelector('.bubble'), 
            avatar: wrap.querySelector('.avatar') 
        };
    }

    function addCopyBtn() {
        return `<button class="copy-btn" title="Copy response"><i class="fa-regular fa-copy"></i></button>`;
    }

    // Delegate copy clicks
    chatHistory.addEventListener('click', (e) => {
        const btn = e.target.closest('.copy-btn');
        if (btn) {
            const bubble = btn.closest('.bubble');
            const textToCopy = bubble.innerText.replace(/\n\n/g, '\n'); // Basic cleanup
            navigator.clipboard.writeText(textToCopy).then(() => {
                const icon = btn.querySelector('i');
                icon.className = 'fa-solid fa-check';
                setTimeout(() => icon.className = 'fa-regular fa-copy', 2000);
            });
        }
    });

    function scrollToBottom() {
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // ─── SERVICES ───
    uploadBtn.onclick = () => fileInput.click();
    fileInput.onchange = async (e) => {
        if (!e.target.files.length) return;
        uploadBtn.innerHTML = `<i class="fa-solid fa-sync fa-spin"></i><span>Linking...</span>`;
        const formData = new FormData();
        Array.from(e.target.files).forEach(f => formData.append('files[]', f));
        try {
            await fetch('/upload', { method: 'POST', body: formData });
            showToast("Neural data injected", "success");
            fetchDocuments();
        } finally {
            uploadBtn.innerHTML = `<i class="fa-solid fa-upload"></i><span>Upload Documents</span>`;
        }
    };

    rebuildBtn.onclick = async () => {
        rebuildBtn.disabled = true;
        rebuildBtn.innerHTML = `<i class="fa-solid fa-sync fa-spin"></i>`;
        try {
            const res = await fetch('/rebuild_stream');
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const lines = decoder.decode(value).split('\n');
                for(let l of lines) {
                    if(!l.trim()) continue;
                    let d = JSON.parse(l);
                    if(d.success) { showToast("Brain map updated", "success"); fetchDocuments(); }
                }
            }
        } finally {
            rebuildBtn.disabled = false;
            rebuildBtn.innerHTML = `<i class="fa-solid fa-rotate"></i><span>Rebuild Index</span>`;
        }
    };

    async function fetchDocuments() {
        try {
            const res = await fetch('/docs');
            const data = await res.json();
            if (data.docs) {
                docCountDisplay.innerText = data.docs.length > 0 ? `${data.docs.length} Sources` : "Ready";
                statusDot.classList.toggle('online', data.docs.length > 0);
            }
        } catch (err) {}
    }

    async function syncApiKey(key, feedback) {
        if (!key) return;
        updateKeyBtn.innerHTML = `<i class="fa-solid fa-sync fa-spin"></i>`;
        try {
            const res = await fetch('/set_key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });
            const data = await res.json();
            if (data.success) {
                localStorage.setItem('genai_api_key', key);
                if(feedback) showToast("Neural Link Active", "success");
            } else {
                if(feedback) showToast("Link Failed: " + data.error, "error");
            }
        } finally { updateKeyBtn.innerHTML = `<i class="fa-solid fa-floppy-disk"></i>`; }
    }

    updateKeyBtn.onclick = () => syncApiKey(apiKeyInput.value.trim(), true);

    function showToast(msg, type) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerText = msg;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
});
