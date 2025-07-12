import fitz  # PyMuPDF for extracting images from PDF
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import requests
import os
from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()


class QRCodeProcessor:
    def __init__(self, pdf_path):
        # Convert relative path to absolute path if needed
        if not os.path.isabs(pdf_path):
            project_root = "/home/ubuntu/backend/DRHP_crud_backend"
            self.pdf_path = os.path.join(project_root, pdf_path)
        else:
            self.pdf_path = pdf_path
            
        self.temp_image_path = "temp_qr_image.jpg"
        print(f"Processing PDF at: {self.pdf_path}")  # Debug print

    def extract_qr_image(self):
        """
        Extracts the first page of the PDF, converts it to an image, and saves it.
        Returns the path to the saved image.
        """
        try:
            if not os.path.exists(self.pdf_path):
                raise FileNotFoundError(f"PDF file not found at: {self.pdf_path}")
                
            doc = fitz.open(self.pdf_path)
            page = doc.load_page(0)  # Extract the first page
            zoom_factor = 4.0  # Increase DPI for better clarity
            mat = fitz.Matrix(zoom_factor, zoom_factor)
            pix = page.get_pixmap(matrix=mat)

            # Convert Pixmap to a NumPy array properly
            img = np.frombuffer(pix.samples, dtype=np.uint8)

            if pix.n == 1:  # Grayscale image
                img = img.reshape((pix.h, pix.w))
            elif pix.n == 3:  # RGB Image
                img = img.reshape((pix.h, pix.w, 3))
            elif pix.n == 4:  # CMYK or Transparent BG
                img = img.reshape((pix.h, pix.w, 4))
                img = img[:, :, :3]  # Drop alpha channel, keep RGB

            # Save the extracted image
            cv2.imwrite(self.temp_image_path, img)
            return self.temp_image_path
        except Exception as e:
            print(f"❌ Error extracting QR image: {e}")
            return None

    def is_url_accessible(self, url):
        """
        Checks if a URL is accessible (returns HTTP 200).
        """
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def process_qr_from_pdf(self):
        """
        Extracts QR code from PDF, decodes it, and checks if the extracted URL is functional.
        Deletes the temporary image after processing.
        """
        image_path = self.extract_qr_image()

        if not image_path:
            print("❌ Failed to extract an image from the PDF.")
            return {"qr_content": None, "is_accessible": None}

        # Load the image
        image = cv2.imread(image_path)

        # Try to decode the QR Code
        decoded_objects = decode(image)
        result = {"qr_content": None, "is_accessible": None}

        if decoded_objects:
            for obj in decoded_objects:
                qr_content = obj.data.decode("utf-8")
                print(f"✅ QR Code Content: {qr_content}")
                result["qr_content"] = qr_content

                # Check if QR content is a valid URL
                if qr_content.startswith("http://") or qr_content.startswith("https://"):
                    is_accessible = self.is_url_accessible(qr_content)
                    result["is_accessible"] = is_accessible
                    print(f"🔗 The URL is {'Accessible' if is_accessible else 'Not Accessible'}.")
                else:
                    print("❌ The QR code content is not a valid URL.")
        else:
            print("❌ QR Code not detected in the extracted image.")

        # Delete the temporary image file
        if os.path.exists(image_path):
            os.remove(image_path)
            print(f"🗑️ Deleted temporary image: {image_path}")

        return result


if __name__ == "__main__":
    processor = QRCodeProcessor("/Users/abhinav/Documents/DRHP_BACKEND/DRHP_Backends/DRHP_crud_backend/DRHP_ai_processing/Final Draft Prospectus of Citichem_20230420151552 (1).pdf")
    result = processor.process_qr_from_pdf()
    print(result)