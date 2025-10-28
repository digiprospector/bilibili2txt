' run_1st_background.vbs
' This script calls the send_msg.py script to trigger the first run task.
' It runs the command in the background without opening a command window.

Set WshShell = CreateObject("WScript.Shell")
command = "python.exe gui\send_msg.py RUN_SCRIPT_2ND"
WshShell.Run command, 0, False
Set WshShell = Nothing