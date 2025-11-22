from flask import Flask, render_template, request, jsonify, url_for
from markdown import markdown
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev"
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        md_content = request.form.get("content", "")
        html = markdown(md_content, extensions=["extra", "fenced_code", "toc"])
        return render_template("preview.html", html=html)
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

if __name__ == "__main__":
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.run(debug=True)
