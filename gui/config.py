# gui/config.py
from pathlib import Path

CURRENT_DIR = Path(__file__).parent

# Define the scripts to be managed by the GUI.
# Each entry is a dictionary with:
# - name: The display name for the tab and button.
# - script: The path to the python script to execute.
# - msg: The secret message to trigger the script via TCP socket.
SCRIPTS_CONFIG = [
    {
        "name": "1st Run",
        "script": str(CURRENT_DIR / "../client/client_run_1st.py"),
        "msg": b"RUN_SCRIPT_1ST"
    },
    {
        "name": "2nd Run",
        "script": str(CURRENT_DIR / "../client/client_run_2nd.py"),
        "msg": b"RUN_SCRIPT_2ND"
    },
    # You can add more scripts here, for example:
    {
        "name": "Test",
        "script": str(CURRENT_DIR / "../client/test_output.py"),
        "msg": b"RUN_SCRIPT_TEST"
    },
]