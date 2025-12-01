import json
from pathlib import Path

CONFIG_DIR = Path.home() / '.mediabrowser'
CONFIG_FILE = CONFIG_DIR / 'config.json'


class Config:
    def __init__(self):
        # Default database configuration
        self.db_config = {
            "host": "",
            "port": "5432",
            "database": "",
            "user": "",
            "password": ""
        }

        # Simple disk label (just the label, not mapping)
        self.disk_label = "X:"

        self.load()

    def load(self):
        """Load configuration from file"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.db_config = data.get('db_config', self.db_config)
                    self.disk_label = data.get('disk_label', self.disk_label)
            except Exception as e:
                print(f"Error loading config: {e}")
                try:
                    backup_file = CONFIG_FILE.with_suffix('.json.bak')
                    CONFIG_FILE.rename(backup_file)
                except:
                    pass

    def save(self):
        """Save configuration to file"""
        try:
            CONFIG_DIR.mkdir(exist_ok=True, parents=True)
            data = {
                'db_config': self.db_config,
                'disk_label': self.disk_label
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
