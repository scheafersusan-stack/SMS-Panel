"""``python -m payamakyar.api``: run the API with uvicorn."""

import os

import uvicorn

from payamakyar.core.logging import configure_logging


def main() -> None:
    configure_logging(os.environ.get("PAYAMAKYAR_LOG_LEVEL", "INFO"))
    uvicorn.run(
        "payamakyar.api.app:create_app",
        factory=True,
        host=os.environ.get("PAYAMAKYAR_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PAYAMAKYAR_API_PORT", "8000")),
        log_config=None,
        proxy_headers=False,  # trust is decided by PAYAMAKYAR_TRUSTED_PROXIES only
    )


if __name__ == "__main__":
    main()
