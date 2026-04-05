# We will not use pip for packagen managing since "uv" is ultra-fast.
# A requirements.txt file is not needed anymore and we just use back/pyproject.toml file for version managing.

Make sure the python version is 3.11.9
Make sure to be in root/backend and have pip installed

NO NEED TO CREATE OR ACTIVATE A VENV. uv handles that by creating it automatically

### 0. Create a .env file that has this exact structure:
    OPENAI_API_KEY=sk-proj-P...

### 1. Install "uv" if not installed
    pip install uv
### 2. !VERY IMPORTANT! Make sure you have python 3.11.9 version installed (check pyproject.toml)
### 3. Run this command for library installing and updating dependencies
    uv sync
### 4. from /root/backend run
    uv run uvicorn main:app --reload

# Once the app runs, a calibration will start. After calibration ended the python app will close and frontend should open.

# !!! make requests to /eye_tracking endpoint for eye tracking status