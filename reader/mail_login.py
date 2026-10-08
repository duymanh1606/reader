"""Đăng nhập Outlook bằng email và mật khẩu dán vào giao diện.

Việc này chỉ làm với HỘP THƯ CỦA BẠN, bằng mật khẩu bạn tự dán vào -
agent không đi lấy mật khẩu từ đâu khác và chỉ gõ nó vào đúng tên miền đăng
nhập của Microsoft (xem `TRUSTED_HOSTS`): một trang giả mạo nằm trên tên miền
khác sẽ không nhận được gì.

Những thứ agent KHÔNG làm, và sẽ dừng để bạn làm:
  * xác thực hai bước (mã authenticator, SMS, email phụ);
  * CAPTCHA / "chứng minh bạn là người";
  * yêu cầu đổi mật khẩu, xác nhận thông tin khôi phục.

Mật khẩu chỉ nằm trong bộ nhớ của lần chạy: không vào log, không vào file, không
đi đâu khác ngoài form đăng nhập của Microsoft.
"""

from __future__ import annotations

import logging
import re
import time

from reader.dom import first_visible as _first_visible
from reader.dom import first_visible_by_role as _first_by_name

logger = logging.getLogger(__name__)

# Chỉ gõ mật khẩu khi URL thuộc một trong các host này.
TRUSTED_HOSTS = (
    "login.live.com",
    "login.microsoftonline.com",
    "login.microsoft.com",
    "outlook.live.com",
    "outlook.office.com",
    "account.live.com",
    "signup.live.com",
)

EMAIL_INPUTS = ("input[name='loginfmt']", "input[type='email']")
PASSWORD_INPUTS = ("input[name='passwd']", "input[type='password']")
SUBMIT_BUTTONS = (
    "#idSIButton9",
    "input[type='submit']",
    "button[type='submit']",
    "button[data-testid='primaryButton']",
)
# Cổng đăng nhập. Chưa đăng nhập thì outlook.live.com/mail/0/ đá sang trang
# giới thiệu trên www.microsoft.com; đi thẳng tới đây chắc hơn nhiều so với dò
# nút "Sign in" trên trang đó - tôi thử rồi: cái link bắt được hoá ra là trang
# chính sách riêng tư, và trang đó không có dấu hiệu "chưa đăng nhập" nào nên
# agent tưởng mình đã vào hộp thư.
LOGIN_URL = "https://login.live.com/login.srf"
LOGOUT_URL = "https://login.live.com/logout.srf"

# Microsoft giờ mời đăng nhập KHÔNG mật khẩu trước: sau khi nhập địa chỉ, nó
# hiện màn hình "Verify your email - We'll send a code to ja*****@..." kèm một
# ô ghi nhãn "Email".

# Cái bẫy: ô đó KHÔNG phải chỗ nhập lại địa chỉ đăng nhập - nó bắt gõ đúng địa
# chỉ phụ (thứ ta không có) để gửi mã tới đó. Gõ nhầm vào đấy là đẩy mã đi một
# hộp thư khác hẳn. Nên hễ thấy lối "Use your password" là đi lối đó, trước cả
# khi nhìn tới bất kỳ ô nhập nào.
USE_PASSWORD_SELECTORS = (
    "#idA_PWD_SwitchToPassword",
    "a[data-testid='usePasswordLink']",
    "[data-testid='signInWithPassword']",
)
USE_PASSWORD_TEXTS = (
    "Use your password",
    "Use password",
    "Sign in with your password",
    "Dùng mật khẩu của bạn",
    "Dùng mật khẩu",
)
MAX_USE_PASSWORD_CLICKS = 3

# Microsoft chen vào đủ thứ màn hình CHỈ ĐỂ THÔNG BÁO trên đường vào hộp thư -
# "We're updating our terms", "A quick note about your Microsoft account",
# "Welcome to the new Outlook"... Danh sách sẽ còn dài ra, nên ở đây không kể
# tên từng màn hình mà hỏi ba câu về màn hình đang đứng:
#
#   1. nó có HỎI gì không? Màn hình thông báo không có ô nhập, không có danh
#      sách chọn - chỉ có chữ và một cái nút.
#   2. chữ trên đó có dính thứ agent không được tự làm không (2FA, CAPTCHA,
#      xác minh qua email phụ, đổi mật khẩu)? Dính là không bấm, kể cả khi
#      màn hình ấy không có ô nhập nào.
#   3. nút có mang nghĩa "đọc rồi, đi tiếp" không?
#
# Ba câu đó qua hết thì bấm là an toàn: không gõ gì, không gửi mã đi đâu, và
# cùng lắm là sang một màn hình mà vòng sau sẽ đọc lại từ đầu.

# Ô nào trong số này ĐANG HIỆN nghĩa là màn hình đang hỏi, không phải thông báo.
FILLABLE = (
    "input:not([type])", "input[type='text']", "input[type='email']",
    "input[type='password']", "input[type='tel']", "input[type='number']",
    "input[type='search']", "textarea", "select",
)
# Chữ trên nút, nghĩa là "đọc rồi, đi tiếp". KHÔNG có "Learn more" (mở trang
# khác), "No"/"Cancel", "Send code" (đẩy mã sang hộp thư khác), hay bất cứ chữ
# nào mang nghĩa xoá/đăng xuất. "Yes" cũng không: một mình nó chẳng nói lên
# đang đồng ý với cái gì - riêng "Stay signed in?" đã có hàm xử lý riêng.
SAFE_CONTINUE = (
    "Next", "OK", "Okay", "Got it", "Continue", "Done", "Finish", "Close",
    "Skip", "Skip for now", "Not now", "Maybe later", "Ask me later",
    "Dismiss", "Accept", "Accept and continue", "Agree", "I agree",
    "Tiếp theo", "Tiếp tục", "Xong", "Đồng ý", "Đã hiểu", "Để sau",
    "Bỏ qua", "Đóng",
)
# Khớp cả hoa thường và khoảng trắng thừa, nhưng vẫn là KHỚP CẢ TÊN: để khớp
# một phần thì "OK" trúng luôn nút "Book now".
SAFE_CONTINUE_PATTERNS = tuple(
    re.compile(rf"^\s*{re.escape(name)}\s*$", re.IGNORECASE) for name in SAFE_CONTINUE
)
MAX_NOTICE_CLICKS = 8

# Nút "Sign in" ngay trên tên miền đăng nhập (màn hình "chọn tài khoản"...).
SIGNIN_LINKS = (
    "a[data-task='signin']",
    "a[href*='login.live.com']",
    "#signinbutton",
)

# Dấu hiệu phải giao lại cho người: agent không tự xoay xở với mấy thứ này.
BLOCKERS = {
    "xác thực hai bước": (
        "approve sign in request", "enter the code displayed", "authenticator app",
        "verify your identity", "we need to verify", "enter the code we sent",
        "two-step verification", "get a code", "text a code", "security code",
        "xác minh danh tính",
    ),
    "CAPTCHA": ("solve the puzzle", "prove you're human", "press and hold", "captcha"),
    "xác minh qua email phụ": (
        "to verify this is your email",
        "enter your full email address to verify",
    ),
    "sai mật khẩu": (
        "your account or password is incorrect",
        "that microsoft account doesn't exist",
        "password is incorrect",
        "we couldn't find an account",
    ),
    "tài khoản bị khoá": (
        "your account has been locked", "account has been suspended",
        "help us secure your account", "unusual sign-in activity",
    ),
    "đổi mật khẩu": ("update your password", "your password has expired"),
}


class MailLoginBlocked(RuntimeError):
    """Gặp thứ agent không được tự làm (2FA, CAPTCHA, sai mật khẩu...)."""


def _trusted(page) -> bool:
    url = (page.url or "").lower()
    return any(host in url for host in TRUSTED_HOSTS)


def _page_text(page) -> str:
    try:
        return (page.inner_text("body", timeout=2000) or "").lower()
    except Exception:
        return ""


def blocker_in(text: str) -> str | None:
    """Chữ này có dính thứ agent không được tự làm không? Trả về tên nhóm."""
    if not text:
        return None
    for name, needles in BLOCKERS.items():
        if any(needle in text for needle in needles):
            return name
    return None


def find_blocker(page) -> str | None:
    """Trang đang hỏi thứ gì mà agent không được tự trả lời? Trả về tên nó."""
    return blocker_in(_page_text(page))


def _click(locator, pace=None) -> None:
    locator.click(timeout=15000)
    if pace is not None:
        pace.pause()


def _type(locator, value: str, pace=None) -> None:
    """Gõ từng ký tự - form của Microsoft cũng là form React."""
    locator.click(timeout=15000)
    locator.fill("", timeout=15000)
    locator.press_sequentially(value, delay=(pace.typing_delay if pace else 0))


def logged_in(page) -> bool:
    """Đã vào được hộp thư chưa?"""
    from reader.outlook import needs_login

    return not needs_login(page)


def _use_password_link(page):
    """Lối 'Use your password' trên màn hình đăng nhập không mật khẩu."""
    link = _first_visible(page, USE_PASSWORD_SELECTORS)
    if link is not None:
        return link
    for text in USE_PASSWORD_TEXTS:
        for role in ("link", "button"):
            items = page.get_by_role(role, name=text)
            try:
                count = min(items.count(), 5)
            except Exception:
                continue
            for index in range(count):
                item = items.nth(index)
                try:
                    if item.is_visible():
                        return item
                except Exception:
                    continue
    return None


def _frames_with_text(page):
    """Từng khung của trang, kèm chữ trong đó (viết thường).

    Phải soi cả iframe: màn hình "A quick note..." có khi nằm trong một khung
    con, và `page.inner_text("body")` không đọc tới chữ bên trong khung đó.
    """
    frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
    for frame in frames:
        try:
            text = (frame.inner_text("body", timeout=1000) or "").lower()
        except Exception:
            continue
        if text:
            yield frame, text


def notice_button(page):
    """Nút "đi tiếp" của một màn hình chỉ-để-thông-báo, nếu đang đứng ở đó.

    Trả về None khi màn hình có ô nhập (nó đang hỏi), khi chữ trên đó dính một
    nhóm trong `BLOCKERS` (việc của người), hoặc khi không có nút nào mang
    nghĩa "đọc rồi, đi tiếp". Xem khối chú thích ở đầu file.
    """
    if not _trusted(page):
        # Chỉ bấm trên tên miền của Microsoft. Một trang lạ thì ngay cả cái
        # nút "OK" cũng không biết nó làm gì.
        return None
    for frame, text in _frames_with_text(page):
        blocked = blocker_in(text)
        if blocked:
            logger.debug("không bấm qua màn hình này: nó đang hỏi %s", blocked)
            continue
        if _first_visible(frame, FILLABLE) is not None:
            continue
        button = _first_by_name(frame, SAFE_CONTINUE_PATTERNS)
        if button is not None:
            return button
    return None


def _signin_link(page):
    """Nút 'Sign in' - chỉ dò khi đã ở trên tên miền đăng nhập.

    Trên trang giới thiệu của Microsoft thì không dò: ở đó mọi link đều có thể
    là một trang bất kỳ, và đi nhầm sang một trang không-phải-đăng-nhập là cách
    agent lặng lẽ tưởng mình đã vào được hộp thư.
    """
    return _first_visible(page, SIGNIN_LINKS)


class _Login:
    """Một lượt đăng nhập: giữ trang, tài khoản, và vài cái cờ nhỏ.

    Mỗi màn hình của Microsoft là một hàm riêng bên dưới, trả về True nghĩa là
    "màn hình này của tôi, tôi vừa xử lý xong" - vòng lặp chính chỉ việc thử
    lần lượt. Viết dưới dạng một chuỗi `if` lồng nhau với bốn cái cờ thì khó
    lần ra thứ tự ưu tiên, mà thứ tự ở đây là thứ quyết định đúng/sai.
    """

    def __init__(self, page, email: str, password: str, pace=None):
        self.page = page
        self.email = email
        self.password = password
        self.pace = pace
        self.typed_email = False
        self.typed_password = False
        self.opened_portal = False
        self.switch_clicks = 0
        self.notice_clicks = 0

    # -- từng màn hình, theo đúng thứ tự ưu tiên ---------------------------
    def answer_stay_signed_in(self) -> bool:
        """Kiểm ở ĐẦU mỗi vòng: màn hình đó hiện chậm hơn một nhịp là lỡ."""
        if _stay_signed_in(self.page, self.pace):
            self.page.wait_for_timeout(2000)
            return True
        return False

    def dismiss_notice(self) -> bool:
        """Bấm qua một màn hình chỉ-để-thông-báo.

        Đứng cạnh `answer_stay_signed_in` vì cùng một loại việc, và đứng TRƯỚC
        `find_blocker` được là vì `notice_button` tự kiểm `BLOCKERS` trên đúng
        khung nó định bấm: màn hình nào dính thì nó bỏ qua, vòng sau
        `find_blocker` nói rõ lý do và agent giao lại cho người.
        """
        if self.notice_clicks >= MAX_NOTICE_CLICKS:
            return False
        button = notice_button(self.page)
        if button is None:
            return False
        self.notice_clicks += 1
        logger.info("hộp thư %s: bấm qua một màn hình thông báo", self.email)
        _click(button, self.pace)
        self.page.wait_for_timeout(2000)
        return True

    def switch_to_password(self) -> bool:
        """Trang mời đăng nhập không mật khẩu vẫn đi tiếp được - đổi lối.

        Phải đứng TRƯỚC phép thử "có bị chặn không": chạy thật cho thấy
        `find_blocker` đọc màn hình ấy ra "xác minh qua email phụ", và nếu nó
        chạy trước thì agent bỏ cuộc ở một màn hình nó đi qua được.
        """
        if self.switch_clicks >= MAX_USE_PASSWORD_CLICKS:
            return False
        link = _use_password_link(self.page)
        if link is None:
            return False
        self.switch_clicks += 1
        logger.info("hộp thư %s: chuyển sang đăng nhập bằng mật khẩu", self.email)
        _click(link, self.pace)
        self.page.wait_for_timeout(2000)
        return True

    def find_input(self) -> bool:
        """Chưa thấy ô nào: mở cổng đăng nhập, hoặc bấm nút "Sign in"."""
        if _first_visible(self.page, EMAIL_INPUTS) or _first_visible(
            self.page, PASSWORD_INPUTS
        ):
            return False

        if not _trusted(self.page) or not self.opened_portal:
            self.opened_portal = True
            logger.info("mở cổng đăng nhập Microsoft")
            try:
                self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logger.debug("không mở được cổng đăng nhập: %s", exc)
            self.page.wait_for_timeout(2000)
            return True

        link = _signin_link(self.page)
        if link is not None:
            _click(link, self.pace)
            self.page.wait_for_timeout(2000)
        else:
            self.page.wait_for_timeout(1000)
        return True

    def type_and_submit(self) -> bool:
        """Gõ mật khẩu nếu đang hỏi mật khẩu, không thì gõ địa chỉ."""
        if not _trusted(self.page):
            raise MailLoginBlocked(
                f"trang đăng nhập nằm ở tên miền lạ ({self.page.url[:80]}) - "
                "không gõ mật khẩu vào đó"
            )

        o_mat_khau = _first_visible(self.page, PASSWORD_INPUTS)
        if o_mat_khau is not None:
            if self.typed_password:
                # Gõ rồi mà vẫn ở đây: chờ một nhịp để vòng sau `find_blocker`
                # nói rõ lý do, đừng gõ lại mật khẩu lần nữa.
                self.page.wait_for_timeout(1500)
                self.typed_password = False
                return True
            _type(o_mat_khau, self.password, self.pace)
            self.typed_password = True
            logger.info("hộp thư %s: đã nhập mật khẩu", self.email)
        else:
            o_dia_chi = _first_visible(self.page, EMAIL_INPUTS)
            if o_dia_chi is None:
                self.page.wait_for_timeout(1000)
                return True
            if self.typed_email:
                self.page.wait_for_timeout(1500)
                self.typed_email = False
                return True
            _type(o_dia_chi, self.email, self.pace)
            self.typed_email = True
            logger.info("hộp thư %s: đã nhập địa chỉ", self.email)

        nut = _first_visible(self.page, SUBMIT_BUTTONS)
        if nut is not None:
            _click(nut, self.pace)
        else:
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(2000)
        return True


def login(
    page,
    email: str,
    password: str,
    pace=None,
    timeout_seconds: int = 90,
    should_stop=None,
) -> None:
    """Đăng nhập, rồi chờ tới khi hộp thư mở ra.

    Ném `MailLoginBlocked` khi gặp 2FA/CAPTCHA/sai mật khẩu, hoặc khi hết thời
    gian chờ. Không bao giờ nhập mật khẩu trên tên miền lạ.
    """
    if not password:
        raise MailLoginBlocked(
            f"chưa có mật khẩu hộp thư cho {email} - dán dạng "
            f"'{email}|matkhau'"
        )

    session = _Login(page, email, password, pace)
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if should_stop is not None and should_stop():
            raise MailLoginBlocked("thôi đăng nhập: bạn đã dừng")

        # Kiểm "đã vào được" TRƯỚC khi soi từ khoá: hộp thư mở ra thường có
        # sẵn mail chứa chữ "security code", soi trước thì nhầm thành 2FA.
        if logged_in(page):
            logger.info("hộp thư %s: đã vào được", email)
            return

        if session.answer_stay_signed_in():
            continue
        if session.dismiss_notice():
            continue
        if session.switch_to_password():
            continue

        rate_limited = find_blocker(page)
        if rate_limited:
            raise MailLoginBlocked(
                f"Outlook đang hỏi {rate_limited} - việc này dành cho bạn, "
                "agent không tự xử lý"
            )

        if session.find_input():
            continue
        session.type_and_submit()

    raise MailLoginBlocked(
        f"hết {timeout_seconds}s mà hộp thư {email} vẫn chưa mở - hãy xem cửa sổ đó"
    )


def _stay_signed_in(page, pace=None) -> bool:
    """Trả lời màn hình "Stay signed in?". Trả True nếu vừa bấm một nút."""
    text = _page_text(page)
    if "stay signed in" not in text and "duy trì đăng nhập" not in text:
        return False

    button = _first_visible(page, SUBMIT_BUTTONS)
    if button is None:
        # Bản giao diện mới dùng <button> trơn, không phải type=submit. Bấm
        # nút nào cũng được, cốt là đi tiếp - "Yes" là nút chính nên thử trước.
        for name in ("Yes", "Có", "No", "Không"):
            for role in ("button", "link"):
                candidate = page.get_by_role(role, name=name, exact=True).first
                try:
                    if candidate.count() and candidate.is_visible():
                        button = candidate
                        break
                except Exception:
                    continue
            if button is not None:
                break
    if button is None:
        logger.warning("thấy 'Stay signed in?' nhưng không tìm ra nút nào")
        return False

    logger.info("hộp thư: trả lời 'Stay signed in?'")
    _click(button, pace)
    return True


def sign_out(page, pace=None) -> str:
    """Đăng xuất khỏi hộp thư, rồi dọn cookie.

    Hai lớp: gọi đúng địa chỉ
    đăng xuất để máy chủ huỷ phiên, rồi mới dọn cookie - chỉ dọn cookie thì
    phiên vẫn sống ở phía Microsoft.

    Không bao giờ ném lỗi: đăng xuất không xong cũng không đáng làm đổ việc.
    """
    try:
        page.goto(LOGOUT_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if pace is not None:
            pace.pause()
    except Exception as exc:
        logger.warning("đăng xuất hộp thư không xong: %s", exc)
    try:
        page.context.clear_cookies()
    except Exception as exc:
        logger.debug("không dọn được cookie hộp thư: %s", exc)
    logger.info("đã đăng xuất hộp thư")
    return "đã đăng xuất hộp thư"


def fresh_login(
    page,
    email: str,
    password: str,
    inbox_url: str,
    pace=None,
    should_stop=None,
    timeout_seconds: int = 90,
) -> None:
    """Đăng XUẤT phiên cũ rồi mới đăng nhập, cuối cùng mở hộp thư.

    Vì sao luôn đăng xuất trước, kể cả khi chưa chắc có phiên nào: còn phiên
    cũ thì `login.srf` không hỏi gì cả, nó đưa thẳng vào hộp thư của TÀI KHOẢN
    TRƯỚC. Lúc đó luồng canh ngồi canh đúng một hộp thư sai, và mã của tài
    khoản vừa dán thì không bao giờ tới.

    Đọc tên tài khoản đang đăng nhập để so cũng được, nhưng phải dò giao diện
    quản lý tài khoản của Microsoft - thứ đổi luôn. Đăng xuất thì chắc chắn,
    và chỉ tốn một lần tải trang.
    """
    # Kiểm TRƯỚC khi đăng xuất. Không có mật khẩu mà vẫn đăng xuất là đá phiên
    # đang có của người dùng ra rồi mới báo không đăng nhập lại được.
    if not password:
        raise MailLoginBlocked(
            f"chưa có mật khẩu hộp thư cho {email} - dán dạng "
            f"'{email}|matkhau'"
        )

    sign_out(page, pace)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    login(page, email, password, pace, timeout_seconds, should_stop)
    page.goto(inbox_url, wait_until="domcontentloaded", timeout=60000)
