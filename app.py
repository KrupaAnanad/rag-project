import os
import json
import time
import pickle
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# LangChain Imports
from langchain_community.document_loaders import PyPDFDirectoryLoader, TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder

# Load environment variables
load_dotenv(override=True)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ─── CONFIG ──────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
pdf_folder = os.path.join(BASE_DIR, "pdfs")
txt_folder = os.path.join(BASE_DIR, "texts")
faiss_db_path = os.path.join(BASE_DIR, "faiss_index") # LangChain FAISS saves to a directory

os.makedirs(pdf_folder, exist_ok=True)
os.makedirs(txt_folder, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# ─── MODELS (LAZY LOAD) ──────────────────────────────
_embeddings = None
_re_ranker = None

def get_embeddings():
    global _embeddings
    if _embeddings is None:
        print("⏳ Loading HuggingFace Embeddings...")
        _embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return _embeddings

def get_re_ranker():
    global _re_ranker
    if _re_ranker is None:
        print("⏳ Loading Cross-Encoder...")
        _re_ranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    return _re_ranker

# ─── FILE HELPERS ────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    try:
        yield json.dumps({"status": "Loading documents..."}) + "\n"
        
        documents = []
        
        # Load PDFs using PyPDFDirectoryLoader
        if os.path.exists(pdf_folder) and any(f.endswith('.pdf') for f in os.listdir(pdf_folder)):
            pdf_loader = PyPDFDirectoryLoader(pdf_folder)
            documents.extend(pdf_loader.load())
        
        # Load TXT files
        if os.path.exists(txt_folder) and any(f.endswith('.txt') for f in os.listdir(txt_folder)):
            txt_loader = DirectoryLoader(txt_folder, glob="*.txt", loader_cls=TextLoader)
            documents.extend(txt_loader.load())

        if not documents:
            yield json.dumps({"error": "No documents found in pdfs/ or texts/ folders."}) + "\n"
            return

        yield json.dumps({"status": f"Loaded {len(documents)} document pages. Splitting text..."}) + "\n"
        
        # Split text using RecursiveCharacterTextSplitter
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_documents(documents)
        
        yield json.dumps({"status": f"Created {len(chunks)} chunks. Generating embeddings and building index..."}) + "\n"
        
        # Create FAISS index
        vectorstore = FAISS.from_documents(chunks, get_embeddings())
        
        # Save index locally
        vectorstore.save_local(faiss_db_path)
        
        yield json.dumps({"success": "Neural Bank rebuilt successfully with LangChain FAISS."}) + "\n"
    except Exception as e:
        yield json.dumps({"error": f"Index Build Error: {str(e)}"}) + "\n"

# ─── RETRIEVE & RE-RANK ──────────────────────────────
def retrieve(query, top_k=10, final_k=5):
    if not os.path.exists(faiss_db_path):
        return []

    # Load FAISS index
    embeddings = get_embeddings()
    vectorstore = FAISS.load_local(faiss_db_path, embeddings, allow_dangerous_deserialization=True)
    
    # Initial retrieval (top_k)
    initial_docs = vectorstore.similarity_search(query, k=top_k)
    
    if not initial_docs:
        return []

    # Re-rank using Cross-Encoder
    re_ranker = get_re_ranker()
    sentence_pairs = [[query, doc.page_content] for doc in initial_docs]
    scores = re_ranker.predict(sentence_pairs)
    
    # Sort docs by score
    results = sorted(zip(initial_docs, scores), key=lambda x: x[1], reverse=True)
    
    # Return top final_k docs
    return [{"text": doc.page_content, "source": doc.metadata.get("source", "Unknown")} for doc, score in results[:final_k]]

# ─── STREAM AI RESPONSE ──────────────────────────────
def AI_assistant_stream(query, api_key):
    from groq import Groq

    model_name = "llama-3.3-70b-versatile"
    try:
        client = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"))
    except Exception as e:
        yield json.dumps({"error": f"Model Initialization Failed: {str(e)}"}) + "\n"
        return

    system_instruction = """You are 'Aurora', a friendly and expert neural assistant. 
    Greet the user warmly when they say hi. 
    For factual questions: You are strictly forbidden from using any internal or general world knowledge. 
    You must ONLY use the provided Context to answer. If the information is not present in the Context, 
    briefly say: 'I don't have the information'. 
    CRITICAL: ALWAYS cite your sources (the filename) for every claim you make."""

    messages = [{"role": "system", "content": system_instruction}]

    docs = retrieve(query)
    is_greeting = query.lower().strip() in ["hi", "hello", "hey", "greetings"]
    
    if not docs and not is_greeting:
        yield json.dumps({"chunk": "No data available in the Neural Bank. Please upload documents and Rebuild Index."}) + "\n"
        return

    context = "\n".join([f"Source: {d.get('source', 'Unknown')}\nText: {d['text']}" for d in docs])
    
    if is_greeting:
        prompt = f"GREETING: {query}\nTASK: Greet the user as Aurora. Do not mention documents unless asked."
    else:
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

    messages.append({"role": "user", "content": prompt})

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True
        )
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                yield json.dumps({"chunk": chunk.choices[0].delta.content}) + "\n"
    except Exception as e:
        yield json.dumps({"error": f"AI Error: {str(e)}"}) + "\n"

# ─── ROUTES ─────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat_stream', methods=['POST'])
def chat_stream():
    data = request.json
    query = data.get('message')
    # Force use of Groq API Key from env to avoid pushing hardcoded key to GitHub
    api_key = os.getenv("GROQ_API_KEY")

    if not query: return jsonify({"error": "No message"}), 400

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
            target = os.path.join(pdf_folder, name) if name.endswith(".pdf") else os.path.join(txt_folder, name)
            file.save(target)
    return jsonify({"success": "Uploaded"})

@app.route('/test_api_key', methods=['POST'])
def test_api():
    from groq import Groq
    data = request.json
    # Force use of Groq API Key from env
    api_key = os.getenv("GROQ_API_KEY")
    try:
        client = Groq(api_key=api_key)
        client.models.list()
        return jsonify({"success": "API Key is valid."})
    except Exception as e: return jsonify({"error": str(e)})

@app.route('/rebuild_stream')
def rebuild():
    return Response(
        stream_with_context(build_index_stream(pdf_folder, txt_folder)),
        mimetype='application/x-ndjson'
    )

@app.route('/index_clear', methods=['POST'])
def clear_index():
    import shutil
    try:
        if os.path.exists(faiss_db_path):
            shutil.rmtree(faiss_db_path)
        return jsonify({"success": "Neural Bank wiped."})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/docs')
def docs():
    import os
    from langchain_community.vectorstores import FAISS
    
    unique_sources = set()
    
    # 1. Check FAISS first to list what's actually successfully synced in the Neural Bank
    if os.path.exists(faiss_db_path):
        try:
            vectorstore = FAISS.load_local(faiss_db_path, get_embeddings(), allow_dangerous_deserialization=True)
            for doc_id, doc in vectorstore.docstore._dict.items():
                if "source" in doc.metadata and doc.metadata["source"] != "Unknown":
                    unique_sources.add(os.path.basename(doc.metadata["source"]))
        except Exception:
            pass
            
    # 2. Add any physical files currently sitting in the directories
    if os.path.exists(pdf_folder):
        for f in os.listdir(pdf_folder):
            if f.endswith(".pdf"): unique_sources.add(f)
    if os.path.exists(txt_folder):
        for f in os.listdir(txt_folder):
            if f.endswith(".txt"): unique_sources.add(f)
                
    return jsonify({"docs": list(unique_sources)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)