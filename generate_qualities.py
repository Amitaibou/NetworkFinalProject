from PIL import Image
import os

SOURCE_FOLDER = "assets/images"
BASE_PATH = "assets/gallery"

sizes = {
    "low":  (320, 240),
    "mid":  (800, 600),
    "high": (1920, 1080)
}

for filename in os.listdir(SOURCE_FOLDER):

    if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
        continue

    image_path = os.path.join(SOURCE_FOLDER, filename)

    for quality, size in sizes.items():

        img = Image.open(image_path)
        img = img.resize(size)

        save_path = os.path.join(BASE_PATH, quality, filename)

        img.save(save_path)

        print(f"{filename} -> {quality} created at size {size}")