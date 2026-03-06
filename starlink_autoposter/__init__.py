"""
Starlink AutoPoster - par Saadaw Systems
Application de gestion automatique des abonnements Starlink.
Interface graphique pour automatiser les changements de forfait.

Saadaw Systems - Architectes du Numérique
https://saadaw-systems.org | contact@saadaw-systems.org
"""

import os
import sys

__version__ = "1.0.0"
__app_name__ = "Starlink AutoPoster"
__company__ = "Saadaw Systems"
__company_url__ = "https://saadaw-systems.org"
__company_email__ = "contact@saadaw-systems.org"
__company_slogan__ = "Architectes du Numérique"


def get_asset_path(filename: str) -> str:
    """
    Retourne le chemin absolu vers un fichier dans le dossier assets.
    Gère automatiquement le mode développement et le mode packagé (PyInstaller).
    """
    # Mode PyInstaller : les données sont dans un répertoire temporaire
    if getattr(sys, "_MEIPASS", None):
        base = os.path.join(sys._MEIPASS, "starlink_autoposter", "assets")
    else:
        # Mode développement : chemin relatif au package
        base = os.path.join(os.path.dirname(__file__), "assets")
    return os.path.join(base, filename)
