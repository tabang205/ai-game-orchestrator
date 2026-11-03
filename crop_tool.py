import cv2
import json
from pathlib import Path

SAMPLE_DIR = Path(r"D:\\ai_game_orchestrator\\games\\ark_recode_data")
OUT_DIR = Path("D:\\ai_game_orchestrator\\games\\ark_recode\\templates")
CONFIG_FILE = Path("D:\\ai_game_orchestrator\\games\\ark_recode\\templates_config.json")

OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    config = load_config()

    for img_path in sorted(SAMPLE_DIR.glob("*.*")):
        img = cv2.imread(str(img_path))
        if img is None:
            continue

        while True:
            win_name = f"{img_path.name} | SPACE: Chon | ESC: Qua anh"
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win_name, 1280, 720)

            x, y, w, h = cv2.selectROI(win_name, img, showCrosshair=True)
            cv2.destroyWindow(win_name)

            if w == 0 or h == 0:
                break

            name = input(f"[{img_path.name}] Tên nút: ").strip()
            if not name:
                continue

            # Lưu ảnh cắt
            file_name = f"{name}.png"
            cv2.imwrite(str(OUT_DIR / file_name), img[y : y + h, x : x + w])

            # Lưu tọa độ (mở rộng 20px để dễ tìm)
            config[name] = {
                "file": file_name,
                "region": [max(0, x - 20), max(0, y - 20), w + 40, h + 40],
            }
            save_config(config)
            print(f"-> Đã lưu: {name}")


if __name__ == "__main__":
    main()
