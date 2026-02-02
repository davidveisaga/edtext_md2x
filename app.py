from flask import Flask, render_template, request, jsonify, url_for, send_file
import urllib.parse
from markdown import markdown
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import shutil
import tempfile
import glob
import re


def sanitize_relative_path(rel_path: str) -> str:
    """Normalize a user-provided relative path without renaming components.

    - Collapses repeated separators and dot segments.
    - Rejects any path that escapes upward ("..") or resolves to root.
    - Preserves spaces and accents so existing files keep working.
    Returns normalized relative path using '/' separators, or '' when invalid/empty.
    """
    if not rel_path:
        return ""

    # Normalize separators first so normpath can collapse dot segments
    rel_path = rel_path.replace('\\', '/')
    normalized = os.path.normpath(rel_path).replace('\\', '/')

    # Disallow traversal or root-like results
    if normalized in ("", ".", "..") or normalized.startswith("../"):
        return ""

    parts = []
    for part in normalized.split('/'):
        if part in ("", "."):
            continue
        if part == "..":
            return ""
        parts.append(part)

    return '/'.join(parts)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev"
# Folder where images will be saved
app.config["IMAGE_FOLDER"] = os.path.expanduser("~/docs/imagenes")
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

@app.route("/images/<path:filename>")
def serve_image(filename):
    """Serve images from the IMAGE_FOLDER directory."""
    from flask import send_from_directory
    return send_from_directory(app.config["IMAGE_FOLDER"], filename)

@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    """Serve PDF files from the SAVE_FOLDER directory."""
    from flask import send_from_directory
    # Sanitize the path
    rel = sanitize_relative_path(filename)
    if not rel:
        return "Invalid path", 400
    
    save_folder = app.config["SAVE_FOLDER"]
    pdf_path = os.path.join(save_folder, *rel.split('/'))
    
    # Security check
    try:
        real_save_folder = os.path.realpath(save_folder)
        real_pdf_path = os.path.realpath(pdf_path)
        if not os.path.commonpath([real_save_folder, real_pdf_path]) == real_save_folder:
            return "Invalid file path", 400
    except Exception:
        return "Invalid file path", 400
    
    if not os.path.exists(pdf_path):
        return "File not found", 404
    
    # Get the directory and filename
    pdf_dir = os.path.dirname(pdf_path)
    pdf_filename = os.path.basename(pdf_path)
    
    return send_from_directory(pdf_dir, pdf_filename)

@app.route("/pdf_absolute/<path:encoded_path>")
def serve_pdf_absolute(encoded_path):
    """Serve PDF files from absolute paths (with security checks)."""
    from flask import send_from_directory
    import base64
    import platform
    import re
    
    # Decode the base64 encoded path
    try:
        decoded_path = base64.b64decode(encoded_path).decode('utf-8')
    except Exception:
        return jsonify({"success": False, "message": "Invalid path encoding"}), 400
    
    # Convertir ruta de Windows a WSL si estamos en Linux
    normalized_path = decoded_path
    
    if platform.system() == 'Linux':
        # Detectar si es una ruta de Windows (C:/, D:/, etc.)
        windows_path_match = re.match(r'^([A-Za-z]):/(.*)$', decoded_path.replace('\\', '/'))
        if windows_path_match:
            drive_letter = windows_path_match.group(1).lower()
            path_rest = windows_path_match.group(2)
            # Convertir a ruta WSL: C:/Users/... -> /mnt/c/Users/...
            normalized_path = f"/mnt/{drive_letter}/{path_rest}"
    elif platform.system() == 'Windows':
        # En Windows, convertir / a \
        normalized_path = decoded_path.replace('/', '\\')
    
    pdf_path = os.path.abspath(os.path.normpath(normalized_path))
    
    # Security checks
    if not os.path.exists(pdf_path):
        return jsonify({"success": False, "message": f"File not found"}), 404
    
    if not os.path.isfile(pdf_path):
        return jsonify({"success": False, "message": "Not a file"}), 400
    
    if not pdf_path.lower().endswith('.pdf'):
        return jsonify({"success": False, "message": "Not a PDF file"}), 400
    
    # Get the directory and filename
    pdf_dir = os.path.dirname(pdf_path)
    pdf_filename = os.path.basename(pdf_path)
    
    print(f"DEBUG: Sirviendo archivo: {pdf_filename} desde {pdf_dir}")
    
    try:
        return send_from_directory(pdf_dir, pdf_filename)
    except Exception as e:
        print(f"DEBUG: Error sirviendo archivo: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/download_odt", methods=["POST"])
def download_odt():
    """Convert markdown file to ODT format and download it."""
    from odf.opendocument import OpenDocumentText
    from odf.style import Style, TextProperties, ParagraphProperties, GraphicProperties
    from odf.text import P, H, Span
    from odf.draw import Frame, Image
    from urllib.parse import urlparse, unquote
    
    filename = request.json.get("filename", "").strip()
    if not filename:
        return jsonify({"success": False, "message": "No filename provided"}), 400
    
    # Sanitize and get file path
    rel = sanitize_relative_path(filename)
    if not rel:
        return jsonify({"success": False, "message": "Invalid filename"}), 400
    
    save_folder = app.config["SAVE_FOLDER"]
    md_path = os.path.join(save_folder, *rel.split('/'))
    
    # Security check
    try:
        real_save_folder = os.path.realpath(save_folder)
        real_md_path = os.path.realpath(md_path)
        if not os.path.commonpath([real_save_folder, real_md_path]) == real_save_folder:
            return jsonify({"success": False, "message": "Invalid file path"}), 400
    except Exception:
        return jsonify({"success": False, "message": "Invalid file path"}), 400
    
    if not os.path.exists(md_path):
        return jsonify({"success": False, "message": "File not found"}), 404
    
    try:
        # Read markdown content
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown(md_content, extensions=["extra", "fenced_code", "toc"])
        
        # Create ODT document
        doc = OpenDocumentText()
        
        # Define styles
        bold_style = Style(name="Bold", family="text")
        bold_style.addElement(TextProperties(fontweight="bold"))
        doc.styles.addElement(bold_style)
        
        italic_style = Style(name="Italic", family="text")
        italic_style.addElement(TextProperties(fontstyle="italic"))
        doc.styles.addElement(italic_style)
        
        # Highlight color styles
        highlight_styles = {}
        color_map = {
            'yellow': '#ffff00',
            'green': '#90EE90',
            'blue': '#ADD8E6',
            'gray': '#D3D3D3',
            'orange': '#FFD580',
            'purple': '#DDA0DD'
        }
        
        for color_name, color_hex in color_map.items():
            style = Style(name=f"Highlight{color_name.capitalize()}", family="text")
            style.addElement(TextProperties(backgroundcolor=color_hex))
            doc.automaticstyles.addElement(style)
            highlight_styles[color_name] = style
        
        # Style for images
        img_style = Style(name="ImageStyle", family="graphic")
        img_style.addElement(GraphicProperties(
            horizontalpos="center",
            horizontalrel="paragraph"
        ))
        doc.automaticstyles.addElement(img_style)
        
        # Parse HTML and convert to ODT
        from html.parser import HTMLParser
        
        class HTMLtoODT(HTMLParser):
            def __init__(self, document, image_folder, img_style, highlight_styles):
                super().__init__()
                self.doc = document
                self.image_folder = image_folder
                self.img_style = img_style
                self.highlight_styles = highlight_styles
                self.current_para = None
                self.style_stack = []
                self.image_counter = 0
                
            def handle_starttag(self, tag, attrs):
                if tag in ['p', 'div']:
                    self.current_para = P()
                elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    level = int(tag[1])
                    self.current_para = H(outlinelevel=level)
                elif tag == 'strong' or tag == 'b':
                    self.style_stack.append('bold')
                elif tag == 'em' or tag == 'i':
                    self.style_stack.append('italic')
                elif tag == 'span':
                    # Handle span tags with highlight classes
                    attrs_dict = dict(attrs)
                    class_attr = attrs_dict.get('class', '')
                    
                    # Check if it's a highlight span
                    if 'text-highlight' in class_attr:
                        # Extract color from class like "text-highlight hl-yellow"
                        for color in ['yellow', 'green', 'blue', 'gray', 'orange', 'purple']:
                            if f'hl-{color}' in class_attr:
                                self.style_stack.append(f'highlight-{color}')
                                break
                elif tag == 'mark':
                    # Handle highlight/mark tags
                    attrs_dict = dict(attrs)
                    color = attrs_dict.get('data-color', '')
                    if color:
                        self.style_stack.append(f'highlight-{color}')
                elif tag == 'br':
                    if self.current_para is None:
                        self.current_para = P()
                    self.doc.text.addElement(self.current_para)
                    self.current_para = P()
                elif tag == 'img':
                    # Handle images
                    attrs_dict = dict(attrs)
                    img_src = attrs_dict.get('src', '')
                    
                    if img_src:
                        # Close current paragraph if exists
                        if self.current_para is not None:
                            self.doc.text.addElement(self.current_para)
                            self.current_para = None
                        
                        # Add image to document
                        self.add_image(img_src)
                        
                        # Start new paragraph
                        self.current_para = P()
            
            def add_image(self, img_src):
                """Add image to ODT document"""
                try:
                    # Parse image URL
                    parsed = urlparse(img_src)
                    
                    # Determine image file path
                    img_path = None
                    if parsed.path.startswith('/images/'):
                        # Image from /images/ route
                        img_filename = unquote(parsed.path.split('/images/')[-1])
                        img_path = os.path.join(self.image_folder, img_filename)
                    elif parsed.scheme in ['http', 'https']:
                        # External URL - skip for now
                        return
                    else:
                        # Relative or absolute path
                        img_filename = unquote(parsed.path.lstrip('/'))
                        img_path = os.path.join(self.image_folder, img_filename)
                    
                    if img_path and os.path.exists(img_path):
                        # Get image dimensions using PIL
                        from PIL import Image as PILImage
                        with PILImage.open(img_path) as pil_img:
                            width_px, height_px = pil_img.size
                        
                        # Calculate size in inches maintaining aspect ratio
                        # Max width: 6 inches (roughly A4 page width minus margins)
                        max_width_in = 6.0
                        dpi = 96  # Standard screen DPI
                        
                        width_in = width_px / dpi
                        height_in = height_px / dpi
                        
                        # Scale down if image is too wide
                        if width_in > max_width_in:
                            scale = max_width_in / width_in
                            width_in = max_width_in
                            height_in = height_in * scale
                        
                        # Get image extension
                        _, ext = os.path.splitext(img_path)
                        ext = ext.lstrip('.')
                        
                        # Add image to document
                        self.image_counter += 1
                        img_name = f"Pictures/Image{self.image_counter}.{ext}"
                        href = self.doc.addPicture(img_path)
                        
                        # Create frame and image elements with correct dimensions
                        frame = Frame(width=f"{width_in}in", height=f"{height_in}in", stylename=self.img_style, anchortype="paragraph")
                        image = Image(href=href)
                        frame.addElement(image)
                        
                        # Add to paragraph
                        para = P()
                        para.addElement(frame)
                        self.doc.text.addElement(para)
                        
                except Exception as e:
                    print(f"Error adding image {img_src}: {e}")
            
            def handle_endtag(self, tag):
                if tag in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    if self.current_para is not None:
                        self.doc.text.addElement(self.current_para)
                        self.current_para = None
                elif tag in ['strong', 'b', 'em', 'i', 'mark']:
                    if self.style_stack:
                        self.style_stack.pop()
                elif tag == 'span':
                    # Check if we pushed a highlight style for this span
                    if self.style_stack and self.style_stack[-1].startswith('highlight-'):
                        self.style_stack.pop()
            
            def handle_data(self, data):
                if data.strip():
                    if self.current_para is None:
                        self.current_para = P()
                    
                    if self.style_stack:
                        style_name = self.style_stack[-1]
                        
                        # Handle highlight styles
                        if style_name.startswith('highlight-'):
                            color = style_name.replace('highlight-', '')
                            if color in self.highlight_styles:
                                span = Span(stylename=self.highlight_styles[color])
                                span.addText(data)
                                self.current_para.addElement(span)
                            else:
                                self.current_para.addText(data)
                        else:
                            # Handle bold/italic
                            span = Span(stylename=style_name.capitalize())
                            span.addText(data)
                            self.current_para.addElement(span)
                    else:
                        self.current_para.addText(data)
        
        parser = HTMLtoODT(doc, app.config["IMAGE_FOLDER"], img_style, highlight_styles)
        parser.feed(html_content)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.odt', delete=False) as tmp:
            odt_path = tmp.name
        
        doc.save(odt_path)
        
        # Generate ODT filename
        base_name = os.path.splitext(os.path.basename(filename))[0]
        odt_filename = f"{base_name}.odt"
        
        # Send file and delete after sending
        response = send_file(
            odt_path,
            as_attachment=True,
            download_name=odt_filename,
            mimetype='application/vnd.oasis.opendocument.text'
        )
        
        # Schedule file deletion after response
        @response.call_on_close
        def cleanup():
            try:
                os.unlink(odt_path)
            except Exception:
                pass
        
        return response
        
    except Exception as e:
        if 'odt_path' in locals() and os.path.exists(odt_path):
            try:
                os.unlink(odt_path)
            except:
                pass
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@app.route("/import_odt", methods=["POST"])
def import_odt():
    """Convert ODT file to Markdown content."""
    from odf.opendocument import load
    from odf.text import P, H
    from odf.table import Table
    
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file provided"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400
    
    if not file.filename.lower().endswith('.odt'):
        return jsonify({"success": False, "message": "File must be .odt format"}), 400
    
    try:
        # Save temporarily
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.odt', delete=False) as tmp:
            tmp_path = tmp.name
            file.save(tmp_path)
        
        # Load ODT document
        odt_doc = load(tmp_path)
        
        # Extract text content
        markdown_content = ""
        
        def extract_text_from_elements(elements, level=0):
            """Recursively extract text from ODT elements."""
            result = ""
            for element in elements:
                if element.qname[1] == 'p':
                    # Paragraph
                    text = "".join([node.data for node in element.childNodes if hasattr(node, 'data')])
                    result += text + "\n"
                elif element.qname[1] == 'h':
                    # Heading
                    outline_level = element.getAttribute('outlinelevel')
                    text = "".join([node.data for node in element.childNodes if hasattr(node, 'data')])
                    heading_level = int(outline_level) if outline_level else 1
                    result += ("#" * heading_level) + " " + text + "\n"
                elif element.qname[1] == 'span':
                    # Span (text with formatting)
                    text = "".join([node.data for node in element.childNodes if hasattr(node, 'data')])
                    result += text
                elif element.qname[1] == 'list':
                    # List
                    for item in element.getElementsByType((element.qname[0], 'list-item')):
                        item_text = extract_text_from_elements(item.childNodes, level + 1)
                        result += ("  " * level) + "- " + item_text.strip() + "\n"
                elif element.qname[1] == 'table':
                    # Simple table handling
                    result += "\n| Table |\n| --- |\n\n"
                elif hasattr(element, 'childNodes'):
                    # Recursively process child nodes
                    result += extract_text_from_elements(element.childNodes, level)
            return result
        
        # Get text from document body
        body = odt_doc.text
        if body:
            markdown_content = extract_text_from_elements(body.childNodes)
        
        # Clean up temporary file
        try:
            os.unlink(tmp_path)
        except:
            pass
        
        return jsonify({
            "success": True, 
            "content": markdown_content,
            "filename": os.path.splitext(file.filename)[0] + ".md"
        })
        
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except:
            pass
        return jsonify({"success": False, "message": f"Error processing ODT: {str(e)}"}), 500


@app.route("/upload_image", methods=["POST"])
def upload_image():
    if "file" not in request.files:
        return jsonify({"success": 0, "message": "No file part"})
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": 0, "message": "No selected file"})
    
    # Obtener el nombre del archivo actual del editor (si existe)
    current_filename = request.form.get("current_filename", "")
    
    # Generar nombre para la imagen
    original_filename = secure_filename(file.filename)
    _, ext = os.path.splitext(original_filename)
    if not ext:
        ext = ".png"  # extensión por defecto para imágenes del portapapeles
    
    image_folder = app.config["IMAGE_FOLDER"]
    os.makedirs(image_folder, exist_ok=True)
    
    if current_filename:
        # Usar el nombre del archivo actual como base
        base_name = os.path.splitext(current_filename)[0]
        base_name = secure_filename(base_name)
        
        # Encontrar el siguiente número disponible
        counter = 1
        while True:
            unique_filename = f"{base_name}{counter:02d}{ext}"
            filepath = os.path.join(image_folder, unique_filename)
            if not os.path.exists(filepath):
                break
            counter += 1
    else:
        # Si no hay archivo actual, usar timestamp como antes
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        unique_filename = f"image_{timestamp}{ext}"
        filepath = os.path.join(image_folder, unique_filename)
    
    file.save(filepath)

    file_url = url_for("serve_image", filename=unique_filename)
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
            # Si es un archivo .md, borrar también sus imágenes asociadas
            if target.endswith('.md'):
                base_name = os.path.splitext(os.path.basename(target))[0]
                image_folder = app.config.get("IMAGE_FOLDER")
                
                if image_folder and os.path.exists(image_folder):
                    # Buscar imágenes con el patrón: basename01.ext, basename02.ext, etc.
                    pattern = os.path.join(image_folder, f"{base_name}[0-9][0-9].*")
                    image_files = glob.glob(pattern)
                    
                    # Borrar cada imagen encontrada
                    for img_path in image_files:
                        try:
                            os.remove(img_path)
                        except Exception:
                            pass  # Continuar aunque falle el borrado de alguna imagen
            
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
    os.makedirs(app.config["IMAGE_FOLDER"], exist_ok=True)
    app.run(debug=True)
