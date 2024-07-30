from abc import ABC, abstractmethod
from typing import List

import chromadb
import datasets

import data
from emmbedding_functions.glove import GloveEmbeddingFunction


DATASET_ID = 'TaylorAI/pubmed_noncommercial'
#NAME = 'pubmed-noncommercial'
NAME = 'test'
CONTEXT_NUM_DOCS = 15
MAX_DISTANCE = 0.9


class VectorDb(ABC):
    def __init__(self, name: str = NAME, dataset_id: str = DATASET_ID):
        print(f'Using {self.__class__.__name__} vector database "{name}"')
        self.name = NAME
        self.dataset_id = dataset_id
    
    @abstractmethod
    def ingest(self):
        print(f'Ingesting dataset "{self.dataset_id}"')
    
    @abstractmethod
    def get_last_doc_ix(self) -> int:
        pass

    @abstractmethod
    def query(self, text: str, n_results: int) -> List[str]:
        pass

    @abstractmethod
    def delete(self):
        print(f'Deleting vector database "{self.name}" if it exists')


class ChromaDb(VectorDb):
    def __init__(self, name: str = NAME, dataset_id: str = DATASET_ID):
        super().__init__(name, dataset_id)
        self.client = chromadb.PersistentClient()
    
    def ingest(self):
        collection = self.client.get_or_create_collection(
            self.name,
            embedding_function=GloveEmbeddingFunction()
        )
        previously_ingested_ids = set(
            s.split('_')[0] 
            for s in collection.get(include=[])['ids']
        )
        metadata = collection.metadata or {}
        last_doc_ix = metadata.get('last_doc_ix', -1)
        total_chars = metadata.get('total_chars', 0)
        ds = datasets.load_dataset(self.dataset_id)['train']
        try:
            for doc_ix, row in enumerate(ds):
                doc_id = data.extract_document_id(row)
                if last_doc_ix is None:
                    if doc_id in previously_ingested_ids:
                        continue
                else:
                    if doc_ix <= last_doc_ix:
                        continue
                print(f'\rIngest "{doc_id}" {doc_ix:,}/{ds.shape[0]:,}', end='')
                text = data.extract_document(row)
                chunks = data.clean_and_chunk(text)
                if chunks:
                    total_chars += sum(len(c) for c in chunks)
                    ids = [f'{doc_id}_{i}' for i in range(len(chunks))]
                    try:
                        collection.add(documents=chunks, ids=ids)
                    except TypeError as e:
                        print(chunks)
                        raise e
                    metadata = {
                        'last_doc_ix': doc_ix, 
                        'last_doc_id': doc_id, 
                        'total_chars': total_chars
                    }
                    collection.modify(metadata=metadata)
        except KeyboardInterrupt:
            pass
        n_chunks = collection.count()
        toks_per_chunk = round(total_chars / 4 / n_chunks)
        print('Totals:')
        print(f'Chars: {total_chars:,}')
        print(f'Chunks: {n_chunks:,}')
        print(f'Tokens/chunk: {toks_per_chunk:,} (assuming 4 chars/token)')

    def get_last_doc_ix(self) -> int:
        try:
            collection = self.client.get_collection(name=self.name)
        except ValueError:
            return -1
        return (collection.metadata or {}).get('last_doc_ix', -1)
    
    def query(
        self, text: str, 
        max_results: int, 
        max_distance: float = MAX_DISTANCE
    ) -> List[str]:
        collection = self.client.get_collection(name=self.name)
        response = collection.query(query_texts=[text], n_results=max_results)
        close_docs = [
            s 
            for s, d in zip(response['documents'][0], response['distances'])
            if d <= max_distance
        ]
        return close_results 

    def delete(self):
        super().delete()
        try:
            self.client.delete_collection(name=self.name)
        except ValueError:
            pass


if __name__ == '__main__':
    db = ChromaDb()
    last_doc_ix = db.get_last_doc_ix()
    if last_doc_ix >= 0:
        print(f'Collection {db.name} last ingested document {last_doc_ix}.')
        print('Choose:')
        print(f'[a]ppend, starting at dataset document {1 + last_doc_ix}')
        print(f'[d]elete (replace) the collection')
        if input('(a/d)? ').lower() == 'd':
            db.delete()
    db.ingest()

