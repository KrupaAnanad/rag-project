import os
import faiss
import pickle
import google.generativeai as genai
from PyPDF2 import PdfReader
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
import json
import time
import speech_recognition as sr
from dotenv import load_dotenv

# ─── CONFIGURATION ──────────────────────────────────────────
load_dotenv()
api_key = os.getenv("api_key") or os.getenv("GOOGLE_API_KEY")

pdf_folder = "pdfs"
txt_folder = "texts"
index_file = "faiss_index.index"
metadata_file = "metadata.pkl"

os.makedirs(pdf_folder, exist_ok=True)
os.makedirs(txt_folder, exist_ok=True)

if not api_key:
    print("⚠️  WARNING: No API key found. Gemini AI features will be disabled.")
    print("Please add 'GOOGLE_API_KEY=your_key' to your .env file.")

genai.configure(api_key=api_key if api_key else "placeholder_key")
model = genai.GenerativeModel("gemini-2.5-flash") 

_embedder = None
def get_embedder():
    global _embedder
    if _embedder is None:
        print("⏳ Loading embedding model...")
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # 50 MB limit
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# ─── MICROPHONE LOGIC ───────────────────────────────────────
def listen_microphone():
    if os.environ.get('RENDER'):
        return {"error": "Voice recognition is not available on server-side deployment."}

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = False

    try:
        with sr.Microphone() as source:
            print("🎤 Adjusting for noise...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            
            print("🎤 Listening NOW... speak clearly!")
            audio = recognizer.listen(
                source,
                timeout=10,
                phrase_time_limit=15
            )
            print("⏳ Processing speech...")
            text = recognizer.recognize_google(audio)
            print(f"✅ You said: {text}")
            return {"text": text}

    except sr.WaitTimeoutError:
        print("⚠️ No speech detected! Try speaking louder.")
        return {"error": "No speech detected. Try speaking louder."}
    except sr.UnknownValueError:
        print("⚠️ Could not understand! Speak clearly.")
        return {"error": "Could not understand. Speak clearly."}
    except sr.RequestError as e:
        print(f"❌ Internet/API error: {e}")
        return {"error": "Speech Recognition API error."}
    except Exception as e:
        print(f"❌ Microphone fault: {e}")
        return {"error": "Microphone hardware not detected."}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ─── LOAD PDF ───────────────────────────────────────────────
def load_pdf(file_path):
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text

# ─── LOAD TXT ───────────────────────────────────────────────
def load_txt(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

# ─── CHUNK TEXT ─────────────────────────────────────────────
def chunk_text(text, chunk_size=200, overlap=40):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

# ─── LOAD FILES FROM DIRECTORIES ────────────────────────────
def load_files_from_directory(pdf_folder, txt_folder):
    files = []
    if os.path.exists(pdf_folder):
        for file in os.listdir(pdf_folder):
            if file.endswith(".pdf"):
                files.append(("pdf", os.path.join(pdf_folder, file)))
    if os.path.exists(txt_folder):
        for file in os.listdir(txt_folder):
            if file.endswith(".txt"):
                files.append(("txt", os.path.join(txt_folder, file)))
    return files

# ─── BUILD FAISS INDEX (STREAMING GENERATOR) ──────────────────────────────────────
def build_index_stream(pdf_folder, txt_folder):
    files = load_files_from_directory(pdf_folder, txt_folder)
    if not files:
        yield json.dumps({"error": "No files found"}) + "\n"
        return

    all_chunks = []
    metadata   = []
    
    yield json.dumps({"status": f"Found {len(files)} files. Starting extraction..."}) + "\n"

    for file_type, file_path in files:
        filename = os.path.basename(file_path)
        yield json.dumps({"file": filename, "status": f"Reading {filename}..."}) + "\n"
        time.sleep(0.1) 
        
        try:
            text = load_pdf(file_path) if file_type == "pdf" else load_txt(file_path)
            if not text.strip(): continue
            chunks = chunk_text(text)
            for chunk in chunks:
                all_chunks.append(chunk)
                metadata.append({"text": chunk, "source": file_path, "type": file_type})
        except Exception as e:
            yield json.dumps({"error": f"Failed reading {filename}: {str(e)}"}) + "\n"
            continue

    if not all_chunks:
        yield json.dumps({"error": "No text could be extracted."}) + "\n"
        return

    yield json.dumps({"status": f"Building embeddings for {len(all_chunks)} chunks..."}) + "\n"
    
    embeddings = get_embedder().encode(all_chunks, convert_to_numpy=True, show_progress_bar=False)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    faiss.write_index(index, index_file)
    with open(metadata_file, "wb") as f:
        pickle.dump(metadata, f)
        
    yield json.dumps({"success": "Index built successfully!", "chunks": len(all_chunks)}) + "\n"

# ─── RETRIEVE DOCUMENTS ─────────────────────────────────────
def retrieve(query, top_k=5):
    if not os.path.exists(index_file) or not os.path.exists(metadata_file):
        return []
    index = faiss.read_index(index_file)
    with open(metadata_file, "rb") as f:
        docs = pickle.load(f)
    query_vec = get_embedder().encode([query], convert_to_numpy=True)
    distances, indices = index.search(query_vec, top_k)
    results = []
    for i in indices[0]:
        if i < len(docs):
            results.append(docs[i])
    return results

# ─── RAG QUERY (STREAMING GENERATOR) ──────────────────────────────────────────────
def AI_assistant_stream(query):
    print(f"🔍 Retrieval for: '{query}'")
    docs = retrieve(query)
    context = ""
    sources = set()

    if not docs:
        print("⚠️ No documents mapped. Sending informative response.")
        yield json.dumps({"chunk": "Knowledge map restricted. Please uplink data into the **Neural Bank** and synchronize via 'Rebuild Index'."}) + "\n"
        return

    print(f"✅ Context found: {len(docs)} chunks mapped.")

    for i, doc in enumerate(docs):
        context += f"[{i+1}] {doc['text']}\n\n"
        sources.add(doc["source"])

    source_names = [os.path.basename(s) for s in list(sources)]
    yield json.dumps({"sources": source_names}) + "\n"

    prompt = f"""
System: Aurora AI Mentor Architecture
Identity: Expert AI Mentor specialized in teaching and simplifying high-level Artificial Intelligence, Machine Learning, and Neural concepts.
Objective: Provide highly educational, structured, and clear synthesis based EXCLUSIVELY on the provided neural context.

Operational Guidelines:
1. Educational Focus: Your primary goal is to teach the user about "AI related topics only". If the context contains non-AI information, pivot the answer to its AI/ML applications if possible.
2. Contextual Integrity: Only use information from the "Neural Context" section. If the answer is not present, respond: "I do not have sufficient data in my current neural curriculum to teach this specific topic."
3. Mentorship Tone: Be encouraging, structured (use bullets), and deeply pedagogical.
4. Code Education: If providing code, explain what each part does from a learner's perspective.
5. Strict Domain: Do not answer questions outside of the AI/ML/Data Science domain.

Neural Context:
{context}

Question:
{query}
"""
    try:
        print("💡 Generating neural synthesis...")
        response = model.generate_content(prompt, stream=True)
        for chunk in response:
            try:
                if chunk.text:
                    yield json.dumps({"chunk": chunk.text}) + "\n"
            except (AttributeError, ValueError) as e:
                print(f"⚠️ Chunk parsing error: {str(e)}")
                continue 
        print("✨ Synthesis complete.")
    except Exception as e:
        print(f"❌ Generation error: {str(e)}")
        yield json.dumps({"error": str(e)}) + "\n"

# ─── FLASK ENDPOINTS ────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat_stream', methods=['POST'])
def chat_stream():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({'error': 'No message provided'}), 400
    query = data['message']
    return Response(stream_with_context(AI_assistant_stream(query)), mimetype='application/x-ndjson')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    files = request.files.getlist('files[]')
    saved_files = []
    
    for file in files:
        if file.filename == '':
            continue
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            if filename.endswith('.pdf'):
                file.save(os.path.join(pdf_folder, filename))
            else:
                file.save(os.path.join(txt_folder, filename))
            saved_files.append(filename)
            
    if saved_files:
        return jsonify({'success': f'Successfully uploaded {len(saved_files)} files'}), 200
    else:
        return jsonify({'error': 'No valid files uploaded.'}), 400

@app.route('/rebuild_stream', methods=['GET'])
def rebuild_index_route():
    return Response(stream_with_context(build_index_stream(pdf_folder, txt_folder)), mimetype='application/x-ndjson')

@app.route('/listen', methods=['POST'])
def listen_route():
    result = listen_microphone()
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 200

@app.route('/docs', methods=['GET'])
def get_docs():
    files = load_files_from_directory(pdf_folder, txt_folder)
    file_list = [os.path.basename(f[1]) for f in files]
    return jsonify({'docs': file_list})

@app.route('/set_key', methods=['POST'])
def set_key():
    global model
    data = request.json
    if not data or 'api_key' not in data:
        return jsonify({'error': 'No API key provided'}), 400
    
    new_key = data['api_key']
    try:
        genai.configure(api_key=new_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        return jsonify({'success': 'API key updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    print("🤖 Server starting...")
    # Auto-build index if missing on startup
    if not os.path.exists(index_file):
        print("🛠️ Knowledge base not found. Initializing neural map...")
        # Note: We don't run build_index_stream here since it returns a generator.
        # We just warn or let the user do it from UI.
    app.run(debug=True, port=5000)