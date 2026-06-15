from __future__ import annotations

import numpy as np
import pytest

from src.agents.rag.vector_store import (
    SearchResult,
    _chunk_by_paragraph,
    _chunk_by_sentence,
    _mmr_diversify,
    chunk_text,
    cosine_similarity,
    extract_keywords,
    strip_html,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0)


class TestExtractKeywords:
    def test_extracts_frequent_words(self):
        text = "python programming python development python code python test"
        keywords = extract_keywords(text)
        assert "python" in keywords
        assert len(keywords) > 0

    def test_filters_stop_words(self):
        text = "the and or in on at to for"
        keywords = extract_keywords(text)
        assert len(keywords) == 0

    def test_short_words_filtered(self):
        text = "a an of it is"
        keywords = extract_keywords(text)
        assert all(len(k) > 2 for k in keywords) or len(keywords) == 0


class TestMMR:
    def test_single_result(self):
        results = [SearchResult(chunk=type("", (), {"embedding": [1, 0]})(), score=0.9)]
        emb = np.array([[1, 0]])
        diversified = _mmr_diversify(results, emb, 0.7)
        assert len(diversified) == 1

    def test_diversity_selects_different(self):
        emb_matrix = np.array([
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
        ])
        results = [
            SearchResult(chunk=type("", (), {"embedding": emb_matrix[i]})(), score=0.9 - i * 0.1)
            for i in range(3)
        ]
        diversified = _mmr_diversify(results, emb_matrix, 0.5)
        assert len(diversified) == 3


class TestChunking:
    def test_chunk_by_paragraph(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = _chunk_by_paragraph(text, 50)
        assert len(chunks) >= 1

    def test_chunk_by_sentence(self):
        text = "First sentence. Second sentence. Third sentence."
        chunks = _chunk_by_sentence(text, 50, 0)
        assert len(chunks) >= 1
        # With overlap
        chunks_overlap = _chunk_by_sentence(text, 50, 10)
        assert len(chunks_overlap) >= 1

    @pytest.mark.asyncio
    async def test_chunk_text_dispatch(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = await chunk_text(text, "paragraph", 100)
        assert len(chunks) >= 1

        chunks_r = await chunk_text(text, "recursive", 500, 80)
        assert len(chunks_r) >= 1

    def test_empty_input(self):
        assert _chunk_by_paragraph("", 100) == []
        assert _chunk_by_sentence("", 100, 0) == []


class TestStripHtml:
    def test_strips_basic_html(self):
        html = "<html><body><p>Hello World</p></body></html>"
        result = strip_html(html)
        assert "Hello World" in result

    def test_strips_scripts(self):
        html = "<script>alert('xss')</script><p>Content</p>"
        result = strip_html(html)
        assert "alert" not in result
        assert "Content" in result

    def test_empty_html(self):
        assert strip_html("") == ""


class TestAddChunks:
    @pytest.mark.asyncio
    async def test_add_and_stats(self, tmp_workspace):
        from src.agents.rag.vector_store import _db_cache, add_chunks, get_store_stats
        _db_cache.clear()
        import os
        os.chdir(tmp_workspace)

        chunks = [
            {"doc_id": "doc_1", "title": "Test Doc", "source": "manual",
             "text": "This is test content", "embedding": [0.1, 0.2, 0.3], "metadata": {}},
        ]
        count = await add_chunks("test-agent-add", chunks)
        assert count == 1

        stats = await get_store_stats("test-agent-add")
        assert stats["doc_count"] >= 1
        assert stats["chunk_count"] >= 1

    @pytest.mark.asyncio
    async def test_search_similar(self, tmp_workspace):
        from src.agents.rag.vector_store import _db_cache, SearchOptions, add_chunks, search_similar
        _db_cache.clear()
        import os
        os.chdir(tmp_workspace)

        chunks = [
            {"doc_id": "doc_2", "title": "Python", "source": "manual",
             "text": "Python is a programming language", "embedding": [0.1, 0.2, 0.3], "metadata": {}},
            {"doc_id": "doc_3", "title": "Java", "source": "manual",
             "text": "Java is another language", "embedding": [0.3, 0.2, 0.1], "metadata": {}},
        ]
        await add_chunks("test-agent-search", chunks)

        results = await search_similar("test-agent-search", [0.1, 0.2, 0.3], "python", SearchOptions(top_k=2))
        assert len(results) > 0
        assert results[0].score > 0


class TestListAndRemove:
    @pytest.mark.asyncio
    async def test_list_documents(self, tmp_workspace):
        from src.agents.rag.vector_store import _db_cache, add_chunks, list_documents
        _db_cache.clear()
        import os
        os.chdir(tmp_workspace)

        await add_chunks("test-agent-list", [
            {"doc_id": "doc_list_1", "title": "Doc", "source": "manual",
             "text": "Content", "embedding": [0.1, 0.2], "metadata": {}},
        ])
        docs = await list_documents("test-agent-list")
        assert len(docs) >= 1

    @pytest.mark.asyncio
    async def test_remove_document(self, tmp_workspace):
        from src.agents.rag.vector_store import _db_cache, add_chunks, get_store_stats, remove_document
        _db_cache.clear()
        import os
        os.chdir(tmp_workspace)

        await add_chunks("test-agent-remove", [
            {"doc_id": "doc_remove_1", "title": "To Delete", "source": "manual",
             "text": "Delete me", "embedding": [0.1], "metadata": {}},
        ])
        ok = await remove_document("test-agent-remove", "doc_remove_1")
        assert ok
        stats = await get_store_stats("test-agent-remove")
        assert stats["chunk_count"] == 0
