import os
import sys

# Ensure backend path is in sys.path
sys.path.insert(0, os.getcwd())

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core.vector_stores.types import MetadataFilters, ExactMatchFilter

embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-m3")
persist_dir = "./vector_store"

# Method 1: Current code
print("--- Method 1: VectorStoreIndex.from_vector_store ---")
try:
    storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
    index1 = VectorStoreIndex.from_vector_store(storage_context.vector_store, embed_model=embed_model)
    filters = MetadataFilters(filters=[ExactMatchFilter(key="tenant_id", value="tenant-default")])
    retriever1 = index1.as_retriever(similarity_top_k=5, filters=filters)
    nodes1 = retriever1.retrieve("Lennox McLeod")
    print(f"Method 1 found {len(nodes1)} nodes")
    for n in nodes1:
        print(f"  - {n.node.get_content()[:100]}...")
except Exception as e:
    print(f"Method 1 failed: {e}")

# Method 2: load_index_from_storage
print("\n--- Method 2: load_index_from_storage ---")
try:
    storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
    index2 = load_index_from_storage(storage_context, embed_model=embed_model)
    filters = MetadataFilters(filters=[ExactMatchFilter(key="tenant_id", value="tenant-default")])
    retriever2 = index2.as_retriever(similarity_top_k=5, filters=filters)
    nodes2 = retriever2.retrieve("Lennox McLeod")
    print(f"Method 2 found {len(nodes2)} nodes")
    for n in nodes2:
        print(f"  - {n.node.get_content()[:100]}...")
except Exception as e:
    print(f"Method 2 failed: {e}")
