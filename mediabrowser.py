import io
import json
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, Menu, messagebox

import psycopg2
from PIL import Image, ImageTk
from psycopg2 import OperationalError

from config import Config
from config_dialog import ConfigDialog


class MediaBrowser:
    def __init__(self, root):
        self.root = root
        self.root.title("Media Browser")
        self.root.geometry("1600x900")

        self.config = Config()

        self.conn = None

        self.current_offset = 0
        self.batch_size = 100
        self.is_loading = False
        self.has_more_data = True
        self.current_search = ""
        self.hide_no_preview = True
        self.thumbnail_cache = {}
        self.thumbnail_photos = {}

        self.current_disk_label = self.config.disk_label

        self.setup_ui()
        self.setup_menu()

        self.try_connect()

    def setup_ui(self):
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        search_frame = ttk.Frame(control_frame)
        search_frame.pack(side=tk.LEFT, padx=20)

        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind('<Return>', lambda e: self.start_search())

        self.search_button = ttk.Button(search_frame, text="Search", command=self.start_search)
        self.search_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = ttk.Button(search_frame, text="Clear", command=self.clear_search)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        filter_frame = ttk.Frame(control_frame)
        filter_frame.pack(side=tk.LEFT, padx=20)

        self.hide_no_preview_var = tk.BooleanVar(value=self.hide_no_preview)
        self.hide_checkbox = ttk.Checkbutton(
            filter_frame,
            text="Hide images without previews",
            variable=self.hide_no_preview_var,
            command=self.on_filter_changed
        )
        self.hide_checkbox.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(control_frame, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT, padx=0, expand=True, fill=tk.X)

        open_frame = ttk.Frame(control_frame)
        open_frame.pack(side=tk.RIGHT, padx=0)

        ttk.Label(open_frame, text="Disk Label:").pack(side=tk.LEFT, padx=0)

        self.disk_label_display = ttk.Label(open_frame, text=self.current_disk_label, width=5)
        self.disk_label_display.pack(side=tk.LEFT, padx=5)

        self.show_in_folder_button = ttk.Button(open_frame, text="Show in folder",
                                                command=self.open_file, state="disabled")
        self.show_in_folder_button.pack(side=tk.LEFT, padx=5)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(left_frame, weight=1)

        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=('Filename',), show='tree headings')

        self.tree.heading('#0', text='Preview', anchor=tk.W)
        self.tree.column('#0', width=50, minwidth=50, stretch=False)

        self.tree.heading('Filename', text='Filename')
        self.tree.column('Filename', width=200, minwidth=150, stretch=True)

        self.v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.on_tree_scroll, xscrollcommand=self.h_scrollbar.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        self.v_scrollbar.grid(row=0, column=1, sticky='ns')
        self.h_scrollbar.grid(row=1, column=0, sticky='ew')

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        right_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(right_frame, weight=3)

        preview_exif_frame = ttk.Frame(right_frame)
        preview_exif_frame.pack(fill=tk.BOTH, expand=True)

        preview_left_frame = ttk.Frame(preview_exif_frame)
        preview_left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        preview_container = ttk.LabelFrame(preview_left_frame, text="Image Preview")
        preview_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.preview_canvas = tk.Canvas(preview_container, background='white')
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.preview_canvas.bind('<Configure>', self.on_preview_resize)
        self.current_image_data = None
        self.current_pil_image = None

        caption_container = ttk.LabelFrame(preview_left_frame, text="Caption")
        caption_container.pack(fill=tk.X, padx=5, pady=5)

        self.caption_text = scrolledtext.ScrolledText(caption_container, height=6, wrap=tk.WORD)
        self.caption_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        exif_frame = ttk.LabelFrame(preview_exif_frame, text="EXIF Information")
        exif_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=5, pady=5)
        exif_frame.config(width=400)

        self.exif_tree = ttk.Treeview(exif_frame, columns=('Property', 'Value'), show='tree headings')
        self.exif_tree.column('#0', width=0, stretch=False)
        self.exif_tree.heading('Property', text='Property')
        self.exif_tree.heading('Value', text='Value')
        self.exif_tree.column('Property', width=150, minwidth=120)
        self.exif_tree.column('Value', width=250, minwidth=200)

        exif_scrollbar = ttk.Scrollbar(exif_frame, orient=tk.VERTICAL, command=self.exif_tree.yview)
        self.exif_tree.configure(yscrollcommand=exif_scrollbar.set)

        self.exif_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        exif_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.paned_window.sashpos(0, 400)

        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        self.tree.bind('<Double-1>', self.on_double_click)

    def on_filter_changed(self):
        self.hide_no_preview = self.hide_no_preview_var.get()
        self.reload_data()

    def load_images(self, initial_load=False):
        if self.is_loading or not self.conn:
            return

        self.is_loading = True
        self.status_var.set("Loading...")

        def load_in_thread():
            try:
                cur = self.conn.cursor()
                offset = 0 if initial_load else self.current_offset

                where_clauses = []
                params = []

                if self.current_search:
                    where_clauses.append(
                        "(latest_caption ILIKE %s OR exif::text ILIKE %s OR rel_filename ILIKE %s)"
                    )
                    search_param = f'%{self.current_search}%'
                    params.extend([search_param, search_param, search_param])

                if self.hide_no_preview:
                    where_clauses.append("preview IS NOT NULL")

                where_clause = ""
                if where_clauses:
                    where_clause = "WHERE " + " AND ".join(where_clauses)

                query = f"""
                SELECT abs_filename, rel_filename, preview, latest_caption, exif 
                FROM dm.images_collection
                {where_clause}
                ORDER BY rel_filename desc
                LIMIT %s OFFSET %s
                """

                params.extend([self.batch_size, offset])
                cur.execute(query, params)

                rows = cur.fetchall()
                cur.close()

                has_more = len(rows) == self.batch_size

                self.root.after(0, self.update_treeview, rows, has_more, initial_load)

            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Error: {str(e)}"))
                self.root.after(0, lambda: setattr(self, 'is_loading', False))

        threading.Thread(target=load_in_thread, daemon=True).start()

    def start_search(self):
        search_term = self.search_var.get().strip()
        self.current_search = search_term
        self.current_offset = 0
        self.has_more_data = True
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.tree.delete(*self.tree.get_children())
        self.load_images(initial_load=True)

    def clear_search(self):
        self.search_var.set("")
        self.current_search = ""
        self.current_offset = 0
        self.has_more_data = True
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.tree.delete(*self.tree.get_children())
        self.load_images(initial_load=True)

    def reload_data(self):
        if not self.conn:
            self.status_var.set("Not connected to database")
            return

        self.current_offset = 0
        self.has_more_data = True
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.tree.delete(*self.tree.get_children())
        self.load_images(initial_load=True)
        self.status_var.set("Data reloaded")

    def try_connect(self):
        if self.connect_db():
            self.load_images(initial_load=True)
        else:
            response = messagebox.askyesno(
                "Connection Failed",
                "Failed to connect to database. Would you like to configure the connection settings?"
            )
            if response:
                self.show_config_dialog(first_time=True)
            else:
                self.status_var.set("Not connected to database. Use File → Configuration to set up connection.")

    def connect_db(self):
        try:
            if self.conn:
                try:
                    self.conn.close()
                except:
                    pass

            self.status_var.set("Connecting to database...")

            self.conn = psycopg2.connect(
                host=self.config.db_config["host"],
                port=self.config.db_config.get("port", "5432"),
                database=self.config.db_config["database"],
                user=self.config.db_config["user"],
                password=self.config.db_config["password"],
                connect_timeout=10
            )

            cur = self.conn.cursor()
            cur.execute("SELECT 1")
            cur.close()

            self.status_var.set("Connected to database")
            return True

        except OperationalError as e:
            error_msg = str(e)
            if "password authentication" in error_msg.lower():
                self.status_var.set("Authentication failed - check username/password")
            elif "connection refused" in error_msg.lower():
                self.status_var.set("Connection refused - check host/port")
            elif "does not exist" in error_msg.lower():
                self.status_var.set("Database does not exist")
            else:
                self.status_var.set(f"Database error: {error_msg[:50]}...")
            self.conn = None
            return False

        except Exception as e:
            self.status_var.set(f"Connection error: {str(e)[:50]}...")
            self.conn = None
            return False

    def setup_menu(self):
        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Configuration", command=self.show_config_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Reconnect", command=self.reconnect_db)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        view_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Reload", command=self.reload_data)
        view_menu.add_command(label="Clear Cache", command=self.clear_cache)

    def reconnect_db(self):
        if self.connect_db():
            self.reload_data()

    def show_config_dialog(self, first_time=False):
        dialog = ConfigDialog(self.root, self.config)
        if dialog.show():
            self.current_disk_label = self.config.disk_label
            self.update_disk_label_display()

            if self.connect_db():
                if not first_time:
                    self.reload_data()
                    messagebox.showinfo("Success", "Configuration saved and reconnected successfully!")
            else:
                if first_time:
                    self.try_connect()
                else:
                    messagebox.showwarning(
                        "Connection Failed",
                        "Configuration saved but connection failed. Check your settings."
                    )

    def update_disk_label_display(self):
        self.disk_label_display.config(text=self.current_disk_label)

    def on_disk_changed(self, event=None):
        pass

    def open_file(self):
        if hasattr(self, 'selected_rel_filename') and self.selected_rel_filename:
            if os.name == 'nt':
                self.open_explorer()
            else:
                self.status_var.set(f"Not implemented for {os.name}")
        else:
            self.status_var.set("No file available")

    def open_explorer(self):
        if hasattr(self, 'selected_rel_filename') and self.selected_rel_filename:
            win_path = os.path.join(self.current_disk_label, self.selected_rel_filename).replace('/', '\\')
            self.open_explorer_for_file(win_path)
        else:
            self.status_var.set("No file available")

    def clear_cache(self):
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.status_var.set("Cache cleared")

    def on_tree_scroll(self, *args):
        self.v_scrollbar.set(*args)

        if float(args[1]) > 0.9 and not self.is_loading and self.has_more_data:
            self.load_more_data()

    def create_thumbnail(self, preview_data, size=(30, 30), exif_json=None):
        """Создает миниатюру изображения с учетом EXIF ориентации"""
        if not preview_data:
            return None

        try:
            # Используем кэш если есть
            cache_key = f"{hash(preview_data)}_{size[0]}_{size[1]}_{str(exif_json)}"
            if cache_key in self.thumbnail_cache:
                return self.thumbnail_cache[cache_key]

            # Создаем изображение
            image = Image.open(io.BytesIO(preview_data))

            # Apply EXIF orientation if available
            if exif_json:
                image = self.apply_exif_orientation(image, exif_json)

            # Сохраняем пропорции
            img_width, img_height = image.size
            ratio = min(size[0] / img_width, size[1] / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)

            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Создаем PhotoImage
            photo = ImageTk.PhotoImage(resized_image)

            # Сохраняем в кэш
            self.thumbnail_cache[cache_key] = photo

            return photo
        except Exception as e:
            print(f"Error creating thumbnail: {e}")
            return None

    def load_more_data(self):
        if not self.is_loading and self.has_more_data:
            self.current_offset += self.batch_size
            self.load_images(initial_load=False)

    def update_treeview(self, rows, has_more_data, initial_load):
        try:
            images_loaded = 0
            for row in rows:
                abs_filename, rel_filename, preview, caption, exif = row

                # If hiding images without previews and this image has no preview, skip it
                if self.hide_no_preview and preview is None:
                    continue

                # Создаем миниатюру с учетом EXIF ориентации
                thumbnail = self.create_thumbnail(preview, exif_json=exif) if preview else None

                # Вставляем в дерево с изображением
                item_id = self.tree.insert('', tk.END,
                                           text='',
                                           values=(rel_filename,),
                                           iid=abs_filename)

                # Устанавливаем изображение для элемента
                if thumbnail:
                    self.tree.item(item_id, image=thumbnail)
                    self.thumbnail_photos[abs_filename] = thumbnail
                else:
                    # Optionally show a placeholder or leave empty
                    pass

                images_loaded += 1

            self.has_more_data = has_more_data
            self.is_loading = False

            total_count = len(self.tree.get_children())

            # Build status text
            status_parts = []
            status_parts.append(f"Loaded {total_count} images")

            if self.current_search:
                status_parts.append(f"for '{self.current_search}'")

            if self.hide_no_preview:
                status_parts.append("(no previews hidden)")

            if has_more_data:
                status_parts.append("(scroll to load more)")

            self.status_var.set(" ".join(status_parts))

        except Exception as e:
            self.is_loading = False
            self.status_var.set(f"Error updating treeview: {str(e)}")

    def update_exif_panel(self, exif_json):
        for item in self.exif_tree.get_children():
            self.exif_tree.delete(item)

        if not exif_json:
            self.exif_tree.insert('', tk.END, values=("Нет данных", "EXIF информация отсутствует"))
            return

        exif_data = self.parse_exif_data(exif_json)

        for prop, value in exif_data:
            self.exif_tree.insert('', tk.END, values=(prop, value))

    def on_select(self, event):
        selection = self.tree.selection()
        if not selection or not self.conn:
            self.show_in_folder_button.config(state="disabled")
            return

        abs_filename = selection[0]
        self.selected_abs_filename = abs_filename
        self.show_in_folder_button.config(state="normal")

        def load_preview_in_thread():
            try:
                cur = self.conn.cursor()
                cur.execute("""
                    SELECT rel_filename, preview, latest_caption, exif 
                    FROM dm.images_collection 
                    WHERE abs_filename = %s
                """, (abs_filename,))
                result = cur.fetchone()
                cur.close()

                if result:
                    rel_filename, preview, caption, exif = result
                    self.selected_rel_filename = rel_filename

                    if preview:
                        image = Image.open(io.BytesIO(preview))
                        # Apply EXIF orientation to preview image
                        if exif:
                            image = self.apply_exif_orientation(image, exif)
                        self.root.after(0, self.update_preview, image, caption, abs_filename, exif)
                    else:
                        self.root.after(0, self.update_preview, None, caption, abs_filename, exif)

            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Preview error: {str(e)}"))

        threading.Thread(target=load_preview_in_thread, daemon=True).start()

    def update_preview(self, image, caption, filename, exif):
        self.current_pil_image = image
        self.current_image_data = (caption, filename)

        if image:
            self.resize_and_display_image()
        else:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text="No preview available",
                font=("Arial", 14)
            )

        self.caption_text.delete(1.0, tk.END)
        self.caption_text.insert(1.0, caption or "No caption")

        self.update_exif_panel(exif)

        short_name = filename.split('/')[-1] if '/' in filename else filename
        self.status_var.set(f"Preview: {short_name}")

    def on_preview_resize(self, event):
        if self.current_pil_image:
            self.resize_and_display_image()

    def resize_and_display_image(self):
        if not self.current_pil_image:
            return

        canvas_width = self.preview_canvas.winfo_width() - 20
        canvas_height = self.preview_canvas.winfo_height() - 20

        if canvas_width <= 1 or canvas_height <= 1:
            return

        img_width, img_height = self.current_pil_image.size
        ratio = min(canvas_width / img_width, canvas_height / img_height)

        if ratio < 1:
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            resized_image = self.current_pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        else:
            resized_image = self.current_pil_image

        photo = ImageTk.PhotoImage(resized_image)

        self.preview_canvas.delete("all")
        x = (canvas_width - photo.width()) // 2 + 10
        y = (canvas_height - photo.height()) // 2 + 10
        self.preview_canvas.create_image(x, y, anchor=tk.NW, image=photo)

        self.preview_canvas.image = photo

    def on_double_click(self, event):
        """Handle double click on tree item"""
        selection = self.tree.selection()
        if selection:
            # Get the absolute filename from the tree item ID
            abs_filename = selection[0]
            self.show_full_image(abs_filename)

    def show_full_image(self, filename):
        """Show full image from filesystem with auto-resizing"""
        try:
            # First get the relative filename from database
            cur = self.conn.cursor()
            cur.execute("""
                SELECT rel_filename, preview, exif 
                FROM dm.images_collection 
                WHERE abs_filename = %s
            """, (filename,))
            result = cur.fetchone()
            cur.close()

            if not result:
                self.status_var.set(f"Image not found in database: {filename}")
                return

            rel_filename, preview_data, exif = result

            # Build filesystem path
            if hasattr(self, 'current_disk_label') and self.current_disk_label:
                filesystem_path = os.path.join(self.current_disk_label, rel_filename).replace('/', '\\')
            else:
                filesystem_path = rel_filename

            # Check if file exists
            if not os.path.exists(filesystem_path):
                self.status_var.set(f"File not found: {filesystem_path}")

                # Fallback to preview from database if available
                if preview_data:
                    self.show_full_image_from_preview(filename, preview_data, exif, rel_filename)
                else:
                    messagebox.showerror("File Not Found",
                                         f"Cannot find file:\n{filesystem_path}\n\n"
                                         f"Check if disk {self.current_disk_label} is available.")
                return

            # Open image from filesystem
            try:
                image = Image.open(filesystem_path)

                # Apply EXIF orientation if available
                if exif:
                    image = self.apply_exif_orientation(image, exif)

                # Create window
                top = tk.Toplevel(self.root)
                top.title(f"Full Size - {os.path.basename(filesystem_path)}")

                # Get screen dimensions
                screen_width = top.winfo_screenwidth()
                screen_height = top.winfo_screenheight()

                # Calculate initial window size (80% of screen, but not larger than image)
                img_width, img_height = image.size
                max_width = int(screen_width * 0.8)
                max_height = int(screen_height * 0.8)

                # If image is larger than screen, scale it down
                if img_width > max_width or img_height > max_height:
                    ratio = min(max_width / img_width, max_height / img_height)
                    initial_width = int(img_width * ratio)
                    initial_height = int(img_height * ratio)
                    top.geometry(
                        f"{initial_width}x{initial_height}+{int((screen_width - initial_width) / 2)}+{int((screen_height - initial_height) / 2)}")
                else:
                    # Window size = image size + some padding for controls
                    top.geometry(
                        f"{img_width}x{img_height + 100}+{int((screen_width - img_width) / 2)}+{int((screen_height - img_height) / 2)}")

                # Store references
                top._image = image  # Original image
                top._current_image = image  # Currently displayed image (may be resized)
                top._zoom_level = 1.0  # Current zoom level
                top._pan_start_x = 0
                top._pan_start_y = 0
                top._pan_x = 0
                top._pan_y = 0

                # Create main frame
                main_frame = ttk.Frame(top)
                main_frame.pack(fill=tk.BOTH, expand=True)

                # Create canvas with scrollbars
                canvas_frame = ttk.Frame(main_frame)
                canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

                canvas = tk.Canvas(canvas_frame, bg='gray20', highlightthickness=0)
                v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
                h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)

                canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

                # Grid layout for canvas and scrollbars
                canvas.grid(row=0, column=0, sticky='nsew')
                v_scrollbar.grid(row=0, column=1, sticky='ns')
                h_scrollbar.grid(row=1, column=0, sticky='ew')

                canvas_frame.grid_rowconfigure(0, weight=1)
                canvas_frame.grid_columnconfigure(0, weight=1)

                # Store canvas reference
                top._canvas = canvas
                top._photo = None  # Will store the PhotoImage

                # Control panel
                control_frame = ttk.Frame(main_frame)
                control_frame.pack(fill=tk.X, padx=5, pady=2)

                # Zoom controls
                zoom_frame = ttk.Frame(control_frame)
                zoom_frame.pack(side=tk.LEFT, padx=5)

                ttk.Button(zoom_frame, text="−", width=3,
                           command=lambda: self.zoom_image(top, 0.8)).pack(side=tk.LEFT, padx=2)
                ttk.Button(zoom_frame, text="Fit", width=4,
                           command=lambda: self.fit_to_window(top)).pack(side=tk.LEFT, padx=2)
                ttk.Button(zoom_frame, text="1:1", width=4,
                           command=lambda: self.actual_size(top)).pack(side=tk.LEFT, padx=2)
                ttk.Button(zoom_frame, text="+", width=3,
                           command=lambda: self.zoom_image(top, 1.25)).pack(side=tk.LEFT, padx=2)

                # Zoom label
                self.zoom_label_var = tk.StringVar(value="100%")
                zoom_label = ttk.Label(zoom_frame, textvariable=self.zoom_label_var, width=6)
                zoom_label.pack(side=tk.LEFT, padx=5)
                top._zoom_label = self.zoom_label_var

                # Action buttons
                action_frame = ttk.Frame(control_frame)
                action_frame.pack(side=tk.RIGHT, padx=5)

                ttk.Button(action_frame, text="Open in viewer",
                           command=lambda: self.open_in_default_viewer(filesystem_path)).pack(side=tk.LEFT, padx=2)
                ttk.Button(action_frame, text="Show in folder",
                           command=lambda: self.open_explorer_for_file(filesystem_path)).pack(side=tk.LEFT, padx=2)
                ttk.Button(action_frame, text="Close",
                           command=top.destroy).pack(side=tk.LEFT, padx=2)

                # Status bar
                status_frame = ttk.Frame(main_frame)
                status_frame.pack(fill=tk.X, padx=5, pady=2)

                file_info = f"{filesystem_path} | {img_width}×{img_height} | {os.path.getsize(filesystem_path) // 1024} KB"
                status_label = ttk.Label(status_frame, text=file_info)
                status_label.pack(side=tk.LEFT)

                # Navigation info
                nav_label = ttk.Label(status_frame, text="Mouse wheel: Zoom | Drag: Pan | Double-click: Fit")
                nav_label.pack(side=tk.RIGHT)

                # Bind events
                canvas.bind("<Configure>", lambda e: self.on_canvas_configure(top))
                canvas.bind("<MouseWheel>", lambda e: self.on_mouse_wheel(top, e))
                canvas.bind("<ButtonPress-1>", lambda e: self.on_pan_start(top, e))
                canvas.bind("<B1-Motion>", lambda e: self.on_pan_move(top, e))
                canvas.bind("<Double-Button-1>", lambda e: self.fit_to_window(top))

                # Keyboard shortcuts
                top.bind("<plus>", lambda e: self.zoom_image(top, 1.25))
                top.bind("<minus>", lambda e: self.zoom_image(top, 0.8))
                top.bind("<Key-0>", lambda e: self.actual_size(top))
                top.bind("<Key-f>", lambda e: self.fit_to_window(top))
                top.bind("<Escape>", lambda e: top.destroy())

                # Initial display
                self.fit_to_window(top)

                self.status_var.set(f"Opened: {os.path.basename(filesystem_path)}")

            except Exception as e:
                self.status_var.set(f"Error opening image: {str(e)}")
                # Fallback to preview from database
                if preview_data:
                    self.show_full_image_from_preview(filename, preview_data, exif, rel_filename)
                else:
                    messagebox.showerror("Error", f"Cannot open image:\n{str(e)}")

        except Exception as e:
            self.status_var.set(f"Error: {str(e)}")

    def on_canvas_configure(self, window):
        """Handle canvas resize"""
        if hasattr(window, '_canvas') and window._canvas:
            # Update scroll region
            window._canvas.configure(scrollregion=window._canvas.bbox("all"))
            # If image is smaller than canvas, center it
            self.center_image(window)

    def zoom_image(self, window, factor):
        """Zoom in/out on the image"""
        if not hasattr(window, '_image') or not window._image:
            return

        # Calculate new zoom level
        new_zoom = window._zoom_level * factor
        if new_zoom < 0.1:  # Minimum zoom
            new_zoom = 0.1
        elif new_zoom > 10.0:  # Maximum zoom
            new_zoom = 10.0

        # Get current canvas dimensions
        canvas_width = window._canvas.winfo_width()
        canvas_height = window._canvas.winfo_height()

        # Get mouse position relative to canvas
        x = window._canvas.winfo_pointerx() - window._canvas.winfo_rootx()
        y = window._canvas.winfo_pointery() - window._canvas.winfo_rooty()

        # Calculate center point for zoom
        center_x = x if 0 <= x <= canvas_width else canvas_width // 2
        center_y = y if 0 <= y <= canvas_height else canvas_height // 2

        # Resize image
        img_width, img_height = window._image.size
        new_width = int(img_width * new_zoom)
        new_height = int(img_height * new_zoom)

        resized_image = window._image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        window._current_image = resized_image
        window._zoom_level = new_zoom

        # Update display
        self.update_image_display(window)

        # Update zoom label
        if hasattr(window, '_zoom_label'):
            window._zoom_label.set(f"{int(new_zoom * 100)}%")

        # Adjust pan to keep mouse position centered
        if factor != 1.0:
            # Calculate new pan position
            scale_change = new_zoom / (window._zoom_level / factor)  # Actual factor applied
            window._pan_x = center_x - (center_x - window._pan_x) * scale_change
            window._pan_y = center_y - (center_y - window._pan_y) * scale_change

            # Update canvas scroll
            window._canvas.xview_moveto(window._pan_x / max(new_width, 1))
            window._canvas.yview_moveto(window._pan_y / max(new_height, 1))

    def fit_to_window(self, window):
        """Fit image to window size"""
        if not hasattr(window, '_image') or not window._image:
            return

        # Get canvas dimensions
        canvas_width = window._canvas.winfo_width()
        canvas_height = window._canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        # Get image dimensions
        img_width, img_height = window._image.size

        # Calculate zoom to fit
        zoom_width = canvas_width / img_width
        zoom_height = canvas_height / img_height
        new_zoom = min(zoom_width, zoom_height) * 0.95  # 95% to add some margin

        # Apply zoom
        window._zoom_level = new_zoom
        new_width = int(img_width * new_zoom)
        new_height = int(img_height * new_zoom)

        resized_image = window._image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        window._current_image = resized_image

        # Update display
        self.update_image_display(window)

        # Center image
        self.center_image(window)

        # Update zoom label
        if hasattr(window, '_zoom_label'):
            window._zoom_label.set(f"{int(new_zoom * 100)}%")

    def actual_size(self, window):
        """Show image at 100% zoom"""
        if not hasattr(window, '_image') or not window._image:
            return

        window._zoom_level = 1.0
        window._current_image = window._image

        # Update display
        self.update_image_display(window)

        # Center image
        self.center_image(window)

        # Update zoom label
        if hasattr(window, '_zoom_label'):
            window._zoom_label.set("100%")

    def update_image_display(self, window):
        """Update the displayed image on canvas"""
        if not hasattr(window, '_current_image') or not window._current_image:
            return

        # Clear canvas
        window._canvas.delete("all")

        # Convert PIL image to PhotoImage
        photo = ImageTk.PhotoImage(window._current_image)

        # Store reference to prevent garbage collection
        window._photo = photo

        # Display image
        window._canvas.create_image(0, 0, anchor=tk.NW, image=photo, tags="image")

        # Update scroll region
        window._canvas.configure(scrollregion=window._canvas.bbox("all"))

    def center_image(self, window):
        """Center the image on canvas"""
        if not hasattr(window, '_current_image') or not window._current_image:
            return

        # Get dimensions
        img_width, img_height = window._current_image.size
        canvas_width = window._canvas.winfo_width()
        canvas_height = window._canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        # Calculate center position
        if img_width < canvas_width:
            window._pan_x = (canvas_width - img_width) // 2
        else:
            window._pan_x = 0

        if img_height < canvas_height:
            window._pan_y = (canvas_height - img_height) // 2
        else:
            window._pan_y = 0

        # Update canvas scroll
        window._canvas.xview_moveto(window._pan_x / max(img_width, 1))
        window._canvas.yview_moveto(window._pan_y / max(img_height, 1))

    def on_mouse_wheel(self, window, event):
        """Handle mouse wheel for zooming"""
        if event.delta > 0:
            self.zoom_image(window, 1.25)
        else:
            self.zoom_image(window, 0.8)

    def on_pan_start(self, window, event):
        """Start panning"""
        window._pan_start_x = event.x
        window._pan_start_y = event.y
        window._canvas.scan_mark(event.x, event.y)

    def on_pan_move(self, window, event):
        """Move during panning"""
        window._canvas.scan_dragto(event.x, event.y, gain=1)

        # Update pan position
        img_width, img_height = window._current_image.size
        window._pan_x = int(window._canvas.canvasx(0))
        window._pan_y = int(window._canvas.canvasy(0))

    def show_full_image_from_preview(self, filename, preview_data, exif, rel_filename):
        """Fallback: show image from database preview with auto-resizing"""
        try:
            image = Image.open(io.BytesIO(preview_data))

            # Apply EXIF orientation if available
            if exif:
                image = self.apply_exif_orientation(image, exif)

            top = tk.Toplevel(self.root)
            top.title(f"Full Size (from DB) - {os.path.basename(filename)}")

            # Get screen dimensions
            screen_width = top.winfo_screenwidth()
            screen_height = top.winfo_screenheight()

            # Calculate initial window size
            img_width, img_height = image.size
            max_width = int(screen_width * 0.8)
            max_height = int(screen_height * 0.8)

            if img_width > max_width or img_height > max_height:
                ratio = min(max_width / img_width, max_height / img_height)
                initial_width = int(img_width * ratio)
                initial_height = int(img_height * ratio)
                top.geometry(
                    f"{initial_width}x{initial_height}+{int((screen_width - initial_width) / 2)}+{int((screen_height - initial_height) / 2)}")
            else:
                top.geometry(
                    f"{img_width}x{img_height + 100}+{int((screen_width - img_width) / 2)}+{int((screen_height - img_height) / 2)}")

            # Store references
            top._image = image
            top._current_image = image
            top._zoom_level = 1.0

            # Create main frame
            main_frame = ttk.Frame(top)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Create canvas with scrollbars
            canvas_frame = ttk.Frame(main_frame)
            canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            canvas = tk.Canvas(canvas_frame, bg='gray20', highlightthickness=0)
            v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
            h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)

            canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

            canvas.grid(row=0, column=0, sticky='nsew')
            v_scrollbar.grid(row=0, column=1, sticky='ns')
            h_scrollbar.grid(row=1, column=0, sticky='ew')

            canvas_frame.grid_rowconfigure(0, weight=1)
            canvas_frame.grid_columnconfigure(0, weight=1)

            top._canvas = canvas
            top._photo = None

            # Control panel
            control_frame = ttk.Frame(main_frame)
            control_frame.pack(fill=tk.X, padx=5, pady=2)

            # Zoom controls
            zoom_frame = ttk.Frame(control_frame)
            zoom_frame.pack(side=tk.LEFT, padx=5)

            ttk.Button(zoom_frame, text="−", width=3,
                       command=lambda: self.zoom_image(top, 0.8)).pack(side=tk.LEFT, padx=2)
            ttk.Button(zoom_frame, text="Fit", width=4,
                       command=lambda: self.fit_to_window(top)).pack(side=tk.LEFT, padx=2)
            ttk.Button(zoom_frame, text="1:1", width=4,
                       command=lambda: self.actual_size(top)).pack(side=tk.LEFT, padx=2)
            ttk.Button(zoom_frame, text="+", width=3,
                       command=lambda: self.zoom_image(top, 1.25)).pack(side=tk.LEFT, padx=2)

            # Zoom label
            self.zoom_label_var = tk.StringVar(value="100%")
            zoom_label = ttk.Label(zoom_frame, textvariable=self.zoom_label_var, width=6)
            zoom_label.pack(side=tk.LEFT, padx=5)
            top._zoom_label = self.zoom_label_var

            # Close button
            ttk.Button(control_frame, text="Close",
                       command=top.destroy).pack(side=tk.RIGHT, padx=5)

            # Warning frame
            warning_frame = ttk.Frame(main_frame)
            warning_frame.pack(fill=tk.X, padx=5, pady=2)

            warning_label = ttk.Label(warning_frame,
                                      text=f"⚠ Showing preview from database. Original file not found: {rel_filename}",
                                      foreground="orange")
            warning_label.pack()

            # Bind events
            canvas.bind("<Configure>", lambda e: self.on_canvas_configure(top))
            canvas.bind("<MouseWheel>", lambda e: self.on_mouse_wheel(top, e))
            canvas.bind("<Double-Button-1>", lambda e: self.fit_to_window(top))

            # Keyboard shortcuts
            top.bind("<plus>", lambda e: self.zoom_image(top, 1.25))
            top.bind("<minus>", lambda e: self.zoom_image(top, 0.8))
            top.bind("<Key-0>", lambda e: self.actual_size(top))
            top.bind("<Key-f>", lambda e: self.fit_to_window(top))
            top.bind("<Escape>", lambda e: top.destroy())

            # Initial display
            self.fit_to_window(top)

            self.status_var.set(f"Opened preview from database: {os.path.basename(filename)}")

        except Exception as e:
            messagebox.showerror("Error", f"Cannot open image preview:\n{str(e)}")

    def open_in_default_viewer(self, filepath):
        """Open image in default system viewer"""
        try:
            if os.name == 'nt':
                os.startfile(filepath)
            else:
                # For Linux/Mac
                import subprocess
                subprocess.Popen(['xdg-open', filepath])
            self.status_var.set(f"Opened in default viewer: {os.path.basename(filepath)}")
        except Exception as e:
            self.status_var.set(f"Error opening in viewer: {str(e)}")

    def open_explorer_for_file(self, filepath):
        """Open file in explorer (alternative to open_explorer)"""
        try:
            if os.name == 'nt':
                import subprocess
                subprocess.Popen(f'explorer /select,"{filepath}"')
                self.status_var.set(f"Opened explorer: {filepath}")
            else:
                # For Linux
                import subprocess
                file_dir = os.path.dirname(filepath)
                subprocess.Popen(['xdg-open', file_dir])
                self.status_var.set(f"Opened folder: {file_dir}")
        except Exception as e:
            self.status_var.set(f"Error opening explorer: {str(e)}")

    def apply_exif_orientation(self, image, exif_json):
        """Apply EXIF orientation to correctly rotate the image"""
        if not exif_json or image is None:
            return image

        try:
            # Parse EXIF data
            if isinstance(exif_json, str):
                try:
                    exif_dict = json.loads(exif_json)
                except json.JSONDecodeError:
                    # Try to fix common JSON issues
                    cleaned = exif_json.strip()
                    if cleaned.startswith('"') and cleaned.endswith('"'):
                        cleaned = cleaned[1:-1]
                    try:
                        exif_dict = json.loads(cleaned)
                    except:
                        # Try literal eval as last resort
                        import ast
                        try:
                            exif_dict = ast.literal_eval(exif_json)
                        except:
                            # If all parsing fails, try to extract orientation manually
                            import re
                            match = re.search(r'"Orientation"\s*:\s*(\d+)', exif_json)
                            if match:
                                exif_dict = {'Orientation': int(match.group(1))}
                            else:
                                return image
                except Exception as e:
                    print(f"Error parsing EXIF string: {e}")
                    return image
            else:
                exif_dict = exif_json

            # Common orientation keys
            orientation_keys = ['Image Orientation']

            orientation = None

            # First try direct keys
            for key in orientation_keys:
                if key in exif_dict:
                    orientation = exif_dict[key]
                    break

            if orientation:
                if orientation == 'Rotated 90 CW':
                    return image.rotate(-90, expand=True)
                if orientation == 'Rotated 90 CCW':
                    return image.rotate(90, expand=True)
                if orientation == 'Horizontal (normal)':
                    return image
                print(f"Unknown orientation value: {orientation}")
                return image

        except Exception as e:
            print(f"Error applying EXIF orientation: {e}")
            import traceback
            traceback.print_exc()
            return image

        return image

    def parse_exif_data(self, exif_json):
        if not exif_json:
            return []

        try:
            exif_data = []

            if isinstance(exif_json, str):
                try:
                    exif_dict = json.loads(exif_json)
                except:
                    # Try to clean and parse
                    cleaned = exif_json.strip()
                    if cleaned.startswith('"') and cleaned.endswith('"'):
                        cleaned = cleaned[1:-1]
                    try:
                        exif_dict = json.loads(cleaned)
                    except:
                        # Try to extract rotation/angle information
                        import re

                        # Check for rotation/angle patterns
                        rotation_patterns = [
                            (r'"rotation"\s*:\s*"?(\d+)"?', 'Поворот'),
                            (r'"angle"\s*:\s*"?(\d+)"?', 'Угол'),
                            (r'"rotate"\s*:\s*"?(\d+)"?', 'Вращение'),
                            (r'rotation[=:]\s*"?(\d+)"?', 'Поворот'),
                            (r'angle[=:]\s*"?(\d+)"?', 'Угол'),
                            (r'rotate[=:]\s*"?(\d+)"?', 'Вращение'),
                            (r'"Orientation"\s*:\s*"?(\d+)"?', 'Ориентация (EXIF)'),
                            (r'"orientation"\s*:\s*"?(\d+)"?', 'Ориентация'),
                        ]

                        for pattern, display_name in rotation_patterns:
                            match = re.search(pattern, exif_json, re.IGNORECASE)
                            if match:
                                value = match.group(1)
                                exif_data.append((display_name, f"{value}°"))

                        return exif_data
            else:
                exif_dict = exif_json

            common_keys = {
                'Make': 'Производитель',
                'Model': 'Модель',
                'DateTime': 'Дата и время',
                'ExposureTime': 'Выдержка',
                'FNumber': 'Диафрагма',
                'ISOSpeedRatings': 'ISO',
                'FocalLength': 'Фокусное расстояние',
                'LensModel': 'Объектив',
                'GPSLatitude': 'Широта',
                'GPSLongitude': 'Долгота',
                'ImageWidth': 'Ширина',
                'ImageHeight': 'Высота',
                'Orientation': 'Ориентация',
                'Software': 'Программное обеспечение',
                'Rotation': 'Поворот',
                'rotation': 'Поворот',
                'angle': 'Угол',
                'Angle': 'Угол'
            }

            for key, display_name in common_keys.items():
                if key in exif_dict:
                    value = exif_dict[key]
                    if key == 'ExposureTime' and isinstance(value, list):
                        value = f"1/{int(1 / value[0])}" if value[0] < 1 else str(value[0])
                    elif key == 'FNumber' and isinstance(value, list):
                        value = f"f/{value[0]}"
                    elif key == 'FocalLength' and isinstance(value, list):
                        value = f"{value[0]} mm"
                    elif key == 'DateTime':
                        try:
                            dt = datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                            value = dt.strftime('%d.%m.%Y %H:%M:%S')
                        except:
                            pass
                    elif key in ['Orientation', 'orientation', 'Rotation', 'rotation', 'Angle', 'angle']:
                        # Add degree symbol for rotation values
                        try:
                            orientation_value = int(value)
                            if orientation_value >= 0 and orientation_value <= 360:
                                value = f"{value}°"
                            else:
                                # For standard EXIF codes, add description
                                orientation_names = {
                                    1: "Normal (0°)",
                                    2: "Flipped horizontally",
                                    3: "Rotated 180°",
                                    4: "Flipped vertically",
                                    5: "Transposed (90° CW + flip)",
                                    6: "Rotated 90° CW",
                                    7: "Transverse (90° CCW + flip)",
                                    8: "Rotated 90° CCW"
                                }
                                if orientation_value in orientation_names:
                                    value = f"{value} ({orientation_names[orientation_value]})"
                        except:
                            pass

                    exif_data.append((display_name, str(value)))

            for key, value in exif_dict.items():
                if key not in common_keys and value not in (None, '', []):
                    display_key = key.replace('_', ' ').title()
                    exif_data.append((display_key, str(value)))

            return exif_data

        except Exception as e:
            print(f"Error parsing EXIF: {e}")
            return [("Ошибка парсинга", str(e))]
