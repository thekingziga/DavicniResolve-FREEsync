import sys
import math
from PIL import Image, ImageDraw

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def create_resolvesync_icon():
    size = (512, 512)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background Rounded Shield / Square with gradient look
    padding = 24
    w, h = size
    # Outer glow / border
    draw.rounded_rectangle([padding - 4, padding - 4, w - padding + 4, h - padding + 4], radius=96, fill=(35, 38, 52, 255))
    # Main dark card
    draw.rounded_rectangle([padding, padding, w - padding, h - padding], radius=90, fill=(22, 24, 33, 255))

    # Inner subtle rim
    draw.rounded_rectangle([padding + 6, padding + 6, w - padding - 6, h - padding - 6], radius=84, outline=(55, 65, 81, 200), width=4)

    # Center coordinates
    cx, cy = w // 2, h // 2

    # 2. Draw circular sync arrows (DaVinci Resolve aesthetic: Vibrant Cyan/Blue & Amber/Orange)
    # Outer sync ring
    radius = 140
    thickness = 32

    # Arc 1: Top-Right (Electric Cyan/Blue #0ea5e9 to #3b82f6)
    draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=210, end=350, fill=(14, 165, 233, 255), width=thickness)
    # Arrow head for Arc 1
    # End angle 350 deg in radians:
    rad1 = math.radians(350)
    ax1 = cx + radius * math.cos(rad1)
    ay1 = cy + radius * math.sin(rad1)
    # Triangle pointing down-right
    arrow1 = [
        (ax1 + 18, ay1 + 22),
        (ax1 - 10, ay1 + 34),
        (ax1 + 4, ay1 - 10),
    ]
    draw.polygon(arrow1, fill=(14, 165, 233, 255))

    # Arc 2: Bottom-Left (Vibrant Amber/Orange #f59e0b to #ea580c)
    draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=30, end=170, fill=(245, 158, 11, 255), width=thickness)
    # Arrow head for Arc 2
    rad2 = math.radians(170)
    ax2 = cx + radius * math.cos(rad2)
    ay2 = cy + radius * math.sin(rad2)
    # Triangle pointing up-left
    arrow2 = [
        (ax2 - 18, ay2 - 22),
        (ax2 + 10, ay2 - 34),
        (ax2 - 4, ay2 + 10),
    ]
    draw.polygon(arrow2, fill=(245, 158, 11, 255))

    # 3. Center Film / Play Emblem (Indigo / Purple #6366f1)
    center_rad = 54
    draw.ellipse([cx - center_rad, cy - center_rad, cx + center_rad, cy + center_rad], fill=(99, 102, 241, 255))
    draw.ellipse([cx - center_rad + 6, cy - center_rad + 6, cx + center_rad - 6, cy + center_rad - 6], fill=(30, 27, 75, 255))

    # Center triangle (playhead)
    pl_size = 28
    play_tri = [
        (cx - pl_size * 0.7, cy - pl_size),
        (cx - pl_size * 0.7, cy + pl_size),
        (cx + pl_size * 1.1, cy),
    ]
    draw.polygon(play_tri, fill=(240, 246, 252, 255))

    # Save PNG and Multi-resolution ICO
    img.save("app_icon.png", format="PNG")
    
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save("app_icon.ico", format="ICO", sizes=icon_sizes)
    print("✓ Successfully generated app_icon.png and app_icon.ico!")

if __name__ == "__main__":
    create_resolvesync_icon()
