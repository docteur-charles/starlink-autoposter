"""
Gestion du navigateur Firefox via Selenium.
Détecte le profil Firefox local, lance le navigateur,
et extrait les cookies d'authentification Starlink.
"""

import glob
import os
import time
import logging
from typing import Optional, Callable

import requests
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions

logger = logging.getLogger(__name__)

# Type du callback de log : (message, level) -> None
LogCallback = Callable[[str, str], None]


def _default_log(message: str, level: str = "info"):
    """Callback de log par défaut (utilise le logger standard)."""
    log_func = getattr(logger, level, logger.info)
    log_func(message)


class BrowserManager:
    """
    Gestionnaire du navigateur Firefox.
    Gère le cycle de vie du driver Selenium et l'extraction des cookies.
    Le navigateur reste ouvert entre les cycles pour réutiliser la session.
    """

    def __init__(self, profile_name: str = "starlink", log_callback: Optional[LogCallback] = None):
        self.profile_name = profile_name
        self.driver: Optional[webdriver.Firefox] = None
        self._log = log_callback or _default_log

    @property
    def is_alive(self) -> bool:
        """Vérifie si le navigateur est toujours ouvert et réactif."""
        if not self.driver:
            return False
        try:
            # Accéder à current_url déclenche une exception si le navigateur est fermé
            _ = self.driver.current_url
            return True
        except Exception:
            self.driver = None
            return False

    def _get_firefox_base_dirs(self) -> list:
        """
        Retourne la liste des répertoires possibles contenant les profils Firefox.
        Gère les installations classiques, Snap et Flatpak.
        """
        home = os.path.expanduser("~")

        if os.name == "nt":
            # Windows
            return [os.path.join(home, r"AppData\Roaming\Mozilla\Firefox\Profiles")]

        # Linux / macOS : plusieurs emplacements possibles
        return [
            os.path.join(home, ".mozilla", "firefox"),                            # Installation classique (apt, .deb)
            os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox"),  # Snap (Ubuntu 22.04+)
            os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox"),  # Flatpak
        ]

    def _find_profile_path(self) -> Optional[str]:
        """
        Recherche le chemin du profil Firefox correspondant au nom configuré.
        Parcourt tous les emplacements possibles (classique, Snap, Flatpak).
        """
        tried_dirs = []

        for base in self._get_firefox_base_dirs():
            if not os.path.isdir(base):
                tried_dirs.append(base)
                continue

            matches = glob.glob(os.path.join(base, f"*{self.profile_name}*"))
            if matches:
                self._log(f"Profil Firefox trouvé : {matches[0]}")
                return matches[0]

            tried_dirs.append(base)

        self._log(
            f"Profil Firefox '{self.profile_name}' non trouvé. "
            f"Emplacements vérifiés : {', '.join(tried_dirs)}. "
            "Créez un profil Firefox nommé ainsi via about:profiles "
            "ou changez le nom dans la configuration.",
            "warning",
        )
        return None

    def launch(self) -> bool:
        """
        Lance Firefox avec le profil configuré.
        Si Firefox est déjà ouvert et réactif, le réutilise.
        Retourne True si le navigateur est prêt.
        """
        # Réutiliser le navigateur existant
        if self.is_alive:
            self._log("Firefox déjà ouvert, réutilisation")
            return True

        profile_path = self._find_profile_path()
        if not profile_path:
            self._log("Impossible de lancer Firefox sans profil valide", "error")
            return False

        try:
            self._log("Lancement de Firefox...")
            options = FirefoxOptions()
            options.add_argument("-profile")
            options.add_argument(profile_path)

            self.driver = webdriver.Firefox(options=options)
            self.driver.get("https://www.starlink.com/account")

            # Attendre le chargement initial de la page
            time.sleep(5)
            self._log("Firefox lancé avec succès")
            return True

        except Exception as e:
            self._log(f"Erreur lancement Firefox : {e}", "error")
            self.driver = None
            return False

    def is_logged_in(self) -> bool:
        """Vérifie si l'utilisateur est connecté (cookie d'authentification présent)."""
        if not self.is_alive:
            return False
        try:
            cookies = self.driver.get_cookies()
            return any("Starlink.Com.Access" in c["name"] for c in cookies)
        except Exception:
            return False

    def get_cookies(self) -> requests.cookies.RequestsCookieJar:
        """
        Extrait les cookies du navigateur pour les utiliser avec la bibliothèque requests.
        Retourne un CookieJar vide si le navigateur n'est pas disponible.
        """
        cj = requests.cookies.RequestsCookieJar()
        if not self.is_alive:
            return cj

        try:
            selenium_cookies = self.driver.get_cookies()
            for cookie in selenium_cookies:
                cj.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ".starlink.com"),
                )
        except Exception as e:
            self._log(f"Erreur extraction cookies : {e}", "error")

        return cj

    def refresh_session(self):
        """Rafraîchit la session en rechargeant la page account."""
        if not self.is_alive:
            return
        try:
            self.driver.get("https://www.starlink.com/account")
            time.sleep(5)
            self._log("Session Firefox rafraîchie")
        except Exception as e:
            self._log(f"Erreur rafraîchissement session : {e}", "warning")

    def quit(self):
        """Ferme proprement le navigateur Firefox."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self._log("Firefox fermé")
