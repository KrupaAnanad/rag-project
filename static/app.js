document.addEventListener('DOMContentLoaded', () => {

    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const stopBtn = document.getElementById('stop-btn');
    const typingIndicator = document.getElementById('typing-indicator');
    const chatList = document.getElementById('chat-list');
    const newChatBtn = document.getElementById('new-chat-btn');

    const settingsModal = document.getElementById('settings-modal');
    const apiKeyInput = document.getElementById('api-key-input');
    const updateKeyBtn = document.getElementById('update-key-btn');

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
            item.className = 'chat-item';
            item.innerText = chat.title;
            item.onclick = () => loadChat(chat.id);
            chatList.appendChild(item);
        });
    }

    function loadChat(id) {
        currentChatId = id;
        const chat = chats.find(c => c.id === id);
        chatHistory.innerHTML = '';
        chat.messages.forEach(msg => appendMessage(msg.role, msg.content));
    }

    function clearDisplay() {
        chatHistory.innerHTML = `<p>Start chatting...</p>`;
    }

    function appendMessage(role, text) {
        const div = document.createElement('div');
        div.className = role;
        div.innerHTML = marked.parse(text);
        chatHistory.appendChild(div);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // 🚀 MAIN FIXED FUNCTION
    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        const apiKey = localStorage.getItem('genai_api_key');

        if (!apiKey) {
            alert("Please enter API key in settings");
            return;
        }

        if (!currentChatId) createNewChat();
        const chat = chats.find(c => c.id === currentChatId);

        userInput.value = '';
        appendMessage('user', text);

        chat.messages.push({ role: 'user', content: text });
        saveChats();

        typingIndicator.style.display = 'block';

        abortController = new AbortController();

        try {
            const response = await fetch('/chat_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    api_key: apiKey   // 🔥 FIX
                }),
                signal: abortController.signal
            });

            typingIndicator.style.display = 'none';

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            let fullText = "";
            const aiDiv = document.createElement('div');
            aiDiv.className = 'ai';
            chatHistory.appendChild(aiDiv);

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const lines = decoder.decode(value).split('\n');

                for (const line of lines) {
                    if (!line.trim()) continue;

                    const data = JSON.parse(line);

                    if (data.error) {
                        aiDiv.innerHTML = "❌ " + data.error;
                        return;
                    }

                    if (data.chunk) {
                        fullText += data.chunk;
                        aiDiv.innerHTML = marked.parse(fullText);
                        chatHistory.scrollTop = chatHistory.scrollHeight;
                    }
                }
            }

            chat.messages.push({ role: 'assistant', content: fullText });
            saveChats();

        } catch (err) {
            console.error(err);
            typingIndicator.style.display = 'none';
        }
    }

    sendBtn.onclick = sendMessage;

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

    newChatBtn.onclick = createNewChat;

    clearDisplay();
    renderChatList();
});