""








from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("sbk-mlx-embed")


_QUERY_INSTRUCT = (
    "Instruct: Given a user query, retrieve relevant passages "
    "from a personal knowledge base\nQuery: "
)


class MLXEmbeddingModel:
    ""





    def __init__(self, model_name: str):
        import mlx.core as mx
        from mlx_embeddings.utils import load

        log.info(f"Loading MLX embedding model: {model_name}")
        self._model, self._tokenizer = load(model_name)
        self._model_name = model_name


        self._tokenizer.padding_side = "left"
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token


        test_emb = self.encode(["test"], normalize_embeddings=True)
        self._dim = test_emb.shape[1]
        log.info(f"MLX model loaded: {model_name} (dim={self._dim})")


        del test_emb
        try:
            mx.clear_cache()
        except AttributeError:
            mx.metal.clear_cache()

    @property
    def dim(self) -> int:
        return self._dim

    def _tokenize_batch(self, texts: list[str]) -> dict:
        ""




        import mlx.core as mx


        hf_tok = (
            self._tokenizer._tokenizer
            if hasattr(self._tokenizer, "_tokenizer")
            else self._tokenizer
        )
        encoded = hf_tok(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )

        return {k: mx.array(v) for k, v in encoded.items()}

    def encode(
        self,
        texts: list[str] | str,
        normalize_embeddings: bool = True,
        batch_size: int = 128,
        show_progress_bar: bool = False,
        **kwargs,
    ) -> np.ndarray:
        ""



        import mlx.core as mx

        if isinstance(texts, str):
            texts = [texts]

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]


            inputs = self._tokenize_batch(batch)
            result = self._model(**inputs)


            if hasattr(result, "text_embeds"):
                emb = result.text_embeds
            elif hasattr(result, "last_hidden_state"):

                emb = self._last_token_pool(result.last_hidden_state, batch)
            else:
                emb = result


            if hasattr(emb, "tolist"):
                emb_np = np.array(emb.tolist(), dtype=np.float32)
            else:
                emb_np = np.array(emb, dtype=np.float32)


            if emb_np.ndim == 1:
                emb_np = emb_np.reshape(1, -1)

            if normalize_embeddings:
                norms = np.linalg.norm(emb_np, axis=1, keepdims=True)
                norms = np.maximum(norms, 1e-12)
                emb_np = emb_np / norms

            all_embeddings.append(emb_np)


            try:
                mx.clear_cache()
            except AttributeError:
                mx.metal.clear_cache()

        return np.vstack(all_embeddings)

    def encode_query(
        self,
        query: str,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        ""



        prefixed = f"{_QUERY_INSTRUCT}{query}"
        return self.encode([prefixed], normalize_embeddings=normalize_embeddings)[0]

    def _last_token_pool(self, hidden_states, texts: list[str]):
        ""






        hf_tok = (
            self._tokenizer._tokenizer
            if hasattr(self._tokenizer, "_tokenizer")
            else self._tokenizer
        )
        encoded = hf_tok(
            texts,
            padding=True,
            truncation=True,
            return_tensors="np",
        )
        attention_mask = encoded["attention_mask"]


        seq_lengths = attention_mask.sum(axis=1) - 1


        hs_np = np.array(hidden_states.tolist(), dtype=np.float32)

        batch_size = hs_np.shape[0]
        pooled = np.zeros((batch_size, hs_np.shape[2]), dtype=np.float32)
        for i in range(batch_size):
            pooled[i] = hs_np[i, int(seq_lengths[i])]

        return pooled
