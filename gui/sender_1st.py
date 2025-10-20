# sender.py
import socket

# --- Configuration (must match listener_app.py) ---
HOST = "127.0.0.1"  # Standard loopback interface address (localhost)
PORT = 54321        # The port the server is listening on
SECRET_MESSAGE = b"RUN_SCRIPT_1ST"
# ----------------------------------------------------

def send_trigger_message():
    """Connects to the listener app and sends the trigger message."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(SECRET_MESSAGE)
            response = s.recv(1024)
            print(f"Sent message, received response: {response.decode('utf-8').strip()}")
    except ConnectionRefusedError:
        print(f"Error: Connection refused. Is the listener_app.py running on port {PORT}?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    send_trigger_message()
