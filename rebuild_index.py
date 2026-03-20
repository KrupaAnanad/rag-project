import os
import faiss
import pickle
import json
import time
from PyPDF2 import PdfReader
from sentence_transformers import SentenceTransformer

# ─── CONFIGURATION ──────────────────────────────────────────
pdf_folder = "pdfs"
txt_folder = "texts"
index_file = "faiss_index.index"
metadata_file = "metadata.pkl"

def get_embedder():
    print("⏳ Loading embedding model...")
    return SentenceTransformer("all-MiniLM-L6-v2")

def load_pdf(file_path):
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
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
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

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

def build_index():
    print("🛠️ Starting Neural Bank Synchronization...")
    files = load_files_from_directory(pdf_folder, txt_folder)
    if not files:
        print("❌ No files found in pdfs/ or texts/")
        return

    all_chunks = []
    metadata   = []
    
    # Sort files to find the newest ones first or just to be deterministic
    files.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
    
    # Only index a subset if it's too large? No, the user wants a full rebuild.
    # But for a demo, maybe I should just index the most recent 50 files for speed?
    # No, I'll do all of them because it's only a few hundred.
    
    print(f"📄 Processing {len(files)} files...")
    for i, (file_type, file_path) in enumerate(files):
        filename = os.path.basename(file_path)
        if i % 50 == 0:
            print(f"   [{i}/{len(files)}] Processing {filename}...")
        
        try:
            text = load_pdf(file_path) if file_type == "pdf" else load_txt(file_path)
            if not text.strip(): continue
            chunks = chunk_text(text)
            for chunk in chunks:
                if isinstance(chunk, str) and chunk.strip():
                    all_chunks.append(chunk)
                    metadata.append({"text": chunk, "source": file_path, "type": file_type})
        except Exception as e:
            print(f"⚠️ Failed reading {filename}: {str(e)}")
            continue

    if not all_chunks:
        print("❌ No text could be extracted.")
        return

    print(f"🧠 Building embeddings for {len(all_chunks)} chunks...")
    embedder = get_embedder()
    embeddings = embedder.encode(all_chunks, convert_to_numpy=True, show_progress_bar=True)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    
    print("💾 Saving neural map...")
    faiss.write_index(index, index_file)
    with open(metadata_file, "wb") as f:
        pickle.dump(metadata, f)
        
    print(f"✨ Neural Bank synchronized successfully! ({len(all_chunks)} chunks mapped)")

if __name__ == "__main__":
    build_index()
