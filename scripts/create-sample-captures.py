"""Reproduce the twelve fictional mobile captures bundled in the debug gallery.

These are code-native screenshots, not edited photographs. Semantic labels live
only in this authoring script; assets are numbered PNG files without metadata.
Requires Pillow and the Windows Malgun Gothic fonts.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "android/app/src/debug/assets/sample-gallery"
QA = ROOT / ".runtime/sample-captures"
W, H, S = 720, 1280, 2
FONT = Path("C:/Windows/Fonts/malgun.ttf")
BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")
INK = "#16262D"
MUTED = "#65737B"
TEAL = "#087F78"
WHITE = "#FFFFFF"


class Canvas:
    def __init__(self, bg=WHITE):
        self.im = Image.new("RGB", (W * S, H * S), bg)
        self.d = ImageDraw.Draw(self.im)

    def font(self, size, bold=False):
        return ImageFont.truetype(str(BOLD if bold else FONT), round(size * S))

    def text(self, x, y, value, size=24, color=INK, bold=False, anchor=None):
        self.d.text((round(x * S), round(y * S)), value,
                    font=self.font(size, bold), fill=color, anchor=anchor)

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

    def save(self, idx):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"cg_sample_{idx:02d}.png"
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


def pin(c, x, y, color=TEAL):
    c.ellipse((x - 17, y - 34, x + 17, y), color)
    c.poly([(x - 13, y - 9), (x + 13, y - 9), (x, y + 12)], color)
    c.ellipse((x - 6, y - 24, x + 6, y - 12), WHITE)


def noodle(c, x, y):
    c.ellipse((x, y, x + 245, y + 170), "#FFF9E9", "#E1BA83", 3)
    c.ellipse((x + 22, y + 22, x + 223, y + 148), "#F4C777")
    for j in range(6):
        c.arc((x + 40 + j * 6, y + 39 + j * 7, x + 187 + j * 2, y + 114 + j * 4),
              15, 330, "#DDA54D", 5)
    c.ellipse((x + 64, y + 46, x + 98, y + 74), "#805A41")
    c.ellipse((x + 151, y + 88, x + 186, y + 116), "#805A41")
    c.poly([(x + 106, y + 37), (x + 120, y + 26), (x + 132, y + 42),
            (x + 119, y + 56)], "#5E8B51")


def restaurant(idx, seoul=False):
    c = Canvas("#FCFBF8")
    c.status()
    c.header("저장한 맛집")
    c.rect((0, 146, 720, 433), "#F1E8D8")
    c.text(36, 177, "SOR A  /  KITCHEN", 18, "#8B6744", True)
    c.text(36, 214, "한 접시의\n느긋한 시간", 31, "#564434", True)
    noodle(c, 414, 227)
    c.pill(35, 366, "일러스트 메뉴 안내", "#FFFFFF", "#725C44", 16)
    branch = "서울 연남점" if seoul else "제주 바람항점"
    c.text(32, 467, "소라식탁", 38, INK, True)
    c.text(32, 522, f"소라식탁 · {branch}", 27, INK, True)
    bookmark(c, 657, 475)
    c.text(32, 572, "이탈리안  ·  파스타  ·  예약 가능", 21, MUTED)
    c.pill(32, 620, "저장됨")
    c.pill(138, 620, "서울" if seoul else "제주 여행", "#F0EBDD", "#786143")
    divider(c, 688)
    c.text(32, 716, "위치", 21, MUTED)
    c.text(32, 753, "서울 마포구 연남동 · 가상 지점" if seoul else "제주 바람항 산책로 · 가상 지점", 24, INK, True)
    c.text(32, 804, "운영 시간", 21, MUTED)
    c.text(32, 840, "매일 11:30–21:00  /  마지막 주문 20:00", 21)
    divider(c, 893)
    c.text(32, 918, "대표 메뉴", 25, INK, True)
    c.text(32, 975, "전복 파스타", 24)
    c.text(685, 975, "22,000원", 24, INK, True, anchor="rt")
    c.text(32, 1027, "감귤 에이드", 24)
    c.text(685, 1027, "6,000원", 24, INK, True, anchor="rt")
    c.rect((32, 1100, 688, 1160), TEAL, 15)
    c.text(360, 1114, "저장한 장소 보기", 23, WHITE, True, anchor="mt")
    c.bottom()
    return c.save(idx)


def map_capture():
    c = Canvas("#F7F8F5")
    c.status()
    c.rect((20, 79, 700, 145), WHITE, 18)
    c.text(47, 96, "소라식탁 바람항점", 25, INK, True)
    c.ellipse((646, 96, 666, 116), None, INK, 3)
    c.line([(664, 114), (675, 125)], INK, 3)
    c.rect((0, 166, 720, 963), "#EFF1E6")
    c.poly([(485, 166), (720, 166), (720, 963), (423, 963), (476, 839),
            (522, 741), (455, 637), (496, 552), (438, 451), (489, 339)], "#C8E8EE")
    c.poly([(55, 342), (229, 331), (263, 472), (104, 488)], "#D4E5C4")
    c.poly([(172, 697), (379, 719), (355, 881), (186, 860)], "#D4E5C4")
    for box in [(58, 190, 153, 272), (192, 186, 302, 291), (342, 190, 405, 280),
                (25, 535, 125, 643), (167, 540, 276, 641), (323, 534, 401, 644),
                (35, 733, 120, 840), (326, 355, 402, 461)]:
        c.rect(box, "#E1E2D8", 9)
    roads = [[(0, 312), (303, 312), (433, 292)], [(10, 511), (400, 498), (476, 461)],
             [(144, 166), (146, 697), (143, 963)], [(306, 166), (310, 670), (423, 963)],
             [(0, 679), (431, 678), (490, 735)]]
    for road in roads:
        c.line(road, "#D9DBC9", 21)
        c.line(road, WHITE, 15)
    c.line([(445, 204), (455, 347), (405, 460), (459, 561), (419, 644),
            (477, 745), (433, 845), (390, 936)], "#D09E6A", 6)
    c.text(80, 379, "바람공원", 24, "#648552", True)
    c.text(535, 389, "바람항", 29, "#48859D", True)
    c.text(518, 433, "가상 해안", 18, "#699CA9")
    c.rect((189, 456, 494, 511), WHITE, 13)
    c.text(342, 468, "소라식탁 바람항점", 23, TEAL, True, anchor="mt")
    pin(c, 351, 554)
    pin(c, 478, 751, "#D4783E")
    c.rect((414, 781, 611, 832), WHITE, 13)
    c.text(512, 791, "하얀등대", 24, INK, True, anchor="mt")
    c.text(210, 748, "산책로", 18, "#819273")
    c.pill(26, 179, "가상 지도 · 실제 길찾기 불가", WHITE, MUTED, 17)
    c.rect((0, 963, 720, 1180), WHITE, 23)
    c.text(32, 990, "소라식탁 바람항점", 30, INK, True)
    c.text(32, 1043, "제주 바람항  ·  하얀등대에서 도보 12분", 21, MUTED)
    c.pill(32, 1098, "저장됨")
    c.pill(145, 1098, "제주 2박 3일", "#F1F3F5", MUTED)
    c.bottom()
    return c.save(2)


def headphones(c, x, y, color):
    c.arc((x + 13, y, x + 247, y + 266), 180, 360, "#253744", 27)
    c.arc((x + 20, y + 10, x + 240, y + 266), 180, 360, color, 15)
    c.line([(x + 23, y + 136), (x + 24, y + 206)], "#445560", 12)
    c.line([(x + 237, y + 136), (x + 236, y + 206)], "#445560", 12)
    c.rect((x - 2, y + 157, x + 57, y + 262), color, 24)
    c.rect((x + 202, y + 157, x + 261, y + 262), color, 24)
    c.rect((x + 43, y + 167, x + 66, y + 253), "#26333B", 10)
    c.rect((x + 193, y + 167, x + 216, y + 253), "#26333B", 10)
    c.line([(x + 11, y + 177), (x + 11, y + 223)], "#FFFFFF", 2)


def product(idx, older=False):
    c = Canvas()
    c.status()
    c.header("관심 상품")
    c.rect((0, 148, 720, 569), "#F1F4F7" if older else "#FAF0EC")
    c.text(34, 174, "ORBIT", 28, "#252C34", True)
    c.text(34, 213, "SOUND IN YOUR ORBIT", 14, "#717B82")
    c.ellipse((223, 500, 504, 525), "#DDE0E3" if older else "#E6DAD5")
    headphones(c, 225, 237, "#396BB1" if older else "#C8493D")
    c.text(661, 529, "1 / 3", 17, MUTED, anchor="rt")
    c.text(32, 601, "오르빗 오디오", 19, MUTED)
    model = "M1" if older else "M2"
    c.text(32, 640, f"ORBIT {model} 무선 헤드폰", 34, INK, True)
    c.text(32, 692, "오버이어  ·  블루" if older else "오버이어  ·  레드", 23, MUTED)
    c.text(32, 751, "69,000원" if older else "89,000원", 40, INK, True)
    divider(c, 825)
    c.text(32, 850, "상품 정보", 24, INK, True)
    for y, name, value in [(906, "모델", f"ORBIT {model}"), (951, "연결", "Bluetooth"),
                           (996, "충전", "Micro USB" if older else "USB-C")]:
        c.text(32, y, name, 22, MUTED)
        c.text(237, y, value, 23, INK, True)
    c.pill(32, 1054, "관심 상품에 저장됨", "#F3F4F6", "#525F69")
    c.rect((32, 1115, 688, 1173), "#263642", 14)
    c.text(360, 1127, "제품 정보 보기", 23, WHITE, True, anchor="mt")
    c.bottom()
    return c.save(idx)


def event(idx, old=False):
    c = Canvas("#101F32")
    c.status(True)
    c.header("저장한 행사", True)
    for i in range(29):
        x = 32 + (i * 83) % 650
        y = 170 + (i * 137) % 475
        r = 2 if i % 4 else 4
        c.ellipse((x - r, y - r, x + r, y + r), "#F7D796" if i % 3 else "#7699BC")
    c.text(360, 191, "JEJU NIGHT WALK", 22, "#C9D6E4", True, anchor="mt")
    c.text(360, 270, "제주", 70, WHITE, True, anchor="mt")
    c.text(360, 368, "빛산책", 96, "#FFE4A3", True, anchor="mt")
    c.text(360, 511, "천천히 걸으며 만나는 가을밤", 23, "#CED9E6", anchor="mt")
    c.arc((127, 548, 593, 1028), 187, 353, "#AA8560", 3)
    c.arc((189, 595, 531, 1028), 185, 355, "#6C7F9B", 2)
    c.line([(0, 746), (98, 720), (176, 749), (294, 724), (400, 753),
            (524, 722), (627, 749), (720, 722)], "#395069", 3)
    c.rect((32, 783, 688, 1115), "#1E3047", 22)
    c.pill(58, 807, "지난 행사 · 2025년" if old else "가을 여행 일정", "#37455B", "#F6DBA8", 19)
    c.text(58, 870, "2025.10.18  토요일" if old else "2026.10.17  토요일", 35, WHITE, True)
    c.text(58, 928, "18:00–21:00", 30, "#FFE4A3", True)
    c.text(58, 987, "장소  제주 바람공원", 25, WHITE)
    c.text(58, 1042, "입장 무료 · 야외 산책 프로그램", 20, "#B3C0D0")
    c.text(360, 1142, "가상 행사 안내 · 실제 개최 정보가 아닙니다", 18, "#A9B6C8", anchor="mt")
    c.bottom(True)
    return c.save(idx)


def note():
    c = Canvas("#FFFDF5")
    c.status()
    c.header("메모")
    c.text(34, 184, "책장 정리 메모", 42, INK, True)
    c.text(34, 254, "2026년 9월 6일  오후 8:42", 19, "#8B887C")
    divider(c, 303, color="#EAE5D5")
    c.text(34, 338, "주말에 할 일", 29, INK, True)
    for y, text, done in [(413, "읽은 책은 위 칸으로 옮기기", True),
                          (480, "빌린 책 따로 모아두기", False),
                          (547, "책갈피와 메모 정리하기", False)]:
        c.rect((37, y + 5, 63, y + 31), "#BDA76B" if done else None, 6, "#BDA76B", 2)
        if done:
            c.line([(43, y + 18), (48, y + 23), (58, y + 12)], WHITE, 3)
        c.text(83, y, text, 24)
    divider(c, 622, color="#EAE5D5")
    c.text(34, 665, "다음에 읽을 책", 29, INK, True)
    c.text(40, 741, "01   구름 아래 작은 우체국", 26)
    c.text(40, 805, "02   오후 네 시의 서가", 26)
    c.text(40, 869, "03   느린 계절의 편지", 26)
    c.rect((32, 965, 688, 1103), "#F4EEDB", 16)
    c.text(54, 989, "기억할 것", 21, "#847149", True)
    c.text(54, 1031, "새 책을 사기 전에 책장부터 살펴보기.", 23, "#71664F")
    c.bottom(text="가상 샘플 · 책 제목은 모두 가상입니다")
    return c.save(16)


def flight():
    c = Canvas("#F0F6F6")
    c.rect((0, 0, 720, 309), "#087E79")
    c.status(True)
    c.header("항공 예약 상세", True)
    c.text(32, 169, "바람항공", 33, WHITE, True)
    c.text(32, 221, "제주로 떠나는 아침", 23, "#C4E6E1")
    c.rect((24, 287, 696, 968), WHITE, 25)
    c.pill(47, 316, "가상 예약 / 사용 불가", "#FFF0DB", "#946A21", 22)
    c.text(48, 381, "2026.10.16  금요일", 27, INK, True)
    c.text(49, 451, "서울", 32, INK, True)
    c.text(49, 500, "GMP", 52, INK, True)
    c.text(670, 451, "제주", 32, INK, True, anchor="rt")
    c.text(670, 500, "CJU", 52, INK, True, anchor="rt")
    c.line([(257, 547), (459, 547)], "#A6C8C4", 2)
    c.poly([(461, 547), (443, 539), (443, 555)], "#A6C8C4")
    c.text(359, 503, "직항 1시간 10분", 18, MUTED, anchor="mt")
    c.text(49, 582, "10:20", 37, TEAL, True)
    c.text(670, 582, "11:30", 37, TEAL, True, anchor="rt")
    divider(c, 660, 47, 673)
    for y, label, value in [(687, "편명", "BA217"), (748, "예약번호", "SAMPLE"),
                            (809, "좌석 등급", "일반석"), (870, "여정", "서울 → 제주")]:
        c.text(48, y, label, 23, MUTED)
        c.text(670, y, value, 25, INK, True, anchor="rt")
    c.rect((24, 1000, 696, 1158), "#E2EEEE", 19)
    c.text(47, 1027, "여행 메모", 23, TEAL, True)
    c.text(47, 1074, "도착 후 파도스테이 제주로 이동", 25)
    c.bottom(text="가상 샘플 · 항공권으로 사용할 수 없습니다")
    return c.save(17)


def hotel():
    c = Canvas("#F8F8F5")
    c.status()
    c.header("숙소 예약")
    c.rect((25, 162, 695, 345), "#E5EFEE", 20)
    c.rect((479, 215, 638, 345), "#B3C9C3", 7)
    c.rect((461, 204, 654, 221), "#647F77", 5)
    for x in (500, 554, 608):
        for y in (243, 289):
            c.rect((x, y, x + 18, y + 22), "#F4F3D8", 2)
    c.text(46, 192, "PADO STAY", 21, "#547970", True)
    c.text(46, 236, "머무는 동안,\n바다 가까이", 29, "#3D6159", True)
    c.pill(32, 378, "가상 예약 / 사용 불가", "#FFF0DB", "#946A21", 19)
    c.text(32, 438, "파도스테이 제주", 38, INK, True)
    c.text(32, 498, "제주 바람항 · 항구에서 도보 10분", 23, MUTED)
    c.rect((25, 562, 695, 731), WHITE, 19)
    c.text(49, 588, "체크인", 21, MUTED)
    c.text(394, 588, "체크아웃", 21, MUTED)
    c.text(49, 631, "2026.10.16", 30, INK, True)
    c.text(394, 631, "2026.10.18", 30, INK, True)
    c.text(49, 680, "금요일 · 15:00", 20, MUTED)
    c.text(394, 680, "일요일 · 11:00", 20, MUTED)
    c.text(32, 779, "예약 정보", 27, INK, True)
    for y, label, value in [(841, "숙박", "2박 · 스탠다드 룸"), (900, "예약번호", "DEMO2026"),
                            (959, "인원", "성인 1명")]:
        c.text(32, y, label, 23, MUTED)
        c.text(686, y, value, 25, INK, True, anchor="rt")
    c.rect((25, 1039, 695, 1151), "#E8EEEA", 18)
    c.text(47, 1065, "저장한 여행", 20, "#64786B")
    c.text(47, 1100, "제주 2박 3일", 24, "#405C4A", True)
    c.bottom(text="가상 샘플 · 숙박 예약으로 사용할 수 없습니다")
    return c.save(18)


def lighthouse():
    c = Canvas()
    c.status()
    c.header("저장한 장소")
    c.rect((0, 148, 720, 631), "#E1F2F4")
    c.ellipse((525, 189, 601, 265), "#FFF2C1")
    c.poly([(0, 406), (134, 402), (297, 416), (459, 385), (720, 410),
            (720, 632), (0, 632)], "#70B6C4")
    c.poly([(0, 508), (119, 449), (273, 456), (373, 528), (447, 537),
            (540, 632), (0, 632)], "#719079")
    c.poly([(0, 544), (108, 491), (255, 492), (354, 558), (425, 565),
            (483, 632), (433, 632), (391, 594), (334, 592), (246, 527),
            (117, 523), (0, 583)], "#E0D3B4")
    c.poly([(184, 474), (205, 302), (242, 302), (264, 474)], "#FDFDF5")
    c.rect((197, 288, 249, 314), "#385668", 4)
    c.poly([(191, 287), (222, 262), (255, 287)], "#476171")
    c.rect((212, 321, 236, 344), "#BCDCE3", 2)
    c.rect((216, 431, 236, 474), "#728D93", 7)
    c.line([(201, 385), (245, 385)], "#DADFD7", 5)
    for y, x in [(443, 498), (483, 579), (550, 564)]:
        c.line([(x, y), (x + 70, y)], "#CAE7E7", 3)
    c.pill(28, 168, "해안 일러스트", WHITE, "#547B87", 16)
    c.text(32, 669, "하얀등대", 43, INK, True)
    bookmark(c, 653, 682)
    c.text(32, 731, "제주 바람항 산책로", 26, MUTED)
    c.pill(32, 791, "제주 2박 3일")
    c.pill(206, 791, "산책 · 바다", "#EEF4F8", "#537F92")
    divider(c, 859)
    c.text(32, 890, "저장한 메모", 24, INK, True)
    c.text(32, 944, "10월 17일 오전, 바람항에서 걸어가기.", 25)
    c.text(32, 992, "산책 후 소라식탁에서 점심 먹기.", 25)
    c.rect((32, 1080, 688, 1159), "#F2F6F4", 17)
    c.text(54, 1104, "가상 장소 · 실제 위치 안내가 아닙니다", 22, MUTED)
    c.bottom()
    return c.save(19)


def itinerary():
    c = Canvas("#F5F6FA")
    c.status()
    c.header("여행 노트")
    c.text(32, 175, "제주 2박 3일", 43, INK, True)
    c.text(32, 240, "2026.10.16–10.18", 25, MUTED)
    c.pill(32, 292, "일정 저장됨", "#E5E6FA", "#635AB5")
    days = [(368, "10.16", "금요일", "도착하는 날", ["10:20  바람항공 BA217 · 서울 → 제주",
              "15:00  파도스테이 제주 체크인", "18:00  소라식탁 바람항점 저녁"]),
            (653, "10.17", "토요일", "걷고 구경하기", ["10:00  하얀등대 · 바람항 산책로",
              "12:00  소라식탁에서 점심", "18:00  바람공원 · 제주 빛산책"]),
            (938, "10.18", "일요일", "집으로", ["11:00  숙소 체크아웃", "오후    제주공항으로 이동"])]
    for y, date, day, title, lines in days:
        height = 253 if len(lines) == 3 else 211
        c.rect((24, y, 696, y + height), WHITE, 19)
        c.rect((46, y + 22, 157, y + 87), "#EEEFFC", 12)
        c.text(101, y + 30, date, 25, "#635AB5", True, anchor="mt")
        c.text(101, y + 66, day, 16, "#7973A3", anchor="mt")
        c.text(181, y + 37, title, 28, INK, True)
        for n, line in enumerate(lines):
            ly = y + 112 + n * 43
            c.ellipse((50, ly + 10, 57, ly + 17), "#A7A4C8")
            c.text(76, ly, line, 22, "#45525F")
    c.bottom(text="가상 샘플 · 여행지와 예약 정보는 가상입니다")
    return c.save(20)


def main():
    files = [restaurant(1), map_capture(), product(3), event(4), restaurant(13, True),
             product(14, True), event(15, True), note(), flight(), hotel(), lighthouse(), itinerary()]
    QA.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (4 * 288, 3 * 540), "#D9DDE1")
    sd = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(BOLD), 16)
    for n, path in enumerate(files):
        thumb = Image.open(path).resize((288, 512), Image.Resampling.LANCZOS)
        x, y = (n % 4) * 288, (n // 4) * 540
        sheet.paste(thumb, (x, y + 28))
        sd.text((x + 10, y + 5), path.name, font=font, fill=INK)
        with Image.open(path) as im:
            assert im.size == (720, 1280) and not im.info, (path, im.size, im.info)
        print(f"{path.name}: {path.stat().st_size:,} bytes; 720x1280; no metadata")
    sheet.save(QA / "contact-sheet.jpg", quality=94)
    print(f"Total: {sum(p.stat().st_size for p in files):,} bytes")
    print(f"Contact sheet: {QA / 'contact-sheet.jpg'}")


if __name__ == "__main__":
    main()
