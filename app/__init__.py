"""Vigrestad lot-sporing – en liten nettside som kjører på én PC og brukes fra nettleseren."""
import os
import secrets

from flask import Flask


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    nokkelfil = os.path.join(app.instance_path, "hemmelig_nokkel.txt")
    if not os.path.exists(nokkelfil):
        with open(nokkelfil, "w") as f:
            f.write(secrets.token_hex(32))
    with open(nokkelfil) as f:
        hemmelig = f.read().strip()

    app.config.from_mapping(
        SECRET_KEY=hemmelig,
        DATABASE=os.environ.get("VIGRESTAD_DB", os.path.join(app.instance_path, "vigrestad.db")),
    )
    if test_config:
        app.config.update(test_config)

    from . import db, views
    db.init_app(app)
    app.register_blueprint(views.bp)
    return app
