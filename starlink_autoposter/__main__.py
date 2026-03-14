"""
Point d'entrée de l'application Starlink AutoPoster.
Configure le logging, l'autostart système, puis lance la GUI.
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


def setup_windows_autostart():
    """
    Enregistre l'application dans le démarrage automatique de Windows.
    Ajoute une clé au registre HKCU\\...\\Run pour lancer l'app au login.
    Ne fait rien si déjà enregistré ou si on n'est pas sur Windows.
    """
    if os.name != "nt":
        return

    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "StarlinkAutoPoster"

        # Chemin du binaire (exécutable PyInstaller ou script Python)
        if getattr(sys, "_MEIPASS", None):
            # Binaire PyInstaller (.exe)
            exe_path = sys.executable
        else:
            # Exécution via Python directement
            exe_path = f'"{sys.executable}" -m starlink_autoposter'

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        )

        # Vérifier si déjà enregistré
        try:
            existing = winreg.QueryValueEx(key, app_name)[0]
            if existing == exe_path:
                winreg.CloseKey(key)
                return
        except FileNotFoundError:
            pass

        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
        logging.info("Autostart Windows configuré")

    except Exception as e:
        logging.warning(f"Impossible de configurer l'autostart Windows : {e}")


def main():
    """Lance l'application GUI."""
    setup_logging()
    setup_windows_autostart()

    # Import différé pour éviter les problèmes de chargement
    from starlink_autoposter.gui import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
