# Aurora AI // Neural Interface 🧠

Aurora is a professional RAG-based AI assistant built with **Flask**, **Google Gemini**, and **FAISS**. It allows for high-performance retrieval and response generation based on your personal neural bank (PDFs and Text documents).

## 🚀 Key Features
- **RAG (Retrieval Augmented Generation)**: Strictly cites sources from uploaded documents.
- **Neural Interface**: Beautifully designed modern chat UI with slate and mercury aesthetics.
- **High Performance**: Uses FAISS for lightning-fast similarity search and `all-MiniLM-L6-v2` for embeddings.
- **Support for PDFs & TXT**: Automatically parses and chunks documents.

## 🛠️ Setup Instructions

### 1. Prerequisites
- Python 3.10 or higher.
- A Google Gemini API Key.

### 2. Installations
Clone the repository and install dependencies:
```bash
git clone <your-repo-url>
cd rag-project
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```text
GOOGLE_API_KEY=your_gemini_api_key_here
PORT=5000
```

### 4. Running the App
Start the Flask server:
```bash
python app.py
```

## 📂 Project Structure
- `app.py`: Core Flask application and RAG logic.
- `static/`: CSS and Javascript assets.
- `templates/`: HTML interface.
- `pdfs/`, `texts/`: Neural bank storage (ignored by git, contents only).
- `requirements.txt`: Project dependencies.

## ⚠️ Important Notes
- The server initializes the embedding model lazily on the first request (first message might take a few seconds).
- All source citing is strictly enforced via system prompts.

## 🛡️ License
MIT License.
