#!/usr/bin/env python3
"""Search over your indexed data: hybrid vector and full-text search with reranking and a recency boost, filters by
source, date and person.

By default it prints the raw results and sends nothing to a model. With --synthesize (or "search": {"synthesis":
true} in sbk.config.json) it also sends your question and the retrieved results to Claude with your own claude
login (`claude -p`), says so in the log, and prints the answer above the sources. --no-synthesis is still accepted:
it forces raw results even when the config turns synthesis on.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import setup_logging

from sbk_config import OWNER_LABEL, VECTOR_DB_DIR

log = logging.getLogger("sbk-l3-search")



LANCEDB_TABLE = "sbk_chunks"
DEFAULT_TOP_K = 10
SEARCH_K = 50
RRF_K = 60
RERANK_TOP_K = 30

SYSTEM_PROMPT = (
    f"You are SBK, {OWNER_LABEL}'s personal intelligence system. "
    "Answer questions using ONLY the provided context. "
    "Always cite sources with [source_type, date]. "
    "If the answer isn't in the context, say so. "
    "Respond in the user's language."
)




_embedding_model = None



_DIM_TO_MODEL = {
    384: ("paraphrase-multilingual-MiniLM-L12-v2", "sentence-transformers"),
    1024: ("BAAI/bge-m3", "sentence-transformers"),
}


MODEL_INFO_FILE = VECTOR_DB_DIR / "model-info.json"


def _detect_index_dimension() -> int | None:
    ""




    try:
        import lancedb

        db = lancedb.connect(str(VECTOR_DB_DIR))

        best_tbl = None
        best_rows = 0
        for tname in [LANCEDB_TABLE, "sbk_chunks_bge"]:
            try:
                tbl = db.open_table(tname)
                rows = tbl.count_rows()
                if rows > best_rows:
                    best_tbl = tbl
                    best_rows = rows
            except Exception:
                continue

        if best_tbl is None:
            return None

        schema = best_tbl.schema
        for field in schema:
            if field.name == "vector":

                return field.type.list_size
    except Exception:
        pass
    return None


_embedding_backend = None


def _read_model_info() -> dict | None:
    ""



    import json as _json

    try:
        if MODEL_INFO_FILE.exists():
            info = _json.loads(MODEL_INFO_FILE.read_text())
            if "model" in info and "backend" in info:
                return info
    except Exception as e:
        log.debug(f"Could not read model-info.json: {e}")
    return None


def _try_load_model(model_name: str, backend: str):
    ""
    global _embedding_model, _embedding_backend  # noqa: PLW0603
    try:
        if backend == "mlx":
            from mlx_embedding_adapter import MLXEmbeddingModel

            _embedding_model = MLXEmbeddingModel(model_name)
            _embedding_backend = "mlx"
            log.info(f"Loaded MLX embedding model: {model_name}")
            return _embedding_model
        else:
            from sentence_transformers import SentenceTransformer

            _embedding_model = SentenceTransformer(model_name)
            _embedding_backend = "sentence-transformers"
            log.info(f"Loaded embedding model: {model_name}")
            return _embedding_model
    except Exception as e:
        log.warning(f"Failed to load {model_name} ({backend}): {e}")
        return None


def _get_embedding_model():
    ""






    global _embedding_model, _embedding_backend  # noqa: PLW0603
    if _embedding_model is not None:
        return _embedding_model


    model_info = _read_model_info()
    if model_info:
        model_name = model_info["model"]
        backend = model_info["backend"]
        log.info(f"model-info.json found: {model_name} ({backend})")
        loaded = _try_load_model(model_name, backend)
        if loaded:
            return loaded
        log.warning(f"Failed to load model from model-info.json ({model_name}), falling back")


    index_dim = _detect_index_dimension()
    if index_dim and index_dim in _DIM_TO_MODEL:
        model_name, backend = _DIM_TO_MODEL[index_dim]
        log.info(f"Index dimension={index_dim}, loading matching model: {model_name} ({backend})")

        if backend == "mlx":
            try:
                from mlx_embedding_adapter import MLXEmbeddingModel

                _embedding_model = MLXEmbeddingModel(model_name)
                _embedding_backend = "mlx"
                log.info(f"Loaded MLX embedding model: {model_name} (dim={index_dim})")
                return _embedding_model
            except Exception as e:
                log.warning(f"Failed to load MLX model {model_name}: {e}")

                log.info("Falling back to BGE-M3 via sentence-transformers")
                try:
                    from sentence_transformers import SentenceTransformer

                    _embedding_model = SentenceTransformer("BAAI/bge-m3")
                    _embedding_backend = "sentence-transformers"
                    log.info("Loaded fallback: BAAI/bge-m3 via sentence-transformers")
                    return _embedding_model
                except Exception as e2:
                    log.warning(f"Failed to load BGE-M3 fallback: {e2}")
        else:
            try:
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(model_name)
                _embedding_backend = "sentence-transformers"
                log.info(f"Loaded embedding model: {model_name} (dim={index_dim})")
                return _embedding_model
            except Exception as e:
                log.warning(f"Failed to load {model_name}: {e}")


    for model_name in ["paraphrase-multilingual-MiniLM-L12-v2", "BAAI/bge-m3"]:
        try:
            from sentence_transformers import SentenceTransformer

            _embedding_model = SentenceTransformer(model_name)
            _embedding_backend = "sentence-transformers"
            log.info(f"Loaded embedding model: {model_name}")
            return _embedding_model
        except Exception as e:
            log.warning(f"Failed to load {model_name}: {e}")

    raise RuntimeError("Could not load any embedding model")


@lru_cache(maxsize=512)
def embed_query(query: str) -> tuple[float, ...]:
    ""




    model = _get_embedding_model()
    if _embedding_backend == "mlx" and hasattr(model, "encode_query"):
        vec = model.encode_query(query, normalize_embeddings=True)
    else:
        vec = model.encode(query, normalize_embeddings=True)
    return tuple(vec.tolist())





def open_lancedb():
    ""







    import lancedb

    db_path = str(VECTOR_DB_DIR)
    if not VECTOR_DB_DIR.exists():
        raise RuntimeError(
            f"LanceDB index not found at {db_path}. "
            "Run xs-l3-index.py first to create the vector index."
        )

    db = lancedb.connect(db_path)


    primary_tbl = None
    primary_rows = 0
    try:
        primary_tbl = db.open_table(LANCEDB_TABLE)
        primary_rows = primary_tbl.count_rows()
    except Exception:
        pass


    bge_tbl = None
    bge_rows = 0
    try:
        bge_tbl = db.open_table("sbk_chunks_bge")
        bge_rows = bge_tbl.count_rows()
    except Exception:
        pass


    if bge_rows > primary_rows and bge_tbl is not None:
        log.info(f"Using BGE table ({bge_rows:,} rows) over primary ({primary_rows:,} rows)")
        return bge_tbl
    if primary_tbl is not None and primary_rows > 0:
        log.info(f"Using primary table ({primary_rows:,} rows)")
        return primary_tbl

    raise RuntimeError(
        f"No LanceDB table found with data at {db_path}. "
        "Run xs-l3-index.py first to create the vector index."
    )


def vector_search(table, query_vector: list[float], k: int = SEARCH_K) -> list[dict]:
    ""




    try:
        results = table.search(query_vector).metric("cosine").limit(k).to_list()
    except Exception as e:
        err_msg = str(e).lower()
        if "not found" in err_msg or "index" in err_msg or "lance" in err_msg:
            log.warning(f"ANN index error ({e}), falling back to flat scan")
            try:
                results = (
                    table.search(query_vector)
                    .metric("cosine")
                    .nprobes(0)
                    .limit(k)
                    .to_list()
                )
            except Exception:

                try:
                    results = (
                        table.search(query_vector)
                        .metric("cosine")
                        .bypass_vector_index()
                        .limit(k)
                        .to_list()
                    )
                except Exception as e3:
                    log.error(f"Flat scan also failed: {e3}")
                    return []
        else:
            log.error(f"Vector search failed: {e}")
            return []



    for r in results:
        dist = r.pop("_distance", 0.0)
        r["vector_score"] = max(0.0, 1.0 - dist)
    return results


def fulltext_search(table, query: str, k: int = SEARCH_K) -> list[dict]:
    ""




    try:
        from lancedb.query import MatchQuery


        results = table.search(MatchQuery(query.lower(), "text", fuzziness=1)).limit(k).to_list()
    except ImportError:

        log.debug("MatchQuery not available, using plain FTS")
        try:
            results = table.search(query, query_type="fts").limit(k).to_list()
        except Exception as e:
            log.warning(f"Full-text search failed ({e}), using vector search only")
            return []
    except Exception as e:
        log.warning(f"Full-text search failed ({e}), using vector search only")
        return []

    for r in results:
        r["fts_score"] = r.pop("_score", 0.0)
        r.pop("_distance", None)
    return results


def hybrid_search(
    table,
    query: str,
    query_vector: list[float],
    top_k: int = DEFAULT_TOP_K,
    source_filter: str | None = None,
    after_date: str | None = None,
    person_filter: str | None = None,
    person_id_filter: str | None = None,
    rerank: bool = True,
) -> list[dict]:
    ""









    vec_results = vector_search(table, query_vector, k=SEARCH_K)
    fts_results = fulltext_search(table, query, k=SEARCH_K)


    candidates = _fuse_rrf(vec_results, fts_results)


    if source_filter:
        sf = source_filter.lower()
        candidates = [c for c in candidates if c.get("source_type", "").lower() == sf]

    if after_date:
        candidates = [c for c in candidates if (c.get("date") or "") >= after_date]

    if person_id_filter:
        pid = person_id_filter.lower()
        candidates = [
            c
            for c in candidates
            if pid in (c.get("person_ids") or "").lower()
            or pid in (c.get("participants") or "").lower()
        ]
    elif person_filter:
        pf = person_filter.lower()
        candidates = [c for c in candidates if pf in (c.get("participants") or "").lower()]


    if rerank and len(candidates) > 1:
        rerank_pool = candidates[:RERANK_TOP_K]
        reranked = rerank_results(query, rerank_pool, top_k=top_k)
        if reranked is not None:
            candidates = reranked
        else:
            candidates = candidates[:top_k]
    else:
        candidates = candidates[:top_k]


    candidates = _apply_recency_boost(candidates)
    return candidates[:top_k]


def _fuse_rrf(
    vec_results: list[dict],
    fts_results: list[dict],
    k: int = RRF_K,
) -> list[dict]:
    ""




    merged: dict[str, dict] = {}

    for rank_0, r in enumerate(vec_results):
        rid = r.get("id", "")
        rank = rank_0 + 1
        merged[rid] = r.copy()
        merged[rid]["rrf_vec"] = 1.0 / (k + rank)
        merged[rid]["rrf_fts"] = 0.0
        merged[rid].setdefault("fts_score", 0.0)

    for rank_0, r in enumerate(fts_results):
        rid = r.get("id", "")
        rank = rank_0 + 1
        rrf_fts = 1.0 / (k + rank)
        if rid in merged:
            merged[rid]["rrf_fts"] = rrf_fts
            merged[rid]["fts_score"] = r.get("fts_score", 0.0)
        else:
            merged[rid] = r.copy()
            merged[rid]["rrf_fts"] = rrf_fts
            merged[rid]["rrf_vec"] = 0.0
            merged[rid].setdefault("vector_score", 0.0)

    for item in merged.values():
        item["combined_score"] = item["rrf_vec"] + item["rrf_fts"]

    return sorted(merged.values(), key=lambda x: x["combined_score"], reverse=True)




_reranker_model = None


def _get_reranker():
    ""




    global _reranker_model  # noqa: PLW0603
    if _reranker_model is not None:
        return _reranker_model

    try:
        from sentence_transformers import CrossEncoder

        model_name = "BAAI/bge-reranker-v2-m3"
        log.info(f"Loading reranker model: {model_name}")
        _reranker_model = CrossEncoder(model_name, max_length=512)
        log.info(f"Reranker loaded: {model_name}")
        return _reranker_model
    except Exception as e:
        log.warning(f"Reranker unavailable ({e}), skipping reranking")
        return None


def rerank_results(
    query: str,
    results: list[dict],
    top_k: int = DEFAULT_TOP_K,
) -> list[dict] | None:
    ""



    reranker = _get_reranker()
    if reranker is None:
        return None

    pairs = []
    for r in results:
        passage = r.get("text", "")
        context = r.get("context", "")
        if context:
            passage = f"{context}\n\n{passage}"
        pairs.append((query, passage))

    try:



        scores = reranker.predict(pairs, batch_size=8, show_progress_bar=False)
    except Exception as e:
        log.warning(f"Reranking failed ({e}), using RRF order")
        return None


    import math

    for r, raw_score in zip(results, scores):
        r["reranker_score"] = 1.0 / (1.0 + math.exp(-float(raw_score)))

    results.sort(key=lambda x: x.get("reranker_score", 0.0), reverse=True)
    return results[:top_k]




RECENCY_WEIGHT = 0.3
MAX_RECENCY_DAYS = 365


def _apply_recency_boost(candidates: list[dict]) -> list[dict]:
    ""






    from datetime import date, datetime

    today = date.today()

    for c in candidates:
        date_str = c.get("date", "")
        if not date_str or len(date_str) < 10:
            continue

        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            days_ago = (today - d).days
            if days_ago < 0:
                days_ago = 0
            recency_factor = max(0.0, 1.0 - days_ago / MAX_RECENCY_DAYS)
        except (ValueError, TypeError):
            continue

        if recency_factor <= 0.0:
            continue


        base_score = c.get("reranker_score") or c.get("combined_score", 0.0)
        boosted = base_score * (1.0 + RECENCY_WEIGHT * recency_factor)

        if "reranker_score" in c:
            c["reranker_score"] = boosted
        else:
            c["combined_score"] = boosted
        c["score"] = boosted
        c["recency_boost"] = recency_factor


    def _sort_key(c):
        if "reranker_score" in c:
            return c["reranker_score"]
        return c.get("combined_score", 0.0)

    candidates.sort(key=_sort_key, reverse=True)
    return candidates





def format_result_for_display(r: dict, idx: int) -> str:
    ""
    source = r.get("source_type", "unknown")
    date = r.get("date", "n/a")
    score = r.get("combined_score", 0.0)
    context = r.get("context", "")
    text = r.get("text", "")


    text_preview = text[:300] + "..." if len(text) > 300 else text

    lines = [f"{idx}. [{source}] {date} (score: {score:.2f})"]
    if context:
        lines.append(f"   Context: {context}")
    lines.append(f"   {text_preview}")
    return "\n".join(lines)


MAX_CONTEXT_TOKENS = 12_000


def _estimate_tokens(text: str) -> int:
    ""
    return len(text) // 4


def format_context_for_claude(results: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    ""





    chunks = []
    total_tokens = 0

    for i, r in enumerate(results, 1):
        source = r.get("source_type", "unknown")
        date = r.get("date", "n/a")
        context = r.get("context", "")
        text = r.get("text", "")
        participants = r.get("participants", "")

        header = f"[Source {i}: {source}, {date}]"
        if context:
            header += f" {context}"
        if participants:
            header += f" | Participants: {participants}"

        chunk = f"{header}\n{text}"
        chunk_tokens = _estimate_tokens(chunk)

        if total_tokens + chunk_tokens > max_tokens and chunks:
            log.debug(
                f"Context window limit reached at source {i}/{len(results)} "
                f"({total_tokens} tokens used, max {max_tokens})"
            )
            break

        chunks.append(chunk)
        total_tokens += chunk_tokens

    return "\n\n---\n\n".join(chunks)


def format_sources_section(results: list[dict]) -> str:
    ""
    lines = ["### Sources"]
    for i, r in enumerate(results, 1):
        source = r.get("source_type", "unknown")
        date = r.get("date", "n/a")
        context = r.get("context", "")
        score = r.get("combined_score", 0.0)
        desc = f"[{source}] {date}"
        if context:
            desc += f" {context}"
        lines.append(f"{i}. {desc} (score: {score:.2f})")
    return "\n".join(lines)






MODELLO_SINTESI = "sonnet"


def _chiama_abbonamento(prompt: str, timeout: int = 300) -> str:
    ""
    # Direct call to the configurable LLM backend (e.g. the `claude` CLI).
    r = subprocess.run(
        [
            "claude",
            "-p",
            "--safe-mode",
            "--tools",
            "",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--model",
            MODELLO_SINTESI,
        ],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/tmp",
    )
    if r.returncode == 75 and not (r.stdout or "").strip():
        raise RuntimeError("usage limit reached")
    try:
        d = json.loads(r.stdout)
    except ValueError as exc:
        raise RuntimeError(
            f"answer is not JSON (exit {r.returncode}): {(r.stdout or r.stderr)[:200]}"
        ) from exc
    if d.get("is_error"):
        raise RuntimeError(f"error from the CLI: {str(d.get('result'))[:200]}")
    return d.get("result") or ""


def synthesize(query: str, results: list[dict], chiama=_chiama_abbonamento) -> str:
    ""
    context = format_context_for_claude(results)



    prompt = f"{SYSTEM_PROMPT}\n\nQuestion: {query}\n\nContext (from {len(results)} SBK sources):\n\n{context}"

    log.info(
        f"Sending your question and {len(results)} results ({len(prompt)} characters) to Claude "
        f"with your own claude login (claude -p --model {MODELLO_SINTESI}) for the answer"
    )
    return chiama(prompt)


def synthesis_wanted(synthesize_flag: bool = False, no_synthesis_flag: bool = False) -> bool:
    """True only when you asked for the model answer: --synthesize, or search.synthesis true in sbk.config.json.

    Off by default, so a plain search sends nothing to a model. --no-synthesis always wins.
    """
    if no_synthesis_flag:
        return False
    if synthesize_flag:
        return True
    import sbk_config

    return sbk_config.user_cfg("search.synthesis", False) is True


def add_synthesis_args(parser: argparse.ArgumentParser) -> None:
    """The two synthesis flags (tools/sbk_cli.py `sbk search` declares the same two)."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--synthesize",
        action="store_true",
        help="Also send the question and the results to Claude with your own claude login "
        "(claude -p) and print its answer. Off by default; search.synthesis true in "
        "sbk.config.json turns it on for every search",
    )
    group.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Raw results only (the default); overrides search.synthesis true in sbk.config.json",
    )


def stampa_risultati(query: str, results: list[dict], grezzo: bool, sintetizza=synthesize) -> None:
    ""




    if not grezzo:
        try:
            answer = sintetizza(query, results)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
            print(f"\nThe summary failed ({str(e)[:200]}). The raw results follow.")
        else:
            print("\n## Answer\n")
            print(answer)
            print("\n---")
            print(format_sources_section(results))
            return
    print(f"\n## Results ({len(results)})\n")
    for i, r in enumerate(results, 1):
        print(format_result_for_display(r, i))
        print()





def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search over your indexed data. Raw results by default; --synthesize also asks "
        "Claude (your own claude login) for an answer."
    )
    parser.add_argument(
        "query",
        help="Search query (e.g., 'when did I last talk with Person A about pricing?')",
    )
    parser.add_argument(
        "--source",
        metavar="TYPE",
        help="Filter by source type (email, plaud, slack, whatsapp, etc.)",
    )
    parser.add_argument(
        "--after",
        metavar="DATE",
        help="Filter results after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--person",
        metavar="NAME",
        help="Filter by participant name",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_K,
        metavar="N",
        help=f"Number of results (default: {DEFAULT_TOP_K})",
    )
    add_synthesis_args(parser)
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    setup_logging(verbose=args.verbose, name="sbk-l3-search")

    log.info(f"Query: {args.query}")


    try:
        table = open_lancedb()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    row_count = table.count_rows()
    log.info(f"LanceDB table '{LANCEDB_TABLE}' loaded: {row_count} chunks")


    query_vector = list(embed_query(args.query))
    log.info(f"Query embedded ({len(query_vector)} dimensions)")


    results = hybrid_search(
        table=table,
        query=args.query,
        query_vector=query_vector,
        top_k=args.top,
        source_filter=args.source,
        after_date=args.after,
        person_filter=args.person,
    )

    if not results:
        print("No results found.")
        sys.exit(0)

    log.info(f"Found {len(results)} results")

    stampa_risultati(
        args.query,
        results,
        grezzo=not synthesis_wanted(args.synthesize, args.no_synthesis),
    )


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-search", source="l3-search", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
