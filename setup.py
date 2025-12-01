import PyInstaller.__main__

additional_files = [
    ('config.py', '.'),
    ('config_dialog.py', '.'),
]

# Create PyInstaller command
args = [
    'main.py',
    '--name=FDWH Collection Viewer',
    '--onefile',
    '--windowed',
    '--icon=icon.ico',
    '--add-data=config.py;.',
    '--add-data=config_dialog.py;.',
    '--hidden-import=PIL._tkinter_finder',
    '--hidden-import=psycopg2',
    '--hidden-import=PIL',
    '--hidden-import=PIL.Image',
    '--hidden-import=PIL.ImageTk',
    '--hidden-import=PIL.ImageOps',
    '--collect-all=PIL',
    '--clean',
]

PyInstaller.__main__.run(args)
