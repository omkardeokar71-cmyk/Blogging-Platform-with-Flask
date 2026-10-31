import re
import secrets
from functools import wraps

from flask import (
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.main import main
from app.models import Post, User

CATEGORIES = ("General", "Technology", "Lifestyle", "Travel", "Food", "Other")


@main.before_request
def protect_post_requests():
    if request.method == "POST":
        submitted_token = request.form.get("csrf_token", "")
        session_token = session.get("_csrf_token", "")
        if not session_token or not secrets.compare_digest(
            submitted_token, session_token
        ):
            abort(400, description="The form expired. Please try again.")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped_view


def owned_post_or_404(post_id):
    post = db.get_or_404(Post, post_id)
    if post.author_id != g.user.id:
        abort(404)
    return post


@main.get("/")
def index():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    posts_query = Post.query.order_by(Post.created_at.desc())

    if category in CATEGORIES:
        posts_query = posts_query.filter_by(category=category)
    else:
        category = ""
    if query:
        pattern = f"%{query}%"
        posts_query = posts_query.filter(
            or_(Post.title.ilike(pattern), Post.content.ilike(pattern))
        )

    return render_template(
        "index.html",
        posts=posts_query.all(),
        categories=CATEGORIES,
        selected_category=category,
        search_query=query,
    )


@main.get("/register")
def register():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))
    return render_template("register.html")


@main.post("/register")
def create_account():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().casefold()
    password = request.form.get("password", "")
    valid_email = (
        len(email) <= 254
        and email.count("@") == 1
        and "@" in email
        and "." in email.rsplit("@", 1)[-1]
        and not any(character.isspace() for character in email)
    )

    if not re.fullmatch(r"[A-Za-z0-9_]{3,40}", username):
        flash("Username must be 3–40 letters, numbers, or underscores.", "error")
    elif not valid_email:
        flash("Enter a valid email address.", "error")
    elif len(password) < 8 or len(password) > 128:
        flash("Password must be between 8 and 128 characters.", "error")
    elif User.query.filter(
        or_(User.username.ilike(username), User.email == email)
    ).first():
        flash("That username or email is already registered.", "error")
    else:
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That username or email is already registered.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            flash("Your account is ready. Welcome to the community!", "success")
            return redirect(url_for("main.dashboard"))

    return render_template("register.html", username=username, email=email), 400


@main.get("/login")
def login():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html")


@main.post("/login")
def sign_in():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    identity = request.form.get("identity", "").strip()
    password = request.form.get("password", "")
    user = User.query.filter(
        or_(
            User.username.ilike(identity),
            User.email == identity.casefold(),
        )
    ).first()

    if user is None or len(password) > 128 or not user.check_password(password):
        flash("The username/email or password is incorrect.", "error")
        return render_template("login.html", identity=identity), 401

    session.clear()
    session["user_id"] = user.id
    flash(f"Welcome back, {user.username}!", "success")
    return redirect(url_for("main.dashboard"))


@main.post("/logout")
@login_required
def sign_out():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))


@main.get("/dashboard")
@login_required
def dashboard():
    posts = Post.query.filter_by(author_id=g.user.id).order_by(
        Post.created_at.desc()
    )
    return render_template("dashboard.html", posts=posts.all())


@main.get("/posts/new")
@login_required
def new_post():
    return render_template(
        "post_form.html",
        post=None,
        categories=CATEGORIES,
        heading="Write a story",
    )


@main.post("/posts/new")
@login_required
def create_post():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category", "General")
    if not title or len(title) > 200 or not content or len(content) > 20000:
        flash("Add a title and story (up to 20,000 characters).", "error")
    elif category not in CATEGORIES:
        flash("Choose one of the listed categories.", "error")
    else:
        post = Post(
            title=title,
            content=content,
            category=category,
            author_id=g.user.id,
        )
        db.session.add(post)
        db.session.commit()
        flash("Your story has been published.", "success")
        return redirect(url_for("main.post_detail", post_id=post.id))

    return (
        render_template(
            "post_form.html",
            post=None,
            categories=CATEGORIES,
            heading="Write a story",
            title=title,
            content=content,
            selected_category=category,
        ),
        400,
    )


@main.get("/posts/<int:post_id>")
def post_detail(post_id):
    post = db.get_or_404(Post, post_id)
    return render_template("post_detail.html", post=post)


@main.get("/posts/<int:post_id>/edit")
@login_required
def edit_post(post_id):
    post = owned_post_or_404(post_id)
    return render_template(
        "post_form.html",
        post=post,
        categories=CATEGORIES,
        heading="Edit your story",
    )


@main.post("/posts/<int:post_id>/edit")
@login_required
def update_post(post_id):
    post = owned_post_or_404(post_id)
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category", "General")
    if not title or len(title) > 200 or not content or len(content) > 20000:
        flash("Add a title and story (up to 20,000 characters).", "error")
    elif category not in CATEGORIES:
        flash("Choose one of the listed categories.", "error")
    else:
        post.title = title
        post.content = content
        post.category = category
        db.session.commit()
        flash("Your changes have been saved.", "success")
        return redirect(url_for("main.post_detail", post_id=post.id))

    return (
        render_template(
            "post_form.html",
            post=post,
            categories=CATEGORIES,
            heading="Edit your story",
            title=title,
            content=content,
            selected_category=category,
        ),
        400,
    )


@main.post("/posts/<int:post_id>/delete")
@login_required
def delete_post(post_id):
    post = owned_post_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Your story has been deleted.", "success")
    return redirect(url_for("main.dashboard"))
