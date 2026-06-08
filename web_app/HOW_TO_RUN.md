# MABS PIMS — Web App — How to Run

## Step 1: Install Python packages

Open a terminal/command prompt, go to this `web_app` folder, and run:

```
pip install -r requirements_web.txt
```

## Step 2: Place your Firebase service key

The app looks for the service key in these locations (in order):
1. `C:\Users\<you>\.mabs\servicekey.json`   ← recommended
2. `..\data\servicekey.json`
3. `..\servicekey.json`

Copy your `servicekey.json` to one of those paths.

## Step 3: Start the web server

```
python app.py
```

You will see output like:
```
 * Running on http://0.0.0.0:5000
```

## Step 4: Open in browser

Open your browser and go to:
```
http://localhost:5000
```

Log in with your existing Firebase email and password.

---

## Production deployment (optional)

Install `gunicorn`:
```
pip install gunicorn
```

Run with gunicorn (Linux/Mac):
```
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

On Windows, use `waitress` instead:
```
pip install waitress
waitress-serve --port=5000 app:app
```

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FLASK_SECRET` | (built-in) | Session secret key — **change in production!** |
| `MABS_FIREBASE_SERVICE_ACCOUNT` | auto-detected | Path to servicekey.json |

To set a strong secret key on Windows:
```
set FLASK_SECRET=your-very-long-random-secret-here
python app.py
```
