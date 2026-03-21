import os
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

# ─── STREAM AI RESPONSE (FIXED) ──────────────────────
def AI_assistant_stream(query, api_key):
    import google.generativeai as genai

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        yield json.dumps({"error": f"Invalid API Key: {str(e)}"}) + "\n"
        return

    docs = retrieve(query)

    if not docs:
        yield json.dumps({"chunk": "No data available. Upload documents first."}) + "\n"
        return

    context = "\n".join([d["text"] for d in docs])

    prompt = f"""
Context:
{context}

Question:
{query}
"""

    try:
        response = model.generate_content(prompt, stream=True)
        for chunk in response:
            if chunk.text:
                yield json.dumps({"chunk": chunk.text}) + "\n"
    except Exception as e:
        yield json.dumps({"error": str(e)}) + "\n"

# ─── ROUTES ─────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat_stream', methods=['POST'])
def chat_stream():
    data = request.json

    query = data.get('message')
    api_key = data.get('api_key')

    if not query:
        return jsonify({"error": "No message"}), 400

    if not api_key:
        return jsonify({"error": "API key required"}), 400

    return Response(
        stream_with_context(AI_assistant_stream(query, api_key)),
        mimetype='application/x-ndjson'
    )

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

@app.route('/docs')
def docs():
    files = load_files_from_directory(pdf_folder, txt_folder)
    return jsonify({"docs": [os.path.basename(f[1]) for f in files]})

# ─── RUN ────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("🚀 Server running...")
    app.run(host="0.0.0.0", port=port)