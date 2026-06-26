import json
import chromadb
from pathlib import Path
from langchain_ollama import OllamaEmbeddings
from sentence_transformers import SentenceTransformer

with open("scipost_papers.json", encoding="utf-8") as f:
    papers = {p["paper_chain"]: p for p in json.load(f)}

with open("scipost_versions.json", encoding="utf-8") as f:
    #Quedarse con la version mas reciente de cada paper
    versions = {}
    for v in json.load(f):
        chain = v["paper_chain"]
        if chain not in versions or v["version_idx"] > versions[chain]["version_idx"]:
             versions[chain] = v

with open("scipost_reviews.json", encoding="utf-8") as f:
    reviews = json.load(f)

print(f"Papers: {len(papers)}, Versions: {len(versions)}, Reviews: {len(reviews)}")


# Construir documentos para chromadb
documents, metadata, ids = [], [], []

for review in reviews:
    chain = review["paper_chain"]

    #Saltar si no tiene texto de review
    if not review.get("report"):
        continue

    paper = papers.get(chain, [])
    version = versions.get(chain, {})

    # El texto que se embeddea e indexa
    report_text = review["report"]

    meta = {
        "paper_chain": chain,
        "title": version.get("title", ""),
        "journal": paper.get("journal", ""),
        "fields": ", ".join(paper.get("fields", [])),
        "final_status": paper.get("final_status", ""),
        "validity": str(review.get("validity", "-")),
        "significance": str(review.get("significance", "-")),
        "originality": str(review.get("originality", "-")),
        "clarity": str(review.get("clarity", "-")),
        "review_len": review.get("report_len", 0),
        "review_idx": review.get("review_idx", 0),
    }

    review_id = f"{chain}_r{review['review_idx']}_{len(ids)+1}"
    documents.append(report_text)
    metadata.append(meta)
    ids.append(review_id)

print(f"Documentos listos para indexar: {len(documents)}")

if len(documents) == 0:
    print("No se encontraron documentos para indexar. Revisa que hay reviews con campo 'report'.")
    raise SystemExit(0)

# Indexar en chroma db
# model = OllamaEmbeddings(
#     model="nomic-embed-text:latest",
#     base_url="127.0.0.1:11435"
# )

model = SentenceTransformer("all-MiniLM-L6-v2")
DB_PATH = Path(__file__).resolve().parent / "sira_chroma_db"
client = chromadb.PersistentClient(path=str(DB_PATH))
collection = client.get_or_create_collection(
    name="scipost_reviews",
    metadata={"hnsw:space":"cosine"}
)

BATCH = 64
for i in range(0, len(documents), BATCH):
    batch_docs = documents[i:i+BATCH]
    batch_meta = metadata[i:i+BATCH]
    batch_ids = ids[i:i+BATCH]

    embeddings = model.encode(batch_docs).tolist()

    collection.add(
        documents=batch_docs,
        embeddings=embeddings,
        metadatas=batch_meta,
        ids=batch_ids
    )
    print(f" Indexados {min(i+BATCH, len(documents))}/{len(documents)}")

print("Indexacion completada")
print('Conteo final en colección:', collection.count())