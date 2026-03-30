Set WshShell = CreateObject("WScript.Shell")
Set shortcut = WshShell.CreateShortcut(WshShell.SpecialFolders("Startup") & "\Meeting Recorder.lnk")
shortcut.TargetPath = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Documents\Agents\Recorder\.venv\Scripts\pythonw.exe"
shortcut.Arguments = "tray.py"
shortcut.WorkingDirectory = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Documents\Agents\Recorder"
shortcut.Description = "Meeting Recorder - System Tray"
shortcut.Save
WScript.Echo "Startup shortcut created."
