### Quick start

When you start working on a this project for the first time, create a virtual environment inside your project.

```bash
python -m venv .venv
```

Activate the new virtual environment.

```bash
.venv\Scripts\activate.bat
```

If you are using `pip` to install packages (it comes by default with Python), you should upgrade it to the latest version.

Many exotic errors while installing a package are solved by just upgrading `pip` first.

```bash
python -m pip install --upgrade pip
```

Install packages from `requirements.txt`.

```bash
pip install -r requirements.txt
```

And finally you can run the development server.

```bash
fastapi dev app/main.py
```
