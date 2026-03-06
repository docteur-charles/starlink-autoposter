"""
Point d'entrée de l'application Starlink AutoPoster.
Configure le logging puis lance la GUI.
"""

import logging
import os
import sys

from starlink_autoposter.config import get_log_path


def setup_logging():
    """Configure le logging vers fichier et console."""
    log_file = get_log_path()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    """Lance l'application GUI."""
    setup_logging()

    # Import différé pour éviter les problèmes de chargement
    from starlink_autoposter.gui import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
