import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app import __version__
from app.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(f"Photo Indexer {__version__}")
    window = MainWindow()
    window.resize(1100, 700)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
