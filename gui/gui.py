# listener_app.py
import sys
from pathlib import Path
 
from PySide6.QtCore import QObject, Signal, Slot, QProcess, QTimer, QProcessEnvironment, QEvent, Qt, QSettings
from PySide6.QtNetwork import QTcpServer, QHostAddress
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu, QMessageBox, QStyle, QTextEdit, QVBoxLayout, QWidget, QFontDialog, QTabWidget, QPushButton, QHBoxLayout
from PySide6.QtGui import QIcon, QAction, QTextCursor, QFont, QPalette

# --- Configuration ---
from config import SCRIPTS_CONFIG # Import the new configuration

HOST = QHostAddress.LocalHost
PORT = 54321  # Choose a port that is unlikely to be in use
PYTHON_EXECUTABLE = sys.executable # Use the same python interpreter that runs this script
CURRENT_SCRIPT_DIR = Path(__file__).parent
# ---------------------

class ScriptRunner(QObject):
    """Handles running external scripts, allowing for concurrent execution."""
    setup_error = Signal(str, str)      # script_id, message
    log_message = Signal(str, str)      # script_id, message
    started_message = Signal(str)       # script_id
    finished_message = Signal(str, str) # script_id, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.processes = {}  # script_id -> {process: QProcess, name: str}

    @Slot(str)
    def run_script(self, script_path_str):
        """Runs the target python script in a non-blocking way."""
        script_path = Path(script_path_str)
        script_id = str(script_path.absolute())

        if script_id in self.processes and self.processes[script_id]['process'].state() != QProcess.NotRunning:
            self.log_message.emit(script_id, "--- 脚本已在运行中 ---\n")
            return False

        if not script_path.exists():
            error_msg = f"Error: The script '{script_path_str}' was not found."
            print(error_msg)
            self.setup_error.emit(script_id, error_msg)
            return False

        print(f"Starting script: {PYTHON_EXECUTABLE} {script_id}")
        self.log_message.emit(script_id, f"--- 开始运行脚本: {script_path.name} ---\n")
        self.started_message.emit(script_id)
        
        process = QProcess()
        self.processes[script_id] = {'process': process, 'name': script_path.name}

        # 设置子进程的环境变量，强制其输出为UTF-8，解决中文乱码问题
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(env)

        # 连接信号和槽
        process.readyReadStandardOutput.connect(lambda: self.handle_stdout(script_id))
        process.readyReadStandardError.connect(lambda: self.handle_stderr(script_id))
        process.finished.connect(lambda code, status: self.on_finished(script_id, code, status))
        process.start(PYTHON_EXECUTABLE, [script_id])

        print(f"'{script_path_str}' has been launched.")
        return True

    def handle_stdout(self, script_id):
        if script_id in self.processes:
            process = self.processes[script_id]['process']
            data = process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
            self.log_message.emit(script_id, data)

    def handle_stderr(self, script_id):
        if script_id in self.processes:
            process = self.processes[script_id]['process']
            data = process.readAllStandardError().data().decode('utf-8', errors='ignore')
            self.log_message.emit(script_id, data)

    def on_finished(self, script_id, exit_code, exit_status):
        status_text = "正常退出" if exit_status == QProcess.NormalExit else "崩溃"
        script_name = self.processes[script_id]['name']
        self.log_message.emit(script_id, f"\n--- 脚本运行结束 (退出码: {exit_code}, 状态: {status_text}) ---\n")
        self.finished_message.emit(script_id, f"{script_name} 脚本运行结束 (退出码: {exit_code}, 状态: {status_text})")
        if script_id in self.processes:
            del self.processes[script_id]


class Server(QObject):
    """A simple TCP server that listens for a specific message."""
    trigger_script = Signal(str) # script_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self.on_new_connection)
        self.message_map = {config['msg']: config['script'] for config in SCRIPTS_CONFIG}

    def start(self):
        if not self._server.listen(HOST, PORT):
            print(f"Error: Unable to start server on port {PORT}.")
            return False
        print(f"Listening on {self._server.serverAddress().toString()}:{self._server.serverPort()}...")
        return True

    def stop(self):
        self._server.close()
        print("Server stopped.")

    @Slot()
    def on_new_connection(self):
        socket = self._server.nextPendingConnection()
        if socket:
            socket.readyRead.connect(lambda: self.on_ready_read(socket))
            socket.disconnected.connect(socket.deleteLater)
            print("Client connected.")

    def on_ready_read(self, socket):
        data = socket.readAll().data()
        print(f"Received data: {data}")
        if data in self.message_map:
            script_to_run = self.message_map[data]
            print(f"Message '{data.decode()}' received! Triggering script: {script_to_run}")
            self.trigger_script.emit(script_to_run)
            socket.write(f"OK: Triggered {Path(script_to_run).name}.\n".encode())
        else:
            socket.write(b"ERROR: Invalid message.\n")
        socket.disconnectFromHost()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("daemon")
        self.setGeometry(100, 100, 800, 600)

        # --- Settings ---
        self.settings = QSettings("bilibili2txt", "daemon_gui")

        # --- Main Widget and Layout ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # --- Tab Widget for multiple scripts ---
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        self.tabs_info = {} # script_id -> {log_display, button, index}

        for config in SCRIPTS_CONFIG:
            script_path = config['script']
            script_id = str(Path(script_path).absolute())
            tab_name = config['name']

            tab = QWidget()
            tab_layout = QVBoxLayout(tab)

            run_button = QPushButton(f"Run {tab_name}")
            run_button.clicked.connect(lambda _, s=script_path: self.runner.run_script(s))

            log_display = QTextEdit()
            log_display.setReadOnly(True)
            log_display.setLineWrapMode(QTextEdit.NoWrap)
            log_display.setStyleSheet("background-color: #F5F5DC;") # 设置米色背景

            tab_layout.addWidget(run_button)
            tab_layout.addWidget(log_display)

            index = self.tab_widget.addTab(tab, tab_name)
            self.tabs_info[script_id] = {"log_display": log_display, "button": run_button, "index": index}

        # --- Load settings after UI is created ---
        self.load_settings()

        # --- Menu Bar for Settings ---
        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu("设置")

        en_font_action = QAction("英文字体...", self)
        en_font_action.triggered.connect(lambda: self.select_font('en'))
        settings_menu.addAction(en_font_action)

        zh_font_action = QAction("中文字体...", self)
        zh_font_action.triggered.connect(lambda: self.select_font('zh'))
        settings_menu.addAction(zh_font_action)

        self.apply_fonts()

        # --- System Tray Icon ---
        self.tray_icon = QSystemTrayIcon(self)
        # You should create a 16x16 or 32x32 .ico or .png file for the icon
        icon_path = CURRENT_SCRIPT_DIR / "icon.png" 
        app_icon = None
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
        else:
            # Fallback to a standard icon if not found
            app_icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        
        self.setWindowIcon(app_icon)
        self.tray_icon.setIcon(app_icon)

        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.quit_application)

        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.setToolTip("Daemon is running.")
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        # --- Core Logic ---
        self.server = Server()
        self.runner = ScriptRunner()
        self.server.trigger_script.connect(self.runner.run_script)
        self.runner.setup_error.connect(self.show_error_message)
        self.runner.started_message.connect(self.mark_tab_as_running)
        self.runner.log_message.connect(self.append_log_message)
        self.runner.finished_message.connect(self.handle_script_finished)

        if not self.server.start():
            QMessageBox.critical(self, "Server Error", f"Could not start server on port {PORT}. The application will now exit.")
            # Use QTimer to exit cleanly after the message box is shown
            QTimer.singleShot(0, self.quit_application)

    @Slot(str, str)
    def append_log_message(self, script_id, message):
        if script_id not in self.tabs_info:
            print(f"Warning: Received log for unknown script_id: {script_id}")
            return

        log_display = self.tabs_info[script_id]["log_display"]

        # --- 智能滚动逻辑 ---
        # 检查滚动条是否在底部，以决定是否需要自动滚动
        scrollbar = log_display.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5 # -5 作为容差

        # --- 字体处理 ---
        # 获取保存的字体设置
        en_font = self.settings.value("logFont_en", QFont())
        zh_font = self.settings.value("logFont_zh", QFont())

        # # 根据用户请求，禁用自动切换标签页的功能
        # self.tab_widget.setCurrentWidget(log_display.parentWidget())

        # 获取文本光标并移动到文档末尾
        cursor = log_display.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 检查是否是行内更新（如tqdm进度条）
        if message.startswith('\r'):
            # 这是一个行内更新
            # 移动到当前块（行）的开始
            cursor.movePosition(QTextCursor.StartOfBlock)
            # 选中到文档末尾（即选中当前最后一行）
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            # 删除选中的文本
            cursor.removeSelectedText()
            # 插入新的、清理过的文本
            if message.endswith('\r\n'):
                # 如果是纯行内更新，没有换行符，则去掉末尾的\r\n
                message = message[1:-2]
            else:
                message = message[1:]  # 去掉开头的\r
            self.insert_formatted_text(cursor, message, en_font, zh_font)
        else:
            # 这是普通日志或进度条的最后一次输出（通常带'\n'）
            # 直接插入文本，保留其原始格式
            self.insert_formatted_text(cursor, message, en_font, zh_font)

        # 如果之前就在底部，则新消息到来后继续滚动到底部
        if is_at_bottom:
            log_display.ensureCursorVisible()

    @Slot()
    def select_font(self, lang):
        """Opens a font dialog to select font for English ('en') or Chinese ('zh')."""
        current_tab_widget = self.tab_widget.currentWidget()
        if not current_tab_widget: return
        log_display = current_tab_widget.findChild(QTextEdit)
        if not log_display: return

        setting_key = f"logFont_{lang}"
        dialog_title = "选择英文字体" if lang == 'en' else "选择中文字体"

        # 从设置中加载当前字体，如果不存在则使用默认字体
        current_font = self.settings.value(setting_key, QFont())

        ok, font = QFontDialog.getFont(current_font, self, dialog_title)
        if ok:
            self.settings.setValue(setting_key, font)
            self.apply_fonts()

    def load_settings(self):
        """Loads settings on application startup."""
        self.apply_fonts()

    def apply_fonts(self):
        """Applies the selected fonts to all log displays."""
        # 加载字体，如果未设置则使用默认值
        en_font = self.settings.value("logFont_en", QFont()) # Load saved font, or default if not found
        zh_font = self.settings.value("logFont_zh", QFont()) # Load saved font, or default if not found

        for info in self.tabs_info.values():
            log_display = info["log_display"]
            # 1. 设置基础字体为英文字体
            log_display.setFont(en_font)

            # 2. 重新渲染已有文本以应用中文字体
            # 获取所有现有文本，然后使用新的字体设置重新插入
            current_text = log_display.toPlainText()
            log_display.clear()
            cursor = log_display.textCursor()
            self.insert_formatted_text(cursor, current_text, en_font, zh_font)

    def insert_formatted_text(self, cursor, text, en_font, zh_font):
        """Inserts text into the QTextCursor, applying different fonts for Chinese and non-Chinese characters."""
        import re
        # 正则表达式匹配中文字符
        chinese_char_pattern = re.compile(r'[\u4e00-\u9fa5]')

        # 将文本转换为HTML，为中文字符包裹特定的字体span
        html_parts = []
        for char in text:
            if chinese_char_pattern.match(char):
                # 对中文字符使用中文字体
                html_parts.append(f'<span style="font-family: \'{zh_font.family()}\';">{char}</span>')
            else:
                # 对非中文字符使用默认（英文）字体
                html_parts.append(char)
        
        # 插入HTML
        cursor.insertHtml("".join(html_parts).replace('\n', '<br>'))

    def show_error_message(self, script_id, message):
        self.tray_icon.showMessage("Error", message, QSystemTrayIcon.Critical)
        QApplication.beep()

    @Slot(str)
    def mark_tab_as_running(self, script_id):
        """Marks the tab corresponding to the script_id as running (e.g., red text)."""
        if script_id in self.tabs_info:
            index = self.tabs_info[script_id]['index']
            self.tab_widget.tabBar().setTabTextColor(index, Qt.red)

    def mark_tab_as_finished(self, script_id):
        """Resets the tab color to default when the script finishes."""
        if script_id in self.tabs_info:
            index = self.tabs_info[script_id]['index']
            default_color = QApplication.palette().color(QPalette.WindowText)
            self.tab_widget.tabBar().setTabTextColor(index, default_color)

    @Slot(QSystemTrayIcon.ActivationReason)
    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation to show window on single-click."""
        # QSystemTrayIcon.Trigger corresponds to a single left-click.
        if reason == QSystemTrayIcon.Trigger:
            if self.isMinimized():
                self.setWindowState(self.windowState() & ~Qt.WindowMinimized) # 恢复窗口状态
            elif not self.isVisible():
                self.show()
            self.raise_() # 提升到顶层
            self.activateWindow() # 激活窗口

    def changeEvent(self, event):
        """Override changeEvent to handle minimizing to tray."""
        if event.type() == QEvent.WindowStateChange:
            # Check if the window was minimized
            if self.windowState() & Qt.WindowMinimized:
                event.ignore()  # Ignore the default minimize event
                self.hide()     # Hide the window
                return
        super().changeEvent(event)

    def closeEvent(self, event):
        """When the user closes the window (clicks X), quit the application."""
        self.quit_application()
        event.accept()

    @Slot(str, str)
    def handle_script_finished(self, script_id, message):
        """Handles all actions when a script is finished: reset tab color and show notification."""
        self.mark_tab_as_finished(script_id)
        self.tray_icon.showMessage("任务完成", message, QSystemTrayIcon.Information, 5000)
        QApplication.beep()

    def quit_application(self):
        """Properly clean up and exit the application."""
        self.server.stop()
        self.tray_icon.hide()
        QApplication.quit()


if __name__ == "__main__":
    # On Windows, set the AppUserModelID to ensure the taskbar icon is correct.
    # This must be done before any windows are created.
    if sys.platform == "win32":
        import ctypes
        myappid = 'my.bilibili2txt.daemon.1.0'  # arbitrary unique string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QApplication(sys.argv)
    # Prevent quitting when the last window is closed
    app.setQuitOnLastWindowClosed(False) 
    
    main_win = MainWindow()
    
    # Check for the --hide argument. If present, start minimized to tray.
    # Otherwise, show the window.
    if "--hide" not in sys.argv:
        main_win.show()
    
    sys.exit(app.exec())
