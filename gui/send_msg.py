# send_msg.py
import socket
import argparse
import sys

# --- Configuration (must match listener_app.py) ---
HOST = "127.0.0.1"  # Standard loopback interface address (localhost)
PORT = 54321        # The port the server is listening on
# ----------------------------------------------------

def send_trigger_message(message):
    """Connects to the listener app and sends the trigger message."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(message.encode('utf-8'))
            response = s.recv(1024)
            print(f"Sent message '{message}', received response: {response.decode('utf-8').strip()}")
    except ConnectionRefusedError:
        print(f"Error: Connection refused. Is the listener_app.py running on port {PORT}?")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Send a trigger message to the listener application.",
        epilog="Example: python send_msg.py RUN_SCRIPT_1ST"
    )
    parser.add_argument("message", help="The secret message to send (e.g., 'RUN_SCRIPT_1ST', 'RUN_SCRIPT_PUSH_DATA')")
    args = parser.parse_args()

    send_trigger_message(args.message)