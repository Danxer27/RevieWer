import chromadb
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "sira_chroma_db"
client = chromadb.PersistentClient(path=str(DB_PATH))

collection = client.get_or_create_collection("scipost_reviews")

# Verifica la cantidad de registros
count = collection.count()
print(f"Registros totales: {count}")

if count > 0:
    # Recupera UN solo registro incluyendo los embeddings
    muestra = collection.get(limit=1, include=['embeddings'])
    embeddings = muestra.get('embeddings', [])

    if len(embeddings) > 0 and len(embeddings[0]) > 0:
        print("Éxito: Los embeddings existen.")
        print(f"Dimensión del vector: {len(embeddings[0])}")
        print(f"Primeros 5 valores: {embeddings[0][:5]}")
    else:
        print("Error: Los embeddings están vacíos o son None.")
else:
    print("Error: La colección está vacía.")   