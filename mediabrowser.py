import io
import json
import os
import subprocess
import threading
import tkinter as tk
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

        self.show_in_folder_button = ttk.Button(
            open_frame,
            text="Show in folder",
            command=self.open_file,
            state="disabled"
        )
        self.show_in_folder_button.pack(side=tk.LEFT, padx=5)

        self.open_in_viewer_button = ttk.Button(
            open_frame,
            text="Open in default viewer",
            command=self.open_in_default_viewer,
            state="disabled"
        )
        self.open_in_viewer_button.pack(side=tk.LEFT, padx=5)

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
        # Убрана привязка двойного клика

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

    def open_in_default_viewer(self):
        """Открывает файл в программе просмотра по умолчанию"""
        if hasattr(self, 'selected_rel_filename') and self.selected_rel_filename:
            win_path = os.path.join(self.current_disk_label, self.selected_rel_filename).replace('/', '\\')

            if os.path.exists(win_path):
                try:
                    if os.name == 'nt':
                        os.startfile(win_path)
                    elif os.name == 'posix':
                        subprocess.Popen(['xdg-open', win_path])
                    else:
                        subprocess.Popen(['open', win_path])  # macOS

                    self.status_var.set(f"Opened in default viewer: {win_path}")
                except Exception as e:
                    self.status_var.set(f"Error opening in viewer: {str(e)}")
            else:
                self.status_var.set(f"Path not found: {win_path}")
        else:
            self.status_var.set("No file available")

    def open_explorer(self):
        win_path = os.path.join(self.current_disk_label, self.selected_rel_filename).replace('/', '\\')
        if os.path.exists(win_path):
            try:
                subprocess.Popen(f'explorer /select,"{win_path}"')
                self.status_var.set(f"Opened explorer: {win_path}")
            except Exception as e:
                self.status_var.set(f"Error opening explorer: {str(e)}")
        else:
            self.status_var.set(f"Path not found: {win_path}")

    def reload_data(self):
        self.current_offset = 0
        self.has_more_data = True
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.tree.delete(*self.tree.get_children())
        self.load_images(initial_load=True)
        self.status_var.set("Data reloaded")

    def clear_cache(self):
        self.thumbnail_cache.clear()
        self.thumbnail_photos.clear()
        self.status_var.set("Cache cleared")

    def on_tree_scroll(self, *args):
        self.v_scrollbar.set(*args)

        if float(args[1]) > 0.9 and not self.is_loading and self.has_more_data:
            self.load_more_data()

    def apply_exif_orientation(self, image, exif_json):
        if not exif_json:
            return image

        try:
            if isinstance(exif_json, str):
                exif_dict = json.loads(exif_json)
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

        return image

    def create_thumbnail(self, preview_data, size=(30, 30), exif_json=None):
        """Создает миниатюру изображения с учетом EXIF ориентации"""
        if not preview_data:
            return None

        try:
            cache_key = f"{hash(preview_data)}_{size[0]}_{size[1]}_{str(exif_json)}"
            if cache_key in self.thumbnail_cache:
                return self.thumbnail_cache[cache_key]

            image = Image.open(io.BytesIO(preview_data))

            if exif_json:
                image = self.apply_exif_orientation(image, exif_json)

            img_width, img_height = image.size
            ratio = min(size[0] / img_width, size[1] / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)

            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(resized_image)

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

                if self.hide_no_preview and preview is None:
                    continue

                thumbnail = self.create_thumbnail(preview, exif_json=exif) if preview else None

                item_id = self.tree.insert('', tk.END,
                                           text='',
                                           values=(rel_filename,),
                                           iid=abs_filename)

                if thumbnail:
                    self.tree.item(item_id, image=thumbnail)
                    self.thumbnail_photos[abs_filename] = thumbnail

                images_loaded += 1

            self.has_more_data = has_more_data
            self.is_loading = False

            total_count = len(self.tree.get_children())

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

    def parse_exif_data(self, exif_json):
        if not exif_json:
            return []

        try:
            exif_data = []

            if isinstance(exif_json, str):
                exif_dict = json.loads(exif_json)
            else:
                exif_dict = exif_json

            for key, value in exif_dict.items():
                if value not in (None, '', []):
                    display_key = key.replace('_', ' ').title()
                    exif_data.append((display_key, str(value)))

            return exif_data

        except Exception as e:
            print(f"Error parsing EXIF: {e}")
            return [("Ошибка парсинга", str(e))]

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
        if not selection:
            self.show_in_folder_button.config(state="disabled")
            self.open_in_viewer_button.config(state="disabled")
            return

        abs_filename = selection[0]
        self.selected_abs_filename = abs_filename
        self.show_in_folder_button.config(state="normal")
        self.open_in_viewer_button.config(state="normal")

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

    # Убраны методы on_double_click и show_full_image
