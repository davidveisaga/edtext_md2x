from flask import Flask, render_template, request, jsonify, url_for
import urllib.parse
from markdown import markdown
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import shutil


def sanitize_relative_path(rel_path: str) -> str:
    """Sanitize a relative path by applying secure_filename to each component.

    Returns normalized relative path (uses '/' as separator) or '' for empty/root.
    """
    if not rel_path:
        return ""
    # normalize separators
    parts = []
    for part in rel_path.replace('\\', '/').split('/'):
        if not part or part == '.':
            continue
        safe = secure_filename(part)
        if safe:
            parts.append(safe)
    return '/'.join(parts)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev"
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
# Folder where generated files will be saved. Default to /home/usuario/docs
app.config["SAVE_FOLDER"] = os.environ.get("SAVE_FOLDER", "/home/davidveisaga/docs")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        md_content = request.form.get("content", "")
        preview_filename = request.form.get('preview_filename', '')
        print(f"DEBUG: Markdown recibido desde editor:\n{md_content[:500]}\n...")
        html = markdown(md_content, extensions=["extra", "fenced_code", "toc", "pymdownx.mark"])
        preview_q = urllib.parse.quote(preview_filename) if preview_filename else ''
        return render_template("preview.html", html=html, preview_q=preview_q, preview_name=preview_filename)
    return render_template("editor.html")

@app.route("/upload_image", methods=["POST"])
def upload_image():
    if "file" not in request.files:
        return jsonify({"success": 0, "message": "No file part"})
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": 0, "message": "No selected file"})
    
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(filepath)

    file_url = url_for("static", filename=f"uploads/{file.filename}")
    return jsonify({"success": 1, "message": "Upload success", "url": file_url})


@app.route("/save", methods=["POST"])
def save_file():
    """Save posted markdown content to the configured SAVE_FOLDER.

    Expects JSON: { "filename": "optional-name.md", "content": "...md..." }
    Returns JSON with success and saved path (absolute).
    """
    data = request.get_json() or {}
    content = data.get("content", "")
    filename = data.get("filename")
    if not filename:
        filename = f"editor-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    # allow nested paths but sanitize each component
    rel = sanitize_relative_path(filename)
    if not rel:
        return jsonify({"success": False, "message": "Invalid filename"}), 400

    save_folder = app.config["SAVE_FOLDER"]
    try:
        os.makedirs(save_folder, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"Could not create save folder: {e}"}), 500

    save_path = os.path.join(save_folder, *rel.split('/'))
    # Ensure the resolved path is contained inside the save_folder (prevent traversal)
    try:
        real_save_folder = os.path.realpath(save_folder)
        real_save_path = os.path.realpath(save_path)
        if not os.path.commonpath([real_save_folder, real_save_path]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid filename/path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid filename/path"}), 400
    try:
        # Write file as UTF-8
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return jsonify({"success": False, "message": f"Error writing file: {e}"}), 500

    return jsonify({"success": True, "path": save_path})


@app.route("/files", methods=["GET"])
def list_files():
    """Return list of files in SAVE_FOLDER as JSON.

    Response: { files: [ { name, mtime } ] }
    """
    save_folder = app.config.get("SAVE_FOLDER")
    try:
        os.makedirs(save_folder, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"Could not access save folder: {e}"}), 500

    # support optional path param to navigate directories
    req_path = request.args.get('path', '')
    rel = sanitize_relative_path(req_path)
    target = os.path.join(save_folder, *rel.split('/')) if rel else save_folder

    try:
        real_save_folder = os.path.realpath(save_folder)
        real_target = os.path.realpath(target)
        if not os.path.commonpath([real_save_folder, real_target]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid path"}), 400

    entries = []
    try:
        for name in os.listdir(target):
            path = os.path.join(target, name)
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = 0
            if os.path.isdir(path):
                entries.append({"name": name, "type": "dir", "mtime": mtime})
            elif os.path.isfile(path):
                entries.append({"name": name, "type": "file", "mtime": mtime})
    except FileNotFoundError:
        return jsonify({"success": False, "message": "Path not found"}), 404

    # sort: dirs first, then files, both by mtime desc
    entries.sort(key=lambda x: (0 if x["type"] == "dir" else 1, -x.get("mtime", 0)))

    parent = ''
    if rel:
        parent = os.path.dirname(rel)

    return jsonify({"success": True, "files": entries, "path": rel, "parent": parent})


@app.route("/file", methods=["GET"])
def get_file():
    """Return file content by name: /file?name=filename.md"""
    name = request.args.get("name")
    if not name:
        return jsonify({"success": False, "message": "Missing 'name' parameter"}), 400

    # filename may include relative path; sanitize each component
    rel = sanitize_relative_path(name)
    if not rel:
        return jsonify({"success": False, "message": "Invalid filename"}), 400

    save_folder = app.config.get("SAVE_FOLDER")
    file_path = os.path.join(save_folder, *rel.split('/'))

    try:
        real_save_folder = os.path.realpath(save_folder)
        real_file_path = os.path.realpath(file_path)
        if not os.path.commonpath([real_save_folder, real_file_path]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid filename/path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid filename/path"}), 400

    if not os.path.exists(file_path):
        return jsonify({"success": False, "message": "File not found"}), 404

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return jsonify({"success": False, "message": f"Error reading file: {e}"}), 500

    return jsonify({"success": True, "name": rel, "content": content})


@app.route("/mkdir", methods=["POST"])
def make_dir():
    """Create a directory under SAVE_FOLDER. Expects JSON { "dirname": "name", "parent": "optional/relative/path" }"""
    data = request.get_json() or {}
    dirname = data.get('dirname')
    parent = data.get('parent', '')
    if not dirname:
        return jsonify({"success": False, "message": "Missing dirname"}), 400

    safe_dir = sanitize_relative_path(dirname)
    parent_rel = sanitize_relative_path(parent)
    if not safe_dir:
        return jsonify({"success": False, "message": "Invalid dirname"}), 400

    save_folder = app.config.get("SAVE_FOLDER")
    target = os.path.join(save_folder, *(parent_rel.split('/') if parent_rel else []), safe_dir)
    try:
        real_save_folder = os.path.realpath(save_folder)
        real_target = os.path.realpath(target)
        if not os.path.commonpath([real_save_folder, real_target]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid path"}), 400

    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify({"success": False, "message": f"Could not create directory: {e}"}), 500

    return jsonify({"success": True, "path": os.path.relpath(target, save_folder)})


@app.route("/delete", methods=["POST"])
def delete_entry():
    """Delete a file or directory under SAVE_FOLDER. Expects JSON { "name": "rel/path" }"""
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({"success": False, "message": "Missing name"}), 400

    rel = sanitize_relative_path(name)
    if not rel:
        return jsonify({"success": False, "message": "Invalid name"}), 400

    save_folder = app.config.get("SAVE_FOLDER")
    target = os.path.join(save_folder, *rel.split('/'))
    try:
        real_save_folder = os.path.realpath(save_folder)
        real_target = os.path.realpath(target)
        if not os.path.commonpath([real_save_folder, real_target]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid path"}), 400

    if not os.path.exists(target):
        return jsonify({"success": False, "message": "Not found"}), 404

    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        return jsonify({"success": False, "message": f"Error deleting: {e}"}), 500

    return jsonify({"success": True})


@app.route("/rename", methods=["POST"])
def rename_entry():
    """Rename a file or directory. Expects JSON { "old": "rel/old", "new": "newname/or/rel/path" }

    If "new" does not contain a path, it will be placed in the same parent directory as old.
    """
    data = request.get_json() or {}
    old = data.get('old')
    new = data.get('new')
    if not old or not new:
        return jsonify({"success": False, "message": "Missing old or new"}), 400

    old_rel = sanitize_relative_path(old)
    new_rel = sanitize_relative_path(new)
    if not old_rel or not new_rel:
        return jsonify({"success": False, "message": "Invalid names"}), 400

    # If new_rel is a simple name (no slash), keep same parent as old
    if '/' not in new_rel:
        parent = os.path.dirname(old_rel)
        new_rel = parent + '/' + new_rel if parent else new_rel

    save_folder = app.config.get("SAVE_FOLDER")
    old_path = os.path.join(save_folder, *old_rel.split('/'))
    new_path = os.path.join(save_folder, *new_rel.split('/'))

    try:
        real_save_folder = os.path.realpath(save_folder)
        if not (os.path.commonpath([real_save_folder, os.path.realpath(old_path)]) == real_save_folder and
                os.path.commonpath([real_save_folder, os.path.realpath(new_path)]) == real_save_folder):
            return jsonify({"success": False, "message": "Invalid path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid path"}), 400

    if not os.path.exists(old_path):
        return jsonify({"success": False, "message": "Source not found"}), 404

    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.rename(old_path, new_path)
    except Exception as e:
        return jsonify({"success": False, "message": f"Error renaming: {e}"}), 500

    return jsonify({"success": True, "new": new_rel})


# Some browser/devtools extensions probe for app-specific JSON under /.well-known.
# Serve a silent 204 for those requests to avoid noisy 404s in the server log.
@app.route('/.well-known/appspecific/<path:filename>', methods=['GET'])
def well_known_probe(filename: str):
    return ('', 204)

if __name__ == "__main__":
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.run(debug=True)
