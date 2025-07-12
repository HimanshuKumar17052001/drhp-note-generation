import fitz  # PyMuPDF for extracting text from PDF
import re
import requests
import os

class WebsiteLinkExtractor:
    def __init__(self, pdf_path):
        # Convert relative path to absolute path if needed
        if not os.path.isabs(pdf_path):
            project_root = "/home/ubuntu/backend/DRHP_crud_backend"
            self.pdf_path = os.path.join(project_root, pdf_path)
        else:
            self.pdf_path = pdf_path
            
        print(f"Processing PDF for links at: {self.pdf_path}")  # Debug print

    def extract_www_links(self):
        """
        Extracts all links that start with 'www.' from the first page of the PDF.
        Returns a list of extracted links.
        """
        if not os.path.exists(self.pdf_path):
            raise FileNotFoundError(f"PDF file not found at: {self.pdf_path}")
            
        doc = fitz.open(self.pdf_path)
        page = doc.load_page(0)  # Extract from first page
        text = page.get_text("text")  # Extract text

        # Regex to find URLs that start with "www."
        url_pattern = r"www\.[^\s,)]+"
        links = re.findall(url_pattern, text)

        # Convert to full URLs (prepend https:// to make valid)
        links = [f"https://{link}" if not link.startswith("http") else link for link in links]

        return links

    def is_website_accessible(self, url):
        """
        Checks if the given URL is accessible (HTTP 200 response).
        Returns True if accessible, False otherwise.
        """
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            return response.status_code == 200  # True if URL is valid
        except requests.RequestException:
            return False  # If there's an error (e.g., network issue, invalid URL)

    def check_all_www_links(self):
        """
        Extracts all 'www.' links from the first page and checks if they're working.
        Returns a list of dictionaries with each link and its status.
        """
        links = self.extract_www_links()
        results = []

        if not links:
            print("❌ No 'www.' links found on the first page.")
            return []

        for link in links:
            is_working = self.is_website_accessible(link)
            results.append({"link": link, "is_working": is_working})
            print(f"🔗 {link} → {'✅ Working' if is_working else '❌ Not Working'}")

        return results


if __name__ == "__main__":
    extractor = WebsiteLinkExtractor("/Users/abhinav/Documents/DRHP_BACKEND/DRHP_Backends/DRHP_crud_backend/DRHP_ai_processing/Draft Red Herring Prospectus_RDSL_20240721132143.pdf")
    results = extractor.check_all_www_links()
    print(results)
