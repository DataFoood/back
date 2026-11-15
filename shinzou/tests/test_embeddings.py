from unittest.mock import patch

from shinzou.config import settings
from shinzou.embeddings import embed_query


def test_embedding_request_can_unload_model_and_limit_context():
    with patch.object(settings, "EMBEDDING_KEEP_ALIVE", "0"), patch.object(settings, "EMBEDDING_NUM_CTX", 512), patch("shinzou.embeddings.httpx.post") as post:
        post.return_value.json.return_value = {"embeddings": [[0.1, 0.2]]}
        assert embed_query("comida caseira") == [0.1, 0.2]
    payload = post.call_args.kwargs["json"]
    assert payload["keep_alive"] == "0"
    assert payload["options"]["num_ctx"] == 512
    assert payload["truncate"] is True
    assert payload["input"] == "comida caseira"
    post.return_value.raise_for_status.assert_called_once()
