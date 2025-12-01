import tkinter as tk
from tkinter import messagebox
import traceback
from mediabrowser import MediaBrowser

def main():
    try:
        root = tk.Tk()

        # Set application icon if available
        try:
            root.iconbitmap('icon.ico')
        except:
            pass

        app = MediaBrowser(root)

        def on_closing():
            """Handle application closing"""
            try:
                if app.conn:
                    app.conn.close()
            except:
                pass
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()

    except Exception as e:
        messagebox.showerror("Fatal Error",
                             f"Application failed to start:\n\n{str(e)}\n\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    main()