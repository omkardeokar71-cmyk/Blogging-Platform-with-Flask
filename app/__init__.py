import secrets

from flask import Flask, g, render_template, session
from sqlalchemy import inspect, text

from app.extensions import db, migrate
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config["MAX_CONTENT_LENGTH"] is None:
        app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    db.init_app(app)
    migrate.init_app(app, db)

    from app.main import main
    from app.models import User

    app.register_blueprint(main)

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        g.user = db.session.get(User, user_id) if user_id is not None else None
        if user_id is not None and g.user is None:
            session.clear()

    @app.context_processor
    def inject_template_values():
        return {"current_user": g.get("user")}

    @app.context_processor
    def inject_csrf_token():
        def csrf_token():
            if "_csrf_token" not in session:
                session["_csrf_token"] = secrets.token_urlsafe(32)
            return session["_csrf_token"]

        return {"csrf_token": csrf_token}

    @app.errorhandler(400)
    def bad_request(error):
        return (
            render_template(
                "error.html",
                status_code=400,
                title="That request didn’t go through.",
                message="The form may have expired. Go back, refresh, and try again.",
            ),
            error.code,
        )

    @app.errorhandler(404)
    def not_found(error):
        return (
            render_template(
                "error.html",
                status_code=404,
                title="This story is off the page.",
                message="The page may have moved, or the link may be out of date.",
            ),
            error.code,
        )

    @app.errorhandler(413)
    def request_too_large(error):
        return (
            render_template(
                "error.html",
                status_code=413,
                title="That’s a lot to share at once.",
                message="Please shorten your submission and try again.",
            ),
            error.code,
        )

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return (
            render_template(
                "error.html",
                status_code=500,
                title="We hit a little snag.",
                message="Your stories are safe. Please try again in a moment.",
            ),
            error.code,
        )

    with app.app_context():
        db.create_all()
        _upgrade_legacy_post_table()

    return app


def _upgrade_legacy_post_table():
    if db.engine.dialect.name != "sqlite":
        return

    columns = {column["name"] for column in inspect(db.engine).get_columns("post")}
    with db.engine.begin() as connection:
        if "category" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE post ADD COLUMN category "
                    "VARCHAR(50) NOT NULL DEFAULT 'General'"
                )
            )
        if "author_id" not in columns:
            connection.execute(
                text("ALTER TABLE post ADD COLUMN author_id INTEGER REFERENCES user(id)")
            )
