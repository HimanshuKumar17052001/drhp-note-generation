# import os
# import tempfile
# import base64
# import cv2
# import numpy as np
# import fitz  # PyMuPDF
# from dotenv import load_dotenv
# import matplotlib.pyplot as plt

# # -----------------------------------------------------------------------------
# # CONFIGURATION (adjust as needed)
# # -----------------------------------------------------------------------------
# load_dotenv()

# from baml_client import b
# from baml_py import Image as BamlImage, Collector

# # Path to the PDF you want to process
# pdf_path = "/home/ubuntu/backend/DRHP_crud_backend/DRHP_ai_processing/DOVE_SOFT_LTD.pdf"

# # 1-based page number that you want to strip the bottom from
# page_num = 3

# # DPI at which to render the PDF page
# dpi = 200

# # When scanning bottom-up for “dark” pixels, any grayscale value < threshold will be considered “ink”
# threshold = 200
# # -----------------------------------------------------------------------------


# def pdf_page_to_cv2_image(pdf_path: str, page_num: int, dpi: int = 200) -> np.ndarray:
#     """
#     Converts a single page of a PDF into a CV2 BGR image via PyMuPDF (fitz).
#     Returns a H×W×3 numpy array in BGR color space.
#     """
#     doc = fitz.open(pdf_path)
#     try:
#         page = doc.load_page(page_num - 1)  # 0-based internally
#         pix = page.get_pixmap(dpi=dpi)
#         img_arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))

#         if pix.n == 4:
#             # RGBA → BGR
#             img_bgr = cv2.cvtColor(img_arr, cv2.COLOR_RGBA2BGR)
#         else:
#             # RGB → BGR
#             img_bgr = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)

#         return img_bgr
#     finally:
#         doc.close()


# def strip_bottom_region(
#     cv2_img: np.ndarray,
#     threshold: int = 200
# ) -> np.ndarray:
#     """
#     Given a grayscale or BGR image, scan from the bottom row upwards
#     to find the first “inked” row (pixel value < threshold). Then keep scanning
#     up until you hit a fully “white” row again. Crop out that slice.

#     Returns a new (h_strip × w) grayscale array (0-255).
#     """
#     # Convert to grayscale if needed
#     if len(cv2_img.shape) == 3 and cv2_img.shape[2] == 3:
#         gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
#     else:
#         gray = cv2_img.copy()

#     h, w = gray.shape
#     y_start = None
#     y_end = None
#     scanning = False

#     # Scan from bottom to top
#     for y in range(h - 1, -1, -1):
#         row = gray[y, :]
#         if not scanning:
#             # Look for the first “dark” row (any pixel < threshold)
#             if np.any(row < threshold):
#                 y_end = y
#                 scanning = True
#         else:
#             # Once in scanning, we stop at the first fully “white” row (all pixels >= threshold)
#             if np.all(row >= threshold):
#                 y_start = y + 1
#                 break

#     # If we found a region to crop
#     if y_start is not None and y_end is not None and y_end >= y_start:
#         strip = gray[y_start : y_end + 1, :]
#         return strip
#     else:
#         # No “inked” region found; return an empty array
#         return np.zeros((0, w), dtype=np.uint8)


# def strip_to_baml_image(strip_gray: np.ndarray) -> BamlImage:
#     """
#     Encode a grayscale numpy array as PNG‐bytes and then Base64-encode it
#     to create a BAML Image object.
#     """
#     if strip_gray.size == 0:
#         raise ValueError("Strip image is empty; nothing to send to BAML.")

#     # Save to a temporary PNG in memory
#     success, png_buf = cv2.imencode(".png", strip_gray)
#     if not success:
#         raise RuntimeError("Could not encode strip to PNG")

#     png_bytes = png_buf.tobytes()
#     b64_str = base64.b64encode(png_bytes).decode("utf-8")
#     return BamlImage.from_base64("image/png", b64_str)


# def call_baml_llm_on_strip(baml_img: BamlImage) -> str:
#     """
#     Example of sending the strip to a BAML LLM endpoint. 
#     We use Collector to capture whatever the LLM returns in `.last.content`.

#     Replace `ExtractPageNumber` below with whichever BAML method you want (e.g. b.ExtractText).
#     """
#     collector = Collector(name="strip‐collector")
#     # ---------- EXAMPLE LLM CALL: Extract page number from image -------------
#     result = b.ExtractPageNumber(
#         baml_img,
#         baml_options={"collector": collector}
#     )
#     # ----------------------------------------------------------

#     # After the call, the result should have a `.page_number` (or change according to the BAML method)
#     return result.page_number


# if __name__ == "__main__":
#     # 1) Convert the specified PDF page → CV2 image
#     cv2_page = pdf_page_to_cv2_image(pdf_path, page_num, dpi=dpi)

#     # 2) Crop only the bottom “inked” region (grayscale)
#     bottom_strip = strip_bottom_region(cv2_page, threshold=threshold)

#     # 3) Display the stripped‐off region using Matplotlib
#     if bottom_strip.size == 0:
#         print("No bottom text found on page; exiting.")
#     else:
#         plt.figure(figsize=(6, 4))
#         plt.imshow(bottom_strip, cmap="gray", vmin=0, vmax=255)
#         plt.axis("off")
#         plt.title(f"Cropped Bottom Strip (Page {page_num})")
#         plt.show()

#         # 4) (Optional) Turn that strip into a BAML Image and call the LLM
#         try:
#             baml_img = strip_to_baml_image(bottom_strip)
#             llm_output = call_baml_llm_on_strip(baml_img)
#             print("=== LLM Output on Bottom Strip ===")
#             print(llm_output)
#         except ValueError as ve:
#             print("Error:", ve)

import cv2
import numpy as np
import base64
from baml_client import b
from baml_py import Image, Collector

def load_png_image(path):
    """
    Loads a PNG image from the given file path using OpenCV.
    """
    try:
        img = cv2.imread(path)
        if img is None:
            raise ValueError("Failed to load image. Check the path.")
        return img
    except Exception as e:
        raise RuntimeError(f"Error loading image: {e}")

def img_to_bytes(cv2_img):
    """
    Converts a cv2 image to bytes in PNG format.
    """
    try:
        success, buf = cv2.imencode('.png', cv2_img)
        if not success:
            raise ValueError("Failed to encode image")
        return buf.tobytes()
    except Exception as e:
        raise RuntimeError(f"Error converting image to bytes: {e}")

def process_image_with_baml(image_path):
    """
    Loads PNG image, sends it to BAML TOC extractor, and prints usage stats.
    """
    cv2_img = load_png_image(image_path)
    img_bytes = img_to_bytes(cv2_img)
    b64 = base64.b64encode(img_bytes).decode()
    baml_img = Image.from_base64("image/png", b64)

    collector = Collector(name="collector-a")

    for i in range(3):
        b.ExtractPageNumber(baml_img, baml_options={"collector": collector})
        print(f"Run {i+1} usage:", collector.last.usage)

if __name__ == "__main__":
    image_path = "/home/ubuntu/drhp-analyser-new/DRHP_crud_backend/image.png"
    process_image_with_baml(image_path)
