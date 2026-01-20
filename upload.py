from flask import Flask, request, Response
import os
import base64
import datetime
import requests

UPLOAD_ROOT = "/images"

USERNAME = "motwane"
PASSWORD = "mmcpl123
GITHUB_TOKEN = "< git-hub token >"     
GITHUB_OWNER = "rathod-rohit-motwane"
GITHUB_REPO = "thermal-images"
GITHUB_BRANCH = "main"

app = Flask(__name__)

def check_auth(auth_header):
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    encoded = auth_header.split(" ", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    user, pwd = decoded.split(":", 1)
    return user == USERNAME and pwd == PASSWORD

def upload_to_github(local_path, github_path):
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{github_path}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    payload = {
        "message": f"Add {os.path.basename(github_path)}",
        "content": content,
        "branch": GITHUB_BRANCH
    }

    r = requests.put(url, json=payload, headers=headers)

    if r.status_code not in (200, 201):
        print("GitHub upload failed:", r.text)
    else:
        print("Uploaded to GitHub:", github_path)

@app.route("/", defaults={"path": ""}, methods=["PUT"])
@app.route("/<path:path>", methods=["PUT"])
def upload(path):
    auth = request.headers.get("Authorization")
    if not check_auth(auth):
        return Response(
            "Unauthorized", 401,
            {"WWW-Authenticate": 'Basic realm="Camera"'}
        )

    now = datetime.datetime.now()
    date_dir = now.strftime("%Y-%m-%d")
    time_name = now.strftime("%H-%M-%S_%f")

    ext = os.path.splitext(path)[1] or ".jpg"

    dir_path = os.path.join(UPLOAD_ROOT, date_dir)
    os.makedirs(dir_path, exist_ok=True)

    filename = f"thermal_{time_name}{ext}"
    full_path = os.path.join(dir_path, filename)

    # SAVE local FIRST
    with open(full_path, "wb") as f:
        f.write(request.get_data())

    print("Saved:", full_path)

    #  THEN upload to cloud/GitHub
    github_path = f"images/{date_dir}/{filename}"
    upload_to_github(full_path, github_path)

    return "OK\n", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=21) #ftp port
