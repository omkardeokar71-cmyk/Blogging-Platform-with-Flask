import re
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import URL, create_engine, text

from app import create_app
from app.extensions import db
from app.models import Post, User
from config import Config


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class BlogApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def csrf_token(self, client=None, path="/"):
        client = client or self.client
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match, "The page should render a CSRF token.")
        return match.group(1).decode()

    def register(
        self, username="story_writer", email="writer@example.com", client=None
    ):
        client = client or self.client
        token = self.csrf_token(client, "/register")
        return client.post(
            "/register",
            data={
                "csrf_token": token,
                "username": username,
                "email": email,
                "password": "a secure test password",
            },
        )

    def create_post(self, client=None, title="A thoughtful story", category="Travel"):
        client = client or self.client
        token = self.csrf_token(client, "/posts/new")
        return client.post(
            "/posts/new",
            data={
                "csrf_token": token,
                "title": title,
                "content": "A story with a beginning, middle, and end.",
                "category": category,
            },
        )

    def test_registration_password_hash_sign_in_and_sign_out(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as state:
            self.assertIn("user_id", state)
            registered_id = state["user_id"]
        with self.app.app_context():
            user = db.session.get(User, registered_id)
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "a secure test password")
            self.assertTrue(user.check_password("a secure test password"))

        token = self.csrf_token(self.client, "/")
        response = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

        token = self.csrf_token(self.client, "/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "identity": "WRITER@example.com",
                "password": "a secure test password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_post_lifecycle_and_owner_permissions(self):
        self.assertEqual(self.register().status_code, 302)
        response = self.create_post(title="A story about careful gardening")
        self.assertEqual(response.status_code, 302)
        post_url = response.headers["Location"]
        post_id = int(post_url.rstrip("/").rsplit("/", 1)[-1])
        detail = self.client.get(post_url)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"careful gardening", detail.data)
        self.assertIn(b"Travel", detail.data)

        stranger = self.app.test_client()
        self.assertEqual(
            self.register(
                "another_writer", "another@example.com", stranger
            ).status_code,
            302,
        )
        self.assertEqual(stranger.get(f"/posts/{post_id}/edit").status_code, 404)
        token = self.csrf_token(stranger, "/")
        self.assertEqual(
            stranger.post(
                f"/posts/{post_id}/delete", data={"csrf_token": token}
            ).status_code,
            404,
        )

        token = self.csrf_token(self.client, f"/posts/{post_id}/edit")
        response = self.client.post(
            f"/posts/{post_id}/edit",
            data={
                "csrf_token": token,
                "title": "The updated story",
                "content": "Updated story text.",
                "category": "Food",
            },
        )
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(post_url)
        self.assertIn(b"The updated story", detail.data)
        self.assertIn(b"Food", detail.data)

        token = self.csrf_token(self.client, "/dashboard")
        response = self.client.post(
            f"/posts/{post_id}/delete", data={"csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(post_url).status_code, 404)

    def test_invalid_registration_and_missing_csrf_are_rejected(self):
        self.assertEqual(self.client.post("/register").status_code, 400)
        response = self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(self.client, "/register"),
                "username": "x",
                "email": "not-an-email",
                "password": "short",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Username must be", response.data)

        self.assertEqual(self.register().status_code, 302)
        another_client = self.app.test_client()
        response = self.register(
            "story_writer", "different@example.com", another_client
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already registered", response.data)

    def test_search_category_xss_escaping_and_error_pages(self):
        self.assertEqual(self.register().status_code, 302)
        token = self.csrf_token(self.client, "/posts/new")
        response = self.client.post(
            "/posts/new",
            data={
                "csrf_token": token,
                "title": "Garden notes",
                "content": "<script>alert('not executable')</script>",
                "category": "Lifestyle",
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/?q=Garden&category=Lifestyle")
        self.assertIn(b"Garden notes", response.data)
        response = self.client.get("/?q=missing&category=Travel")
        self.assertIn(b"No stories found", response.data)
        with self.app.app_context():
            post = Post.query.filter_by(title="Garden notes").one()
            post_id = post.id
        detail = self.client.get(f"/posts/{post_id}")
        self.assertIn(b"&lt;script&gt;", detail.data)
        self.assertNotIn(b"<script>alert", detail.data)

        not_found = self.client.get("/does-not-exist")
        self.assertEqual(not_found.status_code, 404)
        self.assertIn(b"Back to the stories", not_found.data)

    def test_blog_homepage(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Stories to settle into", response.data)
        self.assertIn(b"Good ideas deserve", response.data)

    def test_legacy_sqlite_posts_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = URL.create(
                "sqlite",
                database=str(Path(directory) / "legacy.db"),
            )
            engine = create_engine(database_url)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE post ("
                        "id INTEGER PRIMARY KEY, "
                        "title VARCHAR(200) NOT NULL, "
                        "content TEXT NOT NULL, "
                        "created_at DATETIME NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO post (id, title, content, created_at) "
                        "VALUES (1, 'An older story', 'Saved content', "
                        "'2026-01-01 12:00:00')"
                    )
                )
            engine.dispose()

            class LegacyConfig(TestConfig):
                SQLALCHEMY_DATABASE_URI = database_url

            legacy_app = create_app(LegacyConfig)
            with legacy_app.app_context():
                post = db.session.get(Post, 1)
                self.assertIsNotNone(post)
                self.assertEqual(post.title, "An older story")
                self.assertEqual(post.content, "Saved content")
                self.assertEqual(post.category, "General")
                self.assertIsNone(post.author_id)
                db.session.remove()
                db.drop_all()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
