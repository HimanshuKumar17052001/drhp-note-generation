import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from datetime import datetime
import base64
import os

# --- CONFIGURATION ---
COMPANY_NAME = "Pine Labs Limited"
AXIS_LOGO_PATH = "assets/axis_logo.png"
COMPANY_LOGO_PATH = "assets/Pine Labs_logo.png"
FRONT_HEADER_PATH = "assets/front_header.png"
MARKDOWN_FILE = "input.md"
OUTPUT_PDF = f"output/{COMPANY_NAME}_ipo_notes.pdf"

# --- FUNCTIONS ---
def load_image_base64(path):
    with open(path, 'rb') as f:
        return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

def render_template(env, template_name, context):
    return env.get_template(template_name).render(context)

def main():
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader("templates"))

    # Load and convert Markdown to HTML
    with open(MARKDOWN_FILE, "r", encoding="utf-8") as f:
        md_content = f.read()
    html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])

    # Prepare dynamic context
    context = {
        "company_name": COMPANY_NAME.upper(),
        "document_date": datetime.today().strftime("%B %Y"),
        "company_logo_data": load_image_base64(COMPANY_LOGO_PATH),
        "axis_logo_data": load_image_base64(AXIS_LOGO_PATH),
        "front_header_data": load_image_base64(FRONT_HEADER_PATH),
        "content": html_body,
    }

    # Render full HTML
    front_html = render_template(env, "front_page.html", context)
    content_html = render_template(env, "content_page.html", context)
    full_html = front_html + content_html

    # Generate PDF
    HTML(string=full_html, base_url=".").write_pdf(
        OUTPUT_PDF, stylesheets=[CSS("styles/styles.css")]
    )
    print(f"✅ PDF generated: {OUTPUT_PDF}")

if __name__ == "__main__":
    main()
