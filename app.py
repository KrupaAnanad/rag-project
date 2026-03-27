import os
from dotenv import load_dotenv
load_dotenv(override=True)
print(f"DEBUG: GOOGLE_API_KEY from .env is {'Found' if os.environ.get('GOOGLE_API_KEY') else 'NOT Found'}")

import faiss
import pickle
import json
import time
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader
import speech_recognition as sr

# ─── CONFIG ──────────────────────────────────────────
pdf_folder = "pdfs"
txt_folder = "texts"
index_file = "faiss_index.index"
metadata_file = "metadata.pkl"

os.makedirs(pdf_folder, exist_ok=True)
os.makedirs(txt_folder, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# ─── EMBEDDING MODEL (LAZY LOAD) ─────────────────────
_embedder = None
def get_embedder():
    global _embedder
    if _embedder is None:
        print("⏳ Loading embedding model...")
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder

# ─── FILE HELPERS ────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_pdf(file_path):
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            text += t + "\n"
    return text

def load_txt(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def chunk_text(text, chunk_size=200, overlap=40):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks

def load_files_from_directory(pdf_folder, txt_folder):
    files = []
    if os.path.exists(pdf_folder):
        for f in os.listdir(pdf_folder):
            if f.endswith(".pdf"):
                files.append(("pdf", os.path.join(pdf_folder, f)))
    if os.path.exists(txt_folder):
        for f in os.listdir(txt_folder):
            if f.endswith(".txt"):
                files.append(("txt", os.path.join(txt_folder, f)))
    return files

# ─── BUILD INDEX ─────────────────────────────────────
def build_index_stream(pdf_folder, txt_folder):
    files = load_files_from_directory(pdf_folder, txt_folder)

    if not files:
        yield json.dumps({"error": "No files found"}) + "\n"
        return

    all_chunks = []
    metadata = []

    yield json.dumps({"status": f"Processing {len(files)} files"}) + "\n"

    for ftype, path in files:
        try:
            text = load_pdf(path) if ftype == "pdf" else load_txt(path)
            chunks = chunk_text(text)
            for c in chunks:
                all_chunks.append(c)
                metadata.append({"text": c, "source": path})
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    embeddings = get_embedder().encode(all_chunks)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    faiss.write_index(index, index_file)

    with open(metadata_file, "wb") as f:
        pickle.dump(metadata, f)

    yield json.dumps({"success": "Index built"}) + "\n"

# ─── RETRIEVE ───────────────────────────────────────
def retrieve(query, top_k=5):
    if not os.path.exists(index_file):
        return []

    index = faiss.read_index(index_file)
    docs = pickle.load(open(metadata_file, "rb"))

    query_vec = get_embedder().encode([query])
    _, indices = index.search(query_vec, top_k)

    return [docs[i] for i in indices[0] if i < len(docs)]

# ─── STREAM AI RESPONSE (WITH RETRIES) ────────────────
def AI_assistant_stream(query, api_key):
    import google.generativeai as genai

    model_name = "gemini-2.5-flash" # Updated as per your latest preference
    try:
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction="""You are 'Aurora', a friendly and expert neural assistant. 
            Greet the user warmly when they say hi. 
            For factual questions: You are strictly forbidden from using any internal or general world knowledge. 
            You must ONLY use the provided Context to answer. If the information is not present in the Context, 
            briefly say: 'I don't have the information'. 
            CRITICAL: ALWAYS cite your sources (the filename) for every claim you make."""
        )
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
             yield json.dumps({"error": f"Model Initialization Failed (404): Model '{model_name}' not found. Please check your model name or API access."}) + "\n"
        else:
             yield json.dumps({"error": f"Model Initialization Failed: {error_msg}"}) + "\n"
        return

    docs = retrieve(query)
    
    # Simple Greeting Heuristic
    is_greeting = query.lower().strip() in ["hi", "hello", "hey", "greetings"]
    
    if not docs and not is_greeting:
        yield json.dumps({"chunk": "No data available. Upload documents first."}) + "\n"
        return

    context = ""
    if docs:
        context = "\n".join([f"Source: {d.get('source', 'Unknown')}\nText: {d['text']}" for d in docs])
    
    if is_greeting:
        prompt = f"GREETING: {query}\nTASK: Greet the user as Aurora. Do not mention documents unless asked."
    else:
        # Factual query
        prompt = f"""
USER QUESTION:
{query}

DATA FROM NEURAL BANK:
---
{context if context else 'EMPTY STORE'}
---

FINAL INSTRUCTION: 
If the DATA above contains the answer, use it and cite the filename.
If the DATA is EMPTY or does not contain the answer, say "I don't have the information in my current bank."
"""

    # Generation with Retry Loop
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text:
                    yield json.dumps({"chunk": chunk.text}) + "\n"
            return # Successful completion
            
        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower() or "too many requests" in error_msg.lower() or "500" in error_msg:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
            
            yield json.dumps({"error": f"AI Error: {error_msg}"}) + "\n"
            return

# ─── ROUTES ─────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat_stream', methods=['POST'])
def chat_stream():
    data = request.json

    query = data.get('message')
    # Better API key extraction: use request JSON, then os environment
    api_key_provided = data.get('api_key', '').strip()
    api_key = api_key_provided if api_key_provided else os.environ.get("GOOGLE_API_KEY")

    if not query:
        return jsonify({"error": "No message"}), 400

    if not api_key:
        return jsonify({"error": "API key required (set GOOGLE_API_KEY in .env or provide it in request)"}), 400

    # Mask key for privacy
    masked_key = f"{api_key[:10]}..." if (api_key and len(api_key) > 5) else "NONE"
    
    # Correct model name: sometimes the 'models/' prefix is needed, sometimes not.
    # We already have 'models/gemini-2.5-flash' which we verified earlier.
    model_name = "gemini-2.5-flash"
    
    print(f"📡 AI stream request: model={model_name} key={masked_key}")

    # Fallback to .env if front-end didn't send anything valid
    if not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")
        print("DEBUG: Using fallback GOOGLE_API_KEY from environment.")

    return Response(
        stream_with_context(AI_assistant_stream(query, api_key)),
        mimetype='application/x-ndjson'
    )

@app.route('/test_api_key', methods=['POST'])
def test_api():
    import google.generativeai as genai
    data = request.json
    api_key_provided = data.get('api_key', '').strip()
    api_key = api_key_provided if api_key_provided else os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"error": "No API Key provided in request or .env"})
    
    try:
        genai.configure(api_key=api_key)
        # Try listing models as a quick test
        genai.list_models()
        return jsonify({"success": "API Key is valid and working."})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist("files[]")

    for file in files:
        if file and allowed_file(file.filename):
            name = secure_filename(file.filename)
            if name.endswith(".pdf"):
                file.save(os.path.join(pdf_folder, name))
            else:
                file.save(os.path.join(txt_folder, name))

    return jsonify({"success": "Uploaded"})

@app.route('/rebuild_stream')
def rebuild():
    return Response(
        stream_with_context(build_index_stream(pdf_folder, txt_folder)),
        mimetype='application/x-ndjson'
    )

@app.route('/index_clear', methods=['POST'])
def clear_index():
    try:
        if os.path.exists(index_file): os.remove(index_file)
        if os.path.exists(metadata_file): os.remove(metadata_file)
        return jsonify({"success": "Neural Bank wiped. You can now rebuild with new documents."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/docs')
def docs():
    files = load_files_from_directory(pdf_folder, txt_folder)
    return jsonify({"docs": [os.path.basename(f[1]) for f in files]})

# ─── RUN ────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server starting on port {port}...")
    # Enable debug mode for auto-reloading
    # Disable the reloader to prevent loops with heavy libraries like sentence-transformers
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)