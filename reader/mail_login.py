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
# Hai cổng, dùng ở hai lúc KHÁC nhau:
#
# 1. LOGIN_URL - để NHẬP mật khẩu lần đầu. Phải là login.live.com/login.srf:
#    đây mới là nơi hiện form đăng nhập. KHÔNG dùng outlook.live.com/owa khi
#    chưa có phiên - owa đá ngược về trang giới thiệu www.microsoft.com, và
#    agent quay vòng "mở cổng đăng nhập" mãi không thấy form.
# 2. OUTLOOK_URL - để LẤY phiên Outlook SAU khi đã đăng nhập tài khoản. Đăng
#    nhập xong login.srf đưa về account.microsoft.com (chưa vào hộp thư); mở
#    owa?nlp=1 lúc này - đã có phiên - thì vào thẳng hộp thư. `_on_account_home`
#    lo việc này.
#
# Chưa đăng nhập thì outlook.live.com/mail/0/ đá sang trang giới thiệu trên
# www.microsoft.com; đi thẳng tới cổng chắc hơn nhiều so với dò nút "Sign in"
# trên trang đó - cái link bắt được từng là trang chính sách riêng tư.
LOGIN_URL = "https://login.live.com/login.srf"
OUTLOOK_URL = "https://outlook.live.com/owa/?nlp=1"
# Trang chủ tài khoản Microsoft: đã đăng nhập tài khoản nhưng chưa vào Outlook.
ACCOUNT_HOME_HOSTS = ("account.microsoft.com", "account.live.com/proofs")
MAX_ACCOUNT_HOME_HOPS = 3
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

# Chờ cho màn hình sau hiện ra sau mỗi lần bấm/chuyển trang. Không có sự kiện
# nào báo "màn hình kế đã sẵn" (Microsoft swap div bằng JS, không điều hướng
# thật), nên đành chờ cứng. Vòng đăng nhập tự đọc lại trang mỗi nhịp và mỗi
# bước đều có cờ chống làm lại, nên chờ hơi ngắn chỉ tốn thêm một vòng lặp chứ
# không gõ nhầm - để rộng rãi thì mỗi lượt đăng nhập cộng thêm cả chục giây.
STEP_WAIT_MS = 800

# Gõ mật khẩu mấy lần thì thôi. Lần hai là cho trường hợp form React nuốt mất
# lần đầu; quá nữa thì Microsoft đang từ chối mà ta không đọc ra lý do - gõ
# tiếp chỉ làm tài khoản bị khoá vì nhập sai liên tục.
MAX_PASSWORD_TRIES = 2

# Trang lỗi của trình duyệt (proxy cắt kết nối) thì mở lại cổng mấy nhịp rồi
# thôi. Dai hơn thế là lỗi mạng thật, nổi lên cho người biết thay vì spin.
MAX_ERROR_PAGE_TRIES = 3

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
        # Đi qua IP Việt Nam thì Microsoft trả trang tiếng Việt.
        "mật khẩu của bạn không chính xác",
        "mật khẩu không chính xác",
        "tài khoản microsoft đó không tồn tại",
    ),
    "tài khoản bị khoá": (
        "your account has been locked", "account has been suspended",
        "help us secure your account", "unusual sign-in activity",
    ),
    "đổi mật khẩu": ("update your password", "your password has expired"),
}

# "Password sign-in isn't available. Try another method." - Microsoft chặn đăng
# nhập bằng mật khẩu THEO RỦI RO khi IP proxy bẩn/bị gắn cờ, dù mật khẩu đúng và
# tài khoản vẫn cho dùng mật khẩu. Thử thật trên server: cùng tài khoản + mật
# khẩu, IP proxy 502 thì bị chặn, đổi sang IP VN sạch thì đăng nhập được ngay.
# Nên ĐÂY KHÔNG phải việc giao cho người: báo lỗi có dấu nhận biết để tầng job
# đổi IP rồi chạy lại (xem reader/rotate.py: should_rotate, reader/jobs.py).
PASSWORD_SIGNIN_UNAVAILABLE_TEXTS = (
    "password sign-in isn",  # "...isn't available" (tránh phụ thuộc dấu ')
    "đăng nhập bằng mật khẩu không khả dụng",
)
# Dấu để tầng job biết "đổi IP rồi thử lại" (xem reader/rotate.py: RISK_BLOCK_MARKERS).
# Mọi thông báo lỗi nghi do IP phải KẾT bằng câu này thì `should_rotate` mới bắt.
ROTATE_HINT = "cần đổi IP sạch rồi thử lại"
PASSWORD_SIGNIN_UNAVAILABLE_MSG = (
    "Microsoft chặn đăng nhập bằng mật khẩu trên IP này "
    "(password sign-in isn't available) - IP proxy có thể bẩn, " + ROTATE_HINT
)

# Lỗi TẠM THỜI của Microsoft, hầu như luôn do IP chập chờn (tải trang không
# xong): "There was an issue looking up your account. Tap Next to try again.",
# "Something went wrong". Gặp là đổi IP rồi thử lại, đừng bấm Next hoài tới hết
# giờ (thử thật: lần nào IP yếu là dính, IP ổn thì không).
TRANSIENT_MS_ERROR_TEXTS = (
    "there was an issue looking up your account",
    "issue looking up your account",
    "có sự cố khi tra cứu tài khoản",
)
TRANSIENT_MS_ERROR_MSG = (
    "Microsoft báo lỗi tạm thời khi tra cứu tài khoản - IP proxy chập chờn, "
    + ROTATE_HINT
)


class MailLoginBlocked(RuntimeError):
    """Gặp thứ agent không được tự làm (2FA, CAPTCHA, sai mật khẩu...)."""


def outlook_short_url(page) -> str:
    from reader.outlook import short_url

    return short_url(page)


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


def password_signin_unavailable(page) -> bool:
    """Trang có đang báo "Password sign-in isn't available" không?

    Chỉ hiện sau khi đã gửi mật khẩu, nên gọi trong vòng đăng nhập sau mỗi lần
    gửi. Đây là chặn theo rủi ro do IP, không phải thiết lập cố định của tài
    khoản - người gọi nên đổi IP rồi thử lại, không giao cho người.
    """
    text = _page_text(page)
    return any(t in text for t in PASSWORD_SIGNIN_UNAVAILABLE_TEXTS)


def transient_ms_error(page) -> bool:
    """Trang có đang báo lỗi tạm thời của Microsoft (nghi do IP) không?"""
    text = _page_text(page)
    return any(t in text for t in TRANSIENT_MS_ERROR_TEXTS)


def _click(locator) -> None:
    locator.click(timeout=15000)


def _type(locator, value: str) -> None:
    """Gõ từng ký tự THONG THẢ, rồi KIỂM lại ô có đúng từng ký tự không.

    Form của Microsoft là form React: gõ quá nhanh thì nó nuốt mất ký tự, ô
    còn lại một chuỗi SAI mà không báo gì - đúng là mật khẩu gõ rồi vẫn bị hỏi
    lại. Nên gõ chậm (có `delay`), rồi đọc `input.value` so lại với `value`;
    lệch thì xoá sạch, gõ lại, tối đa 3 lần.
    """
    for attempt in range(3):
        locator.click(timeout=15000)
        locator.fill("", timeout=15000)
        locator.press_sequentially(value, delay=45)
        try:
            typed = locator.input_value(timeout=5000)
        except Exception:
            return  # không đọc lại được thì đành tin là đã gõ xong
        if typed == value:
            return
        logger.warning(
            "ô nhập lệch sau khi gõ (dài %d, cần %d) - gõ lại lần %d",
            len(typed), len(value), attempt + 2,
        )
    raise MailLoginBlocked(
        "gõ mãi mà ô nhập vẫn không khớp giá trị cần gõ - "
        "form có thể đang chặn; xem ảnh chụp màn hình"
    )


def _on_account_home(page) -> bool:
    url = (page.url or "").lower()
    return any(host in url for host in ACCOUNT_HOME_HOSTS)


def logged_in(page) -> bool:
    """Đã vào được hộp thư chưa?

    Kiểm DƯƠNG TÍNH: phải thật sự thấy hộp thư. "Không phải trang đăng nhập" là
    chưa đủ - một trang lỗi của trình duyệt (`chrome-error://chromewebdata/` khi
    proxy cắt kết nối tới login.live.com) cũng không phải trang đăng nhập, mà
    chẳng có mail nào. Trước đây dùng `not needs_login(page)` nên trang lỗi lọt
    qua, `login()` return "đã vào được", rồi `fetch` quay lại và lặp vô tận.
    """
    from reader.outlook import in_inbox

    return in_inbox(page)


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

    def __init__(self, page, email: str, password: str):
        self.page = page
        self.email = email
        self.password = password
        self.typed_email = False
        self.typed_password = False
        # Hai cờ DÍNH (hai cờ trên bị gỡ sau mỗi nhịp chờ): đã từng gõ địa chỉ
        # / mật khẩu trong lượt này chưa. Xem `_email_input`.
        self.email_done = False
        self.password_done = False
        self.password_tries = 0
        self.opened_portal = False
        self.switch_clicks = 0
        self.notice_clicks = 0

    # -- từng màn hình, theo đúng thứ tự ưu tiên ---------------------------
    def answer_stay_signed_in(self) -> bool:
        """Kiểm ở ĐẦU mỗi vòng: màn hình đó hiện chậm hơn một nhịp là lỡ."""
        if _stay_signed_in(self.page):
            self.page.wait_for_timeout(STEP_WAIT_MS)
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
        _click(button)
        self.page.wait_for_timeout(STEP_WAIT_MS)
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
        _click(link)
        self.page.wait_for_timeout(STEP_WAIT_MS)
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
            self.page.wait_for_timeout(STEP_WAIT_MS)
            return True

        link = _signin_link(self.page)
        if link is not None:
            _click(link)
            self.page.wait_for_timeout(STEP_WAIT_MS)
        else:
            self.page.wait_for_timeout(1000)
        return True

    def _email_input(self):
        """Ô nhập ĐỊA CHỈ ĐĂNG NHẬP - không phải ô xác minh.

        Sau khi đã gõ mật khẩu, mọi ô email hiện ra đều là ô XÁC MINH ("nhập
        địa chỉ phụ để nhận mã"), chứ không phải chỗ nhập lại địa chỉ đăng
        nhập. Gõ vào đấy là đẩy mã sang một hộp thư khác - và tệ hơn: nó BIẾN
        một màn hình còn đọc được thành một màn hình 2FA thật.

        Chạy thật trên server cho thấy đúng chuyện đó: sau "đã nhập mật khẩu"
        là một dòng "đã nhập địa chỉ" nữa, rồi mới tới "Outlook đang hỏi xác
        thực hai bước". `find_blocker` không cứu được, vì ở nhịp ấy chữ xác
        minh chưa kịp hiện ra.

        Nên: hễ đã gõ mật khẩu thì không gõ địa chỉ nữa; và khi đã gõ địa chỉ
        một lần rồi thì chỉ nhận đúng ô `loginfmt` của Microsoft, không nhận
        một ô `type=email` bất kỳ.
        """
        if self.password_done:
            return None
        o_dang_nhap = _first_visible(self.page, ("input[name='loginfmt']",))
        if o_dang_nhap is not None:
            return o_dang_nhap
        return None if self.email_done else _first_visible(self.page, EMAIL_INPUTS)

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
            if self.password_tries >= MAX_PASSWORD_TRIES:
                # Gõ đúng mật khẩu bấy nhiêu lần mà vẫn ở màn hình mật khẩu, lại
                # KHÔNG có câu "sai mật khẩu" tường minh (câu đó `find_blocker`
                # bắt trước) - gần như luôn là chặn theo IP, không phải sai mật
                # khẩu. Nên báo lỗi có ROTATE_HINT để tầng job đổi IP rồi thử lại.
                raise MailLoginBlocked(
                    f"đã nhập mật khẩu {self.password_tries} lần mà Microsoft vẫn "
                    "ở màn hình mật khẩu (không báo sai mật khẩu) - gần như chắc "
                    "chắn IP bị chặn, " + ROTATE_HINT
                )
            _type(o_mat_khau, self.password)
            self.password_tries += 1
            self.typed_password = True
            self.password_done = True
            logger.info("hộp thư %s: đã nhập mật khẩu", self.email)
        else:
            o_dia_chi = self._email_input()
            if o_dia_chi is None:
                # Không có ô nào được phép gõ: chờ một nhịp để vòng sau
                # `find_blocker` nói rõ đây là màn hình gì.
                self.page.wait_for_timeout(1000)
                return True
            if self.typed_email:
                self.page.wait_for_timeout(1500)
                self.typed_email = False
                return True
            _type(o_dia_chi, self.email)
            self.typed_email = True
            self.email_done = True
            logger.info("hộp thư %s: đã nhập địa chỉ", self.email)

        nut = _first_visible(self.page, SUBMIT_BUTTONS)
        if nut is not None:
            _click(nut)
        else:
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(STEP_WAIT_MS)
        return True


def login(
    page,
    email: str,
    password: str,
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

    from reader.outlook import is_error_page

    session = _Login(page, email, password)
    deadline = time.monotonic() + timeout_seconds
    error_streak = 0        # số nhịp liên tiếp đứng ở trang lỗi của trình duyệt
    account_hops = 0        # số lần từ trang tài khoản sang Outlook

    while time.monotonic() < deadline:
        if should_stop is not None and should_stop():
            raise MailLoginBlocked("thôi đăng nhập: bạn đã dừng")

        # Kiểm "đã vào được" TRƯỚC khi soi từ khoá: hộp thư mở ra thường có
        # sẵn mail chứa chữ "security code", soi trước thì nhầm thành 2FA.
        if logged_in(page):
            logger.info("hộp thư %s: đã vào được (%s)", email, outlook_short_url(page))
            return

        # Trang lỗi của trình duyệt: không mở được cổng đăng nhập. Thử mở lại
        # vài nhịp - trang có thể hồi. Lỗi dai là lỗi mạng thật (proxy chặn),
        # nổi lên để người biết, đừng lặp câm cho tới khi hết giờ.
        if is_error_page(page):
            error_streak += 1
            if error_streak >= MAX_ERROR_PAGE_TRIES:
                raise MailLoginBlocked(
                    f"không mở được cổng đăng nhập Microsoft (trang lỗi "
                    f"'{outlook_short_url(page)}') - proxy có thể đang chặn "
                    "login.live.com; " + ROTATE_HINT
                )
            logger.info("hộp thư %s: trang lỗi (%s), mở lại cổng đăng nhập",
                        email, outlook_short_url(page))
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logger.debug("mở lại cổng đăng nhập vẫn lỗi: %s", exc)
            page.wait_for_timeout(1500)
            continue
        error_streak = 0

        # Đứng ở trang chủ tài khoản: tài khoản đã đăng nhập, chỉ thiếu phiên
        # Outlook - qua cổng Outlook là vào thẳng, không phải gõ gì nữa.
        if _on_account_home(page):
            account_hops += 1
            if account_hops > MAX_ACCOUNT_HOME_HOPS:
                raise MailLoginBlocked(
                    "đã đăng nhập tài khoản Microsoft nhưng Outlook không mở - "
                    "xem ảnh chụp màn hình"
                )
            logger.info("hộp thư %s: đang ở trang tài khoản (%s), sang Outlook",
                        email, outlook_short_url(page))
            try:
                page.goto(OUTLOOK_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logger.debug("không mở được Outlook: %s", exc)
            page.wait_for_timeout(STEP_WAIT_MS)
            continue

        if session.answer_stay_signed_in():
            continue
        if session.dismiss_notice():
            continue
        if session.switch_to_password():
            continue

        if password_signin_unavailable(page):
            # Chặn theo IP, không phải việc của người: báo lỗi có dấu nhận biết
            # để tầng job đổi IP rồi chạy lại.
            raise MailLoginBlocked(PASSWORD_SIGNIN_UNAVAILABLE_MSG)

        if transient_ms_error(page):
            # Lỗi tạm thời do IP: đổi IP rồi thử lại, đừng bấm Next hoài.
            raise MailLoginBlocked(TRANSIENT_MS_ERROR_MSG)

        rate_limited = find_blocker(page)
        if rate_limited:
            raise MailLoginBlocked(
                f"Outlook đang hỏi {rate_limited} - việc này dành cho bạn, "
                "agent không tự xử lý"
            )

        if session.find_input():
            continue
        session.type_and_submit()

    # Hết giờ mà không vào được, cũng không dính blocker nào rõ ràng (2FA/
    # CAPTCHA/sai mật khẩu đã raise trước) - gần như luôn là IP chập chờn khiến
    # trang không tải xong. Đổi IP rồi thử lại thường qua.
    raise MailLoginBlocked(
        f"hết {timeout_seconds}s mà hộp thư {email} vẫn chưa mở - " + ROTATE_HINT
    )


def _stay_signed_in(page) -> bool:
    """Trả lời màn hình "Stay signed in?". Trả True nếu vừa bấm một nút."""
    text = _page_text(page)
    if "stay signed in" not in text and "duy trì đăng nhập" not in text:
        return False

    # Nút chính thống của màn hình cũ (#idSIButton9 = "Yes").
    button = _first_visible(page, ("#idSIButton9", "input[type='submit']"))
    if button is None:
        # Giao diện Fluent mới: bấm theo TÊN nút ("Yes"/"Có"...). KHÔNG dùng
        # selector `button[type='submit']` chung ở đây - trên form này nút khớp
        # đầu tiên lại là nút X đóng (id=close-button, data-testid=dismissIcon),
        # bấm vào thì treo ở "chờ điều hướng" rồi hết giờ.
        button = _first_by_name(page, ("Yes", "Có", "No", "Không"))
    if button is None:
        logger.warning("thấy 'Stay signed in?' nhưng không tìm ra nút nào")
        return False

    logger.info("hộp thư: trả lời 'Stay signed in?'")
    _click(button)
    return True


def sign_out(page) -> str:
    """Đăng xuất khỏi hộp thư, rồi dọn cookie.

    Hai lớp: gọi đúng địa chỉ
    đăng xuất để máy chủ huỷ phiên, rồi mới dọn cookie - chỉ dọn cookie thì
    phiên vẫn sống ở phía Microsoft.

    Không bao giờ ném lỗi: đăng xuất không xong cũng không đáng làm đổ việc.
    """
    try:
        page.goto(LOGOUT_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as exc:
        logger.warning("đăng xuất hộp thư không xong: %s", exc)
    try:
        page.context.clear_cookies()
    except Exception as exc:
        logger.debug("không dọn được cookie hộp thư: %s", exc)
    logger.info("đã đăng xuất hộp thư")
    return "đã đăng xuất hộp thư"

