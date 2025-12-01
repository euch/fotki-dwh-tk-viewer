import tkinter as tk
from tkinter import ttk, messagebox
import psycopg2
from psycopg2 import OperationalError, Error

class ConfigDialog:
    def __init__(self, parent, config):
        self.parent = parent
        self.config = config
        self.dialog = None
        self.result = None

    def show(self):
        """Show configuration dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Configuration")
        self.dialog.geometry("600x400")  # Reduced height
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        # Create notebook for tabs
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Database tab
        db_frame = ttk.Frame(notebook)
        notebook.add(db_frame, text="Database")
        self.create_database_tab(db_frame)

        # Disk tab
        disk_frame = ttk.Frame(notebook)
        notebook.add(disk_frame, text="Disk")
        self.create_disk_tab(disk_frame)

        # Buttons
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(button_frame, text="Test Connection",
                   command=self.test_connection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save",
                   command=self.save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel",
                   command=self.dialog.destroy).pack(side=tk.RIGHT, padx=5)

        # Center dialog
        self.center_dialog()

        self.dialog.wait_window()
        return self.result

    def center_dialog(self):
        """Center the dialog on screen"""
        self.dialog.update_idletasks()
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry(f'{width}x{height}+{x}+{y}')

    def create_database_tab(self, parent):
        """Create database configuration tab"""
        frame = ttk.LabelFrame(parent, text="Database Connection", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        row = 0

        # Host
        ttk.Label(frame, text="Host/IP:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.host_var = tk.StringVar(value=self.config.db_config.get('host', 'localhost'))
        ttk.Entry(frame, textvariable=self.host_var, width=30).grid(row=row, column=1, padx=5, pady=5, sticky=tk.W)
        row += 1

        # Port
        ttk.Label(frame, text="Port:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.port_var = tk.StringVar(value=self.config.db_config.get('port', '5432'))
        ttk.Entry(frame, textvariable=self.port_var, width=10).grid(row=row, column=1, padx=5, pady=5, sticky=tk.W)
        row += 1

        # Database
        ttk.Label(frame, text="Database Name:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.database_var = tk.StringVar(value=self.config.db_config.get('database', ''))
        ttk.Entry(frame, textvariable=self.database_var, width=30).grid(row=row, column=1, padx=5, pady=5, sticky=tk.W)
        row += 1

        # Username
        ttk.Label(frame, text="Username:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.user_var = tk.StringVar(value=self.config.db_config.get('user', ''))
        ttk.Entry(frame, textvariable=self.user_var, width=30).grid(row=row, column=1, padx=5, pady=5, sticky=tk.W)
        row += 1

        # Password
        ttk.Label(frame, text="Password:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.password_var = tk.StringVar(value=self.config.db_config.get('password', ''))
        ttk.Entry(frame, textvariable=self.password_var, width=30, show="*").grid(row=row, column=1, padx=5, pady=5, sticky=tk.W)
        row += 1

        # Info label
        self.db_info_label = ttk.Label(frame, text="", foreground="red")
        self.db_info_label.grid(row=row, column=0, columnspan=2, pady=10, sticky=tk.W)

        # Add stretch to all rows/columns
        frame.columnconfigure(1, weight=1)
        for i in range(row):
            frame.rowconfigure(i, weight=1)

    def create_disk_tab(self, parent):
        """Create disk configuration tab"""
        frame = ttk.LabelFrame(parent, text="Disk Settings", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Disk label
        ttk.Label(frame, text="Windows Disk Label:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.disk_label_var = tk.StringVar(value=self.config.disk_label)
        ttk.Entry(frame, textvariable=self.disk_label_var, width=10).grid(row=0, column=1, padx=5, pady=10, sticky=tk.W)

        # Info text
        info_text = "Enter the Windows drive letter where your media files are located.\n"
        info_text += "Example: X: for network drive X"

        info_label = ttk.Label(frame, text=info_text, wraplength=400, justify=tk.LEFT)
        info_label.grid(row=1, column=0, columnspan=2, pady=10, sticky=tk.W)

        # Configure grid weights
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

    def test_connection(self):
        """Test database connection"""
        # Clear previous error
        self.db_info_label.config(text="")

        # Get values
        host = self.host_var.get().strip()
        port = self.port_var.get().strip()
        database = self.database_var.get().strip()
        user = self.user_var.get().strip()
        password = self.password_var.get()

        # Validate inputs
        if not all([host, port, database, user]):
            self.db_info_label.config(text="Please fill all required fields")
            return

        try:
            # Try to connect
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                connect_timeout=5
            )

            # Test with a simple query
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            cur.close()
            conn.close()

            # Show success
            self.db_info_label.config(
                text=f"✓ Connection successful!\nPostgreSQL version: {version.split(',')[0]}",
                foreground="green"
            )

        except OperationalError as e:
            error_msg = str(e)
            if "password authentication" in error_msg.lower():
                self.db_info_label.config(text="✗ Authentication failed. Check username/password.", foreground="red")
            elif "connection refused" in error_msg.lower():
                self.db_info_label.config(text="✗ Connection refused. Check host/port and ensure server is running.", foreground="red")
            elif "does not exist" in error_msg.lower():
                self.db_info_label.config(text="✗ Database does not exist.", foreground="red")
            else:
                self.db_info_label.config(text=f"✗ Connection failed: {error_msg}", foreground="red")
        except Exception as e:
            self.db_info_label.config(text=f"✗ Error: {str(e)}", foreground="red")

    def save_config(self):
        """Save configuration and close dialog"""
        # Update config object
        self.config.db_config = {
            'host': self.host_var.get(),
            'port': self.port_var.get(),
            'database': self.database_var.get(),
            'user': self.user_var.get(),
            'password': self.password_var.get()
        }

        # Update disk label
        disk_label = self.disk_label_var.get().strip()
        if disk_label:
            self.config.disk_label = disk_label

        # Save to file
        if self.config.save():
            self.result = True
            self.dialog.destroy()
        else:
            messagebox.showerror("Error", "Failed to save configuration")