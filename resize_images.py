from PIL import Image
import os

SOURCE_IMAGE = "original.jpg"  # תשנה לשם התמונה שלך

BASE_PATH = "assets/gallery"

sizes = {
    "low":  (320, 240),
    "mid":  (800, 600),
    "high": (1920, 1080)
}

for quality, size in sizes.items():
    img = Image.open(SOURCE_IMAGE)
    img = img.resize(size)

    save_path = os.path.join(BASE_PATH, quality, "img1.jpg")
    img.save(save_path)

    print(f"{quality} image created at size {size}")