# listener_app.py
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QProcess, QTimer, QProcessEnvironment, QEvent, Qt
from PySide6.QtNetwork import QTcpServer, QHostAddress
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu, QMessageBox, QStyle, QTextEdit, QVBoxLayout, QWidget
from PySide6.QtGui import QIcon, QAction

# --- Configuration ---
HOST = QHostAddress.LocalHost
PORT = 54321  # Choose a port that is unlikely to be in use
SECRET_MESSAGE_1ST = b"RUN_SCRIPT_1ST"
SECRET_MESSAGE_2ND = b"RUN_SCRIPT_2ND"
PYTHON_EXECUTABLE = sys.executable # Use the same python interpreter that runs this script
CURRENT_SCRIPT_DIR = Path(__file__).parent
SCRIPT_1ST = CURRENT_SCRIPT_DIR / "../client/client_run_1st.py"
SCRIPT_2ND = CURRENT_SCRIPT_DIR / "../client/client_run_2nd.py"
# ---------------------

class ScriptRunner(QObject):
    """Handles running the external script."""
    setup_error = Signal(str)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None

    @Slot(str)
    def run_script(self, script_to_run):
        """Runs the target python script in a non-blocking way."""
        if self.process and self.process.state() != QProcess.NotRunning:
            self.log_message.emit("--- 脚本已在运行中 ---\n")
            return

        script_path = Path(script_to_run)
        if not script_path.exists():
            error_msg = f"Error: The script '{script_to_run}' was not found."
            print(error_msg)
            self.setup_error.emit(error_msg)
            return

        print(f"Starting script: {PYTHON_EXECUTABLE} {script_path.absolute()}")
        self.log_message.emit(f"--- 开始运行脚本: {script_path.name} ---\n")
        self.process = QProcess()

        # 设置子进程的环境变量，强制其输出为UTF-8，解决中文乱码问题
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)

        # 连接信号和槽
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.on_finished)
        self.process.start(PYTHON_EXECUTABLE, [str(script_path.absolute())])

        print(f"'{script_to_run}' has been launched.")

    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        self.log_message.emit(data)

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        self.log_message.emit(data)

    def on_finished(self, exit_code, exit_status):
        status_text = "正常退出" if exit_status == QProcess.NormalExit else "崩溃"
        self.log_message.emit(f"\n--- 脚本运行结束 (退出码: {exit_code}, 状态: {status_text}) ---\n")
        self.process = None


class Server(QObject):
    """A simple TCP server that listens for a specific message."""
    trigger_script = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self.on_new_connection)

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
        if data == SECRET_MESSAGE_1ST:
            print(f"Message '{data.decode()}' received! Triggering script 1.")
            self.trigger_script.emit(str(SCRIPT_1ST))
            socket.write(b"OK: Script 1 triggered.\n")
        elif data == SECRET_MESSAGE_2ND:
            print(f"Message '{data.decode()}' received! Triggering script 2.")
            self.trigger_script.emit(str(SCRIPT_2ND))
            socket.write(b"OK: Script 2 triggered.\n")
        else:
            socket.write(b"ERROR: Invalid message.\n")
        socket.disconnectFromHost()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("daemon")
        self.setGeometry(100, 100, 600, 400)

        # --- Main Widget and Layout ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # --- Log Display ---
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self.log_display)

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
        self.runner.log_message.connect(self.append_log_message)

        if not self.server.start():
            QMessageBox.critical(self, "Server Error", f"Could not start server on port {PORT}. The application will now exit.")
            # Use QTimer to exit cleanly after the message box is shown
            QTimer.singleShot(0, self.quit_application)

    def append_log_message(self, message):
        self.log_display.append(message.strip())

    def show_error_message(self, message):
        self.tray_icon.showMessage("Error", message, QSystemTrayIcon.Critical)

    @Slot(QSystemTrayIcon.ActivationReason)
    def on_tray_icon_activated(self, reason):
        """Handle tray icon activation to show window on double-click."""
        if reason == QSystemTrayIcon.DoubleClick:
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
    # The window is not shown on startup, it's minimized to the tray.
    # The user can open it from the tray icon menu.
    
    sys.exit(app.exec())
