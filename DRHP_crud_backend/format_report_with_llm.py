import os
from mongoengine import connect, Document, StringField, IntField, ReferenceField
from dotenv import load_dotenv
from azure_blob_utils import get_blob_storage

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME", "DRHP_NOTES")
connect(alias="core", host=MONGODB_URI, db=DB_NAME)


# Models
class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    drhp_file_url = StringField(required=True)
    website_link = StringField()
    created_at = StringField()


class ChecklistOutput(Document):
    meta = {"db_alias": "core", "collection": "checklist_outputs"}
    company_id = ReferenceField(Company, required=True)
    checklist_name = StringField(required=True)
    row_index = IntField(required=True)
    topic = StringField()
    ai_output = StringField()
    citations = StringField()
    commentary = StringField()


class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)


def get_company_by_name(company_name):
    company = Company.objects(name=company_name).first()
    if not company:
        raise Exception(f"Company '{company_name}' not found in MongoDB.")
    return company


def generate_markdown_for_company(company_id, company_name):
    # company_id should be a Company object
    rows = (
        ChecklistOutput.objects(company_id=company_id)
        .order_by("row_index")
        .only("topic", "ai_output", "citations", "commentary", "row_index")
    )
    print(f"Found {rows.count()} checklist rows for company_id={company_id}")
    if not rows.count():
        print("No checklist outputs found for this company. Markdown will be empty.")
    md_lines = []
    for row in rows:
        topic = row.topic or ""
        ai_output = row.ai_output or ""
        commentary = row.commentary or ""
        # Format: bold heading, no citations, commentary as requested
        heading_md = f"**{topic}**" if topic else ""
        commentary_md = (
            f'<span style="font-size:10px;"><i>AI Commentary : {commentary}</i></span>'
            if commentary
            else ""
        )
        md_lines.append(f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n")
    markdown = "".join(md_lines)
    return markdown


def save_final_markdown(company_id, company_name, markdown):
    FinalMarkdown.objects(company_id=company_id).update_one(
        set__company_name=company_name, set__markdown=markdown, upsert=True
    )
    print(
        f"Saved markdown for {company_name} ({company_id}) to final_markdown collection."
    )
    # Optionally, upload markdown to Azure Blob Storage
    blob_storage = get_blob_storage()
    import tempfile
    import uuid

    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".md", mode="w", encoding="utf-8"
        ) as f:
            f.write(markdown)
            temp_md_path = f.name
        blob_name = f"markdown/{uuid.uuid4()}_{company_name.replace(' ', '_')}.md"
        blob_url = blob_storage.upload_file(temp_md_path, blob_name)
        print(f"Markdown uploaded to Azure Blob Storage: {blob_url}")
        os.unlink(temp_md_path)
    except Exception as e:
        print(f"Failed to upload markdown to Azure Blob Storage: {e}")


if __name__ == "__main__":
    # Set the company name you want to generate the markdown for
    company_name = "Anthem Biosciences Limited"  # Change as needed
    company = get_company_by_name(company_name)
    markdown = generate_markdown_for_company(company, company.name)
    save_final_markdown(company, company.name, markdown)
    print("\n--- Markdown Preview ---\n")
    print(markdown[:])
