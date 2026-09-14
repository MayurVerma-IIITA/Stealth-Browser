# ```python
import sys
import os
import time
import ctypes
import io
import base64
import json
import urllib.error
import urllib.request

# ---------------------------------------------------------
# Qt configuration
# ---------------------------------------------------------

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

from PyQt6.QtCore import (
    Qt,
    QUrl,
    QPoint,
    QTimer,
    pyqtSignal,
    QObject,
    QByteArray,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLineEdit,
    QLabel,
    QPushButton,
    QStackedWidget,
    QComboBox,
)
from PyQt6.QtGui import QImage, QClipboard
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEnginePage,
)

from cryptography.hazmat.primitives import serialization

import keyboard
import pyautogui
from PIL import ImageGrab


# ---------------------------------------------------------
# Windows constants
# ---------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000


# ---------------------------------------------------------
# Application configuration
# ---------------------------------------------------------

SESSION_DURATION_SECONDS = 3 * 60 * 60

DEFAULT_URL = "https://google.com"

DEFAULT_WIDTH = 950
DEFAULT_HEIGHT = 650
DEFAULT_OPACITY = 0.98

TOKEN_FILE = "token_config.txt"

LICENSE_SERVER_URL = os.environ.get(
    "STEALTH_LICENSE_SERVER_URL",
    "https://stealth-browser-pj9d.onrender.com",
)

LICENSE_REQUEST_TIMEOUT_SECONDS = 10

OFFLINE_LICENSE_FILE = "license.lic"

OFFLINE_LICENSE_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAq3K64lFagiBgQacuXuBmVFdn895Fk/S+i+XQudn+/RM=
-----END PUBLIC KEY-----
"""


# ---------------------------------------------------------
# Windows API
# ---------------------------------------------------------

user32 = ctypes.windll.user32

user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetForegroundWindow.restype = ctypes.c_bool


# ---------------------------------------------------------
# Global hotkey → Qt signal bridge
# ---------------------------------------------------------

class HotkeySignaler(QObject):
    """
    Bridges global keyboard callbacks into the Qt GUI thread.
    """

    trigger_hide = pyqtSignal()
    trigger_screenshot = pyqtSignal()
    trigger_clickthrough = pyqtSignal()
    trigger_autotyper = pyqtSignal()

    trigger_w_grow = pyqtSignal()
    trigger_w_shrink = pyqtSignal()

    trigger_h_grow = pyqtSignal()
    trigger_h_shrink = pyqtSignal()

    trigger_opacity_up = pyqtSignal()
    trigger_opacity_down = pyqtSignal()

    trigger_quit = pyqtSignal()


# ---------------------------------------------------------
# Main application
# ---------------------------------------------------------

class StealthBrowser(QMainWindow):

    def __init__(self):
        super().__init__()

        # ---------------------------------------------
        # Runtime state
        # ---------------------------------------------

        self.drag_position = QPoint()

        self.is_clickthrough = False

        self.copied_stealth_text = ""

        self.autotyper_enabled = True

        self.active_master_token = "ACCESS3H"

        # HWND of the application that had focus before
        # this application took focus.
        self.previous_foreground_hwnd = None

        # ---------------------------------------------
        # Application storage
        # ---------------------------------------------

        self.profile_dir = os.path.join(
            os.getcwd(),
            "stealth_profile",
        )

        os.makedirs(
            self.profile_dir,
            exist_ok=True,
        )

        # ---------------------------------------------
        # Initialization
        # ---------------------------------------------

        self.load_token_config()

        self.configure_browser_profile()

        self.init_window_flags()

        self.init_ui()

        self.license_expiry_timestamp = None

        self.license_timer = QTimer(
            self
        )

        self.license_timer.setInterval(
            1000
        )

        self.license_timer.timeout.connect(
            self.update_license_timer
        )

        self.init_async_hotkeys()

        self.check_token_lifecycle()

    # =====================================================
    # TOKEN CONFIGURATION
    # =====================================================

    def load_token_config(self):
        """
        Load the local activation token.

        If token_config.txt does not exist,
        create it with the default token.
        """

        config_path = os.path.join(
            os.getcwd(),
            TOKEN_FILE,
        )

        if not os.path.exists(config_path):

            with open(
                config_path,
                "w",
                encoding="utf-8",
            ) as file:
                file.write("ACCESS3H")

            return

        try:

            with open(
                config_path,
                "r",
                encoding="utf-8",
            ) as file:

                content = file.read().strip()

                if content:
                    self.active_master_token = content

        except OSError:
            pass

    # =====================================================
    # WEB ENGINE PROFILE
    # =====================================================

    def configure_browser_profile(self):
        """
        Create one persistent Qt WebEngine profile.

        Cookies, local storage and browser data are
        maintained under the application's profile directory.
        """

        browser_data_dir = os.path.join(
            self.profile_dir,
            "browser_data",
        )

        self.storage_profile = QWebEngineProfile(
            "StealthStorageProfile",
            self,
        )

        self.storage_profile.setPersistentStoragePath(
            browser_data_dir
        )

        self.storage_profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )

        settings = self.storage_profile.settings()

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            True,
        )

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            True,
        )

        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )

    # =====================================================
    # WINDOW CONFIGURATION
    # =====================================================

    def init_window_flags(self):

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.resize(
            DEFAULT_WIDTH,
            DEFAULT_HEIGHT,
        )

        self.setWindowOpacity(
            DEFAULT_OPACITY
        )

    # =====================================================
    # USER INTERFACE
    # =====================================================

    def init_ui(self):

        self.central_stack = QStackedWidget(self)

        self.setCentralWidget(
            self.central_stack
        )

        # -------------------------------------------------
        # TOKEN SCREEN
        # -------------------------------------------------

        self.token_widget = QWidget()

        self.token_widget.setStyleSheet(
            """
            background-color: #1e2227;
            color: white;
            font-family: Arial;
            """
        )

        token_layout = QVBoxLayout(
            self.token_widget
        )

        token_layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        token_title = QLabel(
            "STEALTH ENVIRONMENT GATEWAY"
        )

        token_title.setStyleSheet(
            """
            font-size: 16px;
            font-weight: bold;
            color: #e06c75;
            margin-bottom: 5px;
            """
        )

        token_layout.addWidget(
            token_title
        )

        token_help = QLabel(
            "Provide your configured 3-Hour verification key token below:"
        )

        token_help.setStyleSheet(
            """
            font-size: 12px;
            color: #abb2bf;
            margin-bottom: 15px;
            """
        )

        token_layout.addWidget(
            token_help
        )

        self.token_input = QLineEdit()

        self.token_input.setPlaceholderText(
            "Enter active passcode token..."
        )

        self.token_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )

        self.token_input.setStyleSheet(
            """
            background-color: #282c34;
            border: 1px solid #4b5263;
            padding: 8px;
            border-radius: 4px;
            color: white;
            font-size: 13px;
            """
        )

        self.token_input.returnPressed.connect(
            self.validate_user_token
        )

        token_layout.addWidget(
            self.token_input
        )

        submit_btn = QPushButton(
            "Unlock Secure Environment"
        )

        submit_btn.setStyleSheet(
            """
            background-color: #98c379;
            color: #282c34;
            font-weight: bold;
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            margin-top: 10px;
            """
        )

        submit_btn.clicked.connect(
            self.validate_user_token
        )

        token_layout.addWidget(
            submit_btn
        )

        self.token_error = QLabel("")

        self.token_error.setStyleSheet(
            """
            color: #e06c75;
            margin-top: 10px;
            font-size: 12px;
            """
        )

        token_layout.addWidget(
            self.token_error
        )

        self.central_stack.addWidget(
            self.token_widget
        )

        # -------------------------------------------------
        # BROWSER SCREEN
        # -------------------------------------------------

        self.browser_widget = QWidget()

        browser_layout = QVBoxLayout(
            self.browser_widget
        )

        browser_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        browser_layout.setSpacing(0)

        # -------------------------------------------------
        # TOP BAR
        # -------------------------------------------------

        top_bar = QWidget()

        top_bar.setStyleSheet(
            """
            background-color: rgba(40, 44, 52, 250);
            color: white;
            """
        )

        top_bar_layout = QHBoxLayout(
            top_bar
        )

        top_bar_layout.setContentsMargins(
            6,
            4,
            6,
            4,
        )

        # Back button

        self.btn_back = QPushButton("◀")

        self.btn_back.setStyleSheet(
            self.button_style()
        )

        top_bar_layout.addWidget(
            self.btn_back
        )

        # Forward button

        self.btn_next = QPushButton("▶")

        self.btn_next.setStyleSheet(
            self.button_style()
        )

        top_bar_layout.addWidget(
            self.btn_next
        )

        # Address bar

        self.address_bar = QLineEdit()

        self.address_bar.setText(
            DEFAULT_URL
        )

        self.address_bar.setStyleSheet(
            """
            background-color: #21252b;
            color: white;
            border: 1px solid #4b5263;
            border-radius: 4px;
            padding: 4px;
            font-size: 13px;
            """
        )

        self.address_bar.returnPressed.connect(
            self.navigate_to_url
        )

        top_bar_layout.addWidget(
            self.address_bar
        )

        # Auto typer

        self.btn_toggle_typer = QPushButton(
            "Auto-Typer: ON"
        )

        self.btn_toggle_typer.setStyleSheet(
            self.autotyper_button_style(True)
        )

        self.btn_toggle_typer.clicked.connect(
            self.switch_autotyper_state
        )

        top_bar_layout.addWidget(
            self.btn_toggle_typer
        )

        # Speed selector

        self.speed_combo = QComboBox()

        self.speed_combo.addItems(
            [
                "Speed: Normal",
                "Speed: Fast",
                "Speed: Slow",
            ]
        )

        self.speed_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #282c34;
                color: white;
                border: 1px solid #4b5263;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                font-weight: bold;
            }
            """
        )

        top_bar_layout.addWidget(
            self.speed_combo
        )

        # Screenshot

        btn_snap_action = QPushButton(
            "Copy Screenshot"
        )

        btn_snap_action.setStyleSheet(
            """
            background-color: #61afef;
            color: #282c34;
            font-weight: bold;
            border: none;
            padding: 4px 8px;
            border-radius: 3px;
            """
        )

        btn_snap_action.clicked.connect(
            self.execute_full_screenshot
        )

        top_bar_layout.addWidget(
            btn_snap_action
        )

        # Drag label

        drag_label = QLabel(
            " ☰ DRAG "
        )

        drag_label.setStyleSheet(
            """
            color: #abb2bf;
            font-size: 10px;
            font-weight: bold;
            padding-left: 4px;
            """
        )

        top_bar_layout.addWidget(
            drag_label
        )

        self.license_timer_label = QLabel(
            "License: --:--"
        )

        self.license_timer_label.setStyleSheet(
            """
            color: #98c379;
            font-size: 11px;
            font-weight: bold;
            padding: 0 6px;
            """
        )

        top_bar_layout.addWidget(
            self.license_timer_label
        )

        # Close button

        close_button = QPushButton(
            "X"
        )

        close_button.setFixedSize(
            24,
            24,
        )

        close_button.setStyleSheet(
            """
            background-color: #e06c75;
            color: white;
            font-weight: bold;
            border: none;
            border-radius: 3px;
            """
        )

        close_button.clicked.connect(
            self.close
        )

        top_bar_layout.addWidget(
            close_button
        )

        browser_layout.addWidget(
            top_bar
        )

        # -------------------------------------------------
        # WEB ENGINE
        # -------------------------------------------------

        self.browser = QWebEngineView()

        self.browser_page = QWebEnginePage(
            self.storage_profile,
            self.browser,
        )

        self.browser.setPage(
            self.browser_page
        )

        self.browser.setUrl(
            QUrl(
                self.address_bar.text()
            )
        )

        self.browser.urlChanged.connect(
            lambda url:
            self.address_bar.setText(
                url.toString()
            )
        )

        self.browser.selectionChanged.connect(
            self.sync_highlighted_text
        )

        browser_layout.addWidget(
            self.browser
        )

        self.central_stack.addWidget(
            self.browser_widget
        )

        # Button connections

        self.btn_back.clicked.connect(
            self.browser.back
        )

        self.btn_next.clicked.connect(
            self.browser.forward
        )

    # =====================================================
    # STYLES
    # =====================================================

    @staticmethod
    def button_style():

        return """
        background-color: #3e4451;
        color: white;
        border: none;
        padding: 4px 8px;
        font-weight: bold;
        border-radius: 3px;
        """

    @staticmethod
    def autotyper_button_style(enabled):

        if enabled:

            return """
            background-color: #98c379;
            color: #282c34;
            font-weight: bold;
            border: none;
            padding: 4px 8px;
            border-radius: 3px;
            """

        return """
        background-color: #e06c75;
        color: white;
        font-weight: bold;
        border: none;
        padding: 4px 8px;
        border-radius: 3px;
        """

    # =====================================================
    # GLOBAL HOTKEYS
    # =====================================================

    def init_async_hotkeys(self):

        self.hotkey_signaler = HotkeySignaler()

        self.hotkey_signaler.trigger_hide.connect(
            self.toggle_visibility
        )

        self.hotkey_signaler.trigger_screenshot.connect(
            self.execute_full_screenshot
        )

        self.hotkey_signaler.trigger_clickthrough.connect(
            self.toggle_mouse_clickthrough
        )

        self.hotkey_signaler.trigger_autotyper.connect(
            self.execute_auto_typer
        )

        self.hotkey_signaler.trigger_quit.connect(
            self.close
        )

        self.hotkey_signaler.trigger_w_grow.connect(
            lambda:
            self.resize(
                self.width() + 50,
                self.height(),
            )
        )

        self.hotkey_signaler.trigger_w_shrink.connect(
            lambda:
            self.resize(
                max(300, self.width() - 50),
                self.height(),
            )
        )

        self.hotkey_signaler.trigger_h_grow.connect(
            lambda:
            self.resize(
                self.width(),
                self.height() + 50,
            )
        )

        self.hotkey_signaler.trigger_h_shrink.connect(
            lambda:
            self.resize(
                self.width(),
                max(250, self.height() - 50),
            )
        )

        self.hotkey_signaler.trigger_opacity_up.connect(
            self.increase_opacity
        )

        self.hotkey_signaler.trigger_opacity_down.connect(
            self.decrease_opacity
        )

        keyboard.add_hotkey(
            "ctrl+shift+h",
            lambda:
            self.hotkey_signaler.trigger_hide.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+s",
            lambda:
            self.hotkey_signaler.trigger_screenshot.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+t",
            lambda:
            self.hotkey_signaler.trigger_clickthrough.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+a",
            lambda:
            self.hotkey_signaler.trigger_autotyper.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+q",
            lambda:
            self.hotkey_signaler.trigger_quit.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+right",
            lambda:
            self.hotkey_signaler.trigger_w_grow.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+left",
            lambda:
            self.hotkey_signaler.trigger_w_shrink.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+up",
            lambda:
            self.hotkey_signaler.trigger_opacity_up.emit(),
        )

        keyboard.add_hotkey(
            "ctrl+shift+down",
            lambda:
            self.hotkey_signaler.trigger_opacity_down.emit(),
        )

    # =====================================================
    # NAVIGATION
    # =====================================================

    def navigate_to_url(self):

        address = (
            self.address_bar
            .text()
            .strip()
        )

        if not address:
            return

        if not address.startswith(
            (
                "http://",
                "https://",
            )
        ):
            address = "https://" + address

        self.browser.setUrl(
            QUrl.fromUserInput(address)
        )

    # =====================================================
    # CLIPBOARD
    # =====================================================

    def send_image_to_clipboard(
        self,
        pil_img,
    ):

        byte_arr = io.BytesIO()

        try:

            pil_img.save(
                byte_arr,
                format="PNG",
            )

            qbyte_data = QByteArray(
                byte_arr.getvalue()
            )

            q_img = QImage()

            if not q_img.loadFromData(
                qbyte_data,
                "PNG",
            ):
                return

            clipboard = QApplication.clipboard()

            clipboard.setImage(
                q_img,
                QClipboard.Mode.Clipboard,
            )

        finally:

            byte_arr.close()

    # =====================================================
    # SCREENSHOT
    # =====================================================

    def execute_full_screenshot(self):

        was_visible = self.isVisible()

        if was_visible:

            self.hide()

            QApplication.processEvents()

            time.sleep(0.25)

        try:

            screenshot = ImageGrab.grab()

            self.send_image_to_clipboard(
                screenshot
            )

        finally:

            if was_visible:

                self.show()

                self.raise_()

                self.activateWindow()

    # =====================================================
    # SELECTION
    # =====================================================

    def sync_highlighted_text(self):

        try:

            self.copied_stealth_text = (
                self.browser.selectedText()
            )

        except Exception:

            self.copied_stealth_text = ""

    # =====================================================
    # AUTO-TYPER TOGGLE
    # =====================================================

    def switch_autotyper_state(self):

        self.autotyper_enabled = (
            not self.autotyper_enabled
        )

        self.btn_toggle_typer.setText(
            "Auto-Typer: ON"
            if self.autotyper_enabled
            else "Auto-Typer: OFF"
        )

        self.btn_toggle_typer.setStyleSheet(
            self.autotyper_button_style(
                self.autotyper_enabled
            )
        )

    # =====================================================
    # AUTO-TYPER
    # =====================================================

    def execute_auto_typer(self):

        if (
            not self.autotyper_enabled
            or not self.copied_stealth_text
        ):
            return

        # -------------------------------------------------
        # Determine typing speed
        # -------------------------------------------------

        speed_mode = (
            self.speed_combo.currentText()
        )

        if "Fast" in speed_mode:

            delay = 0.01

        elif "Slow" in speed_mode:

            delay = 0.15

        else:

            delay = 0.05

        # -------------------------------------------------
        # Capture the currently focused application
        # before hiding this application.
        # -------------------------------------------------

        self.previous_foreground_hwnd = (
            user32.GetForegroundWindow()
        )

        # Do not use the Shell window as the target.
        #
        # Instead, remember the actual foreground
        # application and restore focus to it.
        #
        # This is more reliable for targets such as
        # Notepad, VS Code, browsers, terminals, etc.
        # -------------------------------------------------

        self.hide()

        QApplication.processEvents()

        time.sleep(0.15)

        target_hwnd = (
            self.previous_foreground_hwnd
        )

        if target_hwnd:

            try:

                user32.SetForegroundWindow(
                    target_hwnd
                )

            except Exception:

                pass

        time.sleep(0.15)

        # -------------------------------------------------
        # Send selected text
        # -------------------------------------------------

        try:

            pyautogui.write(
                self.copied_stealth_text,
                interval=delay,
            )

        finally:

            # -------------------------------------------------
            # Restore our application
            # -------------------------------------------------

            self.show()

            self.raise_()

            self.activateWindow()

    # =====================================================
    # TOKEN LIFECYCLE
    # =====================================================

    def verify_offline_license(self):

        license_path = os.path.join(
            os.getcwd(),
            OFFLINE_LICENSE_FILE,
        )

        try:

            with open(
                license_path,
                "r",
                encoding="utf-8",
            ) as license_file:

                license_document = json.load(
                    license_file
                )

            payload = license_document["payload"]
            signature = base64.b64decode(
                license_document["signature"]
            )
            public_key = serialization.load_pem_public_key(
                OFFLINE_LICENSE_PUBLIC_KEY.encode(
                    "ascii"
                )
            )
            canonical_payload = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

            public_key.verify(
                signature,
                canonical_payload,
            )

            self.license_expiry_timestamp = float(
                payload["expires_at"]
            )

            return time.time() < self.license_expiry_timestamp

        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ):

            self.license_expiry_timestamp = None

            return False

    def start_license_timer(self, expiry_timestamp):

        self.license_expiry_timestamp = float(
            expiry_timestamp
        )

        self.update_license_timer()

        self.license_timer.start()

    def update_license_timer(self):

        if self.license_expiry_timestamp is None:
            return

        remaining_seconds = int(
            self.license_expiry_timestamp
            - time.time()
            + 0.999
        )

        if remaining_seconds <= 0:

            self.license_timer.stop()

            self.license_timer_label.setText(
                "License: EXPIRED"
            )

            self.central_stack.setCurrentIndex(
                0
            )

            return

        minutes, seconds = divmod(
            remaining_seconds,
            60,
        )

        self.license_timer_label.setText(
            f"License: {minutes:02d}:{seconds:02d}"
        )

    def request_license(self, token):

        request_body = json.dumps(
            {
                "token": token,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{LICENSE_SERVER_URL}/activate",
            data=request_body,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=LICENSE_REQUEST_TIMEOUT_SECONDS,
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

                if result.get("valid"):
                    return result

        except (
            OSError,
            ValueError,
            urllib.error.HTTPError,
        ):

            pass

        return None

    def check_token_lifecycle(self):

        if self.verify_offline_license():

            self.start_license_timer(
                self.license_expiry_timestamp
            )

            self.central_stack.setCurrentIndex(
                1
            )

            return

        license_result = self.request_license(
            self.active_master_token
        )

        if license_result is not None:

            self.start_license_timer(
                license_result["expires_at"]
            )

            self.central_stack.setCurrentIndex(
                1
            )

            return

        self.central_stack.setCurrentIndex(
            0
        )

    # =====================================================
    # TOKEN VALIDATION
    # =====================================================

    def validate_user_token(self):
        entered_token = (
            self.token_input
            .text()
            .strip()
        )

        license_result = self.request_license(
            entered_token
        )

        if license_result is not None:

            self.start_license_timer(
                license_result["expires_at"]
            )

            ts_file = os.path.join(
                self.profile_dir,
                ".session_ts",
            )

            try:

                with open(
                    ts_file,
                    "w",
                    encoding="utf-8",
                ) as session_file:

                    session_file.write(
                        str(time.time())
                    )

                self.token_error.clear()

                self.central_stack.setCurrentIndex(
                    1
                )

                self.browser.setUrl(
                    QUrl(DEFAULT_URL)
                )

            except OSError:

                self.token_error.setText(
                    "Unable to create session file."
                )

        else:

            self.token_error.setText(
                "Access token verification check failed."
            )

    # =====================================================
    # VISIBILITY
    # =====================================================

    def toggle_visibility(self):

        if self.isVisible():

            self.hide()

        else:

            self.show()

            self.raise_()

            self.activateWindow()

    # =====================================================
    # CLICK-THROUGH
    # =====================================================

    def toggle_mouse_clickthrough(self):

        hwnd = int(self.winId())

        styles = user32.GetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
        )

        if not self.is_clickthrough:

            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                styles
                | WS_EX_TRANSPARENT
                | WS_EX_LAYERED,
            )

            self.is_clickthrough = True

            self.setWindowOpacity(0.20)

        else:

            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                styles & ~WS_EX_TRANSPARENT,
            )

            self.is_clickthrough = False

            self.setWindowOpacity(
                DEFAULT_OPACITY
            )

    # =====================================================
    # OPACITY
    # =====================================================

    def increase_opacity(self):

        current = self.windowOpacity()

        if current < 1.0:

            self.setWindowOpacity(
                min(
                    1.0,
                    current + 0.05,
                )
            )

    def decrease_opacity(self):

        current = self.windowOpacity()

        if current > 0.20:

            self.setWindowOpacity(
                max(
                    0.20,
                    current - 0.05,
                )
            )

    # =====================================================
    # WINDOW DRAG
    # =====================================================

    def mousePressEvent(self, event):

        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):

            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )

            event.accept()

    def mouseMoveEvent(self, event):

        if (
            event.buttons()
            & Qt.MouseButton.LeftButton
        ):

            self.move(
                event.globalPosition().toPoint()
                - self.drag_position
            )

            event.accept()

    # =====================================================
    # CLEAN SHUTDOWN
    # =====================================================

    def closeEvent(self, event):

        try:

            keyboard.unhook_all()

        except Exception:

            pass

        event.accept()


# =========================================================
# APPLICATION ENTRY POINT
# =========================================================

def main():

    mutex = ctypes.windll.kernel32.CreateMutexW(
        None,
        False,
        "Local\\StealthBrowserSingleInstance",
    )

    if (
        ctypes.windll.kernel32.GetLastError()
        == 183
    ):
        ctypes.windll.kernel32.CloseHandle(
            mutex
        )

        return 0

    app = QApplication(sys.argv)

    window = StealthBrowser()

    window.show()

    exit_code = app.exec()

    ctypes.windll.kernel32.CloseHandle(
        mutex
    )

    return exit_code


if __name__ == "__main__":

    sys.exit(main())

