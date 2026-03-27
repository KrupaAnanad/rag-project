document.addEventListener('DOMContentLoaded', () => {

    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const stopBtn = document.getElementById('stop-btn');
    const typingIndicator = document.getElementById('typing-indicator');
    const chatList = document.getElementById('chat-list');
    const newChatBtn = document.getElementById('new-chat-btn');

    const settingsModal = document.getElementById('settings-modal');
    const openSettingsBtn = document.getElementById('open-settings-btn');
    const apiKeyInput = document.getElementById('api-key-input');
    const updateKeyBtn = document.getElementById('update-key-btn');
    const testKeyBtn = document.getElementById('test-key-btn');
    const clearAllChatsBtn = document.getElementById('clear-all-chats-btn');

    const knowledgeModal = document.getElementById('knowledge-modal');
    const openKnowledgeBtn = document.getElementById('open-knowledge-btn');
    const rebuildBtn = document.getElementById('rebuild-btn');
    const uploadBtn = document.getElementById('upload-btn');
    const fileInput = document.getElementById('file-input');

    const wipeIndexBtn = document.getElementById('wipe-index-btn');

    let currentChatId = null;
    let chats = JSON.parse(localStorage.getItem('aurora_chats')) || [];
    let abortController = null;

    marked.setOptions({ breaks: true });

    // Load saved API key
    const savedKey = localStorage.getItem('genai_api_key');
    if (savedKey) {
        apiKeyInput.value = savedKey;
    }

    function createNewChat() {
        currentChatId = Date.now().toString();
        const newChat = {
            id: currentChatId,
            title: 'New Chat',
            messages: []
        };
        chats.unshift(newChat);
        saveChats();
        clearDisplay();
    }

    function saveChats() {
        localStorage.setItem('aurora_chats', JSON.stringify(chats));
        renderChatList();
    }

    function renderChatList() {
        chatList.innerHTML = '';
        chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = 'chat-item' + (chat.id === currentChatId ? ' active' : '');
            item.innerText = chat.title;
            item.onclick = () => loadChat(chat.id);
            chatList.appendChild(item);
        });
    }

    function loadChat(id) {
        currentChatId = id;
        renderChatList();
        const chat = chats.find(c => c.id === id);
        
        if (chat && chat.messages.length > 0) {
            chatHistory.innerHTML = '';
            chat.messages.forEach(msg => appendMessage(msg.role, msg.content));
        } else {
            clearDisplay();
        }
    }

    function clearDisplay() {
        chatHistory.innerHTML = `
            <div class="welcome-hero">
                <div class="hero-icon"><i class="fa-solid fa-robot"></i></div>
                <h2>Aurora AI</h2>
                <p>Welcome to your neural workstation. Upload documents to the <b>Neural Bank</b> to start a grounded dialogue.</p>
                <div class="features">
                    <div class="feature-tag"><i class="fa-solid fa-bolt"></i> Fast Retrieval</div>
                    <div class="feature-tag"><i class="fa-solid fa-shield-halved"></i> Trusted Logic</div>
                    <div class="feature-tag"><i class="fa-solid fa-quote-right"></i> Direct Citations</div>
                </div>
            </div>
        `;
    }

    function appendMessage(role, text) {
        // Remove welcome hero if it exists
        const hero = chatHistory.querySelector('.welcome-hero');
        if (hero) hero.remove();
        
        // Remove "Start chatting..." p if it somehow exists
        if (chatHistory.innerHTML.includes('Start chatting...')) chatHistory.innerHTML = '';

        const wrapper = document.createElement('div');
        wrapper.className = `message-wrapper ${role}`;
        
        const box = document.createElement('div');
        box.className = 'message-box';
        
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        
        const content = document.createElement('div');
        content.className = 'message-content';
        content.innerHTML = marked.parse(text);
        bubble.appendChild(content);
        
        if (role === 'ai') {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.setAttribute('title', 'Copy code');
            copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
            copyBtn.onclick = () => {
                const textToCopy = content.innerText;
                navigator.clipboard.writeText(textToCopy).then(() => {
                    copyBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
                    copyBtn.style.color = '#10A37F';
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
                        copyBtn.style.color = '';
                    }, 2000);
                });
            };
            bubble.appendChild(copyBtn);
        }
        
        box.appendChild(bubble);
        wrapper.appendChild(box);
        chatHistory.appendChild(wrapper);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        
        return { bubble, content };
    }

    // 🚀 MAIN FIXED FUNCTION
    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;
        
        // Ensure starting area is cleared before first message
        const hero = chatHistory.querySelector('.welcome-hero');
        if (hero) hero.remove();

        const apiKey = localStorage.getItem('genai_api_key') || "";

        if (!currentChatId) createNewChat();
        const chat = chats.find(c => c.id === currentChatId);

        userInput.value = '';
        appendMessage('user', text);

        if (chat.title === 'New Chat') {
            chat.title = text.substring(0, 30) + (text.length > 30 ? '...' : '');
        }

        chat.messages.push({ role: 'user', content: text });
        saveChats();

        typingIndicator.innerText = "Aurora is thinking...";
        typingIndicator.classList.remove('hidden');

        abortController = new AbortController();
        stopBtn.classList.remove('hidden');
        sendBtn.disabled = true;

        try {
            let response = null;
            let attempts = 0;
            const maxRetries = 2; // Up to 3 attempts total

            while (attempts <= maxRetries) {
            try {
                attempts++;
                typingIndicator.innerText = attempts > 1 ? `Retrying (${attempts}/${maxRetries+1})...` : "Connecting to Neural Bank...";
                
                response = await fetch('/chat_stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        api_key: apiKey
                    }),
                    signal: abortController.signal
                });

                if (response.ok) break;

                // Handle server errors that might be worth retrying
                if (response.status >= 500 && attempts <= maxRetries) {
                    console.warn(`Server error ${response.status}, retrying...`);
                    await new Promise(r => setTimeout(r, 2000 * attempts));
                    continue;
                }

                const errData = await response.json();
                appendMessage('ai', "❌ " + (errData.error || "Connection failed"));
                break;

            } catch (err) {
                if (err.name === 'AbortError') {
                    typingIndicator.classList.add('hidden');
                    stopBtn.classList.add('hidden');
                    sendBtn.disabled = false;
                    return;
                }
                
                if (attempts <= maxRetries) {
                    console.warn("Connection error, retrying...", err);
                    await new Promise(r => setTimeout(r, 2000 * attempts));
                    continue;
                }
                
                console.error(err);
                appendMessage('ai', "❌ Connection error occurred.");
                break;
            }
        }

        if (!response || !response.ok) {
            typingIndicator.classList.add('hidden');
            stopBtn.classList.add('hidden');
            sendBtn.disabled = false;
            return;
        }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullText = "";
            let buffer = "";
            const { content: botContent } = appendMessage('ai', "");

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;

                    try {
                        const data = JSON.parse(line);
                        console.log("Stream data:", data); // More logging
                        if (data.error) {
                            botContent.innerHTML = "❌ " + data.error;
                            console.error("Bot AI error detected:", data.error);
                            stopBtn.classList.add('hidden');
                            sendBtn.disabled = false;
                            return;
                        }
                        if (data.chunk) {
                            fullText += data.chunk;
                            botContent.innerHTML = marked.parse(fullText);
                            chatHistory.scrollTop = chatHistory.scrollHeight;
                        }
                    } catch (e) {
                        console.error("JSON parse error:", e, "Line:", line);
                    }
                }
            }

            chat.messages.push({ role: 'assistant', content: fullText });
            saveChats();
            stopBtn.classList.add('hidden');
            sendBtn.disabled = false;

        } catch (err) {
            if (err.name !== 'AbortError') {
                console.error("Final catch:", err);
                appendMessage('ai', "❌ Fatal error during dialogue.");
            }
            typingIndicator.classList.add('hidden');
            stopBtn.classList.add('hidden');
            sendBtn.disabled = false;
        }
    }

    sendBtn.onclick = sendMessage;
    stopBtn.onclick = () => {
        if (abortController) {
            abortController.abort();
            stopBtn.classList.add('hidden');
            sendBtn.disabled = false;
        }
    };

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // Save API key
    updateKeyBtn.onclick = () => {
        const key = apiKeyInput.value.trim();
        localStorage.setItem('genai_api_key', key);
        alert("API key saved!");
        settingsModal.classList.add('hidden');
    };
    testKeyBtn.onclick = async () => {
        const key = apiKeyInput.value.trim();
        testKeyBtn.disabled = true;
        testKeyBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        try {
            const resp = await fetch('/test_api_key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });
            const data = await resp.json();
            if (data.success) alert("✅ " + data.success);
            else alert("❌ " + data.error);
        } catch (e) {
            alert("❌ Network Error: " + e.message);
        } finally {
            testKeyBtn.disabled = false;
            testKeyBtn.innerHTML = '<i class="fa-solid fa-vial"></i>';
        }
    };

    newChatBtn.onclick = createNewChat;

    clearAllChatsBtn.onclick = () => {
        if (confirm("Are you sure you want to delete all conversations?")) {
            chats = [];
            currentChatId = null;
            saveChats();
            clearDisplay();
            settingsModal.classList.add('hidden');
        }
    };

    // Modal Controls
    openSettingsBtn.onclick = () => settingsModal.classList.remove('hidden');
    openKnowledgeBtn.onclick = () => knowledgeModal.classList.remove('hidden');

    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.onclick = () => {
            settingsModal.classList.add('hidden');
            knowledgeModal.classList.add('hidden');
        };
    });

    window.onclick = (e) => {
        if (e.target == settingsModal) settingsModal.classList.add('hidden');
        if (e.target == knowledgeModal) knowledgeModal.classList.add('hidden');
    };

    // Index & Upload
    rebuildBtn.onclick = async () => {
        rebuildBtn.disabled = true;
        rebuildBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Rebuilding...';
        
        try {
            const response = await fetch('/rebuild_stream');
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
                        if (data.success) alert("Neural Bank update complete!");
                        if (data.error) alert("Error rebuilding: " + data.error);
                    } catch (e) {
                        console.error("JSON parse error:", e);
                    }
                }
            }
        } catch (err) {
            console.error(err);
        } finally {
            rebuildBtn.disabled = false;
            rebuildBtn.innerHTML = '<i class="fa-solid fa-rotate"></i><span>Rebuild Index</span>';
        }
    };

    uploadBtn.onclick = () => fileInput.click();
    
    wipeIndexBtn.onclick = async () => {
        if (!confirm("WIPE NEURAL BANK? This deletes everything currently stored.")) return;
        try {
            const resp = await fetch('/index_clear', { method: 'POST' });
            const data = await resp.json();
            if (data.success) alert(data.success);
        } catch (e) {
            console.error("Wipe failed:", e);
        }
    };
    fileInput.onchange = async () => {
        const files = fileInput.files;
        if (files.length === 0) return;

        const formData = new FormData();
        Array.from(files).forEach(f => formData.append('files[]', f));

        try {
            const response = await fetch('/upload', { method: 'POST', body: formData });
            const data = await response.json();
            if (data.success) alert("Files uploaded. Now click Rebuild Index.");
        } catch (err) {
            console.error(err);
        }
    };

    async function updateDocCount() {
        const display = document.getElementById('doc-count-display');
        const dot = document.querySelector('.status-dot');
        if (!display || !dot) return;
        try {
            const resp = await fetch('/docs');
            const data = await resp.json();
            const count = data.docs ? data.docs.length : 0;
            display.innerText = `${count} Doc${count !== 1 ? 's' : ''} Synced`;
            if (count > 0) dot.style.background = "#10A37F";
            else dot.style.background = "#333";
        } catch (e) {
            display.innerText = "Error syncing...";
        }
    }

    updateDocCount();
    setInterval(updateDocCount, 30000); 

    clearDisplay();
    renderChatList();
});