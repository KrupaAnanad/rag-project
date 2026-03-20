import os
import faiss
import pickle
from sentence_transformers import SentenceTransformer

def check_index():
    index_file = "faiss_index.index"
    metadata_file = "metadata.pkl"
    if not os.path.exists(index_file) or not os.path.exists(metadata_file):
        print("❌ Index files missing!")
        return
    
    print("⏳ Loading model and index...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    index = faiss.read_index(index_file)
    with open(metadata_file, "rb") as f:
        docs = pickle.load(f)
    print(f"✅ Loaded {len(docs)} documents.")
    
    query = "What is deep learning?"
    query_vec = embedder.encode([query], convert_to_numpy=True)
    distances, indices = index.search(query_vec, 3)
    print(f"🔍 Test search for '{query}':")
    for i in indices[0]:
        if i < len(docs):
            print(f" - [{docs[i]['source']}] {docs[i]['text'][:100]}...")

if __name__ == "__main__":
    check_index()
