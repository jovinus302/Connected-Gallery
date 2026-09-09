"""Render eight fictional captures for the Connect-latency explore benchmark.

These are code-native screenshots, not edited photographs, matching the style
of scripts/create-sample-captures.py (duplicated here rather than imported
because that module's filename has a hyphen). Semantic labels live only in
this authoring script and in docs/explore-latency-benchmark-cases.json;
the PNGs themselves carry no metadata. Requires Pillow and the Windows
Malgun Gothic fonts.

Output: <repo>/.runtime/benchmark-captures/bench_01.png .. bench_08.png
(git-ignored). Also prints the pixel bounding box of each anchor text run so
the manifest's normalized `box` fields can be computed from real draw
coordinates rather than guessed.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime/benchmark-captures"
W, H, S = 720, 1280, 2
FONT = Path("C:/Windows/Fonts/malgun.ttf")
BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")
INK = "#16262D"
MUTED = "#65737B"
TEAL = "#087F78"
WHITE = "#FFFFFF"

# Collected as {name: (x0, y0, x1, y1)} in unscaled 720x1280 pixel coords.
BOXES = {}


class Canvas:
    def __init__(self, bg=WHITE):
        self.im = Image.new("RGB", (W * S, H * S), bg)
        self.d = ImageDraw.Draw(self.im)

    def font(self, size, bold=False):
        return ImageFont.truetype(str(BOLD if bold else FONT), round(size * S))

    def text(self, x, y, value, size=24, color=INK, bold=False, anchor=None, record=None):
        font = self.font(size, bold)
        self.d.text((round(x * S), round(y * S)), value,
                    font=font, fill=color, anchor=anchor)
        if record:
            bbox = self.d.textbbox((round(x * S), round(y * S)), value,
                                   font=font, anchor=anchor)
            BOXES[record] = tuple(v / S for v in bbox)

    def rect(self, box, fill, radius=0, outline=None, width=1):
        box = tuple(round(v * S) for v in box)
        if radius:
            self.d.rounded_rectangle(box, radius=round(radius * S), fill=fill,
                                     outline=outline, width=round(width * S))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=round(width * S))

    def line(self, points, fill, width=2):
        self.d.line([(round(x * S), round(y * S)) for x, y in points],
                    fill=fill, width=round(width * S), joint="curve")

    def ellipse(self, box, fill, outline=None, width=1):
        self.d.ellipse(tuple(round(v * S) for v in box), fill=fill,
                       outline=outline, width=round(width * S))

    def arc(self, box, start, end, color, width=3):
        self.d.arc(tuple(round(v * S) for v in box), start, end,
                   fill=color, width=round(width * S))

    def poly(self, points, fill):
        self.d.polygon([(round(x * S), round(y * S)) for x, y in points], fill=fill)

    def status(self, dark=False):
        fg = WHITE if dark else INK
        self.text(35, 22, "9:41", 22, fg, True)
        for i in range(4):
            self.rect((581 + i * 9, 39 - i * 5, 586 + i * 9, 46), fg, 1)
        self.arc((626, 25, 654, 50), 218, 322, fg, 3)
        self.arc((632, 31, 648, 47), 218, 322, fg, 3)
        self.ellipse((638, 42, 642, 46), fg)
        self.rect((669, 29, 695, 45), None, 4, fg, 2)
        self.rect((673, 33, 690, 41), fg, 1)
        self.rect((696, 34, 700, 40), fg, 1)

    def header(self, title, dark=False, back=True, subtitle=None):
        fg = WHITE if dark else INK
        if back:
            self.line([(44, 91), (31, 104), (44, 117)], fg, 3)
        self.text(77 if back else 32, 85, title, 26, fg, True)
        for x in (653, 662, 671):
            self.ellipse((x, 102, x + 4, 106), fg)
        if subtitle:
            self.text(77, 122, subtitle, 18, "#A4B8BC" if dark else MUTED)

    def bottom(self, dark=False, text="가상 샘플"):
        color = "#AAB6BE" if dark else "#7B858B"
        self.text(W / 2, 1201, text, 17, color, anchor="mt")
        self.rect((262, 1249, 458, 1255), "#CED4D8" if dark else "#223139", 3)

    def pill(self, x, y, text, bg="#E8F4F0", color=TEAL, size=19, width=None):
        tw = self.d.textlength(text, self.font(size)) / S
        width = width or tw + 28
        self.rect((x, y, x + width, y + 37), bg, 18)
        self.text(x + width / 2, y + 5, text, size, color, True, anchor="mt")
        return width

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        self.im.resize((W, H), Image.Resampling.LANCZOS).save(path, optimize=True)
        return path


def divider(c, y, x=32, right=688, color="#E9ECEC"):
    c.line([(x, y), (right, y)], color, 1)


def bookmark(c, x, y, filled=True, color=TEAL):
    pts = [(x, y), (x + 24, y), (x + 24, y + 34), (x + 12, y + 26), (x, y + 34)]
    if filled:
        c.poly(pts, color)
    else:
        c.line(pts + [pts[0]], color, 2)


def stars(c, x, y, filled=4, total=5, color="#E0A93B"):
    for i in range(total):
        cx = x + i * 26
        c.poly([(cx, y - 12), (cx + 4, y - 3), (cx + 13, y - 2), (cx + 6, y + 4),
                (cx + 8, y + 13), (cx, y + 8), (cx - 8, y + 13), (cx - 6, y + 4),
                (cx - 13, y - 2), (cx - 4, y - 3)],
               color if i < filled else "#E4E4E4")


def qr(c, x, y, size=140):
    c.rect((x, y, x + size, y + size), "#F4F4F4", 6, "#C7CBCC", 1)
    cell = size / 9
    pattern = [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2),
               (6, 0), (7, 0), (8, 0), (6, 1), (8, 1), (6, 2), (7, 2), (8, 2),
               (0, 6), (1, 6), (2, 6), (0, 7), (2, 7), (0, 8), (1, 8), (2, 8),
               (4, 4), (5, 3), (6, 5), (4, 7), (7, 7), (5, 8), (8, 4), (3, 3)]
    for gx, gy in pattern:
        c.rect((x + gx * cell, y + gy * cell, x + (gx + 1) * cell, y + (gy + 1) * cell), "#26333B")


def bench_01():
    """저장한 장소: 달빛서점 성수점."""
    c = Canvas("#F7F6FB")
    c.status()
    c.header("저장한 장소")
    c.rect((0, 148, 720, 470), "#E7E3F5")
    c.poly([(80, 420), (80, 260), (160, 220), (240, 260), (240, 420)], "#6C5CB0")
    c.poly([(260, 420), (260, 240), (340, 200), (420, 240), (420, 420)], "#8676CC")
    c.poly([(440, 420), (440, 270), (520, 232), (600, 270), (600, 420)], "#6C5CB0")
    for bx in (100, 280, 460):
        for by in range(300, 400, 26):
            c.rect((bx, by, bx + 120, by + 16), "#F3EFFF", 3)
    c.pill(28, 168, "서점 내부 일러스트", WHITE, "#5B4C99", 16)
    c.text(32, 490, "달빛서점", 40, INK, True)
    bookmark(c, 657, 498)
    c.text(32, 546, "달빛서점 성수점", 27, INK, True, record="bench_01_title")
    c.text(32, 596, "독립서점 · 에세이 · 여행서", 21, MUTED)
    c.pill(32, 644, "저장됨")
    c.pill(138, 644, "서울", "#F0EBFA", "#6C5CB0")
    divider(c, 712)
    c.text(32, 740, "위치", 21, MUTED)
    c.text(32, 776, "서울 성동구 연무장길 12", 24, INK, True)
    c.text(32, 828, "운영 시간", 21, MUTED)
    c.text(32, 864, "10:00–21:00", 21)
    divider(c, 917)
    c.text(32, 942, "저장한 메모", 25, INK, True)
    c.text(32, 998, "주말에 들르기", 25)
    c.rect((32, 1090, 688, 1150), "#F1EEFB", 16)
    c.text(54, 1114, "가상 장소 · 실제 위치 안내가 아닙니다", 22, MUTED)
    c.bottom()
    return c.save("bench_01")


def bench_02():
    """Paper receipt photographed flat on a table (no phone chrome)."""
    im = Image.new("RGB", (W * S, H * S), "#D7D9D6")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(str(FONT), round(23 * S))
    bold = ImageFont.truetype(str(BOLD), round(26 * S))
    small = ImageFont.truetype(str(FONT), round(18 * S))

    # table texture
    for y in range(0, H * S, 40 * S):
        d.line([(0, y), (W * S, y)], "#CBCDC9", 1)

    paper = (72 * S, 92 * S, (W - 72) * S, (H - 130) * S)
    d.rectangle(paper, fill="#FDFCF6")
    # torn/perforated bottom edge
    px0, py0, px1, py1 = paper
    for x in range(int(px0), int(px1), round(14 * S)):
        d.ellipse((x, py1 - 6 * S, x + round(14 * S), py1 + 6 * S), fill="#D7D9D6")

    def line(y, text, f=font, color="#1B1B1B", anchor=None, x=None, record=None):
        xx = x if x is not None else px0 + 34 * S
        d.text((xx, y * S), text, font=f, fill=color, anchor=anchor)
        if record:
            bbox = d.textbbox((xx, y * S), text, font=f, anchor=anchor)
            BOXES[record] = tuple(v / S for v in bbox)

    y = 150
    line(y, "달빛서점 성수점", bold, record="bench_02_store")
    y += 46
    line(y, "서울 성동구 연무장길 12", small, "#4A4A4A")
    y += 60
    line(y, "2026-11-02 15:10", small, "#4A4A4A")
    y += 60
    d.line([(px0 + 20 * S, y * S), (px1 - 20 * S, y * S)], fill="#C9C7B8", width=round(2 * S))
    y += 40
    line(y, "바람의 지도", font, record="bench_02_book")
    line(y, "16,000", font, anchor="rm", x=px1 - 34 * S)
    y += 52
    line(y, "연필 세트", font)
    line(y, "4,500", font, anchor="rm", x=px1 - 34 * S)
    y += 60
    d.line([(px0 + 20 * S, y * S), (px1 - 20 * S, y * S)], fill="#C9C7B8", width=round(2 * S))
    y += 44
    line(y, "합계", bold)
    line(y, "20,500", bold, anchor="rm", x=px1 - 34 * S)
    y += 66
    line(y, "카드 승인 1234", small, "#4A4A4A")

    out = im.resize((W, H), Image.Resampling.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "bench_02.png"
    dfin = ImageDraw.Draw(out)
    dfin.text((W / 2, H - 34), "가상 샘플", font=ImageFont.truetype(str(FONT), 15),
              fill="#7B858B", anchor="mt")
    out.save(path, optimize=True)
    return path


def bench_03():
    """E-book store product page: 바람의 지도."""
    c = Canvas()
    c.status()
    c.header("전자책 상세")
    c.rect((0, 148, 720, 569), "#F4EFE6")
    c.rect((278, 200, 442, 470), "#3D5A80", 6)
    c.rect((278, 200, 442, 260), "#2C4665", 6)
    c.text(360, 300, "바람의", 30, WHITE, True, anchor="mt")
    c.text(360, 344, "지도", 30, WHITE, True, anchor="mt")
    c.text(360, 421, "한서연", 18, "#C9D5E3", anchor="mt")
    c.text(32, 601, "달빛북스", 19, MUTED)
    c.text(32, 640, "바람의 지도", 34, INK, True, record="bench_03_title")
    c.text(32, 692, "지은이  한서연", 22, MUTED)
    stars(c, 44, 750, 4)
    c.text(155, 738, "4.2 (128)", 20, MUTED)
    c.text(32, 800, "16,000원", 38, INK, True)
    divider(c, 866)
    c.text(32, 892, "책 정보", 24, INK, True)
    for y, name, value in [(946, "출판사", "달빛북스"), (990, "형식", "EPUB"),
                           (1034, "분량", "312쪽")]:
        c.text(32, y, name, 22, MUTED)
        c.text(237, y, value, 23, INK, True)
    c.rect((32, 1096, 688, 1154), TEAL, 14)
    c.text(360, 1108, "미리보기 읽기", 23, WHITE, True, anchor="mt")
    c.bottom()
    return c.save("bench_03")


def bench_04():
    """Train ticket: 한빛열차 HB301, 서울 → 부산."""
    c = Canvas("#F0F5F6")
    c.rect((0, 0, 720, 309), "#1D5C6B")
    c.status(True)
    c.header("승차권 상세", True)
    c.text(32, 169, "한빛열차", 33, WHITE, True)
    c.text(32, 221, "빠르게 이어지는 두 도시", 23, "#B9DEE4")
    c.rect((24, 287, 696, 968), WHITE, 25)
    c.pill(47, 316, "가상 승차권 / 사용 불가", "#FFF0DB", "#946A21", 22)
    c.text(48, 381, "2026.11.05  목요일", 27, INK, True)
    c.text(49, 451, "서울", 32, INK, True)
    c.text(49, 500, "SEL", 52, INK, True)
    c.text(670, 451, "부산", 32, INK, True, anchor="rt")
    c.text(670, 500, "BSN", 52, INK, True, anchor="rt")
    c.line([(257, 547), (459, 547)], "#A6C4C8", 2)
    c.poly([(461, 547), (443, 539), (443, 555)], "#A6C4C8")
    c.text(359, 503, "직통 2시간 45분", 18, MUTED, anchor="mt")
    c.text(49, 582, "08:30", 37, TEAL, True)
    c.text(670, 582, "11:15", 37, TEAL, True, anchor="rt")
    divider(c, 660, 47, 673)
    for y, label, value, rec in [(687, "열차편명", "HB301", "bench_04_train"),
                                  (748, "좌석", "7C", None),
                                  (809, "좌석 등급", "일반실", None),
                                  (870, "여정", "서울 → 부산", None)]:
        c.text(48, y, label, 23, MUTED)
        c.text(670, y, value, 25, INK, True, anchor="rt", record=rec)
    qr(c, 47, 895, 148)
    c.bottom(text="가상 샘플 · 승차권으로 사용할 수 없습니다")
    return c.save("bench_04")


def bench_05():
    """Travel note: 부산 1박 2일."""
    c = Canvas("#F5F6FA")
    c.status()
    c.header("여행 노트")
    c.text(32, 175, "부산 1박 2일", 43, INK, True)
    c.text(32, 240, "2026.11.05–11.06", 25, MUTED)
    c.pill(32, 292, "일정 저장됨", "#E5E6FA", "#635AB5")
    days = [
        (368, "11.05", "목요일", "부산 도착", [
            "08:30  한빛열차 HB301 · 서울 → 부산",
            "15:00  별빛호텔 해운대 체크인",
        ]),
        (593, "11.06", "금요일", "부산에서 서울로", [
            "오전    해운대 산책",
            "18:20  한빛열차 HB308 · 부산 출발",
        ]),
    ]
    for y, date, day, title, lines in days:
        height = 30 + 37 + 20 + len(lines) * 43 + 20
        c.rect((24, y, 696, y + height), WHITE, 19)
        c.rect((46, y + 22, 157, y + 87), "#EEEFFC", 12)
        c.text(101, y + 30, date, 25, "#635AB5", True, anchor="mt")
        c.text(101, y + 66, day, 16, "#7973A3", anchor="mt")
        c.text(181, y + 37, title, 28, INK, True)
        for n, ln in enumerate(lines):
            ly = y + 112 + n * 43
            c.ellipse((50, ly + 10, 57, ly + 17), "#A7A4C8")
            record = "bench_05_train" if "HB301" in ln else None
            c.text(76, ly, ln, 22, "#45525F", record=record)
    c.bottom(text="가상 샘플 · 여행지와 예약 정보는 가상입니다")
    return c.save("bench_05")


def bench_06():
    """Unrelated memo: 장보기 목록 (distractor)."""
    c = Canvas("#FFFDF5")
    c.status()
    c.header("메모")
    c.text(34, 184, "장보기 목록", 42, INK, True, record="bench_06_title")
    c.text(34, 254, "2026년 11월 3일  오후 7:10", 19, "#8B887C")
    divider(c, 303, color="#EAE5D5")
    items = ["우유", "계란 10개", "세제", "휴지"]
    for i, item in enumerate(items):
        y = 350 + i * 66
        c.rect((37, y + 5, 63, y + 31), None, 6, "#BDA76B", 2)
        c.text(83, y, item, 26)
    c.rect((32, 965, 688, 1050), "#F4EEDB", 16)
    c.text(54, 989, "기억할 것", 21, "#847149", True)
    c.text(54, 1024, "오는 길에 편의점 들르기.", 22, "#71664F")
    c.bottom(text="가상 샘플")
    return c.save("bench_06")


def bench_07():
    """Hotel booking: 별빛호텔 부산 해운대."""
    c = Canvas("#F8F8F5")
    c.status()
    c.header("숙소 예약")
    c.rect((25, 162, 695, 345), "#EFE9F5", 20)
    c.rect((479, 215, 638, 345), "#B7A6CC", 7)
    c.rect((461, 204, 654, 221), "#6F5C87", 5)
    for x in (500, 554, 608):
        for y in (243, 289):
            c.rect((x, y, x + 18, y + 22), "#F4E8D8", 2)
    c.text(46, 192, "STARLIGHT BUSAN", 21, "#6F5C87", True)
    c.text(46, 236, "해운대의 밤을\n밝히는 곳", 29, "#4A3B63", True)
    c.pill(32, 378, "가상 예약 / 사용 불가", "#FFF0DB", "#946A21", 19)
    c.text(32, 438, "별빛호텔", 38, INK, True, record="bench_07_title")
    c.text(32, 490, "별빛호텔 부산 해운대", 26, INK, True)
    c.text(32, 540, "부산 해운대구 · 해변에서 도보 5분", 23, MUTED)
    c.rect((25, 600, 695, 769), WHITE, 19)
    c.text(49, 626, "체크인", 21, MUTED)
    c.text(394, 626, "체크아웃", 21, MUTED)
    c.text(49, 669, "2026.11.05", 30, INK, True)
    c.text(394, 669, "2026.11.06", 30, INK, True)
    c.text(49, 718, "목요일 · 15:00", 20, MUTED)
    c.text(394, 718, "금요일 · 11:00", 20, MUTED)
    c.text(32, 817, "예약 정보", 27, INK, True)
    for y, label, value in [(879, "객실", "디럭스 더블 1실"), (938, "예약번호", "STAR-7781"),
                            (997, "인원", "성인 2명")]:
        c.text(32, y, label, 23, MUTED)
        c.text(686, y, value, 25, INK, True, anchor="rt")
    c.rect((25, 1077, 695, 1157), "#F1EEF7", 18)
    c.text(47, 1103, "저장한 여행", 20, "#6F5C87")
    c.text(47, 1128, "부산 1박 2일", 24, "#4A3B63", True)
    c.bottom(text="가상 샘플 · 숙박 예약으로 사용할 수 없습니다")
    return c.save("bench_07")


def bench_08():
    """저장한 장소: 달빛서점 해운대점 (same brand as bench_01, other branch)."""
    c = Canvas("#F7F6FB")
    c.status()
    c.header("저장한 장소")
    c.rect((0, 148, 720, 470), "#DCE8F0")
    for i, (bx, by, hh) in enumerate([(90, 260, 160), (270, 220, 200), (450, 250, 170)]):
        c.rect((bx, by, bx + 150, by + hh), "#5B84A6" if i % 2 else "#7FA6C3", 4)
    c.ellipse((560, 190, 630, 260), "#FBE7A8")
    c.pill(28, 168, "서점 내부 일러스트", WHITE, "#3E668A", 16)
    c.text(32, 490, "달빛서점", 40, INK, True)
    bookmark(c, 657, 498)
    c.text(32, 546, "달빛서점 해운대점", 27, INK, True, record="bench_08_title")
    c.text(32, 596, "독립서점 · 바다 전망 · 카페 겸업", 21, MUTED)
    c.pill(32, 644, "저장됨")
    c.pill(138, 644, "부산", "#E5EEF6", "#3E668A")
    divider(c, 712)
    c.text(32, 740, "위치", 21, MUTED)
    c.text(32, 776, "부산 해운대구 달맞이길 45", 24, INK, True)
    c.text(32, 828, "운영 시간", 21, MUTED)
    c.text(32, 864, "11:00–20:00", 21)
    c.rect((32, 1090, 688, 1150), "#EAF0F6", 16)
    c.text(54, 1114, "가상 장소 · 실제 위치 안내가 아닙니다", 22, MUTED)
    c.bottom()
    return c.save("bench_08")


def pad_box(box, pad=4):
    x0, y0, x1, y1 = box
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def normalized(box):
    x0, y0, x1, y1 = pad_box(box)
    return {
        "x": round(x0 / W, 16),
        "y": round(y0 / H, 16),
        "width": round((x1 - x0) / W, 16),
        "height": round((y1 - y0) / H, 16),
    }


def main():
    files = [bench_01(), bench_02(), bench_03(), bench_04(), bench_05(),
             bench_06(), bench_07(), bench_08()]
    for path in files:
        with Image.open(path) as im:
            assert im.size == (720, 1280) and not im.info, (path, im.size, im.info)
        print(f"{path.name}: {path.stat().st_size:,} bytes; 720x1280; no metadata")
    print(f"Total: {sum(p.stat().st_size for p in files):,} bytes")
    print()
    print("Recorded anchor text boxes (normalized 720x1280):")
    for name, box in BOXES.items():
        print(f"  {name}: {normalized(box)}")


if __name__ == "__main__":
    main()
