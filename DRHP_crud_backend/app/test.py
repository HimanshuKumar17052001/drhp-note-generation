import os
from dotenv import load_dotenv
load_dotenv()
import fitz
import cv2
import numpy as np
import base64

from baml_client import b
import os
import fitz 
import numpy as np
import cv2
import base64
# import baml_py; print("Loaded from:", baml_py.__file__)
from baml_client import b
from baml_py import Image
from baml_py import Collector

def pdf_page_to_cv2_image(page_num, dpi=200):
        """
        Converts a PDF page to a cv2 image using PyMuPDF (fitz)
        """
        try:
            pdf_path = "/Users/abhinav/Downloads/WorkmatesFilingversionDRHP_20250530023507.pdf"
            doc = fitz.open(pdf_path)
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
            
            if pix.n == 4:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            else:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            
            return img_np
        except Exception as e:
            # logger.error(f"Error converting PDF page {page_num} to image: {e}")
            raise

def process_image(baml_img):
    b.ExtractTableOfContents(baml_img, baml_options={"collector": collector_a})
    

def img_to_bytes(cv2_img):
        try:
            success, buf = cv2.imencode('.png', cv2_img)
            if not success:
                raise ValueError("Failed to encode image")
            return buf.tobytes()
        except Exception as e:
            logger.error(f"Error converting image to bytes: {e}")
            raise


if __name__ == "__main__":
    page_num = 4

    cv2_img = pdf_page_to_cv2_image(page_num)
    img_bytes = img_to_bytes(cv2_img)
    b64 = base64.b64encode(img_bytes).decode()
    baml_img = Image.from_base64("image/png", b64)


    collector_a = Collector(name="collector-a")
    b.ExtractTableOfContents(baml_img, baml_options={"collector": collector_a})
    # collector_a.clear()
    print(collector_a.last.usage)
    b.ExtractTableOfContents(baml_img, baml_options={"collector": collector_a})
    # collector_a.clear()
    print(collector_a.last.usage)
    b.ExtractTableOfContents(baml_img, baml_options={"collector": collector_a})
    # collector_a.clear()
    print(collector_a.last.usage)
    
