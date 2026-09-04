' Launch Helper Control with no console window.
' Mirrors assistant_toggle.vbs: wscript -> pythonw -> tkinter.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\User\Documents\telegram-agent-aws\worker"
sh.Run """C:\Users\User\Documents\llm-agent-test\assistant\venv\Scripts\pythonw.exe"" helper_control.py", 0, False
