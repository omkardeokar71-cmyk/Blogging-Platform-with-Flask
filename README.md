# The Sunday Edit

A small, responsive blogging platform built with Flask and SQLite.

## Features

- Account registration, sign-in, and sign-out
- Password hashing and CSRF-protected forms
- Publish, edit, and delete your own stories
- Story categories, search, and a personal dashboard
- Responsive templates and a local SQLite database

## Run locally

Open PowerShell in this folder and activate the existing virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "replace-this-with-a-long-random-value"
python run.py
```

Then visit <http://127.0.0.1:5000/>.

The SQLite database is stored in `instance\blog.db`. Existing posts are kept and
assigned the **General** category when the application adds the new blog fields.
Set `SESSION_COOKIE_SECURE=true` when serving the application over HTTPS.

The built-in secret key is only for local development. Set a private,
unpredictable `SECRET_KEY` before deploying the application.

## Run the tests

The test suite uses Python's built-in `unittest` module and an in-memory
database, so it will not change your local blog:

```powershell
python -m unittest discover -s tests -v
```
