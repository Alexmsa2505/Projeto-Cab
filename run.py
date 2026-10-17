"""Inicia o servidor de desenvolvimento.

    python run.py

Em produção, use um servidor WSGI, por exemplo:
    gunicorn "run:app" --workers 1 --threads 8
(enquanto os dados estiverem em memória, use 1 worker; com banco de dados,
pode escalar normalmente e mover os lembretes para um worker separado.)
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=app.config["DEBUG"],
    )
