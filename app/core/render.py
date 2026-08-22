"""HTML rendering using Jinja2 templates."""
import base64
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from typing import Dict

logger = logging.getLogger(__name__)


def get_embedded_base64_bitmap(filename: str) -> str:
    """Reads the bitmap, encodes it, and prepares the data URI."""
    bitmap_path = Path(__file__).parent.parent / "web" / "static" / filename
    ext = bitmap_path.suffix.lower()

    uri_header = {".ico": "data:image/x-icon", ".png": "data:image/png"}.get(ext, "")
    if not uri_header:
        raise ValueError(f"Unsupported bitmap extension: {ext}")

    try:
        with open(bitmap_path, "rb") as f:
            bitmap_bytes = f.read()
            bitmap_base64 = base64.b64encode(bitmap_bytes).decode('utf-8')
            return f"{uri_header};base64,{bitmap_base64}"
    except FileNotFoundError:
        logger.error(f"Warning: Bitmap file not found at {bitmap_path}")
        return ""


def get_embedded_text_file(filename: str) -> str:
    """Reads a text file (CSS/JS) and returns its content as a string."""
    file_path = Path(__file__).parent.parent / "web" / "static" / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Warning: Text file not found at {file_path}")
        return ""


# def static_url_for(endpoint, path=None, filename=None):
#     """
#     A simplified replacement for url_for for static files.
#     Assumes 'static' endpoint is for relative static assets.
#     """
#     # Accept both 'path' and 'filename' parameters for compatibility
#     file = path or filename
#     if endpoint == 'static':
#         # This assumes your static assets are intended to be accessed
#         # from a relative path like '/static/filename'. Adjust as needed.
#         return f"/static/{file}"
#     # Add other logic if needed, but for favicon, this is usually enough.
#     return f"/{endpoint}/{file}"


def render_app(data: Dict, template: str = "nfm.jinja") -> str:
    """Render data using a Jinja2 template.
    
    Args:
        data: The data to render in the template.
        template: The Jinja2 template filename to use.
    """

    template_folder = Path(__file__).parent.parent / "web" / "templates"
    environment = Environment(loader=FileSystemLoader(template_folder))

    embedded_favicon_ico = get_embedded_base64_bitmap("favicon.ico")
    embedded_favicon_96x96_png = get_embedded_base64_bitmap("favicon-96x96.png")
    embedded_apple_touch_icon_png = get_embedded_base64_bitmap("apple-touch-icon.png")
    embedded_site_webmanifest = get_embedded_text_file("manifest.json")

    embedded_nfm_css = get_embedded_text_file("nfm.css")
    embedded_nfm_js = get_embedded_text_file("nfm.js")

    context = {
        "data": data,
        "enable_hide_unread": False,
        # Pass the embedded data objects to the template context
        "embedded_favicon_ico": embedded_favicon_ico,
        "embedded_favicon_96x96_png": embedded_favicon_96x96_png,
        "embedded_apple_touch_icon_png": embedded_apple_touch_icon_png,
        "embedded_site_webmanifest": embedded_site_webmanifest,
        "embedded_nfm_css": embedded_nfm_css,
        "embedded_nfm_js": embedded_nfm_js,
    #   "url_for": static_url_for,
        "deploy_manifest": False,
    }

    feeds_template = environment.get_template(template)
    app_rendered = feeds_template.render(context)

    return app_rendered
